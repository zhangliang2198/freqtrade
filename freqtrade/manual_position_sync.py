"""Opt-in reconciliation of manual futures trades and orphaned protective stops.

Never creates a market order. Database changes require reconstructable exchange
orders; stop cancellation requires repeated flat snapshots plus a fresh recheck.
"""

from __future__ import annotations

import logging
import math
import re
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ccxt import ROUND_DOWN, ROUND_UP

from freqtrade.constants import NON_OPEN_EXCHANGE_STATES
from freqtrade.enums import TradingMode
from freqtrade.exceptions import OperationalException
from freqtrade.exchange import price_to_precision, timeframe_to_minutes
from freqtrade.persistence import LocalTrade, Order, Trade
from freqtrade.trade_policy import MANUAL_IMPORT_TAG, trade_exit_allowed


if TYPE_CHECKING:
    from freqtrade.freqtradebot import FreqtradeBot

logger = logging.getLogger(__name__)


class ManualPositionSync:
    """Import and reconcile manual Binance futures positions and protective stops."""

    def __init__(self, bot: FreqtradeBot):
        self.bot = bot
        self.settings = bot.config.get("manual_position_sync", {})
        self.enabled = self.settings.get("enabled", False)
        self.last_run = -math.inf
        self.last_orphan_cleanup = -math.inf
        self.confirmed: dict[str, tuple[Any, int]] = {}
        self.blocked: set[str] = set()
        self.stop_retry: set[str] = set()
        self.healthy = not self.enabled
        for name in (
            "enabled",
            "auto_exit_positions",
            "auto_manage_positions",
            "manage_protective_stops",
        ):
            if name in self.settings and type(self.settings[name]) is not bool:
                raise OperationalException(f"manual_position_sync.{name} must be boolean")
        if not self.enabled:
            return
        self._validate_environment()
        for name in ("enabled", "import_positions", "cleanup_orphan_stops"):
            if type(self.settings.get(name)) is not bool:
                raise OperationalException(f"manual_position_sync.{name} must be boolean")
        for name in (
            "interval_seconds",
            "orphan_stop_interval_seconds",
            "history_lookback_days",
        ):
            value = self.settings.get(name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise OperationalException(f"manual_position_sync.{name} must be positive")
        if self.settings["history_lookback_days"] > 89:
            raise OperationalException("manual_position_sync history_lookback_days must be <= 89")
        for name, low, high in (("confirmations", 2, 10), ("history_limit", 1, 1000)):
            value = self.settings.get(name)
            if type(value) is not int or not low <= value <= high:
                raise OperationalException(
                    f"manual_position_sync.{name} must be in [{low}, {high}]"
                )

        if self.settings["cleanup_orphan_stops"] and bot.exchange.id == "binance":
            # Enabling account-wide cleanup explicitly acknowledges CCXT's higher request weight.
            options = bot.exchange._api.options
            options.setdefault("fetchOpenOrders", {})["warnWithoutSymbol"] = False
            options["warnOnFetchOpenOrdersWithoutSymbol"] = False

    def _validate_environment(self) -> None:
        if self.bot.exchange.id != "binance" or self.bot.trading_mode != TradingMode.FUTURES:
            raise OperationalException("manual_position_sync supports Binance linear futures only")

    def entry_allowed(self, pair: str) -> bool:
        """Return whether reconciliation health permits a new entry for ``pair``."""
        return (
            not self.enabled
            or self.bot.config["dry_run"]
            or self.bot.trading_mode != TradingMode.FUTURES
            or (self.healthy and pair not in self.blocked)
        )

    @staticmethod
    def _error_reason(exc: Exception) -> str:
        if type(exc) is ValueError:
            return str(exc)
        diag = getattr(getattr(exc, "orig", None), "diag", None)
        if diag is not None:
            return " ".join(
                str(value)
                for value in (
                    type(exc).__name__,
                    getattr(diag, "sqlstate", None),
                    getattr(diag, "table_name", None),
                    getattr(diag, "column_name", None),
                    getattr(diag, "constraint_name", None),
                )
                if value
            )
        # Exchange messages can contain signed URLs. Log only the class and server error code.
        match = re.search(r'"code"\s*:\s*(-?\d+)', str(exc))
        return type(exc).__name__ + (f" code={match[1]}" if match else "")

    @staticmethod
    def _entry_price_matches(trade: LocalTrade, position: dict) -> bool:
        entry = float(position.get("entryPrice") or 0)
        if not math.isfinite(entry) or entry <= 0:
            return False
        rounded = price_to_precision(entry, trade.price_precision, trade.precision_mode_price)
        if ManualPositionSync._same(trade.open_rate, rounded):
            return True
        lower = price_to_precision(
            entry,
            trade.price_precision,
            trade.precision_mode_price,
            rounding_mode=ROUND_DOWN,
        )
        upper = price_to_precision(
            entry,
            trade.price_precision,
            trade.precision_mode_price,
            rounding_mode=ROUND_UP,
        )
        low, high = sorted((lower, upper))
        return (
            low < trade.open_rate < high
            or ManualPositionSync._same(trade.open_rate, low)
            or ManualPositionSync._same(trade.open_rate, high)
        )

    @staticmethod
    def _same(a: float, b: float) -> bool:
        return math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-12)

    def _ready(self, key: str, signature: Any) -> bool:
        previous, count = self.confirmed.get(key, (None, 0))
        count = count + 1 if previous == signature else 1
        self.confirmed[key] = (signature, count)
        return count >= self.settings["confirmations"]

    def _positions(self) -> dict[str, dict]:
        rows = self.bot.exchange.fetch_positions()
        if not isinstance(rows, list):
            raise ValueError("invalid positions response")
        positions = {}
        for row in rows:
            quantity = float(row["contracts"])
            if not math.isfinite(quantity) or quantity < 0 or not row.get("symbol"):
                raise ValueError("invalid position quantity")
            if not quantity:
                continue
            if row.get("hedged") or row.get("side") not in {"long", "short"}:
                raise ValueError("ambiguous or hedged position")
            pair = row["symbol"]
            if pair in positions:
                raise ValueError("multiple positions for one symbol")
            positions[pair] = {
                **row,
                "amount": self.bot.exchange._contracts_to_amount(pair, quantity),
            }
        return positions

    def run(self) -> None:
        """Run one rate-limited manual-position reconciliation pass."""
        if (
            not self.enabled
            or self.bot.config["dry_run"]
            or self.bot.trading_mode != TradingMode.FUTURES
        ):
            return
        now = time.time()
        if 0 <= now - self.last_run < self.settings["interval_seconds"]:
            return
        if now < self.last_run or now - self.last_run > 2 * self.settings["interval_seconds"]:
            self.confirmed.clear()
        self.last_run = now
        try:
            positions = self._positions()
        except Exception as exc:
            self.confirmed.clear()
            self.healthy = False
            vars(self.bot.strategy)["_manual_sync_healthy"] = False
            logger.warning(
                "Manual position reconciliation failed (%s); preserving records and stops",
                self._error_reason(exc),
            )
            return
        self.healthy = True
        vars(self.bot.strategy)["_manual_sync_healthy"] = True
        trades = {trade.pair: trade for trade in Trade.get_open_trades()}
        self.blocked = set()
        self.stop_retry = set()
        for pair in trades.keys() | positions.keys():
            checking_stop = True
            try:
                self._sync_known_stops(trades.get(pair))
                checking_stop = False
                self._sync_pair(pair, trades.get(pair), positions.get(pair), now)
                current = Trade.get_trades([Trade.pair == pair, Trade.is_open.is_(True)]).first()
                if (
                    current
                    and current.enter_tag == MANUAL_IMPORT_TAG
                    and pair not in self.blocked
                    and positions.get(pair)
                ):
                    self._manage_manual_stop(current, positions[pair])
            except Exception as exc:
                Trade.rollback()
                self.blocked.add(pair)
                if checking_stop:
                    self.stop_retry.add(pair)
                self.confirmed.pop(pair, None)
                logger.warning(
                    "Manual position pending reconciliation %s (%s); leaving fills and amount "
                    "unchanged",
                    pair,
                    self._error_reason(exc),
                )
        self.confirmed = {
            key: value
            for key, value in self.confirmed.items()
            if key.startswith("stop:") or key in self.blocked
        }
        vars(self.bot.strategy)["_manual_sync_blocked_pairs"] = self.blocked.copy()
        if self.settings["cleanup_orphan_stops"] and (
            now < self.last_orphan_cleanup
            or now - self.last_orphan_cleanup >= self.settings["orphan_stop_interval_seconds"]
        ):
            self.last_orphan_cleanup = now
            try:
                self._cleanup_stops(positions)
            except Exception as exc:
                Trade.rollback()
                # A failed scan must break consecutive-flat confirmation, including across restarts.
                self.confirmed = {
                    key: value
                    for key, value in self.confirmed.items()
                    if not key.startswith("stop:")
                }
                logger.warning(
                    "Orphan stop reconciliation incomplete (%s); retrying next pass",
                    self._error_reason(exc),
                )
        try:
            self.bot.wallets.update(require_update=True)
        except Exception as exc:
            self.healthy = False
            vars(self.bot.strategy)["_manual_sync_healthy"] = False
            logger.warning(
                "Wallet refresh after reconciliation failed (%s); pausing new entries",
                self._error_reason(exc),
            )

    @staticmethod
    def _position_signature(position: dict | None) -> tuple:
        if position is None:
            return (0, None, None)
        return (position["amount"], position["side"], position.get("entryPrice"))

    def _pending_orders(self, pair: str) -> list:
        orders = self.bot.exchange._api.fetch_open_orders(pair)
        if not isinstance(orders, list):
            raise ValueError("invalid open orders response")
        conditional = self.bot.exchange._api.fetch_open_orders(pair, params={"stop": True})
        if not isinstance(conditional, list):
            raise ValueError("invalid conditional orders response")
        return orders + [order for order in conditional if not self._reduces_position(order)]

    def _sync_known_stops(self, trade: Trade | None) -> None:
        if trade is None:
            return
        for order in list(trade.open_sl_orders):
            current = self.bot.exchange.fetch_stoploss_order(order.order_id, trade.pair)
            if current.get("status_stop") == "triggered" and current.get("status") == "open":
                raise ValueError("protective stop execution still pending")
            if current.get("status") in NON_OPEN_EXCHANGE_STATES:
                self.bot.update_trade_state(
                    trade, order.order_id, current, stoploss_order=True, send_msg=False
                )

    def _history(self, pair: str, since: datetime, now: float) -> list[dict]:
        limit = self.settings["history_limit"]
        orders = self.bot.exchange.fetch_orders(
            pair, since, params={"limit": limit, "endTime": int(now * 1000)}
        )
        if not isinstance(orders, list) or len(orders) >= limit:
            raise ValueError("order history truncated")
        unique = {}
        for order in orders:
            if order.get("symbol") != pair or not order.get("id"):
                raise ValueError("unidentified order")
            filled = float(order["filled"])
            if not math.isfinite(filled) or filled < 0 or order.get("side") not in {"buy", "sell"}:
                raise ValueError("invalid fill")
            if order["status"] not in {"closed", "canceled", "expired", "rejected"}:
                raise ValueError("order still pending")
            if filled:
                price = float(order.get("average") or order.get("price") or 0)
                stamp = float(order.get("lastTradeTimestamp") or order["timestamp"])
                if not math.isfinite(price) or price <= 0 or not 0 < stamp <= now * 1000:
                    raise ValueError("invalid fill price/time")
                unique[str(order["id"])] = order
        return sorted(
            unique.values(),
            key=lambda o: (o.get("lastTradeTimestamp") or o["timestamp"], str(o["id"])),
        )

    def _untracked_position_can_sync(self, pair: str, position: dict | None) -> bool:
        if not position:
            return False
        self.blocked.add(pair)
        return self.settings["import_positions"]

    def _sync_pair(self, pair: str, trade: Trade | None, position: dict | None, now: float) -> None:
        amount = position["amount"] if position else 0.0
        if trade and not trade.is_open:
            if position:
                raise ValueError(
                    "closed trade has a new position; retry after refreshing local trades"
                )
            return
        if trade and position and position["side"] != trade.trade_direction:
            raise ValueError("position direction changed")
        if position and position["side"] == "short" and not self.bot.strategy.can_short:
            raise ValueError("strategy does not support short imports")
        if (
            trade
            and self._same(trade.amount, amount)
            and (position is None or self._entry_price_matches(trade, position))
        ):
            self.confirmed.pop(pair, None)
            return
        if not trade and not self._untracked_position_can_sync(pair, position):
            return
        self.blocked.add(pair)
        signature = (trade.id if trade else None, self._position_signature(position))
        if not self._ready(pair, signature):
            logger.info(
                "Manual position change %s | local=%s exchange=%s; awaiting confirmation",
                pair,
                trade.amount if trade else 0,
                amount,
            )
            return
        since = (
            trade.open_date_utc
            if trade
            else datetime.fromtimestamp(now, UTC)
            - timedelta(days=self.settings["history_lookback_days"])
        )
        since = max(
            since,
            datetime.fromtimestamp(now, UTC)
            - timedelta(days=self.settings["history_lookback_days"]),
        )
        orders = self._history(pair, since, now)
        if self._pending_orders(pair):
            raise ValueError("regular orders still pending")
        fresh = self._positions().get(pair)
        if self._position_signature(fresh) != self._position_signature(position):
            raise ValueError("position changed during reconciliation")
        if trade:
            self.bot.wallets.update(require_update=True)
            self._reconcile_trade(trade, orders, position)
        elif position:
            self._import_trade(pair, position, orders)
        self.blocked.discard(pair)
        self.confirmed.pop(pair, None)

    def _stop_fill_ids(self, trade: Trade) -> set[str]:
        ids = set()
        for order in trade.orders:
            if order.ft_order_side != "stoploss" or not order.filled:
                continue
            current = self.bot.exchange.fetch_stoploss_order(order.order_id, trade.pair)
            if not self._same(float(current.get("filled") or 0), order.safe_filled):
                raise ValueError("stop fill changed; wait for native stop synchronization")
            ids.add(order.order_id)
            if current.get("id_stop"):
                ids.add(str(current["id_stop"]))
        return ids

    def _reconciliation_orders(
        self, trade: Trade, history: list[dict], position: dict | None
    ) -> list[dict]:
        known = {o.order_id: o for o in trade.orders}
        stop_ids = self._stop_fill_ids(trade)
        changes = []
        latest = max(
            (
                (o.order_filled_utc or o.order_date_utc).timestamp()
                for o in known.values()
                if o.filled
            ),
            default=0,
        )
        for raw in history:
            if str(raw["id"]) in stop_ids:
                continue
            existing = Order.order_by_id(str(raw["id"]), trade.pair)
            if existing is not None:
                if existing.ft_trade_id != trade.id:
                    raise ValueError("order belongs to another trade")
                if not self._same(existing.safe_filled, float(raw["filled"])):
                    raise ValueError("tracked fill changed; wait for native order synchronization")
                continue  # Replaying historical partial exits can incorrectly close a live Trade.
            stamp = (raw.get("lastTradeTimestamp") or raw["timestamp"]) / 1000
            if stamp < latest:
                raise ValueError("untracked fill precedes tracked fills; manual review required")
            changes.append(raw)
        preview = LocalTrade(
            **{
                key: getattr(trade, key)
                for key in (
                    "pair",
                    "open_rate",
                    "fee_open",
                    "fee_close",
                    "leverage",
                    "is_short",
                    "trading_mode",
                    "amount_precision",
                    "price_precision",
                    "precision_mode",
                    "precision_mode_price",
                    "contract_size",
                )
            }
        )
        preview.orders = list(known.values()) + [
            Order.parse_from_ccxt_object(raw, trade.pair, raw["side"]) for raw in changes
        ]
        self._validate_reconstructed_position(preview, position)
        return changes

    def _validate_reconstructed_position(self, preview: LocalTrade, position: dict | None) -> None:
        amount = position["amount"] if position else 0.0
        fills = [o for o in preview.orders if o.filled and not o.ft_is_open]
        running = 0.0
        for index, order in enumerate(fills):
            running += order.safe_amount_after_fee * (
                1 if order.ft_order_side == preview.entry_side else -1
            )
            if running < -1e-12 or (self._same(running, 0) and index < len(fills) - 1):
                raise ValueError("history contains a close/reopen cycle; manual review required")
        if not self._same(running, amount):
            raise ValueError("history does not explain position change")
        preview.recalc_trade_from_orders()
        if position and not self._entry_price_matches(preview, position):
            raise ValueError("reconstructed entry price differs")

    def _reconcile_trade(self, trade: Trade, history: list[dict], position: dict | None) -> None:
        orders = self._reconciliation_orders(trade, history, position)
        amount = position["amount"] if position else 0.0
        if not orders:
            raise ValueError("no new fills explain position change")
        self.bot.handle_onexchange_order(trade, orders=orders)
        Trade.session.refresh(trade)
        if trade.is_open != (amount > 0) or (amount > 0 and not self._same(trade.amount, amount)):
            raise ValueError("framework did not reconcile trade")
        trade.set_custom_data(
            "manual_sync", {"source": "exchange_orders", "synced_at": datetime.now(UTC).isoformat()}
        )
        Trade.commit()
        logger.info(
            "Manual position reconciled %s | trade=%s amount=%s status=%s",
            trade.pair,
            trade.id,
            amount,
            "open" if trade.is_open else "closed",
        )

    def _position_leverage(self, pair: str, position: dict) -> float:
        exchange = self.bot.exchange
        leverage_value = position.get("leverage")
        if not leverage_value:
            leverage_value = exchange._api.fetch_leverages([pair])[pair][
                "shortLeverage" if position["side"] == "short" else "longLeverage"
            ]
        leverage = float(leverage_value or 0)
        if not math.isfinite(leverage) or leverage < 1:
            raise ValueError("position leverage unavailable")
        return leverage

    def _import_trade(self, pair: str, position: dict, orders: list[dict]) -> None:
        if not pair.endswith(":" + self.bot.config["stake_currency"]):
            raise ValueError("position uses another settlement currency")
        remaining = position["amount"]
        entry_side = "buy" if position["side"] == "long" else "sell"
        cycle = []
        for order in reversed(orders):
            remaining -= float(order["filled"]) * (1 if order["side"] == entry_side else -1)
            cycle.append(order)
            if self._same(remaining, 0):
                break
            if remaining < 0:
                raise ValueError("history crosses an unknown position")
        if not cycle or not self._same(remaining, 0):
            raise ValueError("cannot reconstruct opening orders")
        cycle.reverse()
        if any(Order.order_by_id(str(o["id"]), pair) for o in cycle):
            raise ValueError("opening orders already assigned")
        exchange = self.bot.exchange
        leverage = self._position_leverage(pair, position)
        liquidation_price = float(position.get("liquidationPrice") or 0)
        if not math.isfinite(liquidation_price) or liquidation_price < 0:
            raise ValueError("invalid liquidation price")
        first = cycle[0]
        fee = exchange.get_fee(symbol=pair, taker_or_maker="taker")
        trade = Trade(
            pair=pair,
            base_currency=exchange.get_pair_base_currency(pair),
            stake_currency=self.bot.config["stake_currency"],
            amount=0,
            amount_requested=float(first["amount"]),
            stake_amount=0,
            open_rate=float(first.get("average") or first["price"]),
            open_date=datetime.fromtimestamp(first["timestamp"] / 1000, UTC),
            fee_open=fee,
            fee_close=fee,
            is_open=True,
            exchange=exchange.id,
            strategy=self.bot.strategy.get_strategy_name(),
            enter_tag=MANUAL_IMPORT_TAG,
            timeframe=timeframe_to_minutes(self.bot.config["timeframe"]),
            leverage=leverage,
            is_short=position["side"] == "short",
            trading_mode=self.bot.trading_mode,
            amount_precision=exchange.get_precision_amount(pair),
            price_precision=exchange.get_precision_price(pair),
            precision_mode=exchange.precisionMode,
            precision_mode_price=exchange.precision_mode_price,
            contract_size=exchange.get_contract_size(pair),
            funding_fees=0,
            liquidation_price=liquidation_price or None,
        )
        for raw in cycle:
            order_obj = Order.parse_from_ccxt_object(raw, pair, raw["side"])
            order_obj.order_filled_date = datetime.fromtimestamp(
                (raw.get("lastTradeTimestamp") or raw["timestamp"]) / 1000, UTC
            )
            trade.orders.append(order_obj)
        trade.recalc_trade_from_orders()
        if not self._same(trade.amount, position["amount"]):
            raise ValueError("reconstructed amount differs")
        if not self._entry_price_matches(trade, position):
            raise ValueError("reconstructed entry price differs")
        self._attach_stops(trade)
        trade.adjust_stop_loss(trade.open_rate, self.bot.strategy.stoploss, initial=True)
        Trade.session.add(trade)
        Trade.commit()
        trade.set_custom_data(
            "manual_sync",
            {
                "source": "exchange_orders",
                "fee_note": "framework estimate until fee reconciliation",
                "funding_note": "historical funding before import is not reconstructed",
                "imported_at": datetime.now(UTC).isoformat(),
            },
        )
        Trade.commit()
        logger.info(
            "Manual position imported %s | trade=%s amount=%s open_rate=%s",
            pair,
            trade.id,
            trade.amount,
            trade.open_rate,
        )

    @staticmethod
    def _reduces_position(order: dict) -> bool:
        info = order.get("info") or {}
        reducing = order.get("reduceOnly", info.get("reduceOnly"))
        closing = info.get("closePosition", False)
        return str(reducing).lower() == "true" or str(closing).lower() == "true"

    @staticmethod
    def _protective(order: dict) -> bool:
        info = order.get("info") or {}
        kind = str(info.get("orderType") or info.get("type") or order.get("type") or "").lower()
        return bool(
            "stop" in kind
            and "take_profit" not in kind
            and ManualPositionSync._reduces_position(order)
            and order.get("status") == "open"
            and order.get("side") in {"buy", "sell"}
            and str(info.get("positionSide", "BOTH")).upper() == "BOTH"
            and order.get("id")
            and order.get("symbol")
        )

    def _attach_stops(self, trade: Trade) -> None:
        stops = self.bot.exchange._api.fetch_open_orders(trade.pair, params={"stop": True})
        if not isinstance(stops, list):
            raise ValueError("invalid conditional orders")
        for stop in stops:
            if self._protective(stop) and stop["side"] == trade.exit_side:
                if Order.order_by_id(str(stop["id"]), trade.pair):
                    raise ValueError("protective stop already assigned")
                # Fetch via the adapter to normalize contract quantities and algorithm order IDs.
                normalized = self.bot.exchange.fetch_stoploss_order(stop["id"], trade.pair)
                if normalized.get("status") != "open":
                    raise ValueError("protective stop changed during import")
                trade.orders.append(
                    Order.parse_from_ccxt_object(normalized, trade.pair, "stoploss")
                )

    @staticmethod
    def _stop_trigger(order: dict) -> float:
        info = order.get("info") or {}
        price = float(
            order.get("stopPrice") or order.get("triggerPrice") or info.get("triggerPrice") or 0
        )
        if not math.isfinite(price) or price <= 0:
            raise ValueError("invalid protective trigger price")
        return price

    def _cancel_confirmed_stop(self, order_id: str, pair: str, amount: float) -> dict:
        result = self.bot.exchange.cancel_stoploss_order_with_result(order_id, pair, amount)
        if result.get("status") not in {"canceled", "expired", "closed"}:
            result = self.bot.exchange.fetch_stoploss_order(order_id, pair)
        if result.get("status") not in {"canceled", "expired", "closed"}:
            raise ValueError("stop cancellation awaiting exchange confirmation")
        known = Order.order_by_id(str(order_id), pair)
        if known:
            known.update_from_ccxt_object(result)
        return result

    def _manage_manual_stop(self, trade: Trade, position: dict) -> None:
        if not self.settings.get(
            "manage_protective_stops", True
        ) or not self.bot.strategy.order_types.get("stoploss_on_exchange"):
            return
        exchange = self.bot.exchange
        pair = trade.pair
        if not self._same(trade.amount, position["amount"]) or trade.has_open_orders:
            return
        self._attach_current_stops(trade)
        stops = []
        for local in trade.open_sl_orders:
            raw = exchange.fetch_stoploss_order(local.order_id, pair)
            if not self._protective(raw) or raw["side"] != trade.exit_side:
                raise ValueError("manual protective stop changed during reconciliation")
            stops.append(raw)
        prices = [float(trade.stoploss_or_liquidation), *(self._stop_trigger(o) for o in stops)]
        desired = min(prices) if trade.is_short else max(prices)
        if not math.isfinite(desired) or desired <= 0:
            raise ValueError("invalid manual protection price")
        desired = exchange.price_to_precision(
            pair, desired, rounding_mode=ROUND_DOWN if trade.is_short else ROUND_UP
        )
        keeper = next((o for o in stops if self._stop_covers(o, trade, desired)), None)
        if keeper is None:
            # Submit and confirm replacement before removing any existing protection.
            self._assert_manual_position_stable(pair, position)
            if not self.bot.create_stoploss_order(trade, desired):
                raise ValueError("manual protective stop submission failed")
            Trade.commit()  # Keep an accepted order discoverable even if its confirmation fails.
            keeper = exchange.fetch_stoploss_order(trade.open_sl_orders[-1].order_id, pair)
            if not self._protective(keeper) or not self._stop_covers(keeper, trade, desired):
                raise ValueError("replacement manual protection not confirmed")
        redundant = [o for o in stops if str(o["id"]) != str(keeper["id"])]
        if redundant:
            self._assert_manual_position_stable(pair, position)
            for old in redundant:
                self._cancel_confirmed_stop(str(old["id"]), pair, trade.amount)
            logger.info(
                "Manual position protection aligned %s | amount=%s stop=%s duplicates=%s "
                "automatic_exit=%s",
                pair,
                trade.amount,
                desired,
                len(redundant),
                trade_exit_allowed(self.bot.config, trade),
            )
        Trade.commit()

    def _assert_manual_position_stable(self, pair: str, position: dict) -> None:
        fresh = self._positions().get(pair)
        if self._position_signature(fresh) != self._position_signature(
            position
        ) or self._pending_orders(pair):
            raise ValueError("manual position changed before protective stop update")

    def _stop_covers(self, order: dict, trade: Trade, desired: float) -> bool:
        closes_all = str((order.get("info") or {}).get("closePosition", False)).lower() == "true"
        return (
            order.get("side") == trade.exit_side
            and self._same(self._stop_trigger(order), desired)
            and (closes_all or self._same(float(order.get("amount") or 0), trade.amount))
        )

    def _attach_current_stops(self, trade: Trade) -> None:
        stops = self.bot.exchange._api.fetch_open_orders(trade.pair, params={"stop": True})
        if not isinstance(stops, list):
            raise ValueError("invalid manual conditional order response")
        known = {o.order_id for o in trade.orders}
        for raw in stops:
            if (
                not self._protective(raw)
                or raw["side"] != trade.exit_side
                or str(raw["id"]) in known
            ):
                continue
            if Order.order_by_id(str(raw["id"]), trade.pair):
                raise ValueError("manual protection belongs to another trade")
            normalized = self.bot.exchange.fetch_stoploss_order(raw["id"], trade.pair)
            if not self._protective(normalized):
                raise ValueError("manual protection changed before adoption")
            trade.orders.append(Order.parse_from_ccxt_object(normalized, trade.pair, "stoploss"))
        Trade.commit()

    def _cleanup_stops(self, positions: dict[str, dict]) -> None:
        # CCXT defaults symbol-less queries to spot, ignoring defaultType.
        params = (
            {"stop": True, "type": "future", "subType": "linear"}
            if self.bot.exchange.id == "binance"
            else {"stop": True}
        )
        stops = self.bot.exchange._api.fetch_open_orders(params=params)
        if not isinstance(stops, list):
            raise ValueError("invalid conditional order scan")
        active_keys = set()
        for order in stops:
            if not self._protective(order) or not order["symbol"].endswith(
                ":" + self.bot.config["stake_currency"]
            ):
                continue
            pair = order["symbol"]
            key = f"stop:{pair}:{order['id']}"
            if pair in positions or any(t.pair == pair for t in Trade.get_open_trades()):
                self.confirmed.pop(key, None)
                continue
            active_keys.add(key)
            if not self._ready(key, (order["side"], order.get("timestamp"))):
                continue
            # Account may have changed since the first snapshot. Pending entries also protect stops.
            if pair in self._positions() or self._pending_orders(pair):
                self.confirmed.pop(key, None)
                continue
            if any(t.pair == pair for t in Trade.get_open_trades()):
                continue
            self._cancel_confirmed_stop(str(order["id"]), pair, 0)
            Trade.commit()
            self.confirmed.pop(key, None)
            logger.info(
                "Orphan protective stop removed %s | order=%s after consecutive flat checks",
                pair,
                order["id"],
            )
        for key in list(self.confirmed):
            if key.startswith("stop:") and key not in active_keys:
                self.confirmed.pop(key, None)
