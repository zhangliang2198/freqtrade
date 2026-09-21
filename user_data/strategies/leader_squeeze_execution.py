"""Order-book checks and management of externally opened positions."""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

from leader_squeeze_support import (
    LOG_ERROR,
    LOG_GOOD,
    LOG_INFO,
    LOG_WARN,
    LeaderMixinContext,
    logger,
)

from freqtrade.constants import BuySell
from freqtrade.exchange import timeframe_to_seconds
from freqtrade.persistence import Trade


class LeaderExecutionMixin(LeaderMixinContext):
    def _recover_missing_rotation_target(self) -> bool:
        """Cancel a missing target only after repeated, reconciled flat-account checks."""
        state = self._rotation_state
        if not self.settings["rotation_recovery_enabled"] or state["phase"] not in {
            "buy_pending",
            "review",
        }:
            return False
        submitted = state.get("submitted_at", self._risk_state.get("last_rotation"))
        if type(submitted) not in (int, float) or not math.isfinite(submitted) or submitted <= 0:
            return False  # No trustworthy persisted request-time boundary.
        now = time.time()
        age = now - submitted
        if (
            not self.settings["rotation_recovery_grace_seconds"]
            <= age
            <= self.settings["rotation_recovery_max_age_seconds"]
        ):
            return False
        probe = getattr(self, "_rotation_recovery_probe", {})
        if probe.get("token") != state["token"]:
            probe = {"token": state["token"], "count": 0, "checked_at": 0.0}
        if now - probe["checked_at"] < self.settings["rotation_recovery_interval_seconds"]:
            return False
        probe["checked_at"] = now
        self._rotation_recovery_probe = probe
        try:
            proof = self._rotation_flat_proof({**state, "submitted_at": submitted}, now)
        except Exception as exc:
            probe["count"] = 0
            self._record_rotation_event(
                "recovery_blocked",
                "轮换恢复核对未通过, 保留旧仓及开仓暂停",
                {
                    "error_type": type(exc).__name__,
                    "check_stage": getattr(self, "_rotation_recovery_stage", "unknown"),
                },
                once=True,
            )
            return False
        probe["count"] += 1
        self._record_rotation_event(
            "recovery_check",
            "目标未成交或已核实平仓, 无挂单/仓位, 等待连续核对",
            {**proof, "confirmations": probe["count"]},
        )
        if probe["count"] < self.settings["rotation_recovery_confirmations"]:
            return False
        self._last_rotation = now
        self._clear_rotation(
            "连续核对确认目标未成交或已平仓且无挂单/仓位, 取消计划并恢复选币",
            event_type="recovered",
        )
        logger.info("🔄 轮换目标缺失计划已恢复 | 旧仓保留, 按配置冷却后可重新评估", extra=LOG_INFO)
        return True

    def _rotation_closed_target_orders(self, state: dict) -> dict[str, float]:
        trades = [
            trade
            for trade in Trade.get_trades_proxy(pair=state["target"], is_open=False)
            if trade.enter_tag == self._rotation_entry_tag()
            and not trade.is_open
            and not trade.is_short
            and not trade.has_open_orders
            and trade.open_date_utc.timestamp() >= state["submitted_at"] - 1
            and trade.close_date_utc is not None
            and trade.close_date_utc >= trade.open_date_utc
        ]
        if len(trades) != 1:
            raise ValueError("no unique closed rotation target")
        orders = trades[0].orders
        if any(order.ft_is_open for order in orders):
            raise ValueError("closed target still has pending orders")
        filled = {str(order.order_id): float(order.filled or 0) for order in orders if order.filled}
        if not filled or any(not math.isfinite(value) or value <= 0 for value in filled.values()):
            raise ValueError("invalid closed target fills")
        return filled

    def _rotation_flat_proof(self, state: dict, now: float) -> dict:
        pair = state["target"]
        self._rotation_recovery_stage = "order_history"
        if self.config.get("dry_run", True):
            # Paper orders are local: never query the real account for recovery.
            orders = list(self._exchange._dry_run_open_orders.values())
            history = [order for order in orders if order.get("symbol") == pair]
            positions = []
            pending = [order for order in history if order.get("status") == "open"]
        else:
            limit = self.settings["rotation_recovery_history_limit"]
            since = int((state["submitted_at"] - self.settings["data_grace_seconds"]) * 1000)
            history = self._exchange._api.fetch_orders(
                pair, since=since, limit=limit, params={"endTime": int(now * 1000)}
            )
            if not isinstance(history, list) or len(history) >= limit:
                raise ValueError("order history may be truncated")
            self._rotation_recovery_stage = "open_orders"
            regular = self._exchange._api.fetch_open_orders(pair)
            conditional = self._external_stop_orders(pair)
            if not isinstance(regular, list) or not isinstance(conditional, list):
                raise ValueError("invalid open orders response")
            pending = regular + conditional
            positions = self._exchange.fetch_positions(pair)
        if not isinstance(positions, list) or pending:
            raise ValueError("pending orders or invalid position response")
        self._rotation_recovery_stage = "positions"
        for position in positions:
            contracts = float(position["contracts"])
            if position.get("symbol") != pair or not math.isfinite(contracts) or contracts != 0:
                raise ValueError("target position exists or is unknown")
        self._rotation_recovery_stage = "order_fills"
        closed_fills = (
            self._rotation_closed_target_orders(state)
            if any(float(order["filled"]) != 0 for order in history)
            else {}
        )
        matched = set()
        for order in history:
            filled = float(order["filled"])
            reconciled = str(order.get("id")) in closed_fills and math.isclose(
                filled, closed_fills[str(order["id"])], rel_tol=1e-8
            )
            if (
                order.get("symbol") != pair
                or not math.isfinite(filled)
                or (filled != 0 and not reconciled)
                or order.get("status")
                not in (
                    {"closed", "canceled", "expired"}
                    if reconciled
                    else {"canceled", "expired", "rejected"}
                )
            ):
                raise ValueError("target order has fills or uncertain status")
            if reconciled:
                matched.add(str(order["id"]))
        if matched != set(closed_fills):
            raise ValueError("closed target order history is incomplete")
        # Re-read local state after the network calls; never discard a tracked trade.
        self._rotation_recovery_stage = "local_trades"
        if any(trade.pair == pair for trade in Trade.get_open_trades()):
            raise ValueError("target trade exists locally")
        return {
            "history_count": len(history),
            "pending_orders": 0,
            "position_contracts": 0,
            "closed_target_reconciled": bool(closed_fills),
        }

    def _execution_order_book(self, pair: str, *, cached_only: bool = False) -> dict:
        """复用最多5秒的20档盘口; 从请求开始计龄, 失败不回退到旧数据。"""
        now = time.monotonic()
        cache = getattr(self, "_order_book_cache", {})
        self._order_book_cache = {
            key: value
            for key, value in cache.items()
            if 0 <= now - value[0] < self.ORDER_BOOK_MAX_AGE_SECONDS
        }
        cached = self._order_book_cache.get(pair)
        if cached is not None:
            return cached[1]
        if cached_only:
            raise ValueError("盘口缓存缺失或超过5秒, 等待下一轮刷新")
        book = self._exchange.fetch_l2_order_book(pair, self.settings["order_book_depth"])
        if not 0 <= time.monotonic() - now < self.ORDER_BOOK_MAX_AGE_SECONDS:
            raise ValueError("盘口请求耗时超过5秒, 拒绝使用")
        self._order_book_cache[pair] = (now, book)
        return book

    def _entry_price_reference(self, pair: str, *, refresh: bool) -> dict[str, Any] | None:
        """Freeze the signal close and pre-signal ATR; confirmation may never rebase."""
        enabled = self.settings.get("entry_price_guard_enabled", True)
        multiple = self.settings.get("entry_price_max_deviation_atr", 1.0)
        if type(enabled) is not bool or (
            type(multiple) not in (int, float)
            or not math.isfinite(multiple)
            or multiple <= 0
        ):
            raise ValueError("追价保护配置无效: 开关须为bool, ATR倍数须为正有限数")
        if not enabled:
            self._entry_price_references = {}
            return None
        now = time.time()
        seconds = timeframe_to_seconds(self.timeframe)
        references = getattr(self, "_entry_price_references", {})
        self._entry_price_references = {
            key: value
            for key, value in references.items()
            if value["timeframe"] == self.timeframe
            and value["signal_time"] + seconds <= now < value["valid_until"]
        }
        reference = self._entry_price_references.get(pair)
        if not refresh:
            if reference is None:
                raise ValueError("追价保护: 信号基准缺失或过期, 等待重新选币")
            # Runtime tightening is permitted; never lift the frozen cap.
            reference["max_price"] = min(
                reference["max_price"], reference["close"] + multiple * reference["atr"]
            )
            return reference
        frame = self._closed_candles(
            pair,
            self.timeframe,
            self.settings["atr_period"] + 2,
            columns=("high", "low", "close"),
            now=now,
        )
        # Preserve a valid frozen anchor on a temporary feed failure. Otherwise
        # a retry with corrected same-candle data could lift the original cap.
        if frame is None or len(frame) < self.settings["atr_period"] + 2:
            raise ValueError("追价保护: 信号K线或ATR历史缺失、过期或无效")
        signal_date = frame["date"].iloc[-1]
        signal_time = signal_date.timestamp()
        if (
            signal_date.tzinfo is None
            or not math.isfinite(signal_time)
            or signal_time % seconds != 0
            or not signal_time + seconds <= now < signal_time + 2 * seconds
        ):
            raise ValueError("追价保护: 信号K线未收盘、未对齐或已过期")
        if ((frame["high"] < frame["close"]) | (frame["low"] > frame["close"])).any():
            raise ValueError("追价保护: K线高低收关系无效")
        if reference is not None and reference["signal_time"] == signal_time:
            return self._entry_price_reference(pair, refresh=False)
        frame = frame.tail(max(self.ENTRY_HEAT_HISTORY_CANDLES, self.settings["atr_period"] + 2))
        close = float(frame["close"].iloc[-1])
        # A signal candle's own spike must not inflate its ATR allowance.
        atr = float(self._wilder_atr(frame.iloc[:-1]))
        max_price = close + multiple * atr
        if not all(math.isfinite(value) and value > 0 for value in (close, atr, max_price)):
            raise ValueError("追价保护: 信号价格、参考ATR或买入上限无效")
        reference = {
            "timeframe": self.timeframe,
            "signal_time": signal_time,
            "close": close,
            "atr": atr,
            "max_price": max_price,
            # No data-grace extension: an old signal expires at the next close.
            "valid_until": signal_time + 2 * seconds,
        }
        self._entry_price_references[pair] = reference
        return reference

    def _execution_is_safe(
        self, pair: str, *, amount: float | None = None, cached_only: bool = False
    ) -> bool:
        self._execution_block_reason = "盘口安全检查未通过"
        try:
            # Selection/rotation previews establish the signal. Actual-quantity
            # confirmation must reuse it, before _prepare_rotation_buy is called.
            reference = self._entry_price_reference(pair, refresh=amount is None)
            book = self._execution_order_book(pair, cached_only=cached_only)
            bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
            if not all(math.isfinite(value) and value > 0 for value in (bid, ask)) or bid > ask:
                raise ValueError("盘口价格无效")
            spread = 1.0 - bid / ask
            if spread > float(self.settings["max_spread_ratio"]):
                self._execution_block_reason = (
                    f"价差 {spread:.3%} > 上限 {self.settings['max_spread_ratio']:.3%}"
                )
                return False
            if amount is None:
                stake = self._wallets.get_total_stake_amount() * float(self.settings["stake_ratio"])
                amount = stake * float(self.settings["leverage"]) / ask
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError("下单数量无效或可用资金不足")
            remaining = amount
            cost = 0.0
            last_price = ask
            for price, size in book["asks"]:
                price, size = float(price), float(size)
                if (
                    not all(math.isfinite(value) and value > 0 for value in (price, size))
                    or price < last_price
                ):
                    raise ValueError("卖盘档位无效")
                last_price = price
                take = min(remaining, size)
                cost += take * float(price)
                remaining -= take
                if remaining <= 0:
                    break
            if remaining > 0:
                self._execution_block_reason = "前20档卖盘深度不足"
                return False
            vwap = cost / amount
            if not math.isfinite(vwap) or vwap <= 0:
                raise ValueError("预计成交均价无效")
            if not vwap / ask - 1.0 <= float(self.settings["max_slippage_ratio"]):
                self._execution_block_reason = (
                    f"预计滑点 {vwap / ask - 1.0:.3%} > 上限 {self.settings['max_slippage_ratio']:.3%}"
                )
                return False
            if reference is not None:
                # A book request may cross the next close. Expired references
                # reject the order instead of silently switching to a higher cap.
                current = self._entry_price_reference(pair, refresh=False)
                if current is None or current["signal_time"] != reference["signal_time"]:
                    raise ValueError("追价保护: 盘口检查期间信号已变化")
                if vwap > current["max_price"]:
                    self._execution_block_reason = (
                        f"追价拦截: 预计成交均价 {vwap:.8g} > 买入上限 {current['max_price']:.8g} | "
                        f"信号收盘={current['close']:.8g} 参考ATR={current['atr']:.8g} "
                        f"偏离={(vwap - current['close']) / current['atr']:.3f}ATR "
                        f"信号时间戳={current['signal_time']:.0f}"
                    )
                    return False
            self._execution_block_reason = ""
            return True
        except Exception as exc:
            self._execution_block_reason = f"盘口检查异常 ({type(exc).__name__}): {exc}"
            logger.warning("⚠️ 盘口安全检查异常 %s: %s", pair, exc, extra=LOG_WARN)
            return False

    def _external_exit_reason(self, pair: str, side: str) -> str:
        if self._market_exit_required():
            return "龙头市场严重普跌"
        if side == "short":
            return "外部空头仓位"
        if self._rotation_exit_allowed(pair):
            return "龙头轮换"
        if self._trend_reversed(pair):
            return getattr(self, "_trend_exit_details", {}).get(pair, "趋势反转")
        if self._external_hard_stop_hit(pair, side):
            return "外部仓位硬止损"
        return ""

    def _manage_external_positions(self, now: float) -> None:
        positions = self._wallets.get_all_positions()
        if not self.settings["manage_external_positions"]:
            return
        for pair in self._external_pairs:
            try:
                position = positions.get(pair)
                if position is None:
                    continue
                exit_reason = self._external_exit_reason(pair, position.side)
                should_exit = bool(exit_reason)
                if not should_exit:
                    self._external_stop_protected[pair] = self._ensure_external_stop(
                        pair, position, now
                    )
                else:
                    self._external_stop_protected[pair] = False
                if (
                    not should_exit
                    or now - self._external_exit_requested.get(pair, 0)
                    < self.settings["external_exit_retry_seconds"]
                ):
                    continue
                self._external_exit_requested[pair] = now
                if self.config.get("dry_run", True):
                    logger.info(
                        "🧪 模拟盘: 将退出外部仓位 %s | 原因=%s (未发送真实订单)",
                        pair,
                        exit_reason,
                        extra=LOG_INFO,
                    )
                    continue
                side: BuySell = "sell" if position.side == "long" else "buy"
                rate = self._external_exit_rate(pair, position.side)
                order = self._exchange.create_order(
                    pair=pair,
                    ordertype="market",
                    side=side,
                    amount=position.position,
                    rate=rate,
                    leverage=float(position.leverage or self.settings["leverage"]),
                    reduceOnly=True,
                    initial_order=False,
                )
                if pair == getattr(self, "_rotation_pair", None):
                    self._record_rotation_event(
                        "external_exit_submitted",
                        "外部旧仓已提交退出订单",
                        {
                            key: order.get(key)
                            for key in ("id", "status", "filled", "amount", "average", "price")
                        },
                    )
                if order.get("status") == "closed":
                    self._cancel_external_stops(pair, position.side, float(position.position))
                logger.info(
                    "🚪 外部仓位退出订单 %s | 方向=%s 数量=%.8f 状态=%s | 原因=%s (以订单状态为准)",
                    pair,
                    side,
                    position.position,
                    order.get("status", "未知"),
                    exit_reason,
                    extra=LOG_WARN,
                )
                self.dp.send_msg(f"Closed external position {pair}: {side} reduceOnly")
            except Exception as exc:
                self._external_stop_protected[pair] = False
                if pair == getattr(self, "_rotation_pair", None):
                    self._record_rotation_event(
                        "external_exit_failed",
                        "外部旧仓退出处理异常",
                        {"error_type": type(exc).__name__},
                        once=True,
                    )
                logger.error(
                    "🚨 外部仓位处理失败 %s: %s | 继续处理其他仓位, 暂停新开仓",
                    pair,
                    exc,
                    extra=LOG_ERROR,
                )

    def _sync_external_pairs(self) -> None:
        trades = Trade.get_open_trades()
        db_pairs = {trade.pair for trade in trades}
        positions = self._wallets.get_all_positions()
        now = time.time()
        future_pairs = [
            trade.pair
            for trade in trades
            if isinstance(opened := getattr(trade, "open_date_utc", None), datetime)
            and opened.timestamp() > now + float(self.settings["data_grace_seconds"])
        ]
        self._database_time_healthy = not future_pairs
        if future_pairs:
            self._warn_data_unavailable(
                "数据库持仓时间",
                f"开仓时间在未来: {future_pairs}; 暂停新开仓, 已有仓位继续退出; 不自动改写记录",
            )
        for pair in positions:
            self._position_first_seen.setdefault(pair, now)
        for pair in set(self._position_first_seen) - set(positions):
            self._position_first_seen.pop(pair, None)
        self._external_pairs = {pair for pair in positions if pair not in db_pairs}
        for state in (self._external_stop_last_check, self._external_stop_protected):
            for pair in set(state) - self._external_pairs:
                state.pop(pair, None)

    def _refresh_adl_ranks(self) -> None:
        if self.config.get("dry_run"):
            self._adl_ranks = {}
            return
        try:
            ranks = self._exchange._api.fetch_positions_adl_rank(None, params={"subType": "linear"})
            self._adl_ranks = {
                item["symbol"]: float(item["rank"])
                for item in ranks
                if item.get("symbol") and item.get("rank") is not None
            }
            high_risk = {pair: rank for pair, rank in self._adl_ranks.items() if rank >= 4}
            if high_risk:
                logger.warning("⚠️ 仓位处于最高ADL减仓风险等级: %s", high_risk, extra=LOG_WARN)
        except Exception as exc:
            logger.warning("⚠️ ADL减仓风险等级刷新失败: %s", exc, extra=LOG_WARN)

    def _external_exit_rate(self, pair: str, side: str) -> float:
        """盘口定价时复用短时快照, 保留框架的买卖方向及档位计算。"""
        pricing = self.config.get("exit_pricing", {})
        kwargs = {}
        if (
            pricing.get("use_order_book")
            and 1 <= pricing.get("order_book_top", 1) <= self.settings["order_book_depth"]
        ):
            kwargs["order_book"] = self._execution_order_book(pair)
        return self._exchange.get_rate(
            pair, side="exit", is_short=side == "short", refresh=True, **kwargs
        )

    def _external_hard_stop_hit(self, pair: str, side: str) -> bool:
        detail = self._position_details.get(pair, {})
        entry = float(detail.get("entryPrice") or 0)
        if not math.isfinite(entry) or entry <= 0:
            raise ValueError("外部仓位开仓价缺失或无效, 无法计算程序止损")
        rate = self._external_exit_rate(pair, side)
        profit = ((rate / entry) - 1.0) * (-1 if side == "short" else 1)
        profit *= float(detail.get("leverage") or self.settings["leverage"])
        return profit <= self.stoploss

    @staticmethod
    def _is_protective_stop(
        order: dict[str, Any], position_side: str, position_amount: float
    ) -> bool:
        info = order.get("info", {})
        reduce_only = str(info.get("reduceOnly", order.get("reduceOnly", False))).lower() == "true"
        stop_price = info.get("stopPrice") or order.get("stopPrice")
        order_side = str(order.get("side") or info.get("side") or "").lower()
        expected_side = "sell" if position_side == "long" else "buy"
        amount = float(order.get("amount") or info.get("origQty") or 0)
        order_type = str(order.get("type") or info.get("type") or "").lower()
        return bool(
            reduce_only
            and float(stop_price or 0) > 0
            and order_side == expected_side
            and amount >= position_amount * 0.999
            and "take_profit" not in order_type
        )

    def _external_stop_orders(self, pair: str) -> list[dict[str, Any]]:
        return self._exchange._api.fetch_open_orders(pair, params={"stop": True})

    def _ensure_external_stop(self, pair: str, position: Any, now: float) -> bool:
        if not self.order_types.get("stoploss_on_exchange"):
            # Successful local monitoring is required; never create or cancel a remote stop here.
            return True
        if self.config.get("dry_run", True):
            return True
        interval = float(self.settings["external_stop_check_seconds"])
        if now - self._external_stop_last_check.get(pair, 0) < interval:
            return self._external_stop_protected.get(pair, False)
        self._external_stop_last_check[pair] = now
        try:
            position_amount = float(position.position)
            existing = self._external_stop_orders(pair)
            protected = any(
                self._is_protective_stop(order, position.side, position_amount)
                for order in existing
            )
            if not protected:
                detail = self._position_details.get(pair, {})
                leverage = float(
                    detail.get("leverage") or position.leverage or self.settings["leverage"]
                )
                entry = float(detail.get("entryPrice") or 0)
                if entry <= 0:
                    raise ValueError("missing entry price")
                distance = abs(self.stoploss) / leverage
                stop_price = entry * (1.0 - distance)
                self._exchange.create_stoploss(
                    pair=pair,
                    amount=position.position,
                    stop_price=stop_price,
                    order_types=self.order_types,
                    side="sell",
                    leverage=leverage,
                )
                self.dp.send_msg(f"Protected external position {pair} with exchange stop.")
                logger.info(
                    "🛡️ 外部仓位止损已提交 %s | 止损价=%.8f 数量=%.8f",
                    pair,
                    stop_price,
                    position.position,
                    extra=LOG_GOOD,
                )
            self._external_stop_protected[pair] = True
            return True
        except Exception as exc:
            logger.error("🚨 外部仓位止损保护失败 %s: %s", pair, exc, extra=LOG_ERROR)
            self._external_stop_protected[pair] = False
            return False

    def _cancel_external_stops(self, pair: str, position_side: str, position_amount: float) -> None:
        for order in self._external_stop_orders(pair):
            if self._is_protective_stop(order, position_side, position_amount):
                self._exchange.cancel_stoploss_order(order["id"], pair)
