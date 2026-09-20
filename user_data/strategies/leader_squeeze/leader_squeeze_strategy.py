"""币安合约上的多头龙头挤空策略。"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from leader_squeeze_helpers import (
    DISPLAY_TZ,
    LOG_ERROR,
    LOG_GOOD,
    LOG_INFO,
    LOG_SCORE,
    LOG_WARN,
    LeaderConfigMixin,
    LeaderDataMixin,
    LeaderExecutionMixin,
    LeaderProfitMixin,
    LeaderReportingMixin,
    LeaderStorageMixin,
    LeaderTrendMixin,
    configure_strategy,
    decision_snapshot,
    logger,
    report_cached,
    validate_runtime_settings,
)
from pandas import DataFrame

from freqtrade.exceptions import OperationalException
from freqtrade.exchange import timeframe_to_seconds
from freqtrade.persistence import Order, Trade
from freqtrade.strategy import IStrategy


class LeaderSqueezeStrategy(
    LeaderConfigMixin,
    LeaderTrendMixin,
    LeaderDataMixin,
    LeaderReportingMixin,
    LeaderStorageMixin,
    LeaderExecutionMixin,
    LeaderProfitMixin,
    IStrategy,
):
    INTERFACE_VERSION = 3
    can_short = False
    # 盈利棘轮需要框架每轮回调本方法; 是否真正改动止损由 profit_lock_enabled 决定,
    # 关闭时 custom_stoploss 恒返回 None, 行为与未接入前一致。
    use_custom_stoploss = True

    def __init__(self, config: dict) -> None:
        configure_strategy(self, config)
        super().__init__(config)

    @property
    def ETH_PAIR(self) -> str:
        return self.settings["eth_pair"]

    @property
    def ORDER_BOOK_MAX_AGE_SECONDS(self) -> float:
        return self.settings["order_book_max_age_seconds"]

    @property
    def ENTRY_HEAT_HISTORY_CANDLES(self) -> int:
        return (
            int(
                self.settings["entry_heat_history_days"]
                * 86400
                / timeframe_to_seconds(self.timeframe)
            )
            + 1
        )

    def bot_start(self, **kwargs) -> None:
        """初始化运行时状态和后台行情数据工作线程。"""
        runmode = str(self.config.get("runmode", ""))
        if runmode and runmode not in {"live", "dry_run"}:
            raise OperationalException(
                "LeaderSqueezeStrategy requires live or dry_run mode because liquidation, "
                "position-ratio and open-interest inputs have no historical data source."
            )
        # The resolver has already normalized framework attributes after __init__.
        # Reloading raw JSON here would restore string ROI keys and break exits.
        configure_strategy(self, self.config, framework=False)
        self._validate_score_settings()
        self._validate_reversal_settings()
        self._validate_entry_heat_settings()
        self._validate_tuning_settings()
        validate_runtime_settings(self)
        self._initialize_runtime()
        self._initialize_rotation_audit()
        if not self.order_types.get("stoploss_on_exchange"):
            logger.info(
                "🛡️ 止损模式=程序内止损 | 不新建交易所止损; 历史条件单保留并核对成交 | "
                "停机或断网期间, 无交易所止损的新仓无法自动止损",
                extra=LOG_WARN,
            )

    def _initialize_runtime(self) -> None:
        self._pending_entry_scores: dict[str, dict[str, Any]] = {}
        self._order_book_cache: dict[str, tuple[float, dict]] = {}
        self._scores: dict[str, float] = {}
        self._score_leaders: list[str] = []
        self._metrics: dict[str, dict[str, float]] = {}
        self._exit_metrics: dict[str, dict[str, float]] = {}
        self._entry_pairs: set[str] = set()
        self._entry_slot_assignments: dict[str, int] = {}
        self._entry_setup_snapshot: dict[str, dict[str, Any]] = {}
        self._entry_funnel_rows: list[list[str]] = []
        self._entry_funnel_candidates: list[list[str]] = []
        self._external_pairs: set[str] = set()
        self._position_details: dict[str, Any] = {}
        self._position_first_seen: dict[str, float] = {}
        self._last_score_refresh = 0.0
        self._last_score_request = 0.0
        self._entry_leaders: list[str] | None = None
        self._next_score_refresh = 0.0
        self._score_pending = False
        self._score_result: tuple[float, list[str], dict[str, dict[str, float]]] | None = None
        self._score_result_lock = threading.Lock()
        self._last_position_sync = 0.0
        self._position_data_healthy = False
        self._last_good_data = 0.0
        self._data_healthy = False
        self._account_stopped = False
        self._risk_state_load_failed = False
        self._risk_state_save_failed = False
        self._last_risk_state_checkpoint = -math.inf
        self._trend_reversal_cache: dict[str, tuple[Any, bool, Any, Any]] = {}
        self._exit_evaluation_failures: dict[str, int] = {}
        self._profit_shadow: dict[str, dict[str, Any]] = {}
        self._profit_pending_archives: dict[str, dict[str, Any]] = {}
        self._profit_totals: dict[str, Any] | None = None
        self._last_profit_summary = -math.inf
        self._profit_lock_failures = 0
        self._market_data_healthy = False
        self._market_down = False
        self._market_emergency = False
        self._market_valid_until = 0.0
        self._eth_last_log_reason: str | None = None
        self._eth_last_log_time = 0.0
        self._eth_blocked = False
        self._last_status_log = -math.inf
        self._last_status_signature: tuple | None = None
        self._entry_block_reason = "尚未评估"
        self._entry_decisions: dict[str, str] = {}
        self._exit_log_reasons: dict[str, str] = {}
        self._rotation_pair: str | None = None
        self._rotation_target: str | None = None
        self._rotation_state: dict[str, Any] | None = None
        self._rotation_candidate: tuple[str, str] | None = None
        self._rotation_seen = 0
        self._rotation_candidate_bar: float | None = None
        self._rotation_candidate_channel: str | None = None
        self._rotation_score_snapshot = 0.0
        self._last_rotation = 0.0
        self._liquidations: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self._liquidation_lock = threading.Lock()
        self._liquidation_connected = threading.Event()
        self._liquidation_started = 0.0
        self._liquidation_last_message = 0.0
        self._stop_event = threading.Event()
        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        state_file = (
            self.settings["state_file_dry_run"]
            if self.config.get("dry_run", True)
            else self.settings["state_file_live"]
        )
        self._state_path = user_data_dir / state_file
        self._risk_state = self._load_risk_state()
        stored_shadow = self._risk_state.get("profit_shadow")
        if isinstance(stored_shadow, dict):
            # Restore only complete records from the current schema version.
            self._profit_shadow = {
                pair: record
                for pair, record in stored_shadow.items()
                if self._valid_profit_record(pair, record)
            }
        stored_archives = self._risk_state.get("profit_pending_archives")
        if isinstance(stored_archives, dict):
            self._profit_pending_archives = {
                str(record["trade_id"]): record
                for record in stored_archives.values()
                if isinstance(record, dict)
                and isinstance(record.get("pair"), str)
                and self._valid_profit_record(record["pair"], record)
            }
        self._eth_blocked = bool(self._risk_state.get("eth_entry_blocked", False))
        self._rotation_state = self._risk_state.get("rotation")
        if self._rotation_state:
            self._rotation_pair = self._rotation_state["weak"]
            self._rotation_target = self._rotation_state["target"]
        self._last_rotation = float(self._risk_state.get("last_rotation", 0.0))
        self._sync_external_pairs()
        logger.info(
            "🚀 策略初始化 | 模式=%s | 杠杆=%.1fx 单笔占交易总资金=%.1f%% 最大仓位=%s | "
            "逐仓评分=%s | 状态日志间隔=%.0fs | 手动仓位框架对账=%s | 主动退出=%s",
            "模拟盘" if self.config.get("dry_run", True) else "实盘",
            self.settings["leverage"],
            100 * float(self.settings["stake_ratio"]),
            self.settings["max_positions"],
            "/".join(f"{value:g}" for value in self.settings["entry_slot_score_thresholds"]),
            self.settings["status_log_seconds"],
            "开启"
            if self.config.get("manual_position_sync", {}).get("enabled")
            and self.config.get("manual_position_sync", {}).get("import_positions")
            else "关闭",
            "开启"
            if self.config.get("manual_position_sync", {}).get(
                "auto_exit_positions",
                self.config.get("manual_position_sync", {}).get("auto_manage_positions", False),
            )
            else "关闭",
            extra=LOG_INFO,
        )
        logger.info(
            "🔒 盈利保护 | 棘轮=%s 峰值达%.2fR武装 跟踪距离=%.2fR "
            "回吐比例=%.0f%% 费用缓冲=%.2f%% 最小改单=%.2fR | 无进展退出=%s "
            "%s根%s未推进%.2fR且窗口内近期走弱/收益低于%.2fR",
            "开启" if self.settings["profit_lock_enabled"] else "关闭",
            self.settings["profit_lock_arm_r"],
            self.settings["profit_lock_trail_r"],
            100 * self.settings["profit_lock_giveback_frac"],
            100 * self.settings["profit_lock_fee_buffer"],
            self.settings["profit_lock_min_step_r"],
            "开启" if self.settings["profit_no_progress_enabled"] else "关闭",
            self.settings["profit_no_progress_candles"],
            self.settings["holding_timeframe"],
            self.settings["profit_no_progress_new_high_r"],
            self.settings["profit_no_progress_max_r"],
            extra=LOG_INFO,
        )

        if self.settings["weights"]["liquidation"] > 0:
            threading.Thread(
                target=self._liquidation_worker,
                name="leader-squeeze-liquidations",
                daemon=True,
            ).start()

    def ft_bot_cleanup(self) -> None:
        """请求关闭后台工作线程。"""
        stop_event = getattr(self, "_stop_event", None)
        if stop_event is not None:
            stop_event.set()
        super().ft_bot_cleanup()

    def informative_pairs(self):
        """保留主周期源K线; 小时趋势和背景由完整源K线聚合。"""
        if not getattr(self, "dp", None):
            return []
        pairs = set(self.dp.current_whitelist())
        pairs.add(self.ETH_PAIR)
        db_pairs = {trade.pair for trade in Trade.get_open_trades()}
        external = set(getattr(self, "_external_pairs", set()))
        pairs.update(db_pairs)
        pairs.update(external)
        return [(pair, self.timeframe) for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """填充策略接口所使用的指标。"""
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """仅为缓存排名中选出的候选交易对发出开仓信号。"""
        dataframe["enter_long"] = 0
        if (
            metadata["pair"] in self._entry_pairs
            and not dataframe.empty
            and self._eth_entries_allowed(time.time())
            and self._pair_score_current(metadata["pair"])
            and self._candle_metrics(metadata["pair"]) is not None
        ):
            dataframe.loc[dataframe.index[-1], ["enter_long", "enter_tag"]] = (
                1,
                self._rotation_entry_tag()
                if metadata["pair"] == getattr(self, "_rotation_target", None)
                else f"squeeze_{self._entry_score(metadata['pair']):.1f}",
            )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """退出交给 custom_exit 和框架程序止损; 历史交易所止损仍核对成交。"""
        dataframe["exit_long"] = 0
        return dataframe

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        """使用配置的杠杆。不超过市场允许的上限。"""
        return min(float(self.settings["leverage"]), max_leverage)

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        """同一交易资金基数按比例分仓, 不随已有仓位占用而逐笔递减。"""
        try:
            capital = float(self._wallets.get_total_stake_amount())
            target = capital * float(self.settings["stake_ratio"])
            if (
                not math.isfinite(target)
                or target <= 0
                or math.isnan(max_stake)
                or (min_stake is not None and not math.isfinite(min_stake))
            ):
                raise ValueError("invalid stake budget")
            if target > max_stake or (min_stake is not None and target < min_stake):
                logger.warning(
                    "⛔ 等额分仓 %s | 资金基准=%.2f 目标保证金=%.2f "
                    "可下单上限=%.2f 最小保证金=%s | 金额不满足限制, 跳过",
                    pair,
                    capital,
                    target,
                    max_stake,
                    min_stake,
                    extra=LOG_WARN,
                )
                return 0.0
            logger.info(
                "💰 等额分仓 %s | 交易资金基准=%.2f 比例=%.1f%% 保证金=%.2f 杠杆=%.1fx",
                pair,
                capital,
                100 * float(self.settings["stake_ratio"]),
                target,
                leverage,
                extra=LOG_INFO,
            )
            return target
        except Exception as exc:
            # Returning zero prevents the framework's proposed-stake exception fallback.
            logger.warning("⛔ 分仓资金计算失败 %s (%s), 跳过开仓", pair, type(exc).__name__)
            return 0.0

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        """按实际数量复核盘口; 缓存到期时仅补取一次, 不放宽5秒时效。"""
        allowed = (
            side == "long"
            and pair in self._entry_pairs
            and self._entries_allowed(time.time())
            and pair not in self._external_pairs
        )
        if allowed and self._candle_metrics(pair) is None:
            self._entry_block_reason = "当前交易对K线缺失、过期或无效"
            allowed = False
        if allowed and (reason := self._confirmation_quality_reason(pair)):
            self._entry_block_reason = reason
            allowed = False
        if allowed and not self._entry_pair_available(pair):
            self._entry_block_reason = self._pair_entry_block_reason
            allowed = False
        if allowed:
            allowed = self._entry_slot_available(pair, entry_tag)
        if allowed and not self._execution_is_safe(pair, amount=amount):
            self._entry_block_reason = self._execution_block_reason
            allowed = False
        # 补取盘口可能跨过行情/ETH有效期, 网络调用后再次确认开仓条件。
        if allowed:
            allowed = self._entries_allowed(time.time())
        if allowed and (reason := self._confirmation_quality_reason(pair)):
            self._entry_block_reason = reason
            allowed = False
        if allowed and pair == getattr(self, "_rotation_target", None):
            allowed = self._prepare_rotation_buy(pair, amount)
        if allowed:
            self._record_approved_entry_score(pair, entry_tag)
            reason = "通过复核, 等待框架下单 (尚未成交)"
        elif side != "long":
            reason = "策略仅允许多单"
        elif pair not in self._entry_pairs:
            reason = "不在本轮入选名单"
        else:
            reason = self._entry_block_reason or "交易对已有外部仓位"
        self._audit_entry_confirmation(pair, allowed, reason, amount, rate)
        logger.info(
            "%s 开仓复核 %s | 方向=%s 数量=%.8f 参考价=%.8f | %s",
            "✅" if allowed else "⛔",
            pair,
            side,
            amount,
            rate,
            reason,
            extra=LOG_GOOD if allowed else LOG_WARN,
        )
        return allowed

    def _prune_pending_entry_scores(self, now: float) -> None:
        pending = getattr(self, "_pending_entry_scores", {})
        if not pending:
            return
        active = {trade.pair for trade in Trade.get_open_trades()}
        self._pending_entry_scores = {
            pair: snapshot
            for pair, snapshot in pending.items()
            if pair in active
            or 0 <= now - snapshot["confirmed_at"] <= self.settings["data_grace_seconds"]
        }

    def _record_approved_entry_score(self, pair: str, entry_tag: str | None) -> None:
        """Keep the approved score without making diagnostic failures block an order."""
        pending = getattr(self, "_pending_entry_scores", {})
        pending.pop(pair, None)
        self._pending_entry_scores = pending
        try:
            score = self._entry_score(pair)
            if math.isfinite(score):
                pending[pair] = {
                    "score": score,
                    "tag": entry_tag,
                    "confirmed_at": time.time(),
                }
        except Exception as exc:
            logger.warning("开仓评分记录失败 %s: %s", pair, type(exc).__name__)

    def order_filled(
        self, pair: str, trade: Trade, order: Order, current_time: datetime, **kwargs
    ) -> None:
        """Persist the approved entry score on the first entry fill, including rotations."""
        if order.ft_order_side == trade.entry_side and (order.filled or 0) > 0:
            # 尽量在成交当刻冻结 ATR1h; 影子账本每轮也会补齐缺失记录。
            self._capture_profit_entry_context(trade)
        state = getattr(self, "_rotation_state", None) or {}
        if pair in (state.get("weak"), state.get("target")):
            self._record_rotation_event(
                "order_filled",
                "轮换关联订单成交回调",
                {
                    "pair": pair,
                    "trade_id": trade.id,
                    "order": {
                        key: getattr(order, key, None)
                        for key in (
                            "order_id",
                            "ft_order_side",
                            "filled",
                            "average",
                            "price",
                            "status",
                        )
                    },
                },
            )
        if (
            order.ft_order_side != trade.entry_side
            or not order.filled
            or order.filled <= 0
            or trade.get_custom_data("leader_entry_score")
        ):
            return
        pending = getattr(self, "_pending_entry_scores", {})
        snapshot = pending.get(pair)
        if (
            snapshot
            and snapshot["tag"] == trade.enter_tag
            and trade.open_date_utc.timestamp() >= snapshot["confirmed_at"] - 1
        ):
            trade.set_custom_data(
                "leader_entry_score",
                {
                    "score": snapshot["score"],
                    "source": "confirmation",
                },
            )
            pending.pop(pair, None)

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        """盈利棘轮: 峰值达 1R 后保本, 按双重回吐上限单调跟踪。

        回吐额度取 ``profit_lock_trail_r * R`` 与
        ``profit_lock_giveback_frac * (峰值价格 - 入场价格)`` 中的较小值,
        再与费用地板比较, 避免只按固定的峰值减 1.5R 跟踪。

        由 ``leader_squeeze.profit_lock_enabled`` 门控, 关闭时恒返回 None, 框架
        回退到配置的 ``stoploss``, 行为与未接入前完全一致。返回值为保证金口径, 由
        ``_profit_lock_stoploss`` 用 ``stoploss_from_absolute`` 统一换算。
        """
        if not self.settings["profit_lock_enabled"]:
            return None
        try:
            result = self._profit_lock_stoploss(pair, trade, current_rate, current_time)
            self._profit_lock_failures = 0
            return result
        except Exception:
            self._profit_lock_failures = getattr(self, "_profit_lock_failures", 0) + 1
            # 框架层对本方法只记 debug 日志, 失败会静默冻结棘轮, 所以这里必须自己告警。
            logger.exception(
                "🚨 盈利棘轮计算异常 %s | 连续失败=%s | 本轮不改动止损 "
                "(adjust_stop_loss 只向上移动, 不会放松既有止损)",
                pair,
                self._profit_lock_failures,
                extra=LOG_ERROR,
            )
            return None

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        """因市场普跌、计划中的轮换或确认的趋势反转而退出。"""
        try:
            if self._market_exit_required():
                reason = "market_emergency"
            elif self._rotation_exit_allowed(pair):
                reason = "leader_rotation"
            elif self._trend_reversed(pair):
                reason = "trend_reversal"
            elif self._profit_no_progress_exit(pair, trade, current_rate):
                reason = "leader_no_progress"
            else:
                reason = None
            getattr(self, "_exit_evaluation_failures", {}).pop(pair, None)
        except Exception:
            failure_counts = getattr(self, "_exit_evaluation_failures", {})
            failures = failure_counts.get(pair, 0) + 1
            failure_counts[pair] = failures
            self._exit_evaluation_failures = failure_counts
            limit = int(self.settings["exit_evaluation_failure_limit"])
            logger.exception(
                "🚨 退出评估异常 %s | 连续失败=%s | 本轮不生成策略退出信号, "
                "框架与交易所保护止损路径不受本异常影响",
                pair,
                failures,
                extra=LOG_ERROR,
            )
            if failures == limit:
                try:
                    self.dp.send_msg(
                        f"🚨 {pair} 退出评估已连续失败 {failures} 次; 暂停所有新开仓, "
                        "现有仓位仍由框架与交易所保护止损管理。"
                    )
                except Exception:
                    logger.exception("退出评估异常告警发送失败 %s", pair, extra=LOG_ERROR)
            return None
        logged = getattr(self, "_exit_log_reasons", {})
        log_key = (reason, self._trend_exit_rule(pair)) if reason == "trend_reversal" else reason
        if reason and logged.get(pair) != log_key:
            descriptions = {
                "market_emergency": "龙头市场严重普跌",
                "leader_rotation": "龙头轮换",
                "trend_reversal": "持仓趋势反转 | "
                + getattr(self, "_trend_exit_details", {}).get(pair, "多周期趋势退出"),
                "leader_no_progress": "动量论点失效 | "
                f"{self.settings['profit_no_progress_candles']}根"
                f"{self.settings['holding_timeframe']}未推进"
                f"{self.settings['profit_no_progress_new_high_r']:.2f}R且趋势走弱",
            }
            logger.info(
                "🚪 退出信号 %s | 原因=%s | 当前收益=%.2f%% | 等待框架执行, 尚非成交确认",
                pair,
                descriptions[reason],
                current_profit * 100,
                extra=LOG_WARN,
            )
            logged[pair] = log_key
        elif not reason:
            logged.pop(pair, None)
        self._exit_log_reasons = logged
        return reason

    @decision_snapshot
    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """刷新仓位状态。安排非阻塞的行情数据任务。"""
        # Revoke the previous signal before any stage can fail.
        self._entry_pairs.clear()
        now = time.time()
        self._prune_pending_entry_scores(now)
        journal = getattr(self, "_rotation_journal", None)
        if journal is not None:
            journal.flush(now)
        if now - self._last_position_sync >= self.settings["position_sync_seconds"]:
            try:
                self._wallets.update(require_update=True)
                positions = self._exchange.fetch_positions()
                self._position_details = {
                    position["symbol"]: position
                    for position in positions
                    if float(position.get("contracts") or 0) != 0
                }
                self._last_position_sync = now
                self._position_data_healthy = True
            except Exception as exc:
                logger.warning("⚠️ 仓位同步失败, 暂停新开仓: %s", exc, extra=LOG_WARN)
                self._position_data_healthy = False
        self._sync_external_pairs()
        eth_allowed = self._eth_entries_allowed(now)
        eth_reason = self._eth_block_reason if not eth_allowed else self._eth_trend
        if eth_reason != self._eth_last_log_reason or (
            now - self._eth_last_log_time >= float(self.settings["status_log_seconds"])
        ):
            logger.info(
                "%s ETH %s/%s 过滤: %s | %s",
                "⛔" if not eth_allowed else "✅",
                self.timeframe,
                self.settings["holding_timeframe"],
                f"{eth_reason}; 暂停评分、选币、新轮换和新开仓, 已有仓位继续止损和退出; "
                "已提交轮换继续核对成交"
                if not eth_allowed
                else "不拦截, ETH 条件允许开仓 (仍需通过其他风控检查)",
                self._eth_trend_summary,
                extra=LOG_WARN if not eth_allowed else LOG_GOOD,
            )
            self._eth_last_log_reason = eth_reason
            self._eth_last_log_time = now
        if not eth_allowed:
            self._record_rotation_event("blocked", self._eth_block_reason, once=True)
            self._entry_pairs.clear()
            if not self._rotation_in_flight():
                self._clear_rotation("ETH过滤暂停开仓")
            self._rotation_candidate, self._rotation_seen = None, 0
        # Pairlist selection defines market breadth. Open holdings are appended by the
        # framework only to keep their candles available and must not change this universe.
        self._entry_leaders = self.dp.current_selection_whitelist()
        self._consume_score_refresh(now, allow_scoring=eth_allowed)
        # 普跌退出仅依赖本地K线, ETH拦截或远程接口失败时也必须重新评估。
        leaders = self._entry_leaders
        self._update_market_state(
            leaders,
            {pair: item for pair in leaders if (item := self._candle_metrics(pair)) is not None},
        )
        self._advance_score_refresh(now, allow_scoring=eth_allowed)
        if now >= self._next_score_refresh and not self._score_pending:
            self._start_score_refresh(now, exit_only=not eth_allowed)
        self._update_profit_shadow(now, current_time)
        self._refresh_risk_state(current_time)
        self._sync_rotation_state()
        if eth_allowed:
            self._plan_rotation(now, current_time)
        self._entry_pairs = self._select_entries()
        self._log_strategy_status(now)

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        if not math.isfinite(value):
            return low
        return max(low, min(high, value))

    def _required_leader_count(self, total: int) -> int:
        if not total:
            return 0
        return min(
            total,
            max(1, math.ceil(total * float(self.settings["market_min_coverage_ratio"]))),
        )

    def _update_market_state(
        self, leaders: list[str], candle_metrics: dict[str, dict[str, float]]
    ) -> None:
        required = self._required_leader_count(len(leaders))
        available = [candle_metrics[pair] for pair in leaders if pair in candle_metrics]
        self._market_valid_until = min(
            (item.get("_candle_valid_until", 0.0) for item in available), default=0.0
        )
        self._market_data_healthy = bool(required) and len(available) >= required
        self._market_emergency = False
        if not self._market_data_healthy:
            self._market_down = False
            return
        down_required = math.ceil(len(leaders) * float(self.settings["market_down_ratio"]))
        min_momentum = float(self.settings["min_absolute_momentum"])
        self._market_down = (
            sum(item["momentum"] <= min_momentum for item in available) >= down_required
        )
        self._market_emergency = sum(
            item["momentum"] <= -self.settings["market_emergency_drop"] for item in available
        ) >= math.ceil(len(leaders) * self.settings["market_emergency_ratio"])
        self._market_down = self._market_down or self._market_emergency

    def _market_exit_required(self) -> bool:
        """Ordinary breadth weakness blocks entries; only a severe decline forces exits."""
        return bool(
            self.settings["market_emergency_enabled"]
            and getattr(self, "_market_emergency", False)
            and self._market_is_down()
        )

    def _market_is_down(self) -> bool:
        if not self._market_down:
            return False
        if time.time() > getattr(self, "_market_valid_until", 0.0):
            self._warn_data_unavailable("市场普跌", "K线判断已过期, 等待新数据")
            self._market_down = False
            self._market_emergency = False
            self._market_data_healthy = False
            return False
        return True

    def _price_components(self, item: dict[str, float]) -> tuple[float, float, float]:
        price_weight = self.settings["momentum_return_weight"]
        return (
            price_weight * self._clamp(item["momentum"] / self.settings["momentum_full_score"])
            + (1 - price_weight) * self._clamp(item["trend_continuity"]),
            self.settings["volume_activity_weight"]
            * self._clamp(
                (item["volume_activity_ratio"] - 1)
                / (self.settings["volume_activity_full_ratio"] - 1)
            )
            + (1 - self.settings["volume_activity_weight"])
            * self._clamp(
                (item["volume_ratio"] - 1) / (self.settings["volume_score_full_ratio"] - 1)
            ),
            self._clamp((item["taker_ratio"] - 1) / (self.settings["taker_score_full_ratio"] - 1)),
        )

    def _apply_scores(
        self,
        now: float,
        valid: dict[str, dict[str, float]],
        all_metrics: dict[str, dict[str, float]],
    ) -> None:
        weights = self.settings["weights"]
        scores: dict[str, float] = {}
        for pair, item in valid.items():
            # 使用固定尺度, 同币分数不随候选池/持仓变化, 也不随硬门槛调整而漂移。
            momentum_score, volume_score, taker_score = self._price_components(item)
            oi_score = (
                self._clamp(-item["oi_change"] / self.settings["oi_score_full_drop"])
                if weights["oi_squeeze"] > 0 and item["momentum"] > 0 and item["oi_change"] < 0
                else 0.0
            )
            components = {
                "momentum": momentum_score,
                "volume": volume_score,
                "taker_buy": taker_score,
                "liquidation": (
                    self._liquidation_score(self._market_id(pair), now)
                    if weights["liquidation"] > 0
                    else 0.0
                ),
                "oi_squeeze": oi_score,
                "funding": self._funding_score(item, now),
            }
            item.update({f"score_{name}": value for name, value in components.items()})
            contributions = {
                name: 100.0 * weights[name] * value for name, value in components.items()
            }
            scores[pair] = sum(contributions.values())

        self._scores = scores
        self._metrics = all_metrics
        self._last_score_refresh = now
        self._last_good_data = now
        self._data_healthy = True
        self._log_score_tables(now, valid)

    def _funding_score(self, metric: dict[str, float], now: float) -> float:
        rate = metric.get("funding_rate_hourly", math.nan)
        floor = metric.get("funding_floor_hourly", math.nan)
        cap = metric.get("funding_cap_hourly", math.nan)
        if not (metric.get("_funding_valid_until", 0) > now and math.isfinite(rate)):
            return 0.0
        if rate < 0 and math.isfinite(floor) and floor < 0:
            return self._clamp(-rate / -floor)
        if rate > 0 and math.isfinite(cap) and cap > 0:
            return -self._clamp(rate / cap)
        return 0.0

    def _current_score(self, pair: str, now: float | None = None) -> float:
        """资金数据过期/跨结算时去掉费率调整, 不延长或否定核心数据时效。"""
        metric = getattr(self, "_metrics", {}).get(pair, {})
        points = 100 * float(self.settings["weights"].get("funding", 0))
        return self._scores.get(pair, math.nan) + points * (
            self._funding_score(metric, time.time() if now is None else now)
            - metric.get("score_funding", 0.0)
        )

    def _entry_score(self, pair: str) -> float:
        """Discount prospective buys without weakening the score of an existing holding."""
        score = self._current_score(pair)
        if not self.settings["entry_heat_max_penalty"]:
            return score
        heat = self._entry_heat_metrics(pair)
        return score * (1 - heat["penalty"]) if heat is not None else math.nan

    @report_cached
    def _entry_heat_metrics(self, pair: str) -> dict[str, float] | None:
        """Measure long-run heat and recognize a breakout in either of the last two bars."""
        frame = self._closed_candles(
            pair,
            self.timeframe,
            self.ENTRY_HEAT_HISTORY_CANDLES,
            columns=("high", "low", "close"),
        )
        if frame is None:
            return None
        frame = frame.tail(self.ENTRY_HEAT_HISTORY_CANDLES)
        if ((frame["low"] > frame["close"]) | (frame["high"] < frame["close"])).any():
            self._warn_data_unavailable(f"{pair} 入场过热", "K线高低收关系无效")
            return None
        reference = frame.iloc[:-1]
        atr = self._wilder_atr(reference)
        if not math.isfinite(atr) or atr <= 0:
            self._warn_data_unavailable(f"{pair} 入场过热", "ATR14缺少有效波动")
            return None
        close = float(frame["close"].iloc[-1])
        ema = float(
            reference["close"]
            .ewm(span=self.settings["entry_heat_ema_candles"], adjust=False)
            .mean()
            .iloc[-1]
        )
        gain = close / float(frame["close"].iloc[0]) - 1
        extension = (close - ema) / atr
        growth = self._clamp(gain / float(self.settings["entry_heat_return_scale"]))
        start = float(self.settings["entry_heat_extension_start_atr"])
        full = float(self.settings["entry_heat_extension_full_atr"])
        heat = self._clamp((extension - start) / (full - start))
        box = reference.tail(self.settings["entry_heat_box_candles"])
        box_high, box_low = float(box["high"].max()), float(box["low"].min())
        breakout_age = math.nan
        breakout_distance = math.nan
        breakout_box_width = (box_high - box_low) / atr
        launch_candles = int(self.settings["entry_setup_launch_candles"])
        for age in range(launch_candles):
            signal_index = len(frame) - 1 - age
            signal_reference = frame.iloc[:signal_index]
            if len(signal_reference) < max(
                self.settings["entry_heat_ema_candles"],
                self.settings["entry_heat_box_candles"],
                self.settings["atr_period"] + 1,
            ):
                continue
            signal_atr = self._wilder_atr(signal_reference)
            if not math.isfinite(signal_atr) or signal_atr <= 0:
                continue
            signal_ema = float(
                signal_reference["close"]
                .ewm(span=self.settings["entry_heat_ema_candles"], adjust=False)
                .mean()
                .iloc[-1]
            )
            signal_box = signal_reference.tail(self.settings["entry_heat_box_candles"])
            signal_high = float(signal_box["high"].max())
            signal_low = float(signal_box["low"].min())
            signal_close = float(frame["close"].iloc[signal_index])
            if (
                signal_high - signal_low
                <= self.settings["entry_heat_box_max_width_atr"] * signal_atr
                and abs(float(signal_reference["close"].iloc[-1]) - signal_ema)
                <= self.settings["entry_heat_prebreak_extension_max_atr"] * signal_atr
                and signal_high
                < signal_close
                <= signal_high + self.settings["entry_heat_breakout_overshoot_atr"] * signal_atr
                and close >= signal_high
            ):
                breakout_age = float(age)
                breakout_distance = (close - signal_high) / signal_atr
                breakout_box_width = (signal_high - signal_low) / signal_atr
                box_high, box_low = signal_high, signal_low
                break
        cooled_breakout = math.isfinite(breakout_age)
        base = self.settings["entry_heat_base_fraction"]
        penalty = (
            float(self.settings["entry_heat_max_penalty"]) * growth * (base + (1 - base) * heat)
        )
        if cooled_breakout:
            penalty *= self.settings["entry_heat_cooled_breakout_factor"]
        result = {
            "return_15d": gain,
            "extension_atr": extension,
            "cooled_breakout": float(cooled_breakout),
            "breakout_age_candles": breakout_age,
            "breakout_distance_atr": breakout_distance,
            "box_width_atr": breakout_box_width,
            "penalty": penalty,
            "reference_ema": ema,
            "reference_atr": atr,
            "box_high": box_high,
            "box_low": box_low,
        }
        return result

    def _entry_setup_metrics(self, pair: str) -> dict[str, float | str] | None:
        """Score entry location separately so raw strength cannot hide a late chase."""
        if not self.settings["entry_setup_enabled"]:
            return {"stage": "中继", "score": 100.0, "late": 0.0}
        heat = self._entry_heat_metrics(pair)
        if heat is None:
            return None
        extension = heat.get("extension_atr")
        box_width = heat.get("box_width_atr")
        if extension is None or box_width is None:
            # Compatibility for diagnostic/test doubles which only expose the discount.
            return {"stage": "中继", "score": 100.0, "late": 0.0}
        late_atr = float(self.settings["entry_setup_late_extension_atr"])
        start_atr = float(self.settings["entry_heat_extension_start_atr"])
        launch = bool(heat.get("cooled_breakout"))
        late = float(extension) >= late_atr
        stage = "末端" if late else "启动" if launch else "中继"
        extension_quality = self._clamp(
            (late_atr - max(0.0, float(extension))) / max(late_atr - start_atr, 1e-9)
        )
        compression_quality = self._clamp(
            1 - float(box_width) / max(float(self.settings["entry_heat_box_max_width_atr"]), 1e-9)
        )
        points = self.settings["entry_setup_score_points"]
        if launch:
            distance = max(0.0, float(heat.get("breakout_distance_atr", 0.0)))
            proximity_quality = self._clamp(
                1 - distance / max(float(self.settings["entry_setup_late_extension_atr"]), 1e-9)
            )
            stage_points = float(points["launch"])
        else:
            proximity_quality = extension_quality
            stage_points = 0.0 if late else float(points["continuation"])
        score = (
            stage_points
            + float(points["extension"]) * extension_quality
            + float(points["compression"]) * compression_quality
            + float(points["proximity"]) * proximity_quality
        )
        return {
            "stage": stage,
            "score": score,
            "late": float(late),
            "extension_atr": float(extension),
            "box_width_atr": float(box_width),
            "breakout_age_candles": float(heat.get("breakout_age_candles", math.nan)),
        }

    @report_cached
    def _candle_metrics(self, pair: str) -> dict[str, float] | None:
        minimum = max(
            self.settings["candle_min_history"],
            self.settings["momentum_lookback_candles"] + 1,
            self.settings["trend_continuity_candles"] + 1,
            self.settings["volume_window_candles"]
            + max(
                self.settings["volume_baseline_windows"],
                self.settings["volume_activity_baseline_candles"],
            ),
        )
        dataframe = self._closed_candles(pair, self.timeframe, minimum, columns=("close", "volume"))
        if dataframe is None or not {"close", "volume"}.issubset(dataframe.columns):
            return None
        close = dataframe["close"]
        recent_trend = (
            close.iloc[-self.settings["trend_continuity_candles"] - 1 :].pct_change().dropna()
        )
        window = self.settings["volume_window_candles"]
        recent_volume = float(dataframe["volume"].tail(window).mean())
        reference = dataframe["volume"].iloc[:-window]
        baseline = float(reference.tail(self.settings["volume_baseline_windows"]).mean())
        activity_baseline = float(
            reference.tail(self.settings["volume_activity_baseline_candles"]).mean()
        )
        return {
            "momentum": float(
                close.iloc[-1] / close.iloc[-self.settings["momentum_lookback_candles"] - 1] - 1.0
            ),
            "trend_continuity": float((recent_trend > 0).mean()),
            # A zero-volume reference is not evidence of a liquid, active market.
            "volume_ratio": recent_volume / baseline if baseline > 0 else 1.0,
            "volume_activity_ratio": (
                recent_volume / activity_baseline if activity_baseline > 0 else 1.0
            ),
            "volume_recent_mean": recent_volume,
            "volume_short_baseline": baseline,
            "volume_activity_baseline": activity_baseline,
            "_candle_valid_until": dataframe["date"].iloc[-1].timestamp()
            + 2 * timeframe_to_seconds(self.timeframe)
            + float(self.settings["data_grace_seconds"]),
        }

    def _ranked_pairs(self) -> list[tuple[str, float]]:
        leaders = getattr(self, "_entry_leaders", None)
        return sorted(
            (
                (pair, self._entry_score(pair))
                for pair in self._scores
                if leaders is None or pair in leaders
            ),
            key=lambda item: item[1] if math.isfinite(item[1]) else -math.inf,
            reverse=True,
        )

    def _entry_slot_score_floor(self, slot_index: int) -> float:
        thresholds = self.settings["entry_slot_score_thresholds"]
        return float(thresholds[min(max(0, slot_index), len(thresholds) - 1)])

    @staticmethod
    def _funnel_reason_summary(reasons: list[str], limit: int = 3) -> str:
        counts: dict[str, int] = {}
        for reason in reasons:
            label = reason.split(":", 1)[0]
            counts[label] = counts.get(label, 0) + 1
        return (
            "; ".join(
                f"{label}x{count}"
                for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
                    :limit
                ]
            )
            or "—"
        )

    def _entry_setup_shortlist(
        self,
        ranked: list[tuple[str, float]],
        rotation_target: str | None,
    ) -> list[tuple[str, float, dict[str, float | str]]]:
        eligible: list[tuple[str, float, dict[str, float | str]]] = []
        rejected: list[str] = []
        for pair, score in ranked:
            reason = self._entry_eligibility_reason(pair)
            if reason:
                self._entry_decisions[pair] = reason
                rejected.append(reason)
                continue
            setup = self._entry_setup_snapshot.get(pair)
            if setup is None:
                reason = "入场形态所需15日行情不足或无效"
                self._entry_decisions[pair] = reason
                rejected.append(reason)
                continue
            self._entry_setup_snapshot[pair] = setup
            eligible.append((pair, score, setup))
        self._entry_funnel_rows.append(
            [
                "2 硬条件/形态",
                str(len(ranked)),
                str(len(eligible)),
                str(len(ranked) - len(eligible)),
                self._funnel_reason_summary(rejected),
            ]
        )

        if rotation_target or not self.settings["entry_setup_enabled"]:
            shortlisted = eligible
        else:
            shortlist_count = min(
                len(eligible),
                max(
                    int(self.settings["entry_setup_min_candidates"]),
                    math.ceil(len(eligible) * float(self.settings["entry_setup_shortlist_ratio"])),
                ),
            )
            shortlisted = sorted(
                eligible,
                key=lambda item: (float(item[2]["score"]), item[1], item[0]),
                reverse=True,
            )[:shortlist_count]
        shortlist_pairs = {item[0] for item in shortlisted}
        shortlist_ratio = 100 * float(self.settings["entry_setup_shortlist_ratio"])
        for pair, _, setup in eligible:
            if pair not in shortlist_pairs:
                self._entry_decisions[pair] = (
                    f"形态排名未进前{shortlist_ratio:.0f}% (形态{float(setup['score']):.1f})"
                )
        self._entry_funnel_rows.append(
            [
                "3 形态短名单",
                str(len(eligible)),
                str(len(shortlisted)),
                str(len(eligible) - len(shortlisted)),
                "轮换目标单独复核"
                if rotation_target
                else "形态筛选关闭"
                if not self.settings["entry_setup_enabled"]
                else (
                    f"前{shortlist_ratio:.0f}%, 至少{self.settings['entry_setup_min_candidates']}个"
                ),
            ]
        )
        return shortlisted

    def _select_strength_entries(
        self,
        shortlisted: list[tuple[str, float, dict[str, float | str]]],
        *,
        occupied_count: int,
        capacity: int,
        rotation_target: str | None,
    ) -> set[str]:
        ranked = sorted(shortlisted, key=lambda item: (item[1], item[0]), reverse=True)
        selected: list[str] = []
        score_passed = 0
        score_failed = 0
        capacity_skipped = 0
        execution_reasons: list[str] = []
        limit = int(self.settings["max_positions"])
        for pair, score, setup in ranked:
            if len(selected) >= capacity:
                self._entry_decisions[pair] = "本轮剩余名额已用完"
                capacity_skipped += 1
                continue
            slot_index = min(occupied_count + len(selected), limit - 1)
            score_floor = self._entry_slot_score_floor(slot_index)
            if pair == rotation_target:
                channel = (getattr(self, "_rotation_state", None) or {}).get("channel", "normal")
                score_floor = self._rotation_floor(channel)
            if not math.isfinite(score) or score < score_floor:
                self._entry_decisions[pair] = (
                    f"强度评分 {score:.1f} < 第{slot_index + 1}仓门槛 {score_floor:.1f}"
                )
                score_failed += 1
                continue
            score_passed += 1
            if not (self._entry_pair_available(pair) and self._execution_is_safe(pair)):
                reason = getattr(self, "_pair_entry_block_reason", "") or getattr(
                    self, "_execution_block_reason", "盘口安全检查未通过"
                )
                self._entry_decisions[pair] = reason
                execution_reasons.append(reason)
                continue
            selected.append(pair)
            self._entry_slot_assignments[pair] = slot_index
            setup_enabled = self.settings["entry_setup_enabled"]
            setup_label = f"形态{float(setup['score']):.1f}" if setup_enabled else "形态关闭"
            self._entry_decisions[pair] = (
                f"入选第{slot_index + 1}仓: {setup_label} 强度{score:.1f}>={score_floor:.1f}"
            )
            self._entry_funnel_candidates.append(
                [
                    pair,
                    str(slot_index + 1),
                    str(setup["stage"]) if setup_enabled else "关闭",
                    f"{float(setup['score']):.1f}" if setup_enabled else "—",
                    f"{score:.1f}",
                    f"{score_floor:.1f}",
                ]
            )
        self._entry_funnel_rows.extend(
            [
                [
                    "4 强度/逐仓门槛",
                    str(score_passed + score_failed),
                    str(score_passed),
                    str(score_failed),
                    f"{limit}级门槛逐仓递增",
                ],
                [
                    "5 交易资格/盘口",
                    str(score_passed),
                    str(len(selected)),
                    str(score_passed - len(selected)),
                    self._funnel_reason_summary(execution_reasons),
                ],
                [
                    "6 容量截断",
                    str(len(ranked)),
                    str(len(ranked) - capacity_skipped),
                    str(capacity_skipped),
                    f"本轮可用名额{capacity}",
                ],
            ]
        )
        return set(selected)

    def _select_entries(self) -> set[str]:
        self._entry_decisions = {}
        self._entry_slot_assignments = {}
        self._entry_setup_snapshot = {}
        self._entry_funnel_rows = []
        self._entry_funnel_candidates = []
        if not self._entries_allowed(time.time()):
            return set()

        db_open = {trade.pair for trade in Trade.get_open_trades()}
        occupied = db_open | self._external_pairs
        self._entry_decisions.update({pair: "已持仓" for pair in sorted(occupied)})
        rotation_target = getattr(self, "_rotation_target", None)
        limit = int(self.settings["max_positions"])
        capacity = min(1, limit + 1 - len(occupied)) if rotation_target else limit - len(occupied)
        if capacity <= 0:
            self._entry_decisions.update(
                {pair: "仓位已满" for pair in self._scores if pair not in occupied}
            )
            self._entry_funnel_rows = [
                ["仓位容量", str(len(self._scores)), "0", str(len(self._scores)), "仓位已满"]
            ]
            return set()

        ranked = [item for item in self._ranked_pairs() if item[0] not in occupied]
        if rotation_target:
            ranked = [item for item in ranked if item[0] == rotation_target]
        self._entry_funnel_rows.append(
            ["1 候选池", str(len(ranked)), str(len(ranked)), "0", "排除已有仓位后"]
        )
        shortlisted = self._entry_setup_shortlist(ranked, rotation_target)
        return self._select_strength_entries(
            shortlisted,
            occupied_count=len(occupied),
            capacity=capacity,
            rotation_target=rotation_target,
        )

    def _confirmation_quality_reason(self, pair: str) -> str:
        """成交前按实时仓位数和有效资金费加分复核, 防止追加仓误用基础门槛。"""
        try:
            occupied = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
            rotation = pair == getattr(self, "_rotation_target", None)
            if rotation and self._rotation_pair is None:
                return "轮换旧仓缺失"
            assigned = getattr(self, "_entry_slot_assignments", {}).get(pair, len(occupied))
            floor = self._entry_slot_score_floor(max(len(occupied), assigned))
            if rotation:
                channel = (getattr(self, "_rotation_state", None) or {}).get("channel", "normal")
                floor = self._rotation_floor(channel)
            reason = self._entry_quality_reason(pair, floor)
            if reason:
                return reason
            if (
                rotation
                and self._rotation_pair is not None
                and not self._rotation_scores_qualify(self._rotation_pair, pair)
            ):
                return "轮换分差或目标评分不再达标"
            state = getattr(self, "_rotation_state", None) or {}
            if rotation and "channel" in state:
                if self._rotation_pair is None:
                    return "轮换旧仓缺失"
                if len(occupied) != self.settings["max_positions"]:
                    return "仓位数量已变化, 重新评估普通开仓"
                if not self._pair_score_current(self._rotation_pair):
                    return "轮换旧仓评分过期"
                if not self._rotation_signal_valid(self._rotation_pair, pair, state["channel"]):
                    return "轮换突破或旧仓小时走弱条件不再成立"
            return ""
        except Exception as exc:
            logger.warning("⚠️ 开仓质量/仓位复核异常 %s: %s", pair, exc, extra=LOG_WARN)
            return f"开仓质量/仓位复核异常 ({type(exc).__name__})"

    def _entry_quality_reason(self, pair: str, score_floor: float) -> str:
        """选币、轮换和下单复核共用质量门槛, 全局风控仍独立硬拦截。"""
        reason = self._entry_eligibility_reason(pair)
        if reason:
            return reason
        score = self._entry_score(pair)
        if not math.isfinite(score):
            return "买入评分缺失或无效 (需完整有效的15日行情)"
        if score < score_floor:
            return f"评分 {score:.1f} < 门槛 {score_floor:.1f}"
        return ""

    def _entry_eligibility_reason(self, pair: str) -> str:
        """Apply hard data, momentum, setup and trend gates before strength ranking."""
        if not self._pair_score_current(pair):
            return "评分指标缺失、过期或无效"
        if time.time() < getattr(self, "_risk_state", {}).get("rotation_reentry_until", {}).get(
            pair, 0
        ):
            return "刚被轮换退出, 重新买入冷却中"
        # 评分可以缓存, 入场趋势必须按当前已收盘K线重算。
        candle = self._candle_metrics(pair)
        if candle is None:
            return "当前交易对K线缺失、过期或无效"
        if not (
            candle.get("momentum", -math.inf) > float(self.settings["min_absolute_momentum"])
            and candle.get("trend_continuity", 0.0) >= float(self.settings["min_trend_continuity"])
        ):
            return (
                f"上涨条件不足: 1h涨幅={candle.get('momentum', 0):.2%}, "
                f"上涨连续性={candle.get('trend_continuity', 0):.0%}"
            )
        setup = self._entry_setup_metrics(pair)
        if setup is None:
            return "入场形态所需15日行情不足或无效"
        setup_snapshot = getattr(self, "_entry_setup_snapshot", {})
        setup_snapshot[pair] = setup
        self._entry_setup_snapshot = setup_snapshot
        if setup["late"]:
            return (
                f"末端过热: 偏离{float(setup.get('extension_atr', math.nan)):.1f}ATR >= "
                f"{float(self.settings['entry_setup_late_extension_atr']):.1f}ATR"
            )
        if float(setup["score"]) < float(self.settings["entry_setup_min_score"]):
            return (
                f"形态评分 {float(setup['score']):.1f} < "
                f"{float(self.settings['entry_setup_min_score']):.1f}"
            )
        reversed_trend = self._trend_reversed(pair)
        if reversed_trend is None:
            return "趋势退出指标不足或无效, 禁止开仓"
        if reversed_trend:
            return f"趋势退出: {self._trend_exit_rule(pair)}, 禁止开仓"
        return self._higher_entry_reason(pair)

    def _entry_pair_available(self, pair: str) -> bool:
        """复用框架交易锁, 同时排除已离开当前交易名单的候选。"""
        self._pair_entry_block_reason = ""
        try:
            if pair not in self.dp.current_whitelist():
                self._pair_entry_block_reason = "已离开当前交易名单"
            else:
                candles = self._closed_candles(pair, self.timeframe, 1)
                if candles is None:
                    self._pair_entry_block_reason = "交易锁复核所需K线不可用"
                elif self.is_pair_locked(pair, candle_date=candles["date"].iloc[-1], side="long"):
                    self._pair_entry_block_reason = "交易对或全局多单交易锁生效"
        except Exception as exc:
            self._pair_entry_block_reason = f"交易名单/交易锁检查异常 ({type(exc).__name__})"
        if self._pair_entry_block_reason:
            if self._pair_entry_block_reason not in {
                "已离开当前交易名单",
                "交易对或全局多单交易锁生效",
            }:
                self._warn_data_unavailable(f"{pair} 开仓资格", self._pair_entry_block_reason)
            return False
        return True

    def _entries_allowed(self, now: float) -> bool:
        if not getattr(self, "_manual_sync_healthy", True):
            self._entry_block_reason = "手动仓位对账不可用, 暂停新开仓"
            return False
        sync = self.config.get("manual_position_sync", {})
        external_pairs: set[str] = set(getattr(self, "_external_pairs", set()))
        if external_pairs and not (sync.get("enabled") and sync.get("import_positions")):
            self._entry_block_reason = "检测到框架未接管的外部仓位, 暂停新开仓"
            return False
        reconciling = external_pairs & getattr(self, "_manual_sync_blocked_pairs", set())
        if reconciling:
            self._entry_block_reason = f"外部仓位正在框架对账: {sorted(reconciling)}"
            return False
        exit_failure_reason = self._exit_evaluation_block_reason()
        if exit_failure_reason:
            self._entry_block_reason = exit_failure_reason
            return False
        if not self._eth_entries_allowed(now):
            self._entry_block_reason = f"ETH拦截: {self._eth_block_reason}"
            return False
        max_age = float(self.settings["score_refresh_seconds"]) + float(
            self.settings["data_grace_seconds"]
        )
        position_max_age = float(self.settings["position_stale_seconds"])
        fresh_count, total, required = self._score_coverage(now)
        score_checks = (
            (
                (self._data_healthy, "行情评分数据不完整"),
                (
                    bool(required) and fresh_count >= required,
                    f"评分指标有效覆盖不足 ({fresh_count}/{total}, 至少{required})",
                ),
                (now - self._last_good_data <= max_age, "评分数据过期"),
            )
            if self._last_good_data
            else ((False, "首批行情与评分加载中"),)
        )
        checks = (
            (not getattr(self, "_risk_state_load_failed", False), "风控状态读取失败"),
            (not getattr(self, "_risk_state_save_failed", False), "风控状态保存失败"),
            (getattr(self, "_database_time_healthy", True), "数据库持仓时间异常, 请修复UTC时间"),
            (not self._rotation_in_flight(), "轮换买单/旧仓退出尚未完成, 暂停新开仓"),
            *score_checks,
            (
                self.settings["weights"]["liquidation"] <= 0
                or self._liquidation_connected.is_set(),
                "强平数据流断开",
            ),
            (
                self.settings["weights"]["liquidation"] <= 0
                or now - self._liquidation_last_message
                <= float(self.settings["liquidation_stream_max_age_seconds"]),
                "强平流心跳过期",
            ),
            (self._position_data_healthy, "仓位同步失败"),
            (now - self._last_position_sync <= position_max_age, "仓位数据过期"),
            (self._market_data_healthy, "龙头K线覆盖不足"),
            (not getattr(self, "_market_down", False), "龙头市场普跌"),
        )
        self._entry_block_reason = "; ".join(reason for allowed, reason in checks if not allowed)
        return not self._entry_block_reason

    def _exit_evaluation_block_reason(self) -> str | None:
        failures = getattr(self, "_exit_evaluation_failures", {})
        limit = int(self.settings["exit_evaluation_failure_limit"])
        if not any(count >= limit for count in failures.values()):
            return None
        try:
            active_pairs = {trade.pair for trade in Trade.get_open_trades()} | set(
                getattr(self, "_external_pairs", set())
            )
        except Exception as exc:
            self._warn_data_unavailable("退出评估故障持仓复核", str(exc))
            return "退出评估连续失败且持仓复核异常, 暂停新开仓"
        for pair in set(failures) - active_pairs:
            failures.pop(pair, None)
        blocked = sorted(pair for pair, count in failures.items() if count >= limit)
        if not blocked:
            return None
        return f"退出评估连续失败, 暂停新开仓: {blocked}"

    def _eth_entries_allowed(self, now: float) -> bool:
        """Use 15m/1h EMA structure and a fast ATR break to gate new entries."""
        self._eth_block_reason = "数据缺失、过期或无效"
        self._eth_trend = "未知"
        self._eth_trend_summary = "趋势未知"
        try:
            fast = self._eth_timeframe_context(
                self.timeframe,
                int(self.settings["eth_confirm_candles"]),
                now,
            )
            slow = self._eth_timeframe_context(self.settings["holding_timeframe"], 1, now)
            if fast is None or slow is None:
                return False

            emergency_threshold = (
                fast["ema"] - float(self.settings["eth_fast_atr_buffer"]) * fast["atr"]
            )
            emergency = bool(fast["falling"] and fast["close"] < emergency_threshold)
            dual_weak = bool(fast["weakening"] and slow["weakening"])
            recovery = bool(fast["rising"])
            was_blocked = getattr(self, "_eth_blocked", False)

            if emergency:
                self._eth_blocked = True
                self._eth_trend = f"{self.timeframe}急跌"
                self._eth_block_reason = (
                    f"ETH {self.timeframe} 急跌: 收盘 {fast['close']:.4f} < "
                    f"EMA{self.settings['trend_ema_candles']} - "
                    f"{self.settings['eth_fast_atr_buffer']:.1f}xATR ({emergency_threshold:.4f})"
                )
            elif dual_weak:
                self._eth_blocked = True
                self._eth_trend = f"{self.timeframe}/{self.settings['holding_timeframe']}双周期走弱"
                self._eth_block_reason = (
                    f"ETH {self.timeframe} 与 {self.settings['holding_timeframe']} 均低于 "
                    f"EMA{self.settings['trend_ema_candles']} 且均线向下"
                )
            elif was_blocked and not recovery:
                self._eth_blocked = True
                self._eth_trend = "恢复确认中"
                self._eth_block_reason = (
                    f"ETH 恢复未确认: 最近{self.settings['eth_confirm_candles']}根"
                    f"{self.timeframe}尚未全部"
                    f"站上 EMA{self.settings['trend_ema_candles']} 且均线向上"
                )
            else:
                self._eth_blocked = False
                self._eth_block_reason = ""
                self._eth_trend = (
                    "双周期上涨"
                    if fast["rising"] and slow["rising"]
                    else f"{self.timeframe}{fast['state']}/"
                    f"{self.settings['holding_timeframe']}{slow['state']}"
                )

            risk_state = getattr(self, "_risk_state", None)
            if isinstance(risk_state, dict):
                risk_state["eth_entry_blocked"] = self._eth_blocked

            current_time = datetime.fromtimestamp(now, UTC)
            age = (current_time - fast["date"]).total_seconds()
            display_date = fast["date"].astimezone(DISPLAY_TZ).isoformat()
            self._eth_trend_summary = (
                f"当前趋势={self._eth_trend} | "
                f"{self.timeframe}={fast['state']} 收盘={fast['close']:.4f} "
                f"EMA{self.settings['trend_ema_candles']}={fast['ema']:.4f} "
                f"斜率={fast['slope']:+.4f} ATR={fast['atr']:.4f} | "
                f"{self.settings['holding_timeframe']}={slow['state']} 收盘={slow['close']:.4f} "
                f"EMA{self.settings['trend_ema_candles']}={slow['ema']:.4f} "
                f"斜率={slow['slope']:+.4f} | "
                f"最新{self.timeframe}开盘(北京时间)={display_date} "
                f"已收盘={age - timeframe_to_seconds(self.timeframe):.0f}s"
            )
            return not self._eth_blocked
        except Exception as exc:
            self._eth_block_reason = f"数据读取异常 ({type(exc).__name__})"
            logger.debug(
                "🔎 ETH %s/%s 数据异常, 暂停新开仓: %s",
                self.timeframe,
                self.settings["holding_timeframe"],
                exc,
                extra=LOG_WARN,
            )
            return False

    def _eth_timeframe_context(
        self,
        timeframe: str,
        confirmations: int,
        now: float,
    ) -> dict[str, Any] | None:
        """Summarize a closed-candle EMA trend for the ETH entry gate."""
        slope_count = int(self.settings["trend_slope_candles"])
        ema_count = int(self.settings["trend_ema_candles"])
        frame = self._trend_candles(
            self.ETH_PAIR,
            timeframe,
            max(ema_count + slope_count, self.settings["atr_period"] + 2, confirmations + 1),
            columns=("high", "low", "close"),
            now=now,
        )
        if frame is None:
            return None
        close = frame["close"]
        ema = close.ewm(span=ema_count, adjust=False).mean()
        # Keep the signal candle out of its own volatility baseline.  Otherwise a
        # crash bar inflates ATR and can hide the very fast break this gate detects.
        atr = self._wilder_atr(frame.iloc[:-1])
        if not math.isfinite(atr) or atr <= 0:
            self._warn_data_unavailable(f"{self.ETH_PAIR} {timeframe} ETH过滤", "ATR无效")
            return None
        below = bool((close.iloc[-confirmations:] < ema.iloc[-confirmations:]).all())
        above = bool((close.iloc[-confirmations:] > ema.iloc[-confirmations:]).all())
        slope = float(ema.iloc[-1] - ema.iloc[-slope_count - 1])
        falling = slope < 0
        rising = bool(above and slope > 0)
        weakening = bool(below and falling)
        return {
            "date": frame["date"].iloc[-1],
            "close": float(close.iloc[-1]),
            "ema": float(ema.iloc[-1]),
            "slope": slope,
            "atr": atr,
            "falling": falling,
            "rising": rising,
            "weakening": weakening,
            "state": "走弱" if weakening else "上涨" if rising else "整理",
        }

    def _rotation_in_flight(self) -> bool:
        state = getattr(self, "_rotation_state", None)
        return bool(state and state["phase"] != "buy")

    def _rotation_entry_tag(self) -> str:
        state = getattr(self, "_rotation_state", None)
        return f"rotation_{state['token']}" if state else ""

    def _persist_rotation(self) -> bool:
        self._risk_state["rotation"] = self._rotation_state
        self._risk_state["last_rotation"] = self._last_rotation
        saved = self._save_risk_state()
        if not saved:
            self._record_rotation_event(
                "state_save_failed", "轮换状态保存失败, 禁止新开仓", once=True
            )
        return saved

    def _prepare_rotation_buy(self, pair: str, amount: float) -> bool:
        if self._rotation_state is None:
            return False
        try:
            # confirm_trade_entry 收到的是精度处理前数量, 使用与框架下单相同的合约精度。
            requested = self._exchange.amount_to_contract_precision(pair, amount)
            if not math.isfinite(requested) or requested <= 0:
                raise ValueError("交易所精度处理后数量无效")
            self._rotation_state.update(
                phase="buy_pending", amount=requested, submitted_at=time.time()
            )
            self._last_rotation = time.time()
            self._risk_state.setdefault("rotation_reentry_until", {})[
                self._rotation_state["weak"]
            ] = self._last_rotation + self.settings["replacement_reentry_cooldown_minutes"] * 60
            if self._persist_rotation():
                self._record_rotation_event(
                    "entry_approved", "买单提交前状态已保存", {"requested_amount": requested}
                )
                return True
        except Exception as exc:
            logger.error("🚨 轮换买入准备失败 %s: %s", pair, exc, extra=LOG_ERROR)
        self._entry_block_reason = "轮换数量校验或状态保存失败, 不发送买单"
        self._record_rotation_event("entry_rejected", self._entry_block_reason)
        return False

    def _clear_rotation(
        self, reason: str = "轮换条件失效", *, event_type: str = "cancelled"
    ) -> None:
        if getattr(self, "_rotation_state", None) or getattr(self, "_rotation_candidate", None):
            self._record_rotation_event(event_type, reason)
        had_state = bool(getattr(self, "_rotation_state", None))
        self._rotation_pair = self._rotation_target = None
        self._rotation_state = None
        self._rotation_candidate, self._rotation_seen = None, 0
        if had_state:
            self._persist_rotation()

    def _entry_slot_available(self, pair: str, entry_tag: str | None) -> bool:
        try:
            occupied = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
        except Exception as exc:
            self._entry_block_reason = f"仓位名额检查失败 ({type(exc).__name__})"
            logger.error("🚨 %s, 拒绝新开仓", self._entry_block_reason, extra=LOG_ERROR)
            return False
        state = getattr(self, "_rotation_state", None)
        limit = int(self.settings["max_positions"])
        allowed = (
            pair not in occupied
            and len(occupied) < limit
            and not (entry_tag or "").startswith("rotation_")
        )
        if state:
            allowed = (
                state["phase"] == "buy"
                and pair == state["target"]
                and entry_tag == self._rotation_entry_tag()
                and state["weak"] in occupied
                and pair not in occupied
                and len(occupied) < limit + 1
            )
        if not allowed:
            self._entry_block_reason = "仓位名额不足或不属于当前先买后卖轮换"
        return allowed

    def _rotation_trade_filled(self, trade: Trade) -> bool:
        """累计实际成交达到本次请求数量, 未成交/部分成交或已开始退出均不算完成。"""
        state = self._rotation_state
        if not state or trade.enter_tag != self._rotation_entry_tag() or trade.is_short:
            return False
        if not trade.is_open or trade.amount <= 0 or trade.has_open_orders:
            return False
        if any(o.ft_order_side == trade.exit_side and (o.filled or 0) > 0 for o in trade.orders):
            return False
        filled = sum(
            float(o.filled or 0)
            for o in trade.orders
            if o.ft_order_side == trade.entry_side
            and not o.ft_is_open
            and o.status in {"closed", "canceled", "expired"}
        )
        requested = state["amount"]
        return math.isfinite(filled) and requested > 0 and filled >= requested * (1 - 1e-8)

    def _sync_rotation_state(self) -> None:
        state = getattr(self, "_rotation_state", None)
        if not state or not self._position_data_healthy:
            return
        trades = {trade.pair: trade for trade in Trade.get_open_trades()}
        held = trades.keys() | self._external_pairs
        weak = trades.get(state["weak"])
        if weak is None and state["weak"] in self._external_pairs:
            self._clear_rotation("旧仓尚未完成框架对账, 撤销轮换授权")
            return
        if (weak is not None or state["weak"] in self._external_pairs) and not (
            self.is_trade_exit_allowed(weak)
        ):
            self._clear_rotation("手动仓位自动管理关闭, 撤销轮换授权")
            return
        weak_held = state["weak"] in held and (
            state["weak_trade_id"] is None or (weak and weak.id == state["weak_trade_id"])
        )
        target = trades.get(state["target"])
        if state["phase"] == "buy":
            if not weak_held or state["target"] in held:
                self._clear_rotation("买单提交前旧仓消失或目标已有持仓")
            return
        if target is None and self._recover_missing_rotation_target():
            return
        self._record_rotation_event(
            "execution_status",
            "核对目标订单及成交数量",
            self._rotation_execution_details(target),
            once=True,
        )
        if target and self._rotation_trade_filled(target):
            if not weak_held:
                self._risk_state.setdefault("rotation_reentry_until", {})[state["weak"]] = (
                    time.time() + self.settings["replacement_reentry_cooldown_minutes"] * 60
                )
                logger.info(
                    "✅ 先买后卖轮换完成 | %s -> %s", state["weak"], state["target"], extra=LOG_GOOD
                )
                self._clear_rotation("目标已完整买入且旧仓已退出", event_type="completed")
            elif state["phase"] != "sell":
                state["phase"] = "sell"
                self._persist_rotation()
                self._record_rotation_event(
                    "target_filled",
                    "目标完整成交, 允许退出旧仓",
                    self._rotation_execution_details(target),
                )
                logger.info(
                    "✅ 轮换目标完整成交 %s | 允许退出旧仓 %s; 暂停其他开仓",
                    state["target"],
                    state["weak"],
                    extra=LOG_GOOD,
                )
            return
        if state["phase"] != "review" and (
            state["phase"] == "sell" or (target and not target.has_open_orders)
        ):
            state["phase"] = "review"
            self._persist_rotation()
            self._record_rotation_event(
                "review_required",
                "成交异常, 保留旧仓并暂停开仓",
                self._rotation_execution_details(target),
            )
            logger.error(
                "🚨 轮换成交异常 %s -> %s | 保留旧仓, 暂停新开仓, 请核对订单",
                state["weak"],
                state["target"],
                extra=LOG_ERROR,
            )
        self._warn_data_unavailable(
            "轮换成交确认",
            f"{state['weak']} -> {state['target']} 阶段={state['phase']}; "
            "未确认完整买入或目标已退出, "
            "保留旧仓并暂停新开仓; 失败/部分成交/结果不明时请核对订单",
        )

    def _rotation_bar(self, pair: str) -> float | None:
        frame = self._closed_candles(pair, self.timeframe, 1)
        return float(frame["date"].iloc[-1].timestamp()) if frame is not None else None

    def _fast_rotation_quality(self, pair: str) -> bool:
        """A high composite score cannot substitute for a closed, supported breakout."""
        lookback = self.settings["replacement_fast_breakout_candles"]
        volume_count = self.settings["replacement_fast_volume_baseline_candles"]
        frame = self._closed_candles(
            pair,
            self.timeframe,
            max(lookback, volume_count, self.settings["atr_period"] + 1) + 1,
            columns=("high", "low", "close", "volume"),
        )
        candle = self._candle_metrics(pair)
        metric = self._metrics.get(pair, {})
        if frame is None or candle is None or not self._pair_score_current(pair):
            self._audit_rotation_check(
                target=pair, stage="breakout", passed=False, reason="突破数据缺失或过期"
            )
            return False
        if ((frame["low"] > frame["close"]) | (frame["high"] < frame["close"])).any():
            return False
        reference, signal = frame.iloc[:-1], frame.iloc[-1]
        resistance = float(reference["high"].tail(lookback).max())
        atr = self._wilder_atr(reference)
        baseline = float(reference["volume"].tail(volume_count).mean())
        height = float(signal["high"] - signal["low"])
        taker = metric.get("taker_ratio_latest", math.nan)
        taker_aligned = metric.get("taker_latest_candle_time") == signal["date"].timestamp()
        components = self._price_components({**candle, "taker_ratio": taker})
        core = 100 * sum(
            self.settings["weights"][key] * value
            for key, value in zip(("momentum", "volume", "taker_buy"), components, strict=True)
        )
        passed = bool(
            math.isfinite(atr)
            and taker_aligned
            and atr > 0
            and baseline > 0
            and height > 0
            and resistance
            < signal["close"]
            <= resistance + self.settings["replacement_fast_max_breakout_atr"] * atr
            and signal["volume"] / baseline >= self.settings["replacement_fast_volume_ratio"]
            and (signal["close"] - signal["low"]) / height
            >= self.settings["replacement_fast_close_location"]
            and taker >= self.settings["replacement_fast_taker_ratio"]
            and core >= self.settings["replacement_fast_core_score"]
        )
        details = getattr(self, "_fast_rotation_details", {})
        details[pair] = {
            "resistance": resistance,
            "atr": atr,
            "close": float(signal["close"]),
            "volume_ratio": float(signal["volume"] / baseline) if baseline > 0 else None,
            "close_location": float((signal["close"] - signal["low"]) / height)
            if height > 0
            else None,
            "taker_ratio": taker,
            "taker_aligned": taker_aligned,
            "taker_candle_time": metric.get("taker_latest_candle_time"),
            "core_score": core,
            "passed": passed,
        }
        self._fast_rotation_details = details
        self._audit_rotation_check(target=pair, channel="fast", stage="breakout", **details[pair])
        return passed

    def _rotation_signal_valid(self, weak: str, target: str, channel: str) -> bool:
        occupied = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
        return (
            self._rotation_weak_rank_eligible(weak)
            and self._rotation_target_rank_eligible(target, occupied)
            and self._rotation_holding_weak(weak)
            and (channel != "fast" or self._fast_rotation_quality(target))
        )

    def _plan_rotation(self, now: float, current_time: datetime) -> None:
        if self._rotation_in_flight():
            return
        new_snapshot = getattr(self, "_rotation_score_snapshot", None) != self._last_score_refresh
        self._rotation_evaluation: dict[str, Any] | None = {
            "score_snapshot": self._last_score_refresh,
            "checks": [],
            "previous_candidate": getattr(self, "_rotation_candidate", None),
            "previous_confirmations": getattr(self, "_rotation_seen", 0),
        }
        self._rotation_audit_reason = "没有合格的轮换组合"
        self._evaluate_rotation(now, current_time)
        if new_snapshot:
            self._rotation_score_snapshot = self._last_score_refresh
            self._record_rotation_event(
                "evaluation", self._rotation_audit_reason, self._rotation_evaluation
            )
        self._rotation_evaluation = None

    def _audit_rotation_check(self, **check) -> None:
        evaluation = getattr(self, "_rotation_evaluation", None)
        if evaluation is not None:
            evaluation["checks"].append(check)

    def _rotation_challengers(self, occupied: set[str]) -> list[tuple[str, float]]:
        challengers = []
        ranked = self._rotation_target_ranking(occupied)
        for pair, score in ranked:
            if not self._rotation_target_rank_eligible(pair, occupied, ranked):
                continue
            reason = ""
            if not self._entry_pair_available(pair):
                reason = getattr(self, "_pair_entry_block_reason", "交易资格不通过")
            if not reason:
                reason = self._entry_quality_reason(
                    pair, min(self._rotation_floor("normal"), self._rotation_floor("fast"))
                )
            self._audit_rotation_check(
                target=pair, stage="entry_quality", passed=not bool(reason), reason=reason
            )
            if not reason:
                challengers.append((pair, score))
        return challengers

    def _rotation_weak_ranking(self) -> list[tuple[str, float]]:
        return [
            item
            for item in sorted(
                (
                    (candidate, self._current_score(candidate))
                    for candidate in self._scores
                    if self._pair_score_current(candidate)
                ),
                key=lambda item: (item[1], item[0]),
                reverse=True,
            )
            if math.isfinite(item[1])
        ]

    def _rotation_weak_rank_eligible(
        self, pair: str, ranked: list[tuple[str, float]] | None = None
    ) -> bool:
        ranked = self._rotation_weak_ranking() if ranked is None else ranked
        rank = next((index for index, item in enumerate(ranked, 1) if item[0] == pair), None)
        bottom_count = (
            max(1, math.ceil(len(ranked) * self.settings["replacement_weak_bottom_ratio"]))
            if ranked
            else 0
        )
        passed = bool(rank is not None and rank > len(ranked) - bottom_count)
        self._audit_rotation_check(
            weak=pair,
            stage="weak_rank",
            rank=rank,
            universe_size=len(ranked),
            bottom_count=bottom_count,
            ratio=self.settings["replacement_weak_bottom_ratio"],
            passed=passed,
        )
        return passed

    def _rotation_target_ranking(self, occupied: set[str]) -> list[tuple[str, float]]:
        return [
            item
            for item in self._ranked_pairs()
            if item[0] not in occupied and math.isfinite(item[1])
        ]

    def _rotation_target_rank_eligible(
        self,
        pair: str,
        occupied: set[str],
        ranked: list[tuple[str, float]] | None = None,
    ) -> bool:
        ranked = self._rotation_target_ranking(occupied) if ranked is None else ranked
        rank = next((index for index, item in enumerate(ranked, 1) if item[0] == pair), None)
        top_count = (
            max(1, math.ceil(len(ranked) * self.settings["replacement_target_top_ratio"]))
            if ranked
            else 0
        )
        passed = bool(rank is not None and rank <= top_count)
        self._audit_rotation_check(
            target=pair,
            stage="target_rank",
            rank=rank,
            universe_size=len(ranked),
            top_count=top_count,
            ratio=self.settings["replacement_target_top_ratio"],
            passed=passed,
        )
        return passed

    def _rotation_rank_reason(self, weak: str, target: str, occupied: set[str]) -> str:
        if not self._rotation_weak_rank_eligible(weak):
            return "旧仓评分排名已离开后段范围"
        if not self._rotation_target_rank_eligible(target, occupied):
            return "目标评分排名已离开前段范围"
        return ""

    def _pending_rotation_reason(self, now: float) -> str:
        if self._rotation_target is None:
            return "轮换目标缺失"
        state = getattr(self, "_rotation_state", None) or {}
        channel = state.get("channel", "normal")
        occupied = set(self._external_pairs)
        if "channel" in state:
            occupied = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
            if len(occupied) != self.settings["max_positions"]:
                return "持仓数量变化, 取消未提交轮换"
        if not self._entry_pair_available(self._rotation_target):
            return getattr(self, "_pair_entry_block_reason", "目标交易资格失效")
        if not self._rotation_pair or not self._pair_score_current(self._rotation_pair, now):
            return "旧仓评分缺失或过期"
        if not self._pair_score_current(self._rotation_target, now):
            return "目标评分缺失或过期"
        if rank_reason := self._rotation_rank_reason(
            self._rotation_pair, self._rotation_target, occupied
        ):
            return rank_reason
        if not self._rotation_scores_qualify(self._rotation_pair, self._rotation_target):
            return "轮换评分或分差不再达标"
        reason = self._entry_quality_reason(self._rotation_target, self._rotation_floor(channel))
        if reason:
            return reason
        if not self._rotation_holding_weak(self._rotation_pair):
            return "旧仓小时趋势已恢复或走弱证据不足"
        if channel == "fast" and not self._fast_rotation_quality(self._rotation_target):
            return "快速突破质量不再达标"
        return ""

    def _evaluate_rotation(self, now: float, current_time: datetime) -> None:
        if self._rotation_in_flight():
            self._rotation_audit_reason = "已有轮换正在执行"
            return
        if not self._entries_allowed(now):
            self._rotation_audit_reason = getattr(self, "_entry_block_reason", "禁止开仓")
            self._record_rotation_event("blocked", self._rotation_audit_reason, once=True)
            self._clear_rotation(self._rotation_audit_reason)
            self._rotation_score_snapshot = self._last_score_refresh
            return
        if self._rotation_target:
            reason = self._pending_rotation_reason(now)
            if reason:
                self._rotation_audit_reason = reason
                self._clear_rotation(reason)
            return
        if self._rotation_score_snapshot == self._last_score_refresh:
            return
        self._rotation_score_snapshot = self._last_score_refresh
        previous = self._rotation_candidate
        seen = self._rotation_seen
        previous_bar = getattr(self, "_rotation_candidate_bar", None)
        previous_channel = getattr(self, "_rotation_candidate_channel", None)
        self._rotation_candidate, self._rotation_seen = None, 0
        open_trades = {
            trade.pair: trade
            for trade in Trade.get_open_trades()
            if not trade.is_short and self.is_trade_exit_allowed(trade)
        }
        # Fill ordinary free slots first. Rotation only borrows a slot at the normal limit.
        occupied = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
        held_pairs = set(open_trades)
        if len(occupied) != self.settings["max_positions"] or not held_pairs or not self._scores:
            self._rotation_audit_reason = "仓位未满、超限或没有有效持仓评分"
            self._audit_rotation_check(
                stage="capacity", held_count=len(occupied), required=self.settings["max_positions"]
            )
            return
        period = timeframe_to_seconds(self.timeframe)
        if self._last_rotation and int(now // period) == int(self._last_rotation // period):
            self._rotation_audit_reason = "本15分钟周期已授权一次轮换"
            return
        challengers = self._rotation_challengers(occupied)
        scored_held = sorted(
            (
                pair
                for pair in held_pairs & self._scores.keys()
                if self._pair_score_current(pair, now)
            ),
            key=lambda pair: (self._current_score(pair), pair),
        )
        weak_ranking = self._rotation_weak_ranking()
        scored_held = [
            pair for pair in scored_held if self._rotation_weak_rank_eligible(pair, weak_ranking)
        ]
        eligible = challengers.copy()
        if previous and eligible:
            incumbent = next((item for item in eligible if item[0] == previous[1]), None)
            if (
                incumbent
                and eligible[0][1] - incumbent[1]
                <= self.settings["replacement_candidate_hysteresis"]
            ):
                eligible.remove(incumbent)
                eligible.insert(0, incumbent)
        selected = self._find_rotation_candidate(
            now, current_time, open_trades, scored_held, eligible
        )
        if selected is None:
            return
        weak, target, channel, bar, score = selected
        self._rotation_audit_reason = "找到合格组合, 更新收盘确认"
        self._advance_rotation_confirmation(
            weak,
            target,
            channel,
            bar,
            score,
            open_trades.get(weak),
            previous,
            previous_channel,
            previous_bar,
            seen,
        )

    def _advance_rotation_confirmation(
        self,
        weak: str,
        target: str,
        channel: str,
        bar: float,
        score: float,
        weak_trade: Trade | None,
        previous: tuple[str, str] | None,
        previous_channel: str | None,
        previous_bar: float | None,
        seen: int,
    ) -> None:
        period = timeframe_to_seconds(self.timeframe)
        prefix = "replacement_fast_" if channel == "fast" else "replacement_"
        candidate = (weak, target)
        confirmations = 1
        if candidate == previous and channel == previous_channel:
            if bar == previous_bar:
                confirmations = seen
            elif previous_bar is not None and bar == previous_bar + period:
                confirmations = seen + 1
        self._rotation_candidate = candidate
        self._rotation_candidate_channel = channel
        self._rotation_candidate_bar = bar
        self._rotation_seen = confirmations
        required = self.settings[prefix + "confirmations"]
        self._record_rotation_event(
            "candidate_observed",
            "收盘K线轮换确认",
            {"count": confirmations, "required": required, "bar": bar},
            once=True,
        )
        if confirmations < required:
            logger.info(
                "⏳ %s轮换观察 | %s -> %s | 原评分%.1f -> 买入评分%.1f | 已收盘K线确认=%s/%s",
                "快速" if channel == "fast" else "普通",
                weak,
                target,
                self._current_score(weak),
                score,
                confirmations,
                required,
                extra=LOG_SCORE,
            )
            return
        self._rotation_pair, self._rotation_target = candidate
        self._rotation_state = {
            "weak": weak,
            "target": target,
            "channel": channel,
            "signal_bar": bar,
            "token": uuid4().hex,
            "phase": "buy",
            "amount": 0.0,
            "weak_trade_id": weak_trade.id if weak_trade else None,
        }
        logger.info(
            "🔄 %s先买后卖轮换确认 | 保留旧仓=%s (原评分%.1f) -> "
            "先买目标=%s (买入评分%.1f) | 连续收盘确认=%s根",
            "快速" if channel == "fast" else "普通",
            weak,
            self._current_score(weak),
            target,
            score,
            confirmations,
            extra=LOG_SCORE,
        )
        self._persist_rotation()
        self._record_rotation_event("plan_created", "轮换确认, 准备先买目标后卖旧仓")
        self._rotation_candidate, self._rotation_seen = None, 0
        return

    def _find_rotation_candidate(
        self,
        now: float,
        current_time: datetime,
        open_trades: dict[str, Trade],
        scored_held: list[str],
        challengers: list[tuple[str, float]],
    ) -> tuple[str, str, str, float, float] | None:
        for channel in ("fast", "normal"):
            if channel == "fast" and not self.settings["replacement_fast_enabled"]:
                continue
            prefix = "replacement_fast_" if channel == "fast" else "replacement_"
            cooldown = self.settings[prefix + "cooldown_minutes"] * 60
            self._audit_rotation_check(
                channel=channel,
                stage="cooldown",
                elapsed=now - self._last_rotation,
                required=cooldown,
                passed=now - self._last_rotation >= cooldown,
            )
            if now - self._last_rotation < cooldown:
                continue
            for weak in scored_held:
                age = (
                    (current_time - open_trades[weak].open_date_utc).total_seconds()
                    if weak in open_trades
                    else now - self._position_first_seen.get(weak, now)
                )
                age_ready = age >= self.settings[prefix + "min_age_minutes"] * 60
                stalled = self._rotation_holding_weak(weak) if age_ready else None
                self._audit_rotation_check(
                    channel=channel,
                    weak=weak,
                    stage="holding",
                    age_seconds=age,
                    minimum_age=self.settings[prefix + "min_age_minutes"] * 60,
                    holding_weak=stalled,
                    passed=age_ready and stalled,
                )
                if not age_ready or not stalled:
                    continue
                weak_bar = self._rotation_bar(weak)
                if weak_bar is None:
                    continue
                for target, score in challengers:
                    if not self._rotation_scores_qualify(weak, target, channel):
                        continue
                    if channel == "fast" and not self._fast_rotation_quality(target):
                        continue
                    bar = self._rotation_bar(target)
                    same_bar = bar is not None and bar == weak_bar
                    safe = self._execution_is_safe(target) if same_bar else False
                    self._audit_rotation_check(
                        channel=channel,
                        weak=weak,
                        target=target,
                        stage="execution",
                        target_bar=bar,
                        weak_bar=weak_bar,
                        passed=same_bar and safe,
                        reason=getattr(self, "_execution_block_reason", "")
                        if same_bar and not safe
                        else "",
                    )
                    if not same_bar or not safe or bar is None:
                        continue
                    return weak, target, channel, bar, score
        return None

    def _rotation_floor(self, channel: str) -> float:
        prefix = "replacement_fast_" if channel == "fast" else "replacement_"
        return max(
            self._entry_slot_score_floor(int(self.settings["max_positions"]) - 1),
            self.settings[prefix + "entry_score"],
        )

    def _rotation_scores_qualify(self, weak: str, target: str, channel: str | None = None) -> bool:
        if channel is None:
            channel = (getattr(self, "_rotation_state", None) or {}).get("channel", "normal")
        if channel not in ("normal", "fast") or (
            channel == "fast" and not self.settings["replacement_fast_enabled"]
        ):
            return False
        old_score, new_score = self._current_score(weak), self._entry_score(target)
        prefix = "replacement_fast_" if channel == "fast" else "replacement_"
        qualifies = (
            math.isfinite(old_score)
            and math.isfinite(new_score)
            and (channel == "fast" or old_score < self.settings["replacement_weak_score"])
            and new_score >= self._rotation_floor(channel)
            and new_score - old_score >= self.settings[prefix + "score_gap"]
        )
        self._audit_rotation_check(
            channel=channel,
            weak=weak,
            target=target,
            stage="score",
            old_score=old_score,
            new_score=new_score,
            minimum=self._rotation_floor(channel),
            minimum_gap=self.settings[prefix + "score_gap"],
            weak_ceiling=self.settings["replacement_weak_score"] if channel == "normal" else None,
            passed=qualifies,
        )
        return qualifies

    def _rotation_exit_allowed(self, pair: str) -> bool:
        if pair != self._rotation_pair or not self._rotation_in_flight():
            return False
        self._sync_rotation_state()
        state = self._rotation_state
        if not state or state["phase"] != "sell" or not self._position_data_healthy:
            return False
        target = next((t for t in Trade.get_open_trades() if t.pair == state["target"]), None)
        allowed = bool(target and self._rotation_trade_filled(target))
        if allowed:
            self._record_rotation_event(
                "exit_allowed", "目标完整成交, 旧仓可执行轮换退出", once=True
            )
        return allowed

    def _refresh_risk_state(self, current_time: datetime) -> None:
        if getattr(self, "_risk_state_load_failed", False):
            # 无可靠历史基线时不重新建账, 让主循环继续处理已有仓位的止损和退出。
            return
        positions = self._wallets.get_all_positions()
        equity = self._wallets.get_total(self.config["stake_currency"]) + sum(
            position.unrealized_pnl for position in positions.values()
        )
        if equity <= 0:
            return
        day = current_time.astimezone(UTC).date().isoformat()
        state = self._risk_state
        state.pop("daily_blocked", None)
        day_changed = state.get("day") != day
        if day_changed:
            state.update({"day": day, "day_start_equity": equity})
        state["peak_equity"] = max(float(state.get("peak_equity", equity)), equity)
        state.update(
            {
                # 保留旧状态格式兼容性; 峰值回撤只统计, 不再触发账户停止。
                "account_stopped": False,
                "last_equity": equity,
            }
        )
        now = time.monotonic()
        if day_changed or now - getattr(self, "_last_risk_state_checkpoint", -math.inf) >= float(
            self.settings["risk_state_checkpoint_seconds"]
        ):
            state["updated_at"] = current_time.astimezone(UTC).isoformat()
            if self._save_risk_state():
                self._last_risk_state_checkpoint = now

    def _liquidation_score(self, symbol: str, now: float) -> float:
        with self._liquidation_lock:
            events = self._liquidations.get(symbol, ())
            while events and events[0][0] < now - self.settings["liquidation_window_seconds"]:
                events.popleft()
            if (
                not self._liquidation_started
                or now - self._liquidation_started < self.settings["liquidation_window_seconds"]
            ):
                return self.settings["liquidation_warmup_score"]
            recent = sum(
                value
                for timestamp, value in events
                if now - self.settings["liquidation_recent_seconds"] <= timestamp <= now
            )
            previous = sum(
                value
                for timestamp, value in events
                if timestamp < now - self.settings["liquidation_recent_seconds"]
            )
        # Scale the preceding 45m to a 15m baseline, with a minimum notional floor.
        periods = (
            self.settings["liquidation_window_seconds"]
            - self.settings["liquidation_recent_seconds"]
        ) / self.settings["liquidation_recent_seconds"]
        baseline = max(previous / periods, float(self.settings["liquidation_min_notional"]))
        return self._clamp(
            (recent / baseline - 1.0) / (self.settings["liquidation_score_full_ratio"] - 1)
        )
