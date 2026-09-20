"""Implementation helpers for the Leader Squeeze strategy.

This is intentionally the strategy's only helper module so the complete
implementation stays local to its strategy directory.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta, timezone
from functools import wraps
from io import StringIO
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pandas as pd
import requests
from pandas import DataFrame
from rich import box
from rich.console import Console
from rich.table import Table as RichTable
from rich.text import Text as RichText
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from websockets.sync.client import connect

from freqtrade.exchange import Exchange, timeframe_to_seconds
from freqtrade.persistence import ExchangeLedger, Trade
from freqtrade.strategy import stoploss_from_absolute
from freqtrade.wallets import Wallets


logger = logging.getLogger("leader_squeeze_strategy")
DISPLAY_TZ = timezone(timedelta(hours=8), name="北京时间")
LOG_INFO = {"strategy_log_style": "cyan"}
LOG_GOOD = {"strategy_log_style": "green"}
LOG_WARN = {"strategy_log_style": "yellow"}
LOG_ERROR = {"strategy_log_style": "bold red"}
LOG_SCORE = {"strategy_log_style": "magenta"}

_report_cache: ContextVar[dict | None] = ContextVar("leader_report_cache", default=None)
_decision_cache: ContextVar[dict | None] = ContextVar("leader_decision_cache", default=None)


def decision_snapshot(function):
    """Reuse immutable candle calculations during one bot loop only."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _decision_cache.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _decision_cache.reset(token)

    return wrapped


def report_snapshot(function):
    """Reuse calculations within one report, never across trading decisions or threads."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _report_cache.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _report_cache.reset(token)

    return wrapped


def report_cached(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        cache = _decision_cache.get()
        if cache is None:
            cache = _report_cache.get()
        if cache is None:
            return function(*args, **kwargs)
        key = (function, args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = function(*args, **kwargs)
        return cache[key]

    return wrapped


class _TableLogMessage:
    """Render plain text only if a file/API handler requests it, once per record."""

    def __init__(self, title: str, table: RichTable):
        self.title = title
        self.table = table
        self.text: str | None = None

    def __str__(self) -> str:
        if self.text is None:
            output = StringIO()
            Console(file=output, width=240, color_system=None).print(self.table)
            self.text = f"{self.title}\n{output.getvalue().rstrip()}"
        return self.text


def _log_table(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    style: str = "magenta",
    row_styles: list[str] | None = None,
    caption: str | None = None,
) -> None:
    """终端自适应列宽, 文件/API 日志保留不含颜色控制符的完整表格。"""
    if not logger.isEnabledFor(logging.INFO):
        return
    table = RichTable(
        *headers,
        box=box.SIMPLE_HEAD,
        header_style=f"bold {style}",
        caption=RichText(caption) if caption else None,
    )
    for column in table.columns:
        column.overflow = "fold"
    for index, row in enumerate(rows):
        table.add_row(
            *(RichText(cell) for cell in row), style=row_styles[index] if row_styles else style
        )
    if not rows:
        table.add_row("暂无数据")
    logger.info(
        _TableLogMessage(title, table),
        extra={
            "strategy_log_style": style,
            "strategy_log_table": table,
            "strategy_log_title": title,
        },
    )


class LeaderMixinContext:
    """Shared attributes supplied by the composed strategy at runtime.

    Cross-mixin callbacks keep their dynamic signatures here; concrete methods
    retain their own annotations. Declarations do not create runtime defaults.
    """

    ENTRY_HEAT_HISTORY_CANDLES: Any
    ORDER_BOOK_MAX_AGE_SECONDS: Any
    _apply_scores: Any
    _audit_fingerprints: dict[str, str]
    _audit_rotation_check: Any
    _candle_metrics: Any
    _clear_rotation: Any
    _closed_candles: Any
    _current_score: Any
    _data_healthy: Any
    _entry_block_reason: Any
    _entry_decisions: Any
    _entry_heat_metrics: Any
    _entry_pairs: Any
    _entry_score: Any
    _entry_setup_metrics: Any
    _external_pairs: Any
    _fast_rotation_quality: Any
    _funding_score: Any
    _last_good_data: Any
    _last_position_sync: Any
    _last_status_log: float
    _last_status_signature: tuple[Any, ...] | None
    _liquidation_connected: Any
    _liquidation_last_message: float
    _liquidation_lock: Any
    _liquidation_started: float
    _liquidations: Any
    _log_profit_position_table: Any
    _market_data_healthy: Any
    _market_down: Any
    _market_exit_required: Any
    _multi_timeframe_snapshot: Any
    _next_score_refresh: Any
    _opening_score_label: Any
    _pair_score_current: Any
    _position_data_healthy: Any
    _position_details: Any
    _position_first_seen: Any
    _ranked_pairs: Any
    _record_rotation_event: Any
    _required_leader_count: Any
    _risk_state: dict[str, Any]
    _rotation_candidate: tuple[str, str] | None
    _rotation_entry_tag: Any
    _rotation_exit_allowed: Any
    _rotation_floor: Any
    _rotation_pair: Any
    _rotation_seen: Any
    _rotation_state: Any
    _rotation_target: Any
    _score_coverage: Any
    _score_pending: Any
    _score_result: tuple[float, list[str], dict[str, dict[str, float]]] | None
    _score_result_lock: Any
    _scores: dict[str, float]
    _state_path: Any
    _stop_event: Any
    _trend_context: Any
    _trend_candles: Any
    _trend_history_count: Any
    _trend_state_frame: Any
    _wilder_atr: Any
    _trend_reversed: Any
    _update_market_state: Any
    _warn_data_unavailable: Any
    config: dict[str, Any]
    dp: Any
    order_types: Any
    settings: dict[str, Any]
    startup_candle_count: int
    stoploss: Any
    timeframe: str
    wallets: Any

    if TYPE_CHECKING:

        @property
        def _exchange(self) -> Any: ...

        @property
        def _wallets(self) -> Any: ...


metadata = MetaData()
rotation_events = Table(
    "leader_rotation_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("bot_name", String(100), nullable=False),
    Column("dry_run", Boolean, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("rotation_token", String(64)),
    Column("channel", String(16)),
    Column("weak_pair", String(100)),
    Column("target_pair", String(100)),
    Column("weak_score", Float),
    Column("target_raw_score", Float),
    Column("target_entry_score", Float),
    Column("score_gap", Float),
    Column("reason", Text, nullable=False),
    Column("snapshot", JSON().with_variant(JSONB, "postgresql"), nullable=False),
)
Index("ix_leader_rotation_events_time", rotation_events.c.occurred_at)
Index(
    "ix_leader_rotation_events_token_time",
    rotation_events.c.rotation_token,
    rotation_events.c.occurred_at,
)
Index(
    "ix_leader_rotation_events_target_time",
    rotation_events.c.target_pair,
    rotation_events.c.occurred_at,
)


def json_safe(value: Any) -> Any:
    """JSONB rejects NaN; missing metrics must remain null, never invented zeroes."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        return json_safe(value.item())
    return str(value)


class RotationJournal:
    """A durable local outbox retries failed inserts without committing the trading session."""

    def __init__(self, engine, spool_path: Path, timeout_ms: int, retry_seconds: float):
        self.engine = engine
        self.spool_path = spool_path
        self.timeout_ms = timeout_ms
        self.retry_seconds = retry_seconds
        self.next_retry = 0.0
        self.pending: list[dict] = []
        self.spool_read_failed = False
        try:
            if spool_path.exists():
                self.pending = [
                    json.loads(line) for line in spool_path.read_text().splitlines() if line
                ]
        except (OSError, ValueError):
            self.spool_read_failed = True
            logger.error("轮换审计暂存文件读取失败, 保留原文件: %s", spool_path)

    def _save_pending(self) -> bool:
        if self.spool_read_failed:
            return False
        try:
            self.spool_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.spool_path.with_suffix(self.spool_path.suffix + ".tmp")
            temporary.write_text(
                "".join(
                    json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
                    for event in self.pending
                )
            )
            temporary.replace(self.spool_path)
            return True
        except OSError:
            logger.error("轮换审计暂存失败, 事件暂存内存; 请检查磁盘和权限: %s", self.spool_path)
            return False

    def record(self, event: dict, now: float) -> None:
        self.pending.append(json_safe(event))
        self._save_pending()
        self.flush(now)

    def flush(self, now: float) -> None:
        if not self.pending or now < self.next_retry:
            return
        try:
            with self.engine.begin() as connection:
                if connection.dialect.name == "postgresql":
                    connection.execute(
                        text("SELECT set_config('statement_timeout', :timeout, true)"),
                        {"timeout": str(self.timeout_ms)},
                    )
                    connection.execute(
                        text("SELECT set_config('lock_timeout', :timeout, true)"),
                        {"timeout": str(self.timeout_ms)},
                    )
                rotation_events.create(connection, checkfirst=True)
                dialect_insert: Any
                if connection.dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as dialect_insert
                elif connection.dialect.name == "sqlite":
                    from sqlalchemy.dialects.sqlite import insert as dialect_insert
                else:
                    dialect_insert = insert
                for event in self.pending:
                    row = {
                        **event,
                        "occurred_at": datetime.fromisoformat(event["occurred_at"]).astimezone(UTC),
                    }
                    statement = dialect_insert(rotation_events).values(**row)
                    if connection.dialect.name in {"postgresql", "sqlite"}:
                        statement = statement.on_conflict_do_nothing(index_elements=["event_id"])
                    connection.execute(statement)
            self.pending.clear()
            self.next_retry = 0.0
            self._save_pending()
        except Exception as exc:
            self.next_retry = now + self.retry_seconds
            # Never stringify driver errors: some contain connection credentials or bound payloads.
            logger.error(
                "轮换审计写库失败 (%s), %s 条事件等待重试; 已有仓位退出继续运行",
                type(exc).__name__,
                len(self.pending),
            )


class LeaderConfigMixin(LeaderMixinContext):
    def _validate_entry_pipeline_settings(self, max_positions: int) -> None:
        thresholds = self.settings["entry_slot_score_thresholds"]
        if not isinstance(thresholds, list) or len(thresholds) != max_positions:
            raise ValueError(
                "entry_slot_score_thresholds must contain one value per max_positions slot"
            )
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100
            for value in thresholds
        ) or any(left >= right for left, right in pairwise(thresholds)):
            raise ValueError(
                "entry_slot_score_thresholds must be finite, within [0, 100], "
                "and strictly increasing"
            )
        setup_score = self.settings["entry_setup_min_score"]
        setup_ratio = self.settings["entry_setup_shortlist_ratio"]
        setup_count = self.settings["entry_setup_min_candidates"]
        setup_enabled = self.settings["entry_setup_enabled"]
        setup_points = self.settings["entry_setup_score_points"]
        if (
            type(setup_score) not in (int, float)
            or not math.isfinite(setup_score)
            or not 0 <= setup_score <= 100
        ):
            raise ValueError("entry_setup_min_score must be within [0, 100]")
        if (
            type(setup_ratio) not in (int, float)
            or not math.isfinite(setup_ratio)
            or not 0 < setup_ratio <= 1
        ):
            raise ValueError("entry_setup_shortlist_ratio must be within (0, 1]")
        if type(setup_count) is not int or setup_count < 1:
            raise ValueError("entry_setup_min_candidates must be a positive integer")
        if type(setup_enabled) is not bool:
            raise ValueError("entry_setup_enabled must be boolean")
        required_points = {"launch", "continuation", "extension", "compression", "proximity"}
        if not isinstance(setup_points, dict) or set(setup_points) != required_points:
            raise ValueError(
                "entry_setup_score_points must contain launch, continuation, extension, "
                "compression and proximity"
            )
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
            for value in setup_points.values()
        ):
            raise ValueError("entry_setup_score_points must be finite non-negative numbers")
        component_total = sum(
            setup_points[key] for key in ("extension", "compression", "proximity")
        )
        if max(setup_points["launch"], setup_points["continuation"]) + component_total > 100:
            raise ValueError("entry_setup_score_points maximum score must not exceed 100")

    def _validate_score_settings(self) -> None:
        if not math.isclose(sum(self.settings["weights"].values()), 1.0, abs_tol=1e-9):
            raise ValueError("leader_squeeze weights must add up to 1.0")
        if any(not math.isfinite(v) or v < 0 for v in self.settings["weights"].values()):
            raise ValueError("leader_squeeze weights must be finite and non-negative")
        for key in (
            "momentum_full_score",
            "liquidation_min_notional",
            "replacement_score_gap",
        ):
            if not math.isfinite(float(self.settings[key])) or float(self.settings[key]) <= 0:
                raise ValueError(f"leader_squeeze {key} must be positive and finite")
        if not 0 <= float(self.settings["min_trend_continuity"]) <= 1:
            raise ValueError("leader_squeeze min_trend_continuity must be within [0, 1]")
        for key in ("market_min_coverage_ratio", "market_down_ratio"):
            if not 0 < float(self.settings[key]) <= 1:
                raise ValueError(f"leader_squeeze {key} must be within (0, 1]")
        if (
            not math.isfinite(float(self.settings["status_log_seconds"]))
            or float(self.settings["status_log_seconds"]) <= 0
        ):
            raise ValueError("leader_squeeze status_log_seconds must be positive and finite")
        max_positions = self.settings["max_positions"]
        if type(max_positions) is not int or max_positions < 1:
            raise ValueError("leader_squeeze max_positions must be a positive integer")
        self._validate_entry_pipeline_settings(max_positions)
        stake_ratio = self.settings["stake_ratio"]
        if (
            type(stake_ratio) not in (int, float)
            or not math.isfinite(stake_ratio)
            or not 0 < stake_ratio <= 1 / (max_positions + 1)
        ):
            raise ValueError("stake_ratio must be positive and leave one buy-first rotation slot")
        framework_limit = self.config.get("max_open_trades", 0)
        if type(framework_limit) not in (int, float) or not (
            framework_limit in (-1, math.inf)
            or (
                math.isfinite(framework_limit)
                and framework_limit % 1 == 0
                and framework_limit >= max_positions + 1
            )
        ):
            raise ValueError(
                f"max_open_trades must be >= {max_positions + 1} (or unlimited): "
                f"max_positions={max_positions} requires one extra buy-first rotation slot"
            )

    def _validate_reversal_settings(self) -> None:
        if self.timeframe != self.config["timeframe"]:
            raise ValueError("strategy timeframe must match config timeframe")
        for key, minimum in (
            ("reversal_lookback_candles", 5),
            ("reversal_confirm_candles", 2),
            ("reversal_slow_candles", 3),
        ):
            if type(self.settings[key]) is not int or not minimum <= self.settings[key] <= 40:
                raise ValueError(f"leader_squeeze {key} must be an integer within [{minimum}, 40]")
        if (
            max(self.settings["reversal_lookback_candles"], self.settings["atr_period"] + 1)
            + self.settings["reversal_confirm_candles"]
            > self.startup_candle_count
        ):
            raise ValueError("reversal lookback/confirmation exceeds startup_candle_count")
        if (
            not math.isfinite(float(self.settings["reversal_atr_buffer"]))
            or float(self.settings["reversal_atr_buffer"]) < 0
        ):
            raise ValueError("leader_squeeze reversal_atr_buffer must be non-negative and finite")
        fast_buffer = float(self.settings["reversal_fast_atr_buffer"])
        if not math.isfinite(fast_buffer) or fast_buffer <= float(
            self.settings["reversal_atr_buffer"]
        ):
            raise ValueError(
                "reversal_fast_atr_buffer must be finite and exceed reversal_atr_buffer"
            )
        slow_drop = float(self.settings["reversal_slow_atr_drop"])
        if not math.isfinite(slow_drop) or slow_drop <= 0:
            raise ValueError("reversal_slow_atr_drop must be positive and finite")
        if (
            self.settings["trend_ema_candles"] + self.settings["reversal_slow_candles"]
            > self.startup_candle_count
        ):
            raise ValueError("reversal slow confirmation exceeds startup_candle_count")

    def _validate_entry_heat_settings(self) -> None:
        penalty = self.settings["entry_heat_max_penalty"]
        scale = self.settings["entry_heat_return_scale"]
        start = self.settings["entry_heat_extension_start_atr"]
        full = self.settings["entry_heat_extension_full_atr"]
        if any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (penalty, scale, start, full)
        ):
            raise ValueError("entry heat settings must be finite numbers")
        if not (0 <= penalty <= 0.5 and scale > 0 and 0 <= start < full):
            raise ValueError(
                "entry heat requires penalty within [0, .5], scale > 0, 0 <= start < full"
            )
        if (
            penalty or self.settings["entry_setup_enabled"]
        ) and self.startup_candle_count < self.ENTRY_HEAT_HISTORY_CANDLES:
            raise ValueError(
                f"entry heat requires {self.ENTRY_HEAT_HISTORY_CANDLES} closed candles"
            )
        launch_candles = self.settings["entry_setup_launch_candles"]
        late_atr = self.settings["entry_setup_late_extension_atr"]
        if type(launch_candles) is not int or not 1 <= launch_candles <= 8:
            raise ValueError("entry_setup_launch_candles must be an integer within [1, 8]")
        if type(late_atr) not in (int, float) or not math.isfinite(late_atr) or late_atr <= start:
            raise ValueError("entry_setup_late_extension_atr must exceed the heat extension start")

    def _validate_tuning_settings(self) -> None:
        """Reject impossible scales and invalid rotation settings before trading."""
        for key in (
            "momentum_return_weight",
            "volume_activity_weight",
            "liquidation_warmup_score",
            "entry_heat_cooled_breakout_factor",
            "entry_heat_base_fraction",
            "replacement_fast_close_location",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"leader_squeeze {key} must be within [0, 1]")
        for key in (
            "volume_score_full_ratio",
            "volume_activity_full_ratio",
            "taker_score_full_ratio",
            "liquidation_score_full_ratio",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 1:
                raise ValueError(f"leader_squeeze {key} must exceed 1")
        for key in (
            "oi_score_full_drop",
            "entry_heat_box_max_width_atr",
            "entry_heat_prebreak_extension_max_atr",
            "entry_heat_breakout_overshoot_atr",
            "replacement_fast_score_gap",
            "replacement_fast_volume_ratio",
            "replacement_fast_taker_ratio",
            "replacement_fast_max_breakout_atr",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"leader_squeeze {key} must be positive and finite")
        self._validate_rotation_settings()

    def _validate_rotation_settings(self) -> None:
        for key, low, high in (
            ("entry_heat_ema_candles", 2, 1440),
            ("entry_heat_box_candles", 2, 1440),
            ("replacement_no_new_high_candles", 2, 100),
            ("replacement_fast_breakout_candles", 2, 100),
            ("replacement_fast_volume_baseline_candles", 2, 100),
            ("replacement_confirmations", 1, 10),
            ("replacement_fast_confirmations", 1, 10),
        ):
            value = self.settings[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"leader_squeeze {key} must be an integer within [{low}, {high}]")
        for key in (
            "replacement_entry_score",
            "replacement_weak_score",
            "replacement_fast_entry_score",
            "replacement_fast_core_score",
            "replacement_candidate_hysteresis",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"leader_squeeze {key} must be within [0, 100]")
        self._validate_rotation_ratio_settings()
        for key in (
            "replacement_min_age_minutes",
            "replacement_cooldown_minutes",
            "replacement_fast_min_age_minutes",
            "replacement_fast_cooldown_minutes",
            "replacement_reentry_cooldown_minutes",
        ):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError(f"leader_squeeze {key} must be non-negative and finite")
        if type(self.settings["replacement_fast_enabled"]) is not bool:
            raise ValueError("replacement_fast_enabled must be boolean")
        if self.settings["replacement_fast_entry_score"] < self.settings["replacement_entry_score"]:
            raise ValueError("fast entry score must be >= normal entry score")
        if self.settings["replacement_fast_score_gap"] < self.settings["replacement_score_gap"]:
            raise ValueError("fast score gap must be >= normal score gap")
        core_max = 100 * sum(
            self.settings["weights"][k] for k in ("momentum", "volume", "taker_buy")
        )
        if (
            self.settings["replacement_fast_enabled"]
            and self.settings["replacement_fast_core_score"] > core_max
        ):
            raise ValueError("replacement_fast_core_score exceeds available weighted core points")

    def _validate_rotation_ratio_settings(self) -> None:
        for key in ("replacement_weak_bottom_ratio", "replacement_target_top_ratio"):
            value = self.settings[key]
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"leader_squeeze {key} must be within (0, 1]")


REQUIRED_SETTINGS = frozenset(
    (
        "leverage",
        "stake_ratio",
        "max_positions",
        "entry_slot_score_thresholds",
        "entry_setup_enabled",
        "entry_setup_score_points",
        "entry_setup_min_score",
        "entry_setup_shortlist_ratio",
        "entry_setup_min_candidates",
        "entry_setup_launch_candles",
        "entry_setup_late_extension_atr",
        "min_absolute_momentum",
        "min_trend_continuity",
        "momentum_full_score",
        "momentum_return_weight",
        "volume_score_full_ratio",
        "volume_activity_weight",
        "volume_activity_full_ratio",
        "volume_activity_baseline_candles",
        "taker_score_full_ratio",
        "oi_score_full_drop",
        "liquidation_score_full_ratio",
        "liquidation_warmup_score",
        "entry_heat_max_penalty",
        "entry_heat_return_scale",
        "entry_heat_extension_start_atr",
        "entry_heat_extension_full_atr",
        "entry_heat_ema_candles",
        "entry_heat_box_candles",
        "entry_heat_box_max_width_atr",
        "entry_heat_prebreak_extension_max_atr",
        "entry_heat_breakout_overshoot_atr",
        "entry_heat_cooled_breakout_factor",
        "entry_heat_base_fraction",
        "liquidation_min_notional",
        "market_min_coverage_ratio",
        "market_down_ratio",
        "market_emergency_enabled",
        "market_emergency_ratio",
        "market_emergency_drop",
        "taker_window_candles",
        "rotation_recovery_enabled",
        "rotation_recovery_grace_seconds",
        "rotation_recovery_interval_seconds",
        "rotation_recovery_max_age_seconds",
        "rotation_recovery_confirmations",
        "rotation_recovery_history_limit",
        "score_refresh_seconds",
        "score_retry_seconds",
        "score_candle_close_delay_seconds",
        "exit_evaluation_failure_limit",
        "profit_shadow_enabled",
        "profit_shadow_file_live",
        "profit_shadow_file_dry_run",
        "profit_r_atr_multiple",
        "profit_r_min_pct",
        "profit_r_max_pct",
        "profit_lock_enabled",
        "profit_lock_arm_r",
        "profit_lock_fee_buffer",
        "profit_lock_trail_r",
        "profit_lock_giveback_frac",
        "profit_lock_min_step_r",
        "profit_no_progress_enabled",
        "profit_no_progress_candles",
        "profit_no_progress_new_high_r",
        "profit_no_progress_max_r",
        "status_log_seconds",
        "raw_metrics_log_enabled",
        "data_grace_seconds",
        "remote_metric_max_age_seconds",
        "liquidation_stream_max_age_seconds",
        "max_spread_ratio",
        "max_slippage_ratio",
        "reversal_lookback_candles",
        "reversal_confirm_candles",
        "reversal_atr_buffer",
        "reversal_fast_atr_buffer",
        "reversal_slow_candles",
        "reversal_slow_atr_drop",
        "holding_timeframe",
        "background_timeframe",
        "trend_slope_candles",
        "reversal_intrabar_atr_buffer",
        "reversal_emergency_memory_candles",
        "replacement_weak_atr_drop",
        "replacement_entry_score",
        "replacement_weak_score",
        "replacement_score_gap",
        "replacement_confirmations",
        "replacement_min_age_minutes",
        "replacement_cooldown_minutes",
        "replacement_no_new_high_candles",
        "replacement_weak_bottom_ratio",
        "replacement_target_top_ratio",
        "replacement_candidate_hysteresis",
        "replacement_reentry_cooldown_minutes",
        "replacement_fast_enabled",
        "replacement_fast_entry_score",
        "replacement_fast_score_gap",
        "replacement_fast_confirmations",
        "replacement_fast_min_age_minutes",
        "replacement_fast_cooldown_minutes",
        "replacement_fast_core_score",
        "replacement_fast_breakout_candles",
        "replacement_fast_volume_baseline_candles",
        "replacement_fast_volume_ratio",
        "replacement_fast_taker_ratio",
        "replacement_fast_close_location",
        "replacement_fast_max_breakout_atr",
        "weights",
        "eth_pair",
        "order_book_max_age_seconds",
        "order_book_depth",
        "entry_heat_history_days",
        "atr_period",
        "trend_ema_candles",
        "eth_confirm_candles",
        "eth_fast_atr_buffer",
        "reversal_pivot_side_candles",
        "momentum_lookback_candles",
        "trend_continuity_candles",
        "volume_window_candles",
        "volume_baseline_windows",
        "candle_min_history",
        "oi_sample_count",
        "liquidation_window_seconds",
        "liquidation_recent_seconds",
        "position_sync_seconds",
        "position_stale_seconds",
        "risk_state_checkpoint_seconds",
        "metric_request_timeout_seconds",
        "metric_request_retries",
        "metric_retry_backoff_seconds",
        "funding_request_timeout_seconds",
        "funding_max_age_seconds",
        "metric_workers",
        "liquidation_open_timeout_seconds",
        "liquidation_close_timeout_seconds",
        "liquidation_receive_timeout_seconds",
        "liquidation_reconnect_seconds",
        "rest_base_url",
        "liquidation_stream_url",
        "state_file_live",
        "state_file_dry_run",
        "rotation_audit_enabled",
        "rotation_audit_statement_timeout_ms",
        "rotation_audit_retry_seconds",
        "rotation_audit_spool_live",
        "rotation_audit_spool_dry_run",
    )
)
FRAMEWORK_SETTINGS = (
    "timeframe",
    "startup_candle_count",
    "minimal_roi",
    "stoploss",
    "use_exit_signal",
    "exit_profit_only",
    "position_adjustment_enable",
    "process_only_new_candles",
    "order_types",
    "order_time_in_force",
)


def configure_strategy(strategy, config: dict, *, framework: bool = True) -> None:
    from copy import deepcopy

    supplied = config.get("leader_squeeze", {})
    if not isinstance(supplied, dict):
        raise ValueError("leader_squeeze must be a configuration object")
    missing = sorted(REQUIRED_SETTINGS - supplied.keys())
    missing += [key for key in FRAMEWORK_SETTINGS if key not in config]
    if missing:
        raise ValueError("Missing required strategy configuration: " + ", ".join(missing))
    expected_weights = {
        "momentum",
        "volume",
        "taker_buy",
        "liquidation",
        "oi_squeeze",
        "funding",
    }
    if set(supplied["weights"]) != expected_weights:
        raise ValueError("leader_squeeze.weights must specify all six score components")
    strategy.config = config
    strategy.settings = deepcopy(supplied)
    if framework:
        for key in FRAMEWORK_SETTINGS:
            setattr(strategy, key, deepcopy(config[key]))


def validate_runtime_settings(strategy) -> None:
    settings = strategy.settings
    integer_keys = (
        "atr_period",
        "trend_ema_candles",
        "eth_confirm_candles",
        "reversal_pivot_side_candles",
        "momentum_lookback_candles",
        "trend_continuity_candles",
        "volume_window_candles",
        "volume_baseline_windows",
        "volume_activity_baseline_candles",
        "candle_min_history",
        "oi_sample_count",
        "metric_workers",
        "taker_window_candles",
        "rotation_recovery_confirmations",
        "rotation_recovery_history_limit",
        "entry_heat_history_days",
        "order_book_depth",
        "rotation_audit_statement_timeout_ms",
        "trend_slope_candles",
        "reversal_emergency_memory_candles",
        "exit_evaluation_failure_limit",
        "profit_no_progress_candles",
    )
    for key in integer_keys:
        if type(settings[key]) is not int or settings[key] <= 0:
            raise ValueError(f"leader_squeeze.{key} must be a positive integer")
    for key, value in settings.items():
        if key.endswith("_seconds") and (
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
        ):
            raise ValueError(f"leader_squeeze.{key} must be positive and finite")
    _validate_remote_request_settings(settings)
    _validate_score_refresh_timing(settings, strategy.timeframe)
    for key in (
        "replacement_fast_enabled",
        "rotation_audit_enabled",
        "market_emergency_enabled",
        "rotation_recovery_enabled",
        "raw_metrics_log_enabled",
        "profit_shadow_enabled",
        "profit_lock_enabled",
        "profit_no_progress_enabled",
    ):
        if type(settings[key]) is not bool:
            raise ValueError(f"leader_squeeze.{key} must be boolean")
    if settings["liquidation_recent_seconds"] >= settings["liquidation_window_seconds"]:
        raise ValueError(
            "liquidation_recent_seconds must be smaller than liquidation_window_seconds"
        )
    if settings["oi_sample_count"] < 2:
        raise ValueError("oi_sample_count must include at least two observations")
    eth_fast_buffer = settings["eth_fast_atr_buffer"]
    if (
        type(eth_fast_buffer) not in (int, float)
        or not math.isfinite(eth_fast_buffer)
        or eth_fast_buffer <= 0
    ):
        raise ValueError("leader_squeeze.eth_fast_atr_buffer must be positive and finite")
    _validate_volume_history(strategy)
    _validate_execution_safety_settings(settings)
    _validate_profit_protection_settings(settings)
    if settings["reversal_lookback_candles"] < 2 * settings["reversal_pivot_side_candles"] + 1:
        raise ValueError("reversal lookback cannot hold the configured pivot window")
    _validate_multi_timeframe_settings(strategy)
    required_history = max(
        settings[key] + 1 for key in integer_keys if key.endswith("_candles") or key == "atr_period"
    )
    if (
        type(strategy.startup_candle_count) is not int
        or strategy.startup_candle_count < required_history
    ):
        raise ValueError("startup_candle_count does not cover the configured indicator windows")


def _validate_remote_request_settings(settings: dict) -> None:
    retries = settings["metric_request_retries"]
    if type(retries) is not int or not 0 <= retries <= 3:
        raise ValueError("leader_squeeze.metric_request_retries must be within [0, 3]")


def _validate_score_refresh_timing(settings: dict, timeframe: str) -> None:
    if settings["score_candle_close_delay_seconds"] >= timeframe_to_seconds(timeframe):
        raise ValueError("score_candle_close_delay_seconds must be smaller than timeframe")


def _validate_execution_safety_settings(settings: dict) -> None:
    for key in ("market_emergency_ratio", "market_emergency_drop"):
        value = settings[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError(f"{key} must be within (0, 1]")
    if not (
        1 <= settings["taker_window_candles"] <= 500
        and 2 <= settings["rotation_recovery_confirmations"] <= 10
        and 1 <= settings["rotation_recovery_history_limit"] <= 1000
        and settings["rotation_recovery_interval_seconds"]
        <= settings["rotation_recovery_grace_seconds"]
        < settings["rotation_recovery_max_age_seconds"]
        <= 2 * 86400
    ):
        raise ValueError("invalid taker window or rotation recovery limits")


def _validate_profit_protection_settings(settings: dict) -> None:
    """盈利保护参数: R 区间、棘轮步长与影子账本开关的一致性。"""
    for key in (
        "profit_r_atr_multiple",
        "profit_lock_arm_r",
        "profit_no_progress_new_high_r",
    ):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"leader_squeeze.{key} must be positive and finite")
    for key in (
        "profit_lock_fee_buffer",
        "profit_lock_trail_r",
        "profit_lock_giveback_frac",
        "profit_lock_min_step_r",
    ):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"leader_squeeze.{key} must be non-negative and finite")
    if settings["profit_lock_giveback_frac"] >= 1.0:
        raise ValueError("leader_squeeze.profit_lock_giveback_frac must stay below 1.0")
    if settings["profit_lock_fee_buffer"] >= 0.1:
        raise ValueError("leader_squeeze.profit_lock_fee_buffer must stay below 0.1")
    min_pct, max_pct = settings["profit_r_min_pct"], settings["profit_r_max_pct"]
    if not (
        type(min_pct) in (int, float)
        and type(max_pct) in (int, float)
        and 0 < min_pct < max_pct <= 0.5
    ):
        raise ValueError(
            "leader_squeeze.profit_r_min_pct must be within (0, profit_r_max_pct] and <= 0.5"
        )
    max_r = settings["profit_no_progress_max_r"]
    if (
        type(max_r) not in (int, float)
        or not math.isfinite(max_r)
        or not 0 <= max_r < settings["profit_lock_arm_r"]
    ):
        raise ValueError(
            "leader_squeeze.profit_no_progress_max_r must be finite and within "
            "[0, profit_lock_arm_r)"
        )
    for key in ("profit_shadow_file_live", "profit_shadow_file_dry_run"):
        value = settings[key]
        if type(value) is not str or not value.strip():
            raise ValueError(f"leader_squeeze.{key} must be a non-empty path")
    # 棘轮与动量止损都读取影子账本算出的状态, 因此必须先启用账本。
    if (settings["profit_lock_enabled"] or settings["profit_no_progress_enabled"]) and not settings[
        "profit_shadow_enabled"
    ]:
        raise ValueError(
            "leader_squeeze.profit_shadow_enabled must be true when profit protection is enabled"
        )


def _validate_volume_history(strategy) -> None:
    settings = strategy.settings
    if settings["volume_activity_baseline_candles"] <= settings["volume_baseline_windows"]:
        raise ValueError("volume activity baseline must exceed the short baseline")
    if type(strategy.startup_candle_count) is not int or (
        strategy.startup_candle_count
        < settings["volume_window_candles"]
        + max(settings["volume_baseline_windows"], settings["volume_activity_baseline_candles"])
    ):
        raise ValueError("startup_candle_count must cover both volume baselines and signal window")


def _validate_multi_timeframe_settings(strategy) -> None:
    from freqtrade.exchange import timeframe_to_seconds

    settings = strategy.settings
    try:
        base = timeframe_to_seconds(strategy.timeframe)
        holding = timeframe_to_seconds(settings["holding_timeframe"])
        background = timeframe_to_seconds(settings["background_timeframe"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("invalid holding_timeframe/background_timeframe") from exc
    if not (base < holding < background and holding % base == background % base == 0):
        raise ValueError("higher timeframes must increase and be exact multiples of timeframe")
    for key in ("reversal_intrabar_atr_buffer", "replacement_weak_atr_drop"):
        value = settings[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"leader_squeeze.{key} must be positive and finite")
    if settings["reversal_intrabar_atr_buffer"] < settings["reversal_atr_buffer"]:
        raise ValueError("intrabar ATR buffer must be >= ordinary reversal ATR buffer")
    holding_count = max(
        max(settings["reversal_lookback_candles"], settings["atr_period"] + 1)
        + settings["reversal_confirm_candles"],
        settings["trend_ema_candles"] + settings["reversal_slow_candles"],
        settings["trend_ema_candles"] + settings["trend_slope_candles"],
        settings["replacement_no_new_high_candles"],
    )
    background_count = max(
        settings["trend_ema_candles"] + settings["trend_slope_candles"],
        settings["atr_period"] + 2,
    )
    aggregation_history = max(
        (holding_count + 1) * (holding // base),
        (background_count + 1) * (background // base),
        settings["reversal_emergency_memory_candles"]
        + (max(settings["reversal_lookback_candles"], settings["atr_period"] + 1) + 1)
        * (holding // base),
    )
    if strategy.startup_candle_count < aggregation_history:
        raise ValueError("startup_candle_count does not cover complete higher timeframe windows")


class LeaderDataMixin(LeaderMixinContext):
    def _scheduled_score_refresh(self, now: float, deadline: float) -> float:
        period = timeframe_to_seconds(self.timeframe)
        delay = float(self.settings["score_candle_close_delay_seconds"])
        boundary = math.floor(now / period) * period
        after_close = boundary + delay
        if after_close <= now:
            after_close += period
        regular = min(now + float(self.settings["score_refresh_seconds"]), after_close)
        if deadline >= regular:
            return regular
        retry = float(self.settings["score_retry_seconds"])
        return max(now + retry, deadline - retry)

    def _start_score_refresh(self, now: float, *, exit_only: bool = False) -> None:
        self._last_score_request = now
        leaders = [] if exit_only else self.dp.current_selection_whitelist()
        self._score_selection = leaders.copy()
        held = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
        pairs = list(dict.fromkeys([*leaders, *sorted(held)]))
        if not pairs or (not exit_only and not leaders):
            self._data_healthy = False
            self._next_score_refresh = now + float(self.settings["score_retry_seconds"])
            return

        self._score_pending = True
        self._next_score_refresh = math.inf
        if exit_only:
            logger.info("🛡️ ETH拦截期间仅刷新持仓行情指标: %s", pairs, extra=LOG_INFO)

        def fetch() -> None:
            try:
                metrics = (
                    self._fetch_market_metrics(pairs, exit_only=True)
                    if exit_only
                    else self._fetch_market_metrics(pairs)
                )
            except Exception as exc:
                logger.warning("⚠️ 行情指标刷新失败: %s", exc, extra=LOG_WARN)
                metrics = {}
            with self._score_result_lock:
                self._score_result = (time.time(), leaders, metrics)
                self._score_pending = False

        threading.Thread(target=fetch, name="leader-squeeze-metrics", daemon=True).start()

    def _consume_score_refresh(self, now: float, *, allow_scoring: bool = True) -> bool:
        with self._score_result_lock:
            result, self._score_result = self._score_result, None
        if result is None:
            return False

        completed_at, leaders, metrics = result
        exit_metrics = getattr(self, "_exit_metrics", {})
        fresh_exits = {
            pair: item
            for pair, item in metrics.items()
            if self._metrics_current(item, now, exit_only=True)
        }
        exit_metrics.update(fresh_exits)
        self._exit_metrics = exit_metrics
        if not leaders or not allow_scoring:
            deadline = min(
                (item["_exit_valid_until"] for item in fresh_exits.values()), default=now
            )
            self._next_score_refresh = self._scheduled_score_refresh(now, deadline)
            return False
        pairs = list(dict.fromkeys([*leaders, *metrics]))
        candles = {
            pair: candle for pair in pairs if (candle := self._candle_metrics(pair)) is not None
        }
        self._update_market_state(leaders, candles)
        combined = {
            pair: {
                **remote,
                **candles[pair],
                "_score_valid_until": min(
                    remote["_score_valid_until"], candles[pair]["_candle_valid_until"]
                ),
            }
            for pair, remote in metrics.items()
            if pair in candles and self._metrics_current(remote, now)
        }
        valid_leaders = {
            pair: combined[pair]
            for pair in leaders
            if pair in combined and "momentum" in combined[pair]
        }

        required = self._required_leader_count(len(leaders))
        if len(valid_leaders) < required:
            self._data_healthy = False
            self._record_rotation_event(
                "blocked",
                "评分数据覆盖不足, 清除确认计数",
                {"fresh": len(valid_leaders), "required": required},
                once=True,
            )
            self._rotation_candidate, self._rotation_seen = None, 0
            logger.warning(
                "⛔ 行情覆盖不足 | 完整数据=%s/%s | 新开仓保持暂停",
                len(valid_leaders),
                len(leaders),
                extra=LOG_WARN,
            )
            self._next_score_refresh = now + float(self.settings["score_retry_seconds"])
            return False

        scoreable = {pair: item for pair, item in combined.items() if "momentum" in item}
        self._score_leaders = leaders
        self._apply_scores(completed_at, scoreable, combined)
        deadline = min(
            min(item["_score_valid_until"], item["_exit_valid_until"])
            for item in valid_leaders.values()
        )
        self._next_score_refresh = self._scheduled_score_refresh(now, deadline)
        return True

    def _score_coverage(self, now: float) -> tuple[int, int, int]:
        leaders = getattr(self, "_entry_leaders", None)
        if leaders is None:
            leaders = getattr(self, "_score_leaders", [])
        metrics = getattr(self, "_metrics", {})
        fresh = sum(self._metrics_current(metrics.get(pair, {}), now) for pair in leaders)
        return fresh, len(leaders), self._required_leader_count(len(leaders))

    def _advance_score_refresh(self, now: float, *, allow_scoring: bool) -> None:
        """名单变化/有效覆盖丢失后及时补刷新, 最快30秒一批, 不并发重复请求。"""
        if not allow_scoring or self._score_pending:
            return
        if now - getattr(self, "_last_score_request", 0) < float(
            self.settings["score_retry_seconds"]
        ):
            return
        fresh, _, required = self._score_coverage(now)
        leaders = getattr(self, "_entry_leaders", None)
        changed = leaders is not None and set(leaders) != set(getattr(self, "_score_leaders", []))
        if changed or not required or fresh < required or not self._data_healthy:
            self._next_score_refresh = min(self._next_score_refresh, now)

    def _fetch_market_metrics(
        self, pairs: list[str], *, exit_only: bool = False
    ) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        with ThreadPoolExecutor(
            max_workers=min(self.settings["metric_workers"], len(pairs))
        ) as pool:
            funding_future = (
                pool.submit(self._fetch_funding_metrics, pairs)
                if not exit_only and self.settings["weights"].get("funding", 0) > 0
                else None
            )
            futures = {
                pool.submit(self._fetch_pair_metrics, pair, exit_only=exit_only): pair
                for pair in pairs
            }
            for future in as_completed(futures):
                pair = futures[future]
                try:
                    result[pair] = future.result()
                except Exception as exc:
                    logger.warning("⚠️ 行情指标刷新失败 %s: %s", pair, exc, extra=LOG_WARN)
            if funding_future is not None:
                try:
                    for pair, funding in funding_future.result().items():
                        if pair in result:
                            result[pair].update(funding)
                except Exception as exc:
                    logger.warning(
                        "⚠️ 资金费率批次失败, 不调整评分且不单独拦截: %s",
                        exc,
                        extra=LOG_WARN,
                    )
        return result

    def _fetch_funding_metrics(self, pairs: list[str]) -> dict[str, dict[str, float]]:
        """每个评分批次仅两次公开请求; 费率/上下限缺失不会使核心指标失效。"""
        result: dict[str, dict[str, float]] = {}
        requested_at = time.time()
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("httpsProxy")
        session = requests.Session()
        try:
            payloads = []
            for endpoint in ("fundingInfo", "premiumIndex"):
                for attempt in range(int(self.settings["metric_request_retries"]) + 1):
                    try:
                        response = session.get(
                            f"{self.settings['rest_base_url']}/fapi/v1/{endpoint}",
                            proxies={"http": proxy, "https": proxy} if proxy else None,
                            timeout=self.settings["funding_request_timeout_seconds"],
                        )
                        response.raise_for_status()
                        payload = response.json()
                        break
                    except requests.RequestException:
                        if attempt >= int(self.settings["metric_request_retries"]):
                            raise
                        time.sleep(
                            float(self.settings["metric_retry_backoff_seconds"]) * 2**attempt
                        )
                if not isinstance(payload, list):
                    raise ValueError(f"invalid {endpoint} response")
                payloads.append(
                    {
                        item["symbol"]: item
                        for item in payload
                        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
                    }
                )
            infos, rates = payloads
            now = time.time()
            for pair in pairs:
                try:
                    symbol = self._market_id(pair)
                    result[pair] = self._parse_funding_metric(
                        infos[symbol], rates[symbol], now, requested_at
                    )
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    logger.warning(
                        "⚠️ 资金费率/实际限额不可用 %s (%s), 调整=0, 不单独拦截",
                        pair,
                        type(exc).__name__,
                        extra=LOG_WARN,
                    )
        except Exception as exc:
            logger.warning("⚠️ 资金费率获取失败, 调整=0, 不单独拦截: %s", exc, extra=LOG_WARN)
        finally:
            session.close()
        return result

    def _parse_funding_metric(
        self, info: dict, rate: dict, now: float, requested_at: float
    ) -> dict[str, float]:
        hours = float(info["fundingIntervalHours"])
        value = float(rate["lastFundingRate"])
        floor = float(info["adjustedFundingRateFloor"])
        cap = float(info["adjustedFundingRateCap"])
        sampled_at = float(rate["time"]) / 1000
        next_time = float(rate["nextFundingTime"]) / 1000
        max_age = float(self.settings["funding_max_age_seconds"])
        if not (
            all(math.isfinite(v) for v in (hours, value, floor, cap, sampled_at, next_time))
            and 1 <= hours <= 24
            and hours.is_integer()
            and -1 <= floor < 0 < cap <= 1
            and abs(value) <= 1
            and sampled_at > 0
            and 0 <= now - sampled_at <= max_age
            and 0 <= now - requested_at <= max_age
            and next_time > now
            and next_time - sampled_at <= hours * 3600 + float(self.settings["data_grace_seconds"])
        ):
            raise ValueError("invalid or stale funding rate/interval/limits")
        return {
            "funding_rate": value,
            "funding_interval_hours": hours,
            "funding_rate_hourly": value / hours,
            "funding_floor": floor,
            "funding_cap": cap,
            "funding_floor_hourly": floor / hours,
            "funding_cap_hourly": cap / hours,
            "funding_next_time": next_time,
            "_funding_valid_until": min(sampled_at + max_age, requested_at + max_age, next_time),
        }

    @staticmethod
    def _taker_ratio(buy_volume: float, sell_volume: float, full_ratio: float) -> float:
        if not math.isfinite(buy_volume) or not math.isfinite(sell_volume):
            raise ValueError("invalid aggregate taker volumes")
        if sell_volume == 0:
            return 1.0 if buy_volume == 0 else full_ratio
        value = buy_volume / sell_volume
        if not math.isfinite(value):
            raise ValueError("invalid taker ratio")
        return value

    @classmethod
    def _parse_taker_rows(
        cls,
        rows: list[dict[str, Any]],
        *,
        window: int,
        timeframe: str,
        now: float,
        full_ratio: float,
    ) -> tuple[float, float]:
        if len(rows) < window:
            raise ValueError("insufficient taker candles")
        if not math.isfinite(full_ratio) or full_ratio <= 1:
            raise ValueError("invalid taker full ratio")
        period_ms = timeframe_to_seconds(timeframe) * 1000
        timestamps: list[int] = []
        volumes: list[tuple[float, float]] = []
        for row in rows[-window:]:
            timestamp = int(row.get("timestamp") or 0)
            if timestamp <= 0 or timestamp + period_ms > now * 1000:
                raise ValueError("invalid or unclosed taker timestamp")
            buy_volume = float(row["buyVol"])
            sell_volume = float(row["sellVol"])
            if not all(math.isfinite(value) and value >= 0 for value in (buy_volume, sell_volume)):
                raise ValueError("invalid taker volumes")
            timestamps.append(timestamp)
            volumes.append((buy_volume, sell_volume))
        if any(current - previous != period_ms for previous, current in pairwise(timestamps)):
            raise ValueError("taker candles are not continuous")

        buy_volume = sum(buy for buy, _ in volumes)
        sell_volume = sum(sell for _, sell in volumes)
        return (
            cls._taker_ratio(buy_volume, sell_volume, full_ratio),
            cls._taker_ratio(*volumes[-1], full_ratio),
        )

    def _fetch_metric_rows(
        self,
        session,
        base: str,
        common: dict[str, str],
        proxies: dict[str, str] | None,
        path: str,
        limit: int,
        *,
        bucket_start_timestamp: bool = False,
        request_extra_bucket: bool = False,
    ) -> tuple[list[dict[str, Any]], float]:
        period_seconds = timeframe_to_seconds(self.timeframe)
        now = time.time()
        params: dict[str, str | int] = {
            **common,
            "limit": limit + int(request_extra_bucket),
        }
        for attempt in range(int(self.settings["metric_request_retries"]) + 1):
            try:
                response = session.get(
                    f"{base}/{path}",
                    params=params,
                    proxies=proxies,
                    timeout=self.settings["metric_request_timeout_seconds"],
                )
                response.raise_for_status()
                payload = response.json()
                break
            except requests.RequestException:
                if attempt >= int(self.settings["metric_request_retries"]):
                    raise
                time.sleep(float(self.settings["metric_retry_backoff_seconds"]) * 2**attempt)
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"empty {path} response")
        payload = sorted(payload, key=lambda row: int(row.get("timestamp") or 0))
        if bucket_start_timestamp:
            payload = [
                row
                for row in payload
                if int(row.get("timestamp") or 0) > 0
                and int(row["timestamp"]) / 1000 + period_seconds <= now
            ]
        payload = payload[-limit:]
        if len(payload) < limit:
            if path == "takerlongshortRatio":
                raise ValueError("insufficient taker candles")
            raise ValueError(f"insufficient {path} buckets")
        timestamp = int(payload[-1]["timestamp"])
        max_age = float(self.settings["remote_metric_max_age_seconds"])
        period_end = timestamp / 1000 + (period_seconds if bucket_start_timestamp else 0)
        if not 0 <= now - period_end <= max_age:
            raise ValueError(f"stale {path} response")
        return payload, period_end + max_age

    def _fetch_pair_metrics(self, pair: str, *, exit_only: bool = False) -> dict[str, float]:
        symbol = self._market_id(pair)
        base = f"{self.settings['rest_base_url']}/futures/data"
        common: dict[str, str] = {"symbol": symbol, "period": self.timeframe}
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("httpsProxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        api_key = self.config.get("exchange", {}).get("key")
        session = requests.Session()
        if api_key:
            session.headers["X-MBX-APIKEY"] = api_key
        valid_until: dict[str, float] = {}

        def get(
            path: str,
            limit: int,
            *,
            bucket_start_timestamp: bool = False,
            request_extra_bucket: bool = False,
        ) -> list[dict[str, Any]]:
            payload, deadline = self._fetch_metric_rows(
                session,
                base,
                common,
                proxies,
                path,
                limit,
                bucket_start_timestamp=bucket_start_timestamp,
                request_extra_bucket=request_extra_bucket,
            )
            valid_until[path] = deadline
            return payload

        try:
            taker_window = self.settings["taker_window_candles"]
            if type(taker_window) is not int or taker_window < 1:
                raise ValueError("invalid taker window")
            taker_rows = get("takerlongshortRatio", taker_window, bucket_start_timestamp=True)
            taker_ratio, taker_ratio_latest = self._parse_taker_rows(
                taker_rows,
                window=taker_window,
                timeframe=self.timeframe,
                now=time.time(),
                full_ratio=float(self.settings["taker_score_full_ratio"]),
            )
            oi_change = 0.0
            if self.settings["weights"]["oi_squeeze"] > 0:
                oi = get(
                    "openInterestHist",
                    self.settings["oi_sample_count"],
                    bucket_start_timestamp=True,
                    request_extra_bucket=True,
                )
                oi_first, oi_last = (
                    float(oi[0]["sumOpenInterest"]),
                    float(oi[-1]["sumOpenInterest"]),
                )
                if not all(math.isfinite(value) for value in (oi_first, oi_last)) or (
                    oi_first <= 0 or oi_last < 0
                ):
                    raise ValueError("invalid OI values")
                oi_change = oi_last / oi_first - 1.0
            if not math.isfinite(taker_ratio) or taker_ratio < 0:
                raise ValueError("invalid taker values")
            exit_metric = {
                "taker_ratio": taker_ratio,
                "taker_ratio_latest": taker_ratio_latest,
                "taker_latest_candle_time": int(taker_rows[-1]["timestamp"]) / 1000,
                "oi_change": oi_change,
                "_exit_valid_until": min(valid_until.values()),
            }
            if exit_only:
                return exit_metric
            return {**exit_metric, "_score_valid_until": exit_metric["_exit_valid_until"]}
        finally:
            session.close()

    @staticmethod
    def _metrics_current(metric: dict[str, float], now: float, *, exit_only: bool = False) -> bool:
        deadlines = (
            ("_exit_valid_until",) if exit_only else ("_exit_valid_until", "_score_valid_until")
        )
        return all(
            type(metric.get(key)) in (int, float)
            and math.isfinite(metric[key])
            and 0 < metric[key] >= now
            for key in deadlines
        )

    def _pair_score_current(self, pair: str, now: float | None = None) -> bool:
        if self._metrics_current(
            getattr(self, "_metrics", {}).get(pair, {}), time.time() if now is None else now
        ):
            return True
        self._warn_data_unavailable(f"{pair} 评分指标", "缓存缺失或已过期, 等待新指标")
        return False

    def _warn_data_unavailable(self, key: str, reason: str) -> None:
        now = time.time()
        warnings = getattr(self, "_data_warning_times", {})
        if now - warnings.get(key, -math.inf) >= float(self.settings["status_log_seconds"]):
            logger.warning(
                "⚠️ 数据不可用 %s | %s | 跳过依赖此数据的信号", key, reason, extra=LOG_WARN
            )
            warnings[key] = now
        self._data_warning_times = warnings

    @report_cached
    def _closed_candles(
        self,
        pair: str,
        timeframe: str,
        count: int,
        *,
        columns: tuple[str, ...] = ("close",),
        now: float | None = None,
    ) -> DataFrame | None:
        """仅接受新鲜、连续且已收盘的 K 线, 不以接口响应时间替代行情时间。"""
        try:
            dataframe = self.dp.get_pair_dataframe(pair, timeframe)
            if not {"date", *columns}.issubset(dataframe.columns):
                raise ValueError("缺少必要K线字段")
            seconds = timeframe_to_seconds(timeframe)
            current_time = datetime.fromtimestamp(time.time() if now is None else now, UTC)
            dataframe = dataframe.loc[
                dataframe["date"] <= current_time - timedelta(seconds=seconds)
            ]
            if len(dataframe) < count:
                raise ValueError("已收盘K线数量不足")
            dates = dataframe["date"]
            age = (current_time - dates.iloc[-1]).total_seconds()
            if age > 2 * seconds + float(self.settings["data_grace_seconds"]):
                raise ValueError(f"K线过期: {age:.0f}秒")
            if not dates.diff().dropna().dt.total_seconds().eq(seconds).all():
                raise ValueError("K线时间不连续")
            for column in ("close", "high", "low", "volume"):
                if column in dataframe:
                    values = dataframe[column]
                    if not values.map(math.isfinite).all() or (
                        (values < 0).any() if column == "volume" else (values <= 0).any()
                    ):
                        raise ValueError(f"K线{column}数值无效")
            return dataframe
        except Exception as exc:
            self._warn_data_unavailable(f"{pair} {timeframe}", str(exc))
            return None

    def _market_id(self, pair: str) -> str:
        return self._exchange._api.market_id(pair)

    @property
    def _exchange(self) -> Exchange:
        exchange = self.dp._exchange
        if exchange is None:
            raise RuntimeError("Exchange is not available")
        return exchange

    @property
    def _wallets(self) -> Wallets:
        if self.wallets is None:
            raise RuntimeError("Wallets are not available")
        return self.wallets

    def _liquidation_stream_stale(
        self, now: float, connected_at: float, stream_max_age: float
    ) -> bool:
        with self._liquidation_lock:
            last_message = self._liquidation_last_message
        reference = last_message or connected_at
        return now >= reference and now - reference > stream_max_age

    def _receive_liquidation_payload(
        self, socket: Any, timeout: float, connected_at: float, stream_max_age: float
    ) -> tuple[Any, bool]:
        try:
            raw_payload = socket.recv(timeout=timeout)
        except TimeoutError:
            if self._stop_event.is_set():
                return None, True
            if self._liquidation_stream_stale(time.time(), connected_at, stream_max_age):
                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
            # A single websocket receive timeout is not proof of a断流. Keep the
            # existing window and let the age gate decide when reconnecting is necessary.
            return None, False
        try:
            return json.loads(raw_payload), False
        except (TypeError, ValueError, UnicodeDecodeError):
            # Malformed input is isolated to this message. It does not refresh the
            # stream heartbeat or force a reconnect.
            if self._liquidation_stream_stale(time.time(), connected_at, stream_max_age):
                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
            return None, False

    def _liquidation_worker(self) -> None:
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("wsProxy")
        url = self.settings["liquidation_stream_url"]
        while not self._stop_event.is_set():
            try:
                with connect(
                    url,
                    proxy=proxy or True,
                    open_timeout=self.settings["liquidation_open_timeout_seconds"],
                    close_timeout=self.settings["liquidation_close_timeout_seconds"],
                ) as socket:
                    self._reset_liquidation_window()
                    connected_at = time.time()
                    stream_max_age = float(self.settings["liquidation_stream_max_age_seconds"])
                    receive_timeout = min(
                        float(self.settings["liquidation_receive_timeout_seconds"]),
                        stream_max_age,
                    )
                    while not self._stop_event.is_set():
                        payload, stop = self._receive_liquidation_payload(
                            socket, receive_timeout, connected_at, stream_max_age
                        )
                        if stop:
                            break
                        if payload is None:
                            if self._liquidation_stream_stale(
                                time.time(), connected_at, stream_max_age
                            ):
                                self._liquidation_connected.clear()
                                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
                            continue
                        received_at = time.time()
                        if self._liquidation_last_message and (
                            received_at - self._liquidation_last_message > stream_max_age
                            or received_at < self._liquidation_last_message
                        ):
                            self._reset_liquidation_window()
                        if not self._process_liquidation_payload(payload, received_at):
                            if self._liquidation_stream_stale(
                                received_at, connected_at, stream_max_age
                            ):
                                self._liquidation_connected.clear()
                                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
                            continue
                        with self._liquidation_lock:
                            self._liquidation_last_message = received_at
                            if not self._liquidation_started:
                                self._liquidation_started = received_at
                        self._prune_liquidations(received_at)
                        self._liquidation_connected.set()
            except Exception as exc:
                self._liquidation_connected.clear()
                if not self._stop_event.wait(self.settings["liquidation_reconnect_seconds"]):
                    logger.warning("🔌 强平数据流断开, 正在重连: %s", exc, extra=LOG_WARN)
            finally:
                self._liquidation_connected.clear()

    def _reset_liquidation_window(self) -> None:
        initial = not (
            getattr(self, "_liquidation_window_initialized", False)
            or getattr(self, "_liquidation_started", 0)
            or getattr(self, "_liquidation_last_message", 0)
        )
        self._liquidation_connected.clear()
        with self._liquidation_lock:
            self._liquidations.clear()
            self._liquidation_started = 0.0
            self._liquidation_last_message = 0.0
        self._liquidation_window_initialized = True
        logger.log(
            logging.INFO if initial else logging.WARNING,
            "🔌 强平流%s | %s%.0f分钟; 期间强平评分使用配置值, 收到有效心跳后不单独阻止开仓",
            "初始化统计窗口" if initial else "连接重建或心跳断档, 清空统计窗口",
            "预热" if initial else "重新预热",
            self.settings["liquidation_window_seconds"] / 60,
            extra=LOG_INFO if initial else LOG_WARN,
        )

    def _prune_liquidations(self, now: float) -> None:
        """由全市场心跳清理所有币种, 不依赖币种是否参与排名。"""
        with self._liquidation_lock:
            for symbol, events in list(self._liquidations.items()):
                while events and events[0][0] < now - self.settings["liquidation_window_seconds"]:
                    events.popleft()
                if not events:
                    del self._liquidations[symbol]

    def _process_liquidation_payload(self, payload: Any, received_at: float) -> bool:
        if not isinstance(payload, dict):
            return False
        stream = payload.get("stream")
        data = payload.get("data", payload)
        if stream == "!markPrice@arr@1s":
            return isinstance(data, list)
        if not isinstance(data, dict) or (
            stream != "!forceOrder@arr" and data.get("e") != "forceOrder"
        ):
            return False
        if data.get("st") != 1:
            return True
        order = data.get("o", {})
        if not isinstance(order, dict):
            return False
        if order.get("S") != "BUY":
            return True
        symbol = order.get("s")
        if not isinstance(symbol, str) or not symbol:
            return False
        try:
            price = float(order.get("ap") or order.get("p") or 0)
            quantity = float(order.get("z") or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        notional = price * quantity
        if not (
            math.isfinite(price)
            and math.isfinite(quantity)
            and math.isfinite(notional)
            and price > 0
            and quantity > 0
            and notional > 0
            and math.isfinite(received_at)
        ):
            return False
        with self._liquidation_lock:
            self._liquidations[symbol].append((received_at, notional))
        return True


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
            conditional = self._exchange._api.fetch_open_orders(pair, params={"stop": True})
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

    def _execution_is_safe(
        self, pair: str, *, amount: float | None = None, cached_only: bool = False
    ) -> bool:
        self._execution_block_reason = "盘口安全检查未通过"
        try:
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
            self._execution_block_reason = (
                f"预计滑点 {vwap / ask - 1.0:.3%} > 上限 {self.settings['max_slippage_ratio']:.3%}"
            )
            return vwap / ask - 1.0 <= float(self.settings["max_slippage_ratio"])
        except Exception as exc:
            self._execution_block_reason = f"盘口检查异常 ({type(exc).__name__}): {exc}"
            logger.warning("⚠️ 盘口安全检查异常 %s: %s", pair, exc, extra=LOG_WARN)
            return False

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


class LeaderReportingMixin(LeaderMixinContext):
    def _log_entry_funnel(self) -> None:
        rows = [list(row) for row in getattr(self, "_entry_funnel_rows", [])]

        def candidate_summary(row: list[str]) -> str:
            setup = "形态关闭" if row[2] == "关闭" else f"{row[2]} 形态{row[3]}"
            return f"第{row[1]}仓 {setup} 强度{row[4]}/门槛{row[5]}"

        rows.extend(
            [
                [
                    f"最终候选 {row[0]}",
                    "—",
                    "1",
                    "0",
                    candidate_summary(row),
                ]
                for row in getattr(self, "_entry_funnel_candidates", [])
            ]
        )
        if not rows:
            rows = [["全局闸门", "—", "0", "—", self._entry_block_reason or "尚未评估"]]
        _log_table(
            "🚦 入场漏斗 (本轮管道筛选)",
            ["阶段", "输入", "通过", "淘汰", "规则/主要原因"],
            rows,
            style="cyan",
            caption=(
                "先做硬条件和入场形态, 再取形态短名单, 最后按强度和逐仓门槛选择; "
                "第1仓最宽, 第10仓最严"
            ),
        )

    def _external_sync_label(self, pair: str) -> str:
        sync = self.config.get("manual_position_sync", {})
        if not (sync.get("enabled") and sync.get("import_positions")):
            return "框架未接管"
        if not getattr(self, "_manual_sync_healthy", True):
            return "框架对账异常"
        if pair in getattr(self, "_manual_sync_blocked_pairs", set()):
            return "框架对账中"
        return "等待框架导入"

    def _trend_labels(self, pair: str) -> list[str]:
        names = {"unknown": "数据不足", "weakening": "走弱", "up": "上行", "consolidating": "整理"}
        return [
            names[self._trend_context(pair, self.settings[key])["state"]]
            for key in ("holding_timeframe", "background_timeframe")
        ]

    @staticmethod
    def _opening_score_label(trade: Trade | None) -> str:
        """Use recorded entry data only; old signal tags remain explicitly labelled."""
        if trade is None:
            return "未记录"
        getter = getattr(trade, "get_custom_data", None)
        if callable(getter):
            record = getter("leader_entry_score")
            if isinstance(record, dict):
                score = record.get("score")
                if (
                    score is not None
                    and type(score) in (int, float)
                    and math.isfinite(score)
                    and score >= 0
                ):
                    return f"{score:.1f}"
        tag = getattr(trade, "enter_tag", None)
        if isinstance(tag, str) and tag.startswith("squeeze_"):
            try:
                score = float(tag.removeprefix("squeeze_"))
                if math.isfinite(score) and score >= 0:
                    return f"{score:.1f}(标签)"
            except ValueError:
                pass
        return "未记录"

    @staticmethod
    def _leveraged_return_label(
        entry_price: Any,
        current_price: Any,
        leverage: Any,
        side: Any,
        *,
        stale: bool,
    ) -> str:
        """Return the mark-to-entry price move multiplied by leverage."""
        try:
            entry = float(entry_price)
            current = float(current_price)
            multiplier = float(leverage)
        except (TypeError, ValueError):
            return "未知"
        if (
            side not in {"long", "short"}
            or not all(math.isfinite(value) for value in (entry, current, multiplier))
            or entry <= 0
            or current <= 0
            or multiplier <= 0
        ):
            return "未知"
        price_return = current / entry - 1
        if side == "short":
            price_return = -price_return
        label = f"{100 * price_return * multiplier:+.1f}%"
        return f"{label}(旧)" if stale else label

    @staticmethod
    def _position_principal_label(
        trade: Trade | None,
        position: Any,
        entry_price: Any,
        leverage: Any,
    ) -> str:
        """Return the stake currency committed to the open position."""
        candidates = (
            getattr(trade, "stake_amount", None),
            getattr(position, "collateral", None),
        )
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                principal = float(candidate)
            except (TypeError, ValueError):
                continue
            if math.isfinite(principal) and principal > 0:
                return f"{principal:.2f}"
        try:
            principal = abs(float(position.position)) * float(entry_price) / float(leverage)
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            return "未知"
        return f"{principal:.2f}" if math.isfinite(principal) and principal > 0 else "未知"

    @staticmethod
    def _holding_duration_label(opened: object, now: float) -> str:
        if not isinstance(opened, datetime):
            return "未知"
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=UTC)
        seconds = max(0, int(now - opened.timestamp()))
        if seconds < 60:
            return f"{seconds}秒"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}分钟"
        hours, minutes = divmod(minutes, 60)
        if hours < 24:
            return f"{hours}时{minutes}分"
        days, hours = divmod(hours, 24)
        return f"{days}天{hours}时{minutes}分"

    @staticmethod
    def _holding_sort_key(pair: str, positions: dict[str, Any]) -> tuple[int, float, str]:
        try:
            pnl = float(positions[pair].unrealized_pnl)
        except (AttributeError, KeyError, TypeError, ValueError):
            return (1, 0.0, pair)
        return (0, -pnl, pair) if math.isfinite(pnl) else (1, 0.0, pair)

    @report_snapshot
    def _log_strategy_status(self, now: float) -> None:
        """使用本轮已有结果打印状态, 不为日志额外请求行情或执行交易。"""
        rotation = getattr(self, "_rotation_state", None) or {}
        phase = {
            "buy": "准备先买",
            "buy_pending": "等待买入确认",
            "sell": "等待旧仓退出",
            "review": "需要核对订单",
        }.get(rotation.get("phase", ""), "无轮换")
        signature = (
            self._entry_block_reason,
            tuple(sorted(self._entry_pairs)),
            self._rotation_pair,
            self._rotation_target,
            phase,
            tuple(sorted(getattr(self, "_entry_decisions", {}).items())),
        )
        signature_changed = signature != self._last_status_signature
        if (
            not signature_changed
            and now - self._last_status_log < float(self.settings["status_log_seconds"])
            and not getattr(self, "_score_report_dirty", False)
        ):
            return
        self._last_status_signature, self._last_status_log = signature, now

        def age(timestamp: float) -> str:
            return f"{max(0, now - timestamp):.0f}s" if timestamp else "从未成功"

        heat_labels: dict[str, list[str]] = {}

        def heat_cells(pair: str) -> list[str]:
            if pair not in heat_labels:
                if not (
                    self.settings["entry_heat_max_penalty"] or self.settings["entry_setup_enabled"]
                ):
                    heat_labels[pair] = ["—", "关闭"]
                elif (heat := self._entry_heat_metrics(pair)) is not None:
                    heat_labels[pair] = [
                        f"{100 * heat['return_15d']:+.1f}%",
                        f"{100 * heat['penalty']:.1f}%",
                    ]
                else:
                    heat_labels[pair] = ["未知", "未知"]
            return heat_labels[pair]

        fresh_count, total, required = self._score_coverage(now)
        logger.info(
            "🧭 策略状态 | 全局开仓=%s | 上批评分=%s 当前有效=%s/%s (至少%s) 评分年龄=%s | "
            "评分任务=%s 下次刷新=%s | 仓位同步=%s 年龄=%s | 强平流=%s 心跳年龄=%s | "
            "市场状态=%s",
            self._entry_block_reason or "允许 (仍须通过逐币筛选)",
            "成功" if self._data_healthy else "等待/不足",
            fresh_count,
            total,
            required,
            age(self._last_good_data),
            "进行中" if self._score_pending else "空闲",
            "等待后台结果"
            if math.isinf(self._next_score_refresh)
            else f"{max(0, self._next_score_refresh - now):.0f}s 后",
            "正常" if self._position_data_healthy else "异常",
            age(self._last_position_sync),
            "关闭"
            if self.settings["weights"]["liquidation"] <= 0
            else "已连接"
            if self._liquidation_connected.is_set()
            else "断开",
            "—"
            if self.settings["weights"]["liquidation"] <= 0
            else age(self._liquidation_last_message),
            "未知"
            if not self._market_data_healthy
            else "严重普跌"
            if getattr(self, "_market_emergency", False)
            else "转弱/暂停买入"
            if self._market_down
            else "非普跌",
            extra=LOG_WARN if self._entry_block_reason else LOG_INFO,
        )
        self._log_entry_funnel()
        if not self._consume_score_report(force=True, report_now=now):
            ranked = self._ranked_pairs()
            scores = dict(ranked)
            ranks = {pair: str(rank) for rank, (pair, _) in enumerate(ranked, 1)}
            pairs = dict.fromkeys([*scores, *self._entry_decisions, *sorted(self._entry_pairs)])
            _log_table(
                "📊 评分综合明细 (等待完整评分快照)",
                ["排名", "交易对", "买入评分", "15日涨幅", "热度折扣", "本轮入选", "筛选结果"],
                [
                    [
                        ranks.get(pair, "—"),
                        pair,
                        f"{scores[pair]:.1f}" if math.isfinite(scores.get(pair, math.nan)) else "—",
                        *heat_cells(pair),
                        "是" if pair in self._entry_pairs else "否",
                        self._entry_decisions.get(pair, self._entry_block_reason or "尚未评估"),
                    ]
                    for pair in pairs
                ],
                caption=self._entry_block_reason or "尚无完整评分批次, 仅显示当前可用结果",
            )
        positions = self._wallets.get_all_positions()
        db_trades = {trade.pair: trade for trade in Trade.get_open_trades()}
        db_pairs = set(db_trades)
        logger.info(
            "📦 仓位状态 | 已占用=%s 常规上限=%s 轮换临时上限=%s | 数据库持仓数=%s | "
            "手动仓位框架对账=%s | 主动退出=%s | 钱包缓存仓位数=%s",
            len(db_pairs | self._external_pairs),
            self.settings["max_positions"],
            int(self.settings["max_positions"]) + 1,
            len(db_pairs),
            "开启"
            if self.config.get("manual_position_sync", {}).get("enabled")
            and self.config.get("manual_position_sync", {}).get("import_positions")
            else "关闭",
            "开启"
            if self.config.get("manual_position_sync", {}).get("auto_exit_positions") is True
            else "关闭",
            len(positions),
            extra=LOG_INFO,
        )
        holding_rows, holding_styles = [], []
        for pair in sorted(
            set(positions) | db_pairs | self._external_pairs,
            key=lambda pair: self._holding_sort_key(pair, positions),
        ):
            trade = db_trades.get(pair)
            position = positions.get(pair)
            detail = self._position_details.get(pair, {})
            mark: float | None = None
            try:
                mark = float(detail.get("markPrice"))
                current_price = f"{mark:.8g}" if math.isfinite(mark) and mark > 0 else "未知"
            except (TypeError, ValueError):
                current_price = "未知"
            snapshot_stale = (
                not self._position_data_healthy
                or not 0
                <= now - self._last_position_sync
                <= self.settings["position_stale_seconds"]
            )
            if current_price != "未知" and snapshot_stale:
                current_price += "(旧)"
            entry_score = self._opening_score_label(trade)
            holding_duration = self._holding_duration_label(
                getattr(trade, "open_date_utc", None), now
            )
            protection = (
                "已接管"
                if getattr(trade, "enter_tag", None) == "manual_import"
                else "已跟踪"
                if trade
                else self._external_sync_label(pair)
            )
            heat_return, heat_discount = heat_cells(pair)
            if position is None:
                holding_rows.append(
                    [
                        pair,
                        (
                            "手动导入"
                            if getattr(trade, "enter_tag", None) == "manual_import"
                            else "策略仓位"
                        )
                        if trade
                        else "外部仓位",
                        "钱包缓存缺失",
                        "—",
                        "—",
                        "—",
                        current_price,
                        "—",
                        "—",
                        "—",
                        "—",
                        entry_score,
                        heat_discount,
                        heat_return,
                        "—",
                        protection,
                        *self._trend_labels(pair),
                        holding_duration,
                    ]
                )
                holding_styles.append("yellow")
                continue
            entry_price = getattr(trade, "open_rate", None) or detail.get("entryPrice")
            leverage = (
                position.leverage or detail.get("leverage") or getattr(trade, "leverage", None)
            )
            holding_rows.append(
                [
                    pair,
                    (
                        "手动导入"
                        if getattr(trade, "enter_tag", None) == "manual_import"
                        else "策略仓位"
                    )
                    if trade
                    else "外部仓位",
                    "多单" if position.side == "long" else "空单",
                    f"{position.position:.8f}",
                    str(leverage or "未知"),
                    str(entry_price or "未知"),
                    current_price,
                    self._position_principal_label(trade, position, entry_price, leverage),
                    self._leveraged_return_label(
                        entry_price,
                        mark,
                        leverage,
                        position.side,
                        stale=snapshot_stale,
                    ),
                    f"{position.unrealized_pnl:+.2f}",
                    str(trade.stoploss_or_liquidation) if trade else "等待框架导入",
                    entry_score,
                    heat_discount,
                    heat_return,
                    ("有" if trade.has_open_sl_orders else "无")
                    if trade
                    else self._external_sync_label(pair),
                    protection,
                    *self._trend_labels(pair),
                    holding_duration,
                ]
            )
            holding_styles.append("green" if position.unrealized_pnl >= 0 else "red")
        _log_table(
            "📦 持仓明细",
            [
                "交易对",
                "来源",
                "方向",
                "数量",
                "杠杆",
                "开仓价",
                "当前价(标记)",
                f"本金({self.config['stake_currency']})",
                "当前涨幅(含杠杆)",
                f"未实现盈亏({self.config['stake_currency']})",
                "策略止损价",
                "开仓分数",
                "热度折扣",
                "15日涨幅",
                "交易所止损记录",
                "框架对账",
                f"{self.settings['holding_timeframe']}趋势",
                f"{self.settings['background_timeframe']}背景",
                "持仓时间",
            ],
            holding_rows,
            style="cyan",
            row_styles=holding_styles,
            caption="本金优先使用框架持仓金额, 其次使用交易所保证金, 缺失时按仓位回算; "
            "按未实现盈亏从高到低排序, 缺失盈亏的仓位排在最后; "
            "当前价使用最近同步标记价, (旧)表示同步失效; 当前涨幅按开仓价至标记价的"
            "方向收益乘杠杆计算, "
            "未扣手续费和资金费; 热度折扣仅供新买入参考; "
            "开仓分数取下单复核记录, (标签)为历史信号分, 旧版可能未扣热度",
        )
        self._log_profit_position_table(now, db_trades)
        state = self._risk_state
        equity = float(state.get("last_equity", 0))
        day_start = float(state.get("day_start_equity", 0))
        peak = float(state.get("peak_equity", 0))
        logger.info(
            "🛡️ 账户风控 | 权益=%.2f %s | UTC日收益=%s (仅统计, 不限制开仓) | "
            "峰值回撤=%s (仅统计, 不清仓、不限制开仓) | 状态文件=%s 权益更新时间(UTC)=%s | "
            "轮换候选=%s 确认=%s/%s 旧仓=%s 目标=%s 阶段=%s 通道=%s",
            equity,
            self.config["stake_currency"],
            f"{(equity / day_start - 1) * 100:+.2f}%" if day_start > 0 else "未知",
            f"{(1 - equity / peak) * 100:.2f}%" if peak > 0 else "未知",
            "读取失败, 暂停开仓并保留原文件"
            if getattr(self, "_risk_state_load_failed", False)
            else "读取正常/首次初始化",
            state.get("updated_at", "尚未更新"),
            self._rotation_candidate,
            self._rotation_seen,
            self.settings[
                "replacement_fast_confirmations"
                if getattr(self, "_rotation_candidate_channel", None) == "fast"
                else "replacement_confirmations"
            ],
            self._rotation_pair,
            self._rotation_target,
            phase,
            (getattr(self, "_rotation_state", None) or {}).get("channel")
            or getattr(self, "_rotation_candidate_channel", None)
            or "—",
            extra=LOG_ERROR if getattr(self, "_risk_state_load_failed", False) else LOG_INFO,
        )

    @report_snapshot
    def _log_score_tables(self, now: float, valid: dict[str, dict[str, float]]) -> None:
        """保存本批评分, 等本轮选币决策完成后再输出。"""
        selected = set(getattr(self, "_score_selection", getattr(self, "_score_leaders", ())))
        ranked = self._ranked_pairs()
        self._score_report_snapshot = {
            "now": now,
            "valid": {pair: dict(item) for pair, item in valid.items()},
            "scores": dict(self._scores),
            "ranks": {pair: str(rank) for rank, (pair, _) in enumerate(ranked, 1)},
            "selected": tuple(selected),
        }
        self._score_report_dirty = True

    def _consume_score_report(
        self, *, force: bool = False, report_now: float | None = None
    ) -> bool:
        snapshot = getattr(self, "_score_report_snapshot", None)
        if snapshot is None or (not force and not getattr(self, "_score_report_dirty", False)):
            return False
        self._render_score_report(snapshot, report_now=report_now)
        self._score_report_dirty = False
        return True

    def _render_score_report(
        self, snapshot: dict[str, Any], *, report_now: float | None = None
    ) -> None:
        now = snapshot["now"]
        report_now = now if report_now is None else report_now
        valid = snapshot["valid"]
        scores = snapshot["scores"]
        ranks = snapshot["ranks"]
        selected = set(snapshot["selected"])
        selected_count = len(selected.intersection(valid))
        rows = []
        detail_rows = []
        show_details = self.settings["raw_metrics_log_enabled"]
        for pair in sorted(
            valid, key=lambda pair: (int(ranks.get(pair, len(ranks) + 1)), -scores[pair])
        ):
            item = valid[pair]
            contributions = [
                f"{100 * self.settings['weights'][name] * item[f'score_{name}']:.1f}"
                for name in ("momentum", "volume", "taker_buy", "funding")
            ]
            heat_enabled = bool(
                self.settings["entry_heat_max_penalty"] or self.settings["entry_setup_enabled"]
            )
            heat = self._entry_heat_metrics(pair) if heat_enabled else None
            if not heat_enabled:
                heat_text = "—/关闭"
                entry_score = self._current_score(pair, report_now)
            elif heat is None:
                heat_text = "行情不足/禁止"
                entry_score = math.nan
            else:
                if not self.settings["entry_setup_enabled"]:
                    setup_text = " 形关闭"
                else:
                    setup = self._entry_setup_metrics(pair)
                    setup_text = (
                        f" 形{setup['stage']}{float(setup['score']):.0f}"
                        if setup is not None
                        else " 形未知"
                    )
                heat_text = (
                    f"涨{100 * heat['return_15d']:+.1f}% "
                    f"偏{heat['extension_atr']:.1f}ATR "
                    f"折{100 * heat['penalty']:.1f}%"
                    + (" 整理突" if heat["cooled_breakout"] else "")
                    + setup_text
                )
                entry_score = self._current_score(pair, report_now) * (
                    1 - heat["penalty"] if self.settings["entry_heat_max_penalty"] else 1
                )

            trend = self._trend_labels(pair)
            rows.append(
                [
                    ranks.get(pair, "—"),
                    pair,
                    f"{entry_score:.1f}" if math.isfinite(entry_score) else "—",
                    f"{scores[pair]:.1f}" if math.isfinite(scores[pair]) else "—",
                    "动{} 放{} 买{} 费{}".format(*contributions),
                    heat_text,
                    f"{trend[0]}/{trend[1]}",
                    (
                        f"榜外持仓 | {getattr(self, '_entry_decisions', {}).get(pair, '尚未评估')}"
                        if pair not in selected
                        else getattr(self, "_entry_decisions", {}).get(pair, "尚未评估")
                    ),
                ]
            )
            if show_details:
                raw_text = (
                    f"动{100 * item['momentum']:+.2f}% "
                    f"连{round(3 * item['trend_continuity'])}/3 "
                    f"量{item['volume_ratio']:.2f}/{item['volume_activity_ratio']:.2f} "
                    f"买{item['taker_ratio']:.2f}/{item['taker_ratio_latest']:.2f}"
                )
                funding_metric = getattr(self, "_metrics", {}).get(pair) or item
                funding_valid_until = funding_metric.get("_funding_valid_until", 0)
                if funding_valid_until > report_now:
                    funding_score = self._funding_score(funding_metric, report_now)
                    settlement = datetime.fromtimestamp(
                        funding_metric["funding_next_time"], DISPLAY_TZ
                    ).strftime("%m-%d %H:%M")
                    funding_text = (
                        f"本{100 * funding_metric['funding_rate']:+.5f}%/"
                        f"{funding_metric['funding_interval_hours']:.0f}h "
                        f"每h{100 * funding_metric['funding_rate_hourly']:+.5f}% "
                        f"8h{800 * funding_metric['funding_rate_hourly']:+.5f}% "
                        f"限{100 * funding_metric['funding_floor']:+.3f}~"
                        f"{100 * funding_metric['funding_cap']:+.3f}% "
                        f"位{100 * funding_score:+.0f}% "
                        f"调{100 * self.settings['weights']['funding'] * funding_score:+.2f} "
                        f"结{settlement}"
                    )
                else:
                    funding_text = "不可用/过期(费0)"
                detail_rows.append([ranks.get(pair, "—"), pair, raw_text, funding_text])
        _log_table(
            "📊 评分综合明细 (每个交易对一行)",
            [
                "排名",
                "交易对",
                "买入评分",
                "原评分",
                "加权分项(动/放/买/费)",
                "热度/形态(涨幅/偏离/折扣/阶段分)",
                "趋势(持仓/背景)",
                "筛选结果",
            ],
            rows,
            caption=(
                f"本批评分 {len(valid)} 个 = 本轮选币 {selected_count} 个"
                f" + 榜外持仓监控 {len(valid) - selected_count} 个; "
                f"选币池共 {len(selected)} 个; 已在选币池的持仓不重复计数; "
                "买入评分按当前有效资金费及热度折扣计算; 原评分/分项为本批快照; "
                "本批评分时间="
                f"{datetime.fromtimestamp(now, DISPLAY_TZ).strftime('%m-%d %H:%M:%S')}; "
                "本轮选币不代表买入"
            ),
        )
        if show_details:
            _log_table(
                "🔬 原始指标与资金费率",
                [
                    "排名",
                    "交易对",
                    "原始指标(动/量/买)",
                    "资金费率(本期/每h/8h/限/位/调/结)",
                ],
                detail_rows,
                caption=(
                    "原始指标依次显示动量、连续、短期/持续量比、"
                    "平滑/最新主动买比; 资金费率显示本期、每小时、等效8小时、"
                    "上下限、带方向的限位比例、评分调整和下次结算时间"
                ),
            )


class LeaderStorageMixin(LeaderMixinContext):
    def _load_risk_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self._state_path.read_text())
            if not isinstance(state, dict):
                raise ValueError("风控状态必须是JSON对象")
            if type(state.get("account_stopped")) is not bool:
                raise ValueError("account_stopped缺失或不是布尔值")
            if "eth_entry_blocked" in state and type(state["eth_entry_blocked"]) is not bool:
                raise ValueError("eth_entry_blocked不是布尔值")
            for key in ("peak_equity", "day_start_equity", "last_equity"):
                if key != "peak_equity" and key not in state:
                    continue
                value = state.get(key)
                if (
                    value is None
                    or type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise ValueError(f"{key}缺失或不是正有限数值")
            self._validate_rotation_state(state)
            return state
        except FileNotFoundError:
            # 首次运行没有状态文件是正常情况; 不将损坏/权限错误视为首次运行。
            return {}
        except (ValueError, OSError, OverflowError) as exc:
            self._risk_state_load_failed = True
            logger.error(
                "🚨 风控状态读取失败 | 文件=%s | %s: %s | 暂停新开仓和轮换, "
                "保留原文件; 已有仓位继续止损和退出。请修复状态文件或权限后重启, "
                "不要删除文件重置历史风控",
                self._state_path,
                type(exc).__name__,
                exc,
                extra=LOG_ERROR,
            )
            return {}

    @staticmethod
    def _validate_rotation_state(state: dict[str, Any]) -> None:
        last_rotation = state.get("last_rotation", 0.0)
        if (
            type(last_rotation) not in (int, float)
            or not math.isfinite(last_rotation)
            or last_rotation < 0
        ):
            raise ValueError("last_rotation无效")
        rotation = state.get("rotation")
        if rotation is None:
            return
        if not isinstance(rotation, dict):
            raise ValueError("rotation必须是对象")
        if not all(
            isinstance(rotation.get(key), str) and rotation[key]
            for key in ("weak", "target", "token")
        ):
            raise ValueError("rotation交易对或标识无效")
        if rotation["weak"] == rotation["target"] or rotation.get("phase") not in {
            "buy",
            "buy_pending",
            "sell",
            "review",
        }:
            raise ValueError("rotation阶段无效")
        amount = rotation.get("amount")
        if (
            amount is None
            or type(amount) not in (int, float)
            or not math.isfinite(amount)
            or amount < 0
            or (rotation["phase"] != "buy" and amount <= 0)
        ):
            raise ValueError("rotation数量无效")
        trade_id = rotation.get("weak_trade_id")
        if "weak_trade_id" not in rotation or (
            trade_id is not None and (type(trade_id) is not int or trade_id <= 0)
        ):
            raise ValueError("rotation旧仓记录无效")

    def _save_risk_state(self) -> bool:
        if getattr(self, "_risk_state_load_failed", False):
            return False
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(json_safe(self._risk_state), indent=2, allow_nan=False))
            temporary.replace(self._state_path)
            self._risk_state_save_failed = False
            return True
        except (OSError, TypeError, ValueError) as exc:
            logger.error("🚨 风控状态保存失败, 暂停新开仓: %s", exc, extra=LOG_ERROR)
            self._data_healthy = False
            self._risk_state_save_failed = True
            return False

    def _initialize_rotation_audit(self) -> None:
        self._rotation_journal = None
        self._audit_run_id = str(uuid4())
        self._audit_fingerprints = {}
        if not self.settings["rotation_audit_enabled"]:
            return
        mode = "dry_run" if self.config.get("dry_run", True) else "live"
        spool = Path(self.config["user_data_dir"]) / self.settings[f"rotation_audit_spool_{mode}"]
        self._rotation_journal = RotationJournal(
            Trade.session.get_bind(),
            spool,
            self.settings["rotation_audit_statement_timeout_ms"],
            self.settings["rotation_audit_retry_seconds"],
        )
        self._record_rotation_event("startup", "策略启动, 恢复轮换状态和未写入的历史事件")

    def _rotation_snapshot(self) -> dict:
        """Only cached/local market data and explicitly allowed config, never credentials."""
        pairs = {}
        for pair, stored_score in getattr(self, "_scores", {}).items():
            raw = self._current_score(pair)
            heat = (
                self._entry_heat_metrics(pair)
                if self.settings["entry_heat_max_penalty"] or self.settings["entry_setup_enabled"]
                else None
            )
            entry = (
                raw
                if not self.settings["entry_heat_max_penalty"]
                else (raw * (1 - heat["penalty"]) if heat is not None else None)
            )
            frame = self._closed_candles(pair, self.timeframe, 1)
            pairs[pair] = {
                "stored_score": stored_score,
                "raw_score": raw,
                "entry_score": entry,
                "heat": heat,
                "metrics": getattr(self, "_metrics", {}).get(pair),
                "score_current": self._pair_score_current(pair),
                "last_closed_candle": frame.iloc[-1].to_dict() if frame is not None else None,
                "fast_breakout": getattr(self, "_fast_rotation_details", {}).get(pair),
                "no_new_high": getattr(self, "_no_new_high_details", {}).get(pair),
                "multi_timeframe": self._multi_timeframe_snapshot(pair),
                "score_components": {
                    name: 100
                    * weight
                    * (
                        self._funding_score(
                            getattr(self, "_metrics", {}).get(pair, {}), time.time()
                        )
                        if name == "funding"
                        else getattr(self, "_metrics", {})
                        .get(pair, {})
                        .get(f"score_{name}", math.nan)
                    )
                    for name, weight in self.settings["weights"].items()
                },
            }
        holdings = []
        for trade in Trade.get_open_trades():
            holdings.append(
                {
                    "trade_id": trade.id,
                    "pair": trade.pair,
                    "is_short": trade.is_short,
                    "open_date": trade.open_date_utc,
                    "open_rate": trade.open_rate,
                    "amount": trade.amount,
                    "leverage": trade.leverage,
                    "opening_score": self._opening_score_label(trade),
                }
            )
        return json_safe(
            {
                "configuration": {
                    "leader_squeeze": self.settings,
                    **{key: self.config[key] for key in FRAMEWORK_SETTINGS},
                },
                "score_refreshed_at": getattr(self, "_last_score_refresh", None),
                "rotation": getattr(self, "_rotation_state", None),
                "candidate": getattr(self, "_rotation_candidate", None),
                "confirmations": getattr(self, "_rotation_seen", 0),
                "signal_bar": getattr(self, "_rotation_candidate_bar", None),
                "pairs": pairs,
                "holdings": holdings,
                "positions": getattr(self, "_position_details", {}),
                "external_pairs": sorted(getattr(self, "_external_pairs", set())),
                "account": getattr(self, "_risk_state", {}),
                "gates": {
                    name: getattr(self, name, None)
                    for name in (
                        "_entry_block_reason",
                        "_eth_block_reason",
                        "_eth_trend",
                        "_market_down",
                        "_market_emergency",
                        "_market_data_healthy",
                        "_position_data_healthy",
                        "_data_healthy",
                        "_risk_state_load_failed",
                        "_risk_state_save_failed",
                        "_execution_block_reason",
                    )
                },
            }
        )

    def _record_rotation_event(
        self, event_type: str, reason: str, details: dict | None = None, *, once: bool = False
    ) -> None:
        journal = getattr(self, "_rotation_journal", None)
        if journal is None:
            return
        state = getattr(self, "_rotation_state", None) or {}
        candidate = getattr(self, "_rotation_candidate", None) or (None, None)
        weak, target = state.get("weak", candidate[0]), state.get("target", candidate[1])
        fingerprint = json.dumps(json_safe([state, candidate, reason, details]), sort_keys=True)
        fingerprints = getattr(self, "_audit_fingerprints", {})
        if once and fingerprints.get(event_type) == fingerprint:
            return
        now = time.time()
        try:
            snapshot = self._rotation_snapshot()
        except Exception as exc:
            # Event identity and lifecycle must survive a broken/missing market snapshot.
            snapshot = {
                "snapshot_error": type(exc).__name__,
                "rotation": json_safe(state),
                "configuration": {"leader_squeeze": json_safe(self.settings)},
            }
            logger.error("轮换现场快照不完整 (%s), 仍记录事件", type(exc).__name__)
        snapshot["decision"] = json_safe(details or {})
        pairs = snapshot.get("pairs", {})
        old = pairs.get(weak, {}).get("raw_score")
        new = pairs.get(target, {}).get("entry_score")
        event = {
            "event_id": str(uuid4()),
            "occurred_at": datetime.fromtimestamp(now, UTC).isoformat(),
            "run_id": self._audit_run_id,
            "bot_name": self.config.get("bot_name", type(self).__name__),
            "dry_run": bool(self.config.get("dry_run", True)),
            "event_type": event_type,
            "rotation_token": state.get("token"),
            "channel": state.get("channel", getattr(self, "_rotation_candidate_channel", None)),
            "weak_pair": weak,
            "target_pair": target,
            "weak_score": old,
            "target_raw_score": pairs.get(target, {}).get("raw_score"),
            "target_entry_score": new,
            "score_gap": new - old if new is not None and old is not None else None,
            "reason": reason,
            "snapshot": snapshot,
        }
        try:
            journal.record(event, now)
        except Exception as exc:
            logger.error("轮换审计记录异常 (%s), 不阻断交易风控", type(exc).__name__)
            return
        fingerprints[event_type] = fingerprint
        self._audit_fingerprints = fingerprints

    def _rotation_execution_details(self, target) -> dict:
        return {
            "target_trade_id": target.id if target else None,
            "orders": [
                {
                    key: getattr(order, key, None)
                    for key in (
                        "order_id",
                        "ft_order_side",
                        "status",
                        "ft_is_open",
                        "amount",
                        "filled",
                        "average",
                        "price",
                    )
                }
                for order in target.orders
            ]
            if target
            else [],
        }

    def _audit_entry_confirmation(
        self, pair: str, allowed: bool, reason: str, amount: float, rate: float
    ) -> None:
        if pair == getattr(self, "_rotation_target", None) and not allowed:
            self._record_rotation_event(
                "entry_rejected", reason, {"amount": amount, "rate": rate}, once=True
            )


class LeaderTrendMixin(LeaderMixinContext):
    def _trend_history_count(self) -> int:
        """返回一次趋势判定所需的最少完整 K 线数量。"""
        return max(
            int(self.settings["trend_ema_candles"]) + int(self.settings["trend_slope_candles"]),
            int(self.settings["atr_period"]) + 2,
        )

    def _trend_state_frame(self, frame: DataFrame) -> DataFrame:
        """集中计算逐根趋势状态, 供实时判定和历史回放共用。"""
        slope = int(self.settings["trend_slope_candles"])
        close, high, low = frame["close"], frame["high"], frame["low"]
        ema = close.ewm(span=int(self.settings["trend_ema_candles"]), adjust=False).mean()
        below = close < ema
        falling = ema < ema.shift(slope)
        lower_structure = (high < high.shift(1)) & (low < low.shift(1)) & (close < close.shift(1))
        weakening = below & (falling | lower_structure)
        rising = (close > ema) & ~falling
        state = pd.Series("consolidating", index=frame.index)
        state[rising] = "up"
        state[weakening] = "weakening"
        return DataFrame(
            {
                "state": state,
                "ema": ema,
                "below": below,
                "falling": falling,
                "lower_structure": lower_structure,
            },
            index=frame.index,
        )

    def _trend_candles(
        self,
        pair: str,
        timeframe: str,
        count: int,
        *,
        columns=("high", "low", "close"),
        now: float | None = None,
    ) -> DataFrame | None:
        """Aggregate complete UTC buckets only; neither partial ends nor missing bars qualify."""
        base_seconds = timeframe_to_seconds(self.timeframe)
        seconds = timeframe_to_seconds(timeframe)
        if timeframe == self.timeframe:
            return self._closed_candles(pair, timeframe, count, columns=columns, now=now)
        ratio = seconds // base_seconds
        base = self._closed_candles(pair, self.timeframe, count * ratio, columns=columns, now=now)
        if base is None:
            return None
        dates = pd.to_datetime(base["date"], utc=True)
        if (dates.dt.floor(f"{base_seconds}s") != dates).any():
            self._warn_data_unavailable(f"{pair} {timeframe}", "源K线未对齐UTC周期")
            return None
        rules = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        source = base.set_index(dates)
        grouped = source.resample(f"{seconds}s", origin="epoch", label="left", closed="left")
        frame = grouped.agg({key: value for key, value in rules.items() if key in base})
        frame = frame.loc[grouped.size().eq(ratio)].rename_axis("date").reset_index()
        # _closed_candles has already rejected stale, gapped and unclosed source candles.
        if len(frame) < count:
            self._warn_data_unavailable(f"{pair} {timeframe}", "完整聚合K线数量不足")
            return None
        if {"high", "low", "close"}.issubset(frame) and (
            (base["high"] < base["close"]) | (base["low"] > base["close"])
        ).any():
            self._warn_data_unavailable(f"{pair} {timeframe}", "源K线高低收关系无效")
            return None
        return frame

    @report_cached
    def _trend_context(self, pair: str, timeframe: str) -> dict:
        slope = int(self.settings["trend_slope_candles"])
        frame = self._trend_candles(pair, timeframe, self._trend_history_count())
        if frame is None:
            return {"timeframe": timeframe, "available": False, "state": "unknown"}
        trend = self._trend_state_frame(frame)
        close = frame["close"]
        atr = self._wilder_atr(frame.iloc[:-1])
        if not math.isfinite(atr) or atr <= 0:
            return {"timeframe": timeframe, "available": False, "state": "unknown"}
        latest = trend.iloc[-1]
        return {
            "timeframe": timeframe,
            "available": True,
            "state": str(latest["state"]),
            "last_closed_candle": frame.iloc[-1].to_dict(),
            "ema": float(latest["ema"]),
            "reference_ema": float(trend["ema"].iloc[-slope - 1]),
            "atr": atr,
            "below_ema": bool(latest["below"]),
            "ema_falling": bool(latest["falling"]),
            "lower_high_low": bool(latest["lower_structure"]),
            "pullback_atr": float((close.iloc[-slope - 1 : -1].max() - close.iloc[-1]) / atr),
        }

    def _multi_timeframe_snapshot(self, pair: str) -> dict:
        return {
            "holding": self._trend_context(pair, self.settings["holding_timeframe"]),
            "background": self._trend_context(pair, self.settings["background_timeframe"]),
            "entry": getattr(self, "_higher_entry_details", {}).get(pair),
            "rotation": getattr(self, "_holding_rotation_details", {}).get(pair),
            "emergency": getattr(self, "_emergency_exit_details", {}).get(pair),
            "exit_reason": getattr(self, "_trend_exit_details", {}).get(pair),
        }

    def _higher_entry_reason(self, pair: str) -> str:
        """A strong 15m launch can bypass early hourly weakness, never a confirmed exit."""
        context = self._trend_context(pair, self.settings["holding_timeframe"])
        exception = False
        if not context["available"]:
            reason = "小时趋势数据不足或无效, 禁止开仓"
        elif context["state"] == "weakening":
            exception = bool(
                self.settings["replacement_fast_enabled"]
                and self._entry_score(pair) >= self._rotation_floor("fast")
                and self._fast_rotation_quality(pair)
            )
            reason = "" if exception else "小时趋势走弱且未满足快速启动条件"
        else:
            reason = ""
        details = getattr(self, "_higher_entry_details", {})
        details[pair] = {
            **context,
            "fast_exception": exception,
            "passed": not reason,
            "reason": reason,
        }
        self._higher_entry_details = details
        return reason

    def _rotation_holding_weak(self, pair: str) -> bool:
        context = self._trend_context(pair, self.settings["holding_timeframe"])
        stalled = self._no_new_high(pair) if context["available"] else False
        passed = bool(
            context["available"]
            and stalled
            and context["state"] == "weakening"
            and context["pullback_atr"] >= self.settings["replacement_weak_atr_drop"]
        )
        details = getattr(self, "_holding_rotation_details", {})
        details[pair] = {
            **context,
            "no_new_high": stalled,
            "passed": passed,
            "required_pullback_atr": self.settings["replacement_weak_atr_drop"],
        }
        self._holding_rotation_details = details
        self._audit_rotation_check(weak=pair, stage="holding_trend", **details[pair])
        return passed

    def _trend_exit_rule(self, pair: str) -> str:
        """Compact rule name for selection tables and exit log deduplication."""
        details = getattr(self, "_trend_exit_details", {}).get(pair, "趋势反转")
        return details.split(" | ", 1)[0]

    def _trend_reversed(self, pair: str) -> bool | None:
        """Hourly normal exits plus independent 15m breaks of pre-existing hourly support."""
        latest = self._closed_candles(pair, self.timeframe, 1, columns=("high", "low", "close"))
        latest_hour = self._trend_candles(
            pair,
            self.settings["holding_timeframe"],
            1,
            columns=("high", "low", "close"),
        )
        if latest is None or latest_hour is None:
            return None
        candle_key = (
            *latest.iloc[-1][["date", "high", "low", "close"]],
            *latest_hour.iloc[-1][["date", "high", "low", "close"]],
        )
        cache = getattr(self, "_trend_reversal_cache", {})
        cached = cache.get(pair)
        if cached is not None and cached[0] == candle_key:
            _, result, exit_detail, emergency_detail = cached
            details = getattr(self, "_trend_exit_details", {})
            if exit_detail is None:
                details.pop(pair, None)
            else:
                details[pair] = exit_detail
            self._trend_exit_details = details
            emergency = getattr(self, "_emergency_exit_details", {})
            if emergency_detail is None:
                emergency.pop(pair, None)
            else:
                emergency[pair] = emergency_detail
            self._emergency_exit_details = emergency
            return result
        normal = self._timeframe_reversed(pair, self.settings["holding_timeframe"])
        emergency = self._intrabar_reversed(pair)
        result = True if emergency is True or normal is True else None
        if result is None and normal is not None and emergency is not None:
            result = False
        if result is not None:
            cache[pair] = (
                candle_key,
                result,
                getattr(self, "_trend_exit_details", {}).get(pair),
                getattr(self, "_emergency_exit_details", {}).get(pair),
            )
            self._trend_reversal_cache = cache
        return result

    def _intrabar_reversed(self, pair: str) -> bool | None:
        timeframe = self.settings["holding_timeframe"]
        count = max(self.settings["reversal_lookback_candles"], self.settings["atr_period"] + 1)
        hours = self._trend_candles(pair, timeframe, count + 1)
        candles = self._closed_candles(pair, self.timeframe, 1, columns=("high", "low", "close"))
        details = getattr(self, "_emergency_exit_details", {})
        details[pair] = {"available": False, "passed": False}
        self._emergency_exit_details = details
        if hours is None or candles is None:
            return None
        if ((candles["high"] < candles["close"]) | (candles["low"] > candles["close"])).any():
            return None
        close = float(candles["close"].iloc[-1])
        hour_end = hours["date"] + pd.Timedelta(seconds=timeframe_to_seconds(timeframe))
        recent = candles.tail(self.settings["reversal_emergency_memory_candles"])
        available = False
        for index in range(len(recent) - 1, -1, -1):
            signal = recent.iloc[index]
            # Never use the hour containing this 15m signal to set its own support or ATR.
            reference = hours.loc[hour_end <= signal["date"]]
            if len(reference) < count:
                continue
            support, atr, _ = self._reversal_levels(
                reference, self.settings["reversal_lookback_candles"]
            )
            if not math.isfinite(atr) or atr <= 0:
                continue
            available = True
            threshold = support - self.settings["reversal_intrabar_atr_buffer"] * atr
            broken = float(signal["close"]) < threshold
            carried = close < support - self.settings["reversal_atr_buffer"] * atr and bool(
                (recent["close"].iloc[index:] < support).all()
            )
            if index == len(recent) - 1:
                details[pair] = {
                    "available": True,
                    "passed": False,
                    "support": support,
                    "atr": atr,
                    "threshold": threshold,
                    "close": close,
                    "signal_time": signal["date"],
                    "reference_time": reference["date"].iloc[-1],
                }
            if broken and (index == len(recent) - 1 or carried):
                details[pair] = {
                    "available": True,
                    "passed": True,
                    "support": support,
                    "atr": atr,
                    "threshold": threshold,
                    "close": close,
                    "signal_time": signal["date"],
                    "reference_time": reference["date"].iloc[-1],
                    "carried": index != len(recent) - 1,
                }
                exit_details = getattr(self, "_trend_exit_details", {})
                exit_details[pair] = (
                    f"{self.timeframe}急跌破位/{timeframe}支撑 | 支撑={support:.8g} "
                    f"ATR={atr:.8g} 急跌阈值={threshold:.8g} 收盘={close:.8g}"
                )
                self._trend_exit_details = exit_details
                return True
        return False if available else None

    def _timeframe_reversed(self, pair: str, timeframe: str) -> bool | None:
        """Return None when a complete trend assessment is unavailable."""
        details = getattr(self, "_trend_exit_details", {})
        details.pop(pair, None)
        self._trend_exit_details = details
        lookback = int(self.settings["reversal_lookback_candles"])
        confirmations = int(self.settings["reversal_confirm_candles"])
        dataframe = self._trend_candles(
            pair,
            timeframe,
            max(lookback, self.settings["atr_period"] + 1) + confirmations,
            columns=("high", "low", "close"),
        )
        if dataframe is None:
            return None
        if (
            (dataframe["low"] > dataframe["close"])
            | (dataframe["high"] < dataframe["close"])
            | (dataframe["low"] > dataframe["high"])
        ).any():
            self._warn_data_unavailable(f"{pair} 反转指标", "K线高低收关系无效")
            return None
        # Exclude signal candles from both support and volatility estimates.
        reference = dataframe.iloc[:-confirmations]
        support, atr, pivot = self._reversal_levels(reference, lookback)
        if not math.isfinite(atr) or atr <= 0:
            self._warn_data_unavailable(
                f"{pair} 反转指标", f"ATR{self.settings['atr_period']}缺少有效波动"
            )
            return None
        threshold = support - float(self.settings["reversal_atr_buffer"]) * atr
        fast_threshold = support - float(self.settings["reversal_fast_atr_buffer"]) * atr
        closes = dataframe["close"].iloc[-confirmations:]
        fast_break = bool(closes.iloc[-1] < fast_threshold)
        structure_break = bool((closes < threshold).all())
        slow_count = int(self.settings["reversal_slow_candles"])
        close = dataframe["close"]
        ema20 = close.ewm(span=self.settings["trend_ema_candles"], adjust=False).mean()
        below_ema = close < ema20
        run_start = len(close)
        while run_start > 0 and below_ema.iloc[run_start - 1]:
            run_start -= 1
        slow_drop = float(close.iloc[max(0, run_start - 1)] - close.iloc[-1])
        slow_ready = len(close) >= self.settings["trend_ema_candles"] + slow_count
        slow_reversal = bool(
            slow_ready
            and below_ema.iloc[-slow_count:].all()
            and ema20.iloc[-1] < ema20.iloc[-slow_count - 1]
            and close.iloc[-1] <= close.iloc[-slow_count - 1]
            and slow_drop >= float(self.settings["reversal_slow_atr_drop"]) * atr
        )
        # Reconstruct unrecovered breaks from all available candle history. Do not
        # assume slow confirmation takes over: selloff volatility can raise its ATR.
        carried_break = False
        for offset in range(
            1, len(dataframe) - max(lookback, self.settings["atr_period"] + 1) - confirmations + 1
        ):
            if fast_break or structure_break or slow_reversal:
                break
            old_reference = dataframe.iloc[: -confirmations - offset]
            if close.iloc[-1] >= old_reference["low"].tail(lookback).max():
                continue
            old_support, old_atr, old_pivot = self._reversal_levels(old_reference, lookback)
            if not math.isfinite(old_atr) or old_atr <= 0:
                continue
            old_threshold = old_support - float(self.settings["reversal_atr_buffer"]) * old_atr
            old_fast = old_support - float(self.settings["reversal_fast_atr_buffer"]) * old_atr
            old_closes = close.iloc[-confirmations - offset : -offset]
            broken = old_closes.iloc[-1] < old_fast or (old_closes < old_threshold).all()
            if (
                broken
                and (close.iloc[-offset:] < old_support).all()
                and close.iloc[-1] < old_threshold
            ):
                carried_break = True
                pivot = old_pivot
                support, atr, threshold, fast_threshold = (
                    old_support,
                    old_atr,
                    old_threshold,
                    old_fast,
                )
                break
        reversed_trend = fast_break or structure_break or slow_reversal or carried_break
        if reversed_trend:
            branch = (
                "急跌破位"
                if fast_break
                else "结构破位"
                if structure_break
                else "持续走弱"
                if slow_reversal
                else "破位未收复"
            )
            details[pair] = (
                f"{timeframe}{branch} | "
                f"{'波段支撑' if pivot else '区间支撑'}={support:.8g} "
                f"ATR{self.settings['atr_period']}={atr:.8g} 普通阈值={threshold:.8g} "
                f"急跌阈值={fast_threshold:.8g} | "
                f"最近{confirmations}根收盘="
                + ", ".join(f"{value:.8g}" for value in closes)
                + f" | 慢跌确认={slow_count}根 连续弱势累计下跌={slow_drop:.8g} "
                f"EMA{self.settings['trend_ema_candles']}={ema20.iloc[-1]:.8g}"
            )
            return True
        if not slow_ready:
            self._warn_data_unavailable(f"{pair} 反转指标", "慢跌确认历史不足")
            return None
        return False

    def _reversal_levels(self, reference: DataFrame, lookback: int) -> tuple[float, float, bool]:
        """Calculate causal support and Wilder ATR before a signal window."""
        lows = reference["low"].tail(lookback).reset_index(drop=True)
        side = self.settings["reversal_pivot_side_candles"]
        pivots = [
            index
            for index in range(side, len(lows) - side)
            if lows.iloc[index] < lows.iloc[index - side : index].min()
            and lows.iloc[index] < lows.iloc[index + 1 : index + side + 1].min()
        ]
        support = float(lows.iloc[pivots[-1]] if pivots else lows.min())
        return support, self._wilder_atr(reference), bool(pivots)

    def _wilder_atr(self, reference: DataFrame) -> float:
        """Compute ATR14 from closed history, excluding the candidate signal candle."""
        previous_close = reference["close"].shift(1)
        true_range = DataFrame(
            {
                "range": reference["high"] - reference["low"],
                "high_gap": (reference["high"] - previous_close).abs(),
                "low_gap": (reference["low"] - previous_close).abs(),
            }
        ).max(axis=1)
        # Seed Wilder ATR14 with the first 14 TRs having a previous close.
        period = self.settings["atr_period"]
        atr = float(true_range.iloc[1 : period + 1].mean())
        for value in true_range.iloc[period + 1 :]:
            atr = ((period - 1) * atr + float(value)) / period
        return atr

    def _no_new_high(self, pair: str) -> bool:
        count = self.settings["replacement_no_new_high_candles"]
        dataframe = self._trend_candles(
            pair, self.settings["holding_timeframe"], count, columns=("high",)
        )
        details = getattr(self, "_no_new_high_details", {})
        if dataframe is None or "high" not in dataframe:
            details[pair] = {"available": False}
            self._no_new_high_details = details
            return False
        high = float(dataframe["high"].iloc[-1])
        previous_high = float(dataframe["high"].iloc[-count:-1].max())
        details[pair] = {
            "available": True,
            "timeframe": self.settings["holding_timeframe"],
            "high": high,
            "reference_high": previous_high,
            "passed": high <= previous_high,
        }
        self._no_new_high_details = details
        return high <= previous_high


class LeaderProfitMixin(LeaderMixinContext):
    """盈利保护: 逐笔影子账本(只统计) + 可选保本棘轮/动量止损(受配置门控)。

    影子账本按已收盘 K 线做保守盘中模拟, 与真实止损完全独立, 因此**无论功能是否
    开启**都会给出"若启用本会在哪里退出"的反事实结果, 用于在无法回测的前提下评估
    盈利保护的实际价值。棘轮与动量止损分别经 ``custom_stoploss`` 与
    ``custom_exit`` 生效, 并各自保留配置闸门。

    单位约定(已用真实 ``Trade`` 实测): ``custom_stoploss`` 的返回值与 ``stoploss``
    同为保证金口径, 框架内部会除以杠杆换算成价格距离。因此本模块统一先用
    ``stoploss_from_absolute`` 把目标"止损价"转成返回值, 不手工折算, 避免 5x 下
    把 2% 写成 0.4% 这类错误。
    """

    # Closed-candle replay is throttled to once per holding-timeframe bucket.
    # ------------------------------------------------------------------ 入场上下文

    _PROFIT_RECORD_VERSION = 3

    def _capture_profit_entry_context(self, trade: Trade) -> None:
        """首次入场成交时冻结该笔的 ATR1h, 作为 R 单位与棘轮步长基准。"""
        if not self.settings["profit_shadow_enabled"]:
            return
        shadow = getattr(self, "_profit_shadow", None)
        if shadow is None:
            return
        record = shadow.get(trade.pair)
        same_trade = (
            record is not None
            and record.get("trade_id") == trade.id
            and self._valid_profit_record(trade.pair, record)
        )
        if same_trade and not self._profit_record_rebuildable(record):
            return
        if not same_trade and self._valid_profit_record(trade.pair, record):
            # 同一 pair 的上一笔先归档, 不丢反事实样本。
            self._queue_profit_archive(record)
        # 入场单挂出后 trade 即出现在 get_open_trades(), 早于本回调, 因此影子账本
        # 通常已按 reconstructed 建好同 trade_id 的记录。此刻才拿到真实成交时刻,
        # 用它重建入场上下文, 让无进展时钟从入场后第一根完整 K 线起算, 并把
        # context_source 修正为 entry_fill, 使该样本能进入反事实汇总。
        shadow[trade.pair] = self._new_profit_record(
            trade, self._profit_entry_atr(trade.pair), context_source="entry_fill"
        )
        self._profit_shadow = shadow

    @staticmethod
    def _profit_record_rebuildable(record: dict[str, Any]) -> bool:
        """记录尚未做出任何决策时才能安全重建, 否则会丢掉已武装的棘轮状态。"""
        return (
            record.get("context_source") == "reconstructed"
            and record.get("execution_lock_armed_at") is None
            and record.get("shadow_lock_armed_at") is None
            and record.get("shadow_exit_price") is None
        )

    def _profit_entry_atr(self, pair: str) -> float | None:
        try:
            context = self._trend_context(pair, self.settings["holding_timeframe"])
        except Exception:
            logger.exception("🚨 盈利保护: 入场 ATR 读取异常 %s", pair, extra=LOG_ERROR)
            return None
        atr = context.get("atr")
        if isinstance(atr, (int, float)) and math.isfinite(atr) and atr > 0:
            return float(atr)
        return None

    def _hydrate_profit_r(self, pair: str, record: dict[str, Any]) -> None:
        """Retry a missing entry volatility snapshot without changing a frozen R."""
        if record.get("r_price") is not None:
            return
        atr = self._profit_entry_atr(pair)
        r_price = self._profit_r_price(float(record["entry_price"]), atr)
        if r_price is None:
            return
        record["entry_atr"] = atr
        record["r_price"] = r_price

    def _profit_r_price(self, entry: float, atr: float | None) -> float | None:
        """R 以入场 ATR1h 计并夹在合理区间, 避免 ATR 退化时棘轮一开仓就触发。"""
        if atr is None or not math.isfinite(entry) or entry <= 0:
            return None
        candidate = float(self.settings["profit_r_atr_multiple"]) * float(atr)
        if not math.isfinite(candidate) or candidate <= 0:
            return None
        low = entry * float(self.settings["profit_r_min_pct"])
        high = entry * float(self.settings["profit_r_max_pct"])
        return float(min(max(candidate, low), high))

    def _new_profit_record(
        self, trade: Trade, atr: float | None, *, context_source: str = "reconstructed"
    ) -> dict[str, Any]:
        entry = float(trade.open_rate)
        leverage = float(trade.leverage or 1.0)
        stop_fraction = abs(float(getattr(self, "stoploss", -1.0) or -1.0)) / max(leverage, 1e-9)
        opened_at = trade.open_date_utc.timestamp() if trade.open_date_utc else time.time()
        period = timeframe_to_seconds(self.settings["holding_timeframe"])
        first_full_bar = math.ceil(opened_at / period) * period
        # trade.max_rate survives a restart, but it does not say *when* that peak
        # happened.  The ratchet may recover it immediately; the no-progress clock
        # must start after reconstruction or it could count bars that preceded the
        # peak and issue an immediate false exit.
        progress_tracking_from = first_full_bar
        if context_source == "reconstructed":
            progress_tracking_from = max(
                first_full_bar,
                math.ceil(time.time() / period) * period,
            )
        observed_peak = max(entry, float(getattr(trade, "max_rate", None) or entry))
        return {
            "version": self._PROFIT_RECORD_VERSION,
            "pair": trade.pair,
            "trade_id": trade.id,
            "context_source": context_source,
            "leverage": leverage,
            "entry_price": entry,
            "entry_atr": atr,
            "r_price": self._profit_r_price(entry, atr),
            "opened_at": opened_at,
            "tracking_from_ts": first_full_bar,
            "progress_tracking_from_ts": progress_tracking_from,
            "peak_price": observed_peak,
            "progress_high_price": observed_peak,
            "peak_profit_ratio": 0.0,
            "peak_profit_r": None,
            "last_profit_ratio": 0.0,
            "last_profit_r": None,
            "current_price": entry,
            "last_bar_ts": first_full_bar - 1e-6,
            "last_scan_bucket": None,
            "bars_seen": 0,
            "bars_since_new_high": 0,
            "max_bars_since_new_high": 0,
            "bars_since_weakening": None,
            "execution_lock_armed_at": None,
            "execution_lock_stop_price": None,
            "shadow_lock_armed_at": None,
            "shadow_lock_stop_price": None,
            "no_progress_setup": False,
            "no_progress": False,
            "shadow_stop_price": entry * (1.0 - stop_fraction),
            "shadow_exit_price": None,
            "shadow_exit_ratio": None,
            "shadow_exit_r": None,
            "shadow_exit_reason": None,
            "shadow_exit_at": None,
            "archive_retry_at": 0.0,
            "updated_at": time.time(),
        }

    def _migrate_profit_record(self, record: Any) -> dict[str, Any] | None:
        """Upgrade persisted records whose momentum clock cannot be reused safely."""
        if not isinstance(record, dict):
            return None
        if record.get("version") == 2:
            # Version 3 separates the true price peak from the meaningful-progress
            # anchor. Preserve the live peak/ratchets, but restart the progress clock
            # because the old one-tick reset semantics cannot be converted reliably.
            entry, peak = record.get("entry_price"), record.get("peak_price")
            if type(entry) not in (int, float) or type(peak) not in (int, float):
                return None
            record["version"] = self._PROFIT_RECORD_VERSION
            record["progress_high_price"] = max(
                float(cast(int | float, entry)), float(cast(int | float, peak))
            )
            # A mid-trade policy upgrade cannot reproduce the old intrabar path.
            # Keep protecting the live trade, but exclude this mixed-policy sample
            # from aggregate shadow statistics.
            record["context_source"] = "reconstructed"
            record["bars_since_new_high"] = 0
            record["no_progress_setup"] = False
            record["no_progress"] = False
        if (
            record.get("version") == self._PROFIT_RECORD_VERSION
            and "progress_tracking_from_ts" not in record
        ):
            tracking_from = record.get("tracking_from_ts")
            if type(tracking_from) not in (int, float) or not math.isfinite(
                float(cast(int | float, tracking_from))
            ):
                return None
            period = timeframe_to_seconds(self.settings["holding_timeframe"])
            if record.get("context_source") == "reconstructed":
                record["progress_tracking_from_ts"] = max(
                    float(cast(int | float, tracking_from)),
                    math.ceil(time.time() / period) * period,
                )
                record["bars_since_new_high"] = 0
                record["no_progress_setup"] = False
                record["no_progress"] = False
            else:
                record["progress_tracking_from_ts"] = float(cast(int | float, tracking_from))
        if (
            record.get("version") == self._PROFIT_RECORD_VERSION
            and "bars_since_weakening" not in record
        ):
            # 旧记录没有保存最近一次走弱距今多久; 从“未观测到”开始, 避免在真正
            # 出现走弱 K 线前凭空获得退出豁免。
            record["bars_since_weakening"] = None
        if (
            record.get("version") == self._PROFIT_RECORD_VERSION
            and "max_bars_since_new_high" not in record
        ):
            # 记录该交易曾经离动量闸门多近; 否则归档只有最终快照, 无法判断赢家
            # 是否曾在持仓中途停滞 8 根以上。
            bars_since_new_high = record.get("bars_since_new_high", 0)
            if type(bars_since_new_high) is not int or bars_since_new_high < 0:
                return None
            record["max_bars_since_new_high"] = bars_since_new_high
        return record

    @staticmethod
    def _valid_profit_optional_numbers(record: dict[str, Any]) -> bool:
        optional_numbers = (
            "entry_atr",
            "r_price",
            "last_scan_bucket",
            "execution_lock_armed_at",
            "execution_lock_stop_price",
            "shadow_lock_armed_at",
            "shadow_lock_stop_price",
            "shadow_stop_price",
            "shadow_exit_price",
            "shadow_exit_ratio",
            "shadow_exit_r",
            "shadow_exit_at",
            "archive_retry_at",
        )
        if any(
            value is not None and (type(value) not in (int, float) or not math.isfinite(value))
            for key in optional_numbers
            if (value := record.get(key)) is not None
        ):
            return False
        positive_numbers = (
            "entry_atr",
            "r_price",
            "execution_lock_stop_price",
            "shadow_lock_stop_price",
            "shadow_stop_price",
            "shadow_exit_price",
        )
        return all(record.get(key) is None or float(record[key]) > 0 for key in positive_numbers)

    def _valid_profit_record(self, pair: str, record: Any) -> bool:
        """Reject partial or old records before they can interrupt the trading loop."""
        record = self._migrate_profit_record(record)
        if not isinstance(record, dict) or record.get("version") != self._PROFIT_RECORD_VERSION:
            return False
        required = {
            "context_source",
            "entry_atr",
            "r_price",
            "last_scan_bucket",
            "execution_lock_armed_at",
            "execution_lock_stop_price",
            "shadow_lock_armed_at",
            "shadow_lock_stop_price",
            "progress_high_price",
            "progress_tracking_from_ts",
            "bars_since_weakening",
            "max_bars_since_new_high",
            "no_progress_setup",
            "no_progress",
            "shadow_stop_price",
            "shadow_exit_price",
            "shadow_exit_ratio",
            "shadow_exit_r",
            "shadow_exit_reason",
            "shadow_exit_at",
            "archive_retry_at",
        }
        if not required.issubset(record):
            return False
        if (
            record.get("pair") != pair
            or type(record.get("trade_id")) is not int
            or record["trade_id"] <= 0
            or record.get("context_source") not in {"entry_fill", "reconstructed"}
            or type(record.get("no_progress_setup")) is not bool
            or type(record.get("no_progress")) is not bool
        ):
            return False
        required_numbers = {
            "leverage": True,
            "entry_price": True,
            "opened_at": False,
            "tracking_from_ts": False,
            "progress_tracking_from_ts": False,
            "last_bar_ts": False,
            "peak_price": True,
            "progress_high_price": True,
            "current_price": True,
        }
        for key, positive in required_numbers.items():
            value = record.get(key)
            if type(value) not in (int, float):
                return False
            numeric = float(cast(int | float, value))
            if not math.isfinite(numeric) or (positive and numeric <= 0):
                return False
        if float(record["progress_high_price"]) > float(record["peak_price"]):
            return False
        if float(record["progress_tracking_from_ts"]) < float(record["tracking_from_ts"]):
            return False
        counters = ("bars_seen", "bars_since_new_high", "max_bars_since_new_high")
        if not all(type(record.get(key)) is int and record[key] >= 0 for key in counters):
            return False
        bars_since_weakening = record.get("bars_since_weakening")
        if bars_since_weakening is not None and (
            type(bars_since_weakening) is not int or bars_since_weakening < 0
        ):
            return False
        if record["max_bars_since_new_high"] < record["bars_since_new_high"]:
            return False
        return self._valid_profit_optional_numbers(record)

    @staticmethod
    def _profit_r_of(record: dict[str, Any], price: float) -> float | None:
        r_price = record.get("r_price")
        entry = record.get("entry_price")
        if type(r_price) not in (int, float) or type(entry) not in (int, float):
            return None
        r_value = float(cast(int | float, r_price))
        entry_value = float(cast(int | float, entry))
        if (
            not math.isfinite(r_value)
            or not math.isfinite(entry_value)
            or not math.isfinite(float(price))
            or r_value <= 0
            or entry_value <= 0
        ):
            return None
        return (float(price) - entry_value) / r_value

    def _profit_lock_target(self, record: dict[str, Any], peak: float) -> float | None:
        """持久峰值武装后, 返回只升不降的锁盈目标。

        回吐额度取两个上限中更紧的一个:
        * 波动口径 ``trail_r * R``: 让大行情按波动缩放地跟随, 不截断右尾;
        * 涨幅口径 ``giveback_frac * (峰值 - 入场)``: 让中等行情不必把浮盈全部吐回。

        峰值超过 ``trail_r / giveback_frac`` 倍 R 之后只剩波动口径生效, 因此右尾
        (策略赖以盈利的少数大赢家) 的行为与纯 R 跟踪完全一致。
        """
        peak_r = self._profit_r_of(record, peak)
        if peak_r is None or peak_r < float(self.settings["profit_lock_arm_r"]):
            return None
        entry = float(record["entry_price"])
        target = entry * (1.0 + float(self.settings["profit_lock_fee_buffer"]))
        allowance = math.inf
        trail_r = float(self.settings["profit_lock_trail_r"])
        if trail_r > 0:
            allowance = trail_r * float(record["r_price"])
        giveback_frac = float(self.settings["profit_lock_giveback_frac"])
        if giveback_frac > 0:
            allowance = min(allowance, giveback_frac * max(peak - entry, 0.0))
        if math.isfinite(allowance):
            target = max(target, peak - allowance)
        return target

    # ------------------------------------------------------------------ 影子账本

    def _queue_profit_archive(self, record: dict[str, Any]) -> None:
        pending = getattr(self, "_profit_pending_archives", {})
        record.setdefault("archive_retry_at", 0.0)
        pending[str(record["trade_id"])] = record
        self._profit_pending_archives = pending

    def _flush_profit_archives(self, pending: dict[str, dict[str, Any]], now: float) -> None:
        for trade_id, record in list(pending.items()):
            if now < float(record.get("archive_retry_at") or 0.0):
                continue
            record["archive_retry_at"] = now + float(self.settings["position_sync_seconds"])
            evidence = self._closed_profit_evidence(record)
            if evidence is not None and self._finalize_profit_record(record, evidence, now):
                pending.pop(trade_id, None)

    def _update_profit_shadow(self, now: float, current_time: datetime) -> None:
        """每轮刷新未平仓记录; 平仓时归档到 JSONL 并累计汇总。"""
        if not self.settings["profit_shadow_enabled"]:
            return
        shadow = getattr(self, "_profit_shadow", None)
        if shadow is None:
            return
        try:
            open_trades = {trade.pair: trade for trade in Trade.get_open_trades()}
        except Exception:
            logger.exception("🚨 盈利影子账本读取持仓失败", extra=LOG_ERROR)
            return
        for pair, trade in open_trades.items():
            record = shadow.get(pair)
            if self._valid_profit_record(pair, record) and record.get("trade_id") != trade.id:
                self._queue_profit_archive(record)
            if not self._valid_profit_record(pair, record) or record.get("trade_id") != trade.id:
                record = self._new_profit_record(
                    trade, self._profit_entry_atr(pair), context_source="reconstructed"
                )
                shadow[pair] = record
            try:
                self._hydrate_profit_r(pair, record)
                self._advance_profit_record(record, trade, now)
            except Exception:
                logger.exception(
                    "🚨 盈利影子账本更新失败 %s | 本轮保留记录并继续其他仓位",
                    pair,
                    extra=LOG_ERROR,
                )
        for pair in [name for name in shadow if name not in open_trades]:
            self._queue_profit_archive(shadow.pop(pair))
        pending = getattr(self, "_profit_pending_archives", {})
        self._flush_profit_archives(pending, now)
        self._profit_pending_archives = pending
        self._profit_shadow = shadow
        risk_state = getattr(self, "_risk_state", None)
        if isinstance(risk_state, dict):
            risk_state["profit_shadow"] = shadow
            risk_state["profit_pending_archives"] = pending
        self._log_profit_shadow_summary(now, current_time)

    def _advance_profit_record(self, record: dict[str, Any], trade: Trade, now: float) -> None:
        period = timeframe_to_seconds(self.settings["holding_timeframe"])
        delay = float(self.settings["score_candle_close_delay_seconds"])
        scan_bucket = math.floor((now - delay) / period)
        if record.get("last_scan_bucket") == scan_bucket:
            return
        frame = self._profit_trend_frame(record["pair"])
        record["updated_at"] = now
        if frame is None or frame.empty:
            return
        record["last_scan_bucket"] = scan_bucket
        last_ts = float(record.get("last_bar_ts") or 0.0)
        tracking_from = float(record["tracking_from_ts"])
        pending = frame.loc[
            frame["date"].map(
                lambda value: value.timestamp() >= tracking_from and value.timestamp() > last_ts
            )
        ]
        if pending.empty:
            return
        entry = float(record["entry_price"])
        atr = record.get("entry_atr")
        # 止损是价格水平, 必须逐根回放才能还原真实的盘中触发顺序; 动量闸门同样需要
        # 每根 K 线"当时"的状态, 否则一次重放多根(重建记录/停机追赶)时只有最后一根
        # 参与判定, 交易就可能带着一个从未更新过的旧结论一路跌到灾难止损。
        states = self._profit_trend_states(
            frame, start_ts=float(pending["date"].iloc[0].timestamp())
        )
        rows = list(pending.itertuples(index=False))
        for row in rows:
            record["last_bar_ts"] = row.date.timestamp()
            record["bars_seen"] = int(record.get("bars_seen", 0)) + 1
            high, low, close = float(row.high), float(row.low), float(row.close)
            self._simulate_profit_bar(
                record,
                trade,
                high,
                low,
                close,
                entry,
                atr,
                None if states is None else states.get(row.date.timestamp()),
            )
        record["peak_profit_ratio"] = self._profit_ratio_at(trade, float(record["peak_price"]))
        record["last_profit_ratio"] = self._profit_ratio_at(
            trade, float(record.get("current_price") or entry)
        )
        record["peak_profit_r"] = self._profit_r_of(record, float(record["peak_price"]))
        record["last_profit_r"] = self._profit_r_of(
            record, float(record.get("current_price") or entry)
        )

    @staticmethod
    def _profit_ratio_at(trade: Trade, price: float) -> float | None:
        """Return a finite profit ratio, or None so invalid samples stay out of totals."""
        try:
            ratio = float(trade.calc_profit_ratio(price))
        except Exception:
            return None
        return ratio if math.isfinite(ratio) else None

    def _simulate_profit_bar(
        self,
        record: dict[str, Any],
        trade: Trade,
        high: float,
        low: float,
        close: float,
        entry: float,
        _atr: float | None,
        trend_state: str | None,
    ) -> None:
        """保守盘中模拟: 先用本根开盘前的止损判断是否被打到, 再用本根高点抬升止损。"""
        already_exited = record.get("shadow_exit_price") is not None
        stop_before = record.get("shadow_stop_price")
        if not already_exited and stop_before is not None and low <= float(stop_before):
            reason = "ratchet" if record.get("shadow_lock_stop_price") is not None else "stoploss"
            self._record_shadow_exit(record, trade, float(stop_before), reason)
            already_exited = True
        previous_peak = float(record["peak_price"])
        peak = max(previous_peak, high)
        record["peak_price"] = peak
        if float(record["last_bar_ts"]) >= float(record["progress_tracking_from_ts"]):
            progress_high = float(record.get("progress_high_price") or entry)
            r_price = record.get("r_price")
            meaningful_advance = (
                float(self.settings["profit_no_progress_new_high_r"]) * float(r_price)
                if r_price
                else math.inf
            )
            if high >= progress_high + meaningful_advance:
                record["progress_high_price"] = high
                record["bars_since_new_high"] = 0
                # 创新高否定了"动量失效"的论点, 此前的走弱观测随之作废。
                record["bars_since_weakening"] = None
            else:
                record["bars_since_new_high"] = int(record.get("bars_since_new_high", 0)) + 1
            record["max_bars_since_new_high"] = max(
                int(record.get("max_bars_since_new_high", 0)),
                int(record["bars_since_new_high"]),
            )
            self._track_weakening_recency(record, trend_state)
        target = self._profit_lock_target(record, peak)
        if not already_exited and target is not None:
            current = record.get("shadow_lock_stop_price")
            record["shadow_lock_stop_price"] = (
                max(float(current), target) if current is not None else target
            )
            if record.get("shadow_lock_armed_at") is None:
                record["shadow_lock_armed_at"] = record["last_bar_ts"]
            record["shadow_stop_price"] = max(
                float(stop_before or 0.0), float(record["shadow_lock_stop_price"])
            )
        record["current_price"] = close
        record["last_profit_r"] = self._profit_r_of(record, close)
        record["no_progress_setup"] = self._profit_no_progress_setup(record)
        record["no_progress"] = self._profit_no_progress_at_price(record, close)
        if record["no_progress"] and not already_exited:
            self._record_shadow_exit(record, trade, close, "no_progress")

    def _record_shadow_exit(
        self, record: dict[str, Any], trade: Trade, price: float, reason: str
    ) -> None:
        record["shadow_exit_price"] = float(price)
        record["shadow_exit_ratio"] = self._profit_ratio_at(trade, float(price))
        record["shadow_exit_r"] = self._profit_r_of(record, float(price))
        record["shadow_exit_reason"] = reason
        record["shadow_exit_at"] = record.get("last_bar_ts")

    def _profit_trend_frame(self, pair: str) -> DataFrame | None:
        """Read the closed holding-timeframe bars used by the shadow replay."""
        settings = self.settings
        return self._trend_candles(
            pair,
            settings["holding_timeframe"],
            self._trend_history_count(),
            columns=("high", "low", "close"),
        )

    def _profit_no_progress_trend(self, pair: str) -> str | None:
        """Return the latest closed holding-timeframe trend state."""
        context = self._trend_context(pair, self.settings["holding_timeframe"])
        if not context.get("available"):
            return None
        return str(context.get("state"))

    def _profit_trend_states(
        self, frame: DataFrame | None, *, start_ts: float = -math.inf
    ) -> dict[float, str] | None:
        """为每根已收盘的持仓周期 K 线重算当时的趋势状态。

        ``_trend_context`` 只描述最新一根; 重建记录或停机追赶时一次扫描会回放多根,
        因此动量闸门必须使用每根 K 线当时的状态。分类规则与实时趋势判定共用同一
        实现; 历史不足或 ATR 无效的早期 K 线不生成状态。
        """
        required = {"date", "high", "low", "close"}
        if frame is None or frame.empty or not required.issubset(frame.columns):
            return None
        history_count = self._trend_history_count()
        if len(frame) < history_count:
            return None
        trend = self._trend_state_frame(frame)
        states: dict[float, str] = {}
        for index in range(history_count - 1, len(frame)):
            date = frame["date"].iloc[index]
            timestamp = float(date.timestamp())
            if timestamp < start_ts:
                continue
            atr = self._wilder_atr(frame.iloc[:index])
            if math.isfinite(atr) and atr > 0:
                states[timestamp] = str(trend["state"].iloc[index])
        return states

    @staticmethod
    def _track_weakening_recency(record: dict[str, Any], trend_state: str | None) -> None:
        """把“最近一次趋势走弱距今多久”的时钟推进一根。

        ``None`` 表示最近一次有效新高后尚未观测到走弱。未知趋势仍会让已有观测
        变旧, 避免一次陈旧读数永久打开闸门。
        """
        if trend_state == "weakening":
            record["bars_since_weakening"] = 0
            return
        previous = record.get("bars_since_weakening")
        if previous is not None:
            record["bars_since_weakening"] = int(previous) + 1

    def _profit_no_progress_setup(self, record: dict[str, Any]) -> bool:
        """要求最近一次有效新高后经过 N 根完整 K 线。

        旧趋势条件只看最新一根快照, 只要该根碰巧不弱, 交易就可能扛过整段下跌。
        现在改为近期窗口: 在动量时钟使用的同一个 N 根窗口内曾走弱即可。
        """
        if record.get("r_price") is None:
            return False
        window = int(self.settings["profit_no_progress_candles"])
        if int(record.get("bars_since_new_high", 0)) < window:
            return False
        since_weakening = record.get("bars_since_weakening")
        if since_weakening is None:
            return False
        return int(since_weakening) <= window

    def _profit_no_progress_at_price(self, record: dict[str, Any], price: float) -> bool:
        if not record.get("no_progress_setup"):
            return False
        profit_r = self._profit_r_of(record, price)
        if profit_r is None:
            return False
        return float(profit_r) < float(self.settings["profit_no_progress_max_r"])

    # ------------------------------------------------------------------ 归档与汇总

    def _closed_profit_evidence(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Return final framework or verified exchange-ledger profit for a closed trade."""
        try:
            trade = Trade.get_trades([Trade.id == int(record["trade_id"])]).first()
            if trade is None or trade.is_open:
                return None
            ratio = trade.close_profit
            source = "framework"
            if self.config.get("exchange_accounting", {}).get("enabled") and not self.config.get(
                "dry_run", True
            ):
                checkpoint = Trade.session.scalars(
                    select(ExchangeLedger).where(
                        ExchangeLedger.trade_id == trade.id,
                        ExchangeLedger.record_type == "checkpoint",
                        ExchangeLedger.record_id == str(trade.id),
                    )
                ).first()
                state = checkpoint.data if checkpoint is not None else {}
                signature = [
                    trade.is_open,
                    trade.leverage,
                    [
                        [
                            order.order_id,
                            order.ft_order_side,
                            order.safe_filled,
                            order.safe_price,
                            order.ft_is_open,
                        ]
                        for order in trade.orders
                    ],
                ]
                if state.get("status") != "verified" or state.get("signature") != signature:
                    return None
                ratio = state.get("profit_ratio")
                source = "exchange_ledger"
            if type(ratio) not in (int, float):
                return None
            profit_ratio = float(cast(int | float, ratio))
            if not math.isfinite(profit_ratio):
                return None
            peak_profit_ratio = self._profit_ratio_at(trade, float(record["peak_price"]))
            if peak_profit_ratio is None:
                return None
            shadow_exit_ratio = None
            if record.get("shadow_exit_price") is not None:
                shadow_exit_ratio = self._profit_ratio_at(trade, float(record["shadow_exit_price"]))
                if shadow_exit_ratio is None:
                    return None
            closed_at = trade.close_date_utc.timestamp() if trade.close_date_utc else time.time()
            return {
                "actual_profit_ratio": profit_ratio,
                "actual_close_price": trade.close_rate,
                "actual_closed_at": closed_at,
                "actual_profit_source": source,
                "peak_profit_ratio": peak_profit_ratio,
                "peak_profit_r": self._profit_r_of(record, float(record["peak_price"])),
                "shadow_exit_ratio": shadow_exit_ratio,
            }
        except Exception:
            logger.exception(
                "🚨 盈利影子账本读取已平仓交易失败 %s",
                record.get("pair"),
                extra=LOG_ERROR,
            )
            return None

    def _finalize_profit_record(
        self, record: dict[str, Any], evidence: dict[str, Any], now: float
    ) -> bool:
        record.update(evidence)
        record["closed_at"] = float(evidence["actual_closed_at"])
        peak_ratio = float(record.get("peak_profit_ratio") or 0.0)
        final_ratio = float(evidence["actual_profit_ratio"])
        shadow_ratio = record.get("shadow_exit_ratio")
        record["giveback_ratio"] = peak_ratio - final_ratio
        record["duration_minutes"] = max(
            0.0, (record["closed_at"] - float(record.get("opened_at") or now)) / 60.0
        )
        record["archive_key"] = f"trade:{record['trade_id']}"
        record["would_lock"] = record.get("shadow_lock_stop_price") is not None
        record["shadow_improvement"] = (
            float(shadow_ratio) - final_ratio if shadow_ratio is not None else None
        )
        if not self._append_profit_shadow(record):
            return False
        self._accumulate_profit_totals(record)
        return True

    def _profit_shadow_path(self) -> Path:
        mode = "dry_run" if self.config.get("dry_run", True) else "live"
        return (
            Path(self.config.get("user_data_dir", "user_data"))
            / self.settings[f"profit_shadow_file_{mode}"]
        )

    def _append_profit_shadow(self, record: dict[str, Any]) -> bool:
        try:
            path = self._profit_shadow_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            archive_key = record.get("archive_key")
            if archive_key and path.exists():
                with path.open(encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            if json.loads(line).get("archive_key") == archive_key:
                                return True
                        except (json.JSONDecodeError, AttributeError):
                            continue
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(json_safe(record), ensure_ascii=False) + "\n")
            return True
        except OSError as exc:
            logger.error("🚨 盈利影子账本写入失败: %s", exc, extra=LOG_ERROR)
            return False

    def _accumulate_profit_totals(self, record: dict[str, Any]) -> None:
        totals = getattr(self, "_profit_totals", None)
        if totals is None:
            totals = {
                "closed": 0,
                "actual_sum": 0.0,
                "peak_sum": 0.0,
                "giveback_sum": 0.0,
                "shadow_sum": 0.0,
                "shadow_count": 0,
                "shadow_better": 0,
                "shadow_worse": 0,
                "ratchet_exits": 0,
                "no_progress_exits": 0,
                "stop_exits": 0,
                "locked": 0,
            }
        if record.get("context_source") != "entry_fill":
            logger.info(
                "📊 盈利保护样本已归档但不纳入汇总 %s | 入场上下文=%s",
                record.get("pair"),
                record.get("context_source"),
                extra=LOG_SCORE,
            )
            return
        totals["closed"] += 1
        totals["actual_sum"] += float(record.get("actual_profit_ratio") or 0.0)
        totals["peak_sum"] += float(record.get("peak_profit_ratio") or 0.0)
        totals["giveback_sum"] += float(record.get("giveback_ratio") or 0.0)
        reason = record.get("shadow_exit_reason")
        if reason == "ratchet":
            totals["ratchet_exits"] += 1
        elif reason == "no_progress":
            totals["no_progress_exits"] += 1
        elif reason == "stoploss":
            totals["stop_exits"] += 1
        if record.get("shadow_lock_stop_price") is not None:
            totals["locked"] += 1
        improvement = record.get("shadow_improvement")
        if improvement is not None:
            totals["shadow_count"] += 1
            totals["shadow_sum"] += float(record.get("shadow_exit_ratio") or 0.0)
            if float(improvement) > 0:
                totals["shadow_better"] += 1
            elif float(improvement) < 0:
                totals["shadow_worse"] += 1
        self._profit_totals = totals
        logger.info(
            "📊 盈利保护反事实 | %s 实际=%.2f%% 峰值=%.2f%% 回吐=%.2f%% | 影子=%s(%s) | 累计=%d笔",
            record.get("pair"),
            100 * float(record.get("actual_profit_ratio") or 0.0),
            100 * float(record.get("peak_profit_ratio") or 0.0),
            100 * float(record.get("giveback_ratio") or 0.0),
            (
                f"{100 * float(record['shadow_exit_ratio']):.2f}%"
                if record.get("shadow_exit_ratio") is not None
                else "未触发"
            ),
            record.get("shadow_exit_reason") or "—",
            totals["closed"],
            extra=LOG_SCORE,
        )

    def _log_profit_position_table(self, now: float, trades: dict[str, Trade]) -> None:
        """Render the live ratchet and no-progress state beside the holdings report."""
        if not self.settings["profit_shadow_enabled"]:
            return
        shadow = getattr(self, "_profit_shadow", {})
        rows: list[tuple[float, list[str], str]] = []
        for pair, trade in trades.items():
            record = shadow.get(pair)
            if not self._valid_profit_record(pair, record):
                continue
            record = cast(dict[str, Any], record)
            if record.get("trade_id") != trade.id:
                continue
            if row := self._profit_position_row(now, pair, trade, record):
                rows.append(row)
        if not rows:
            return
        rows.sort(key=lambda item: item[0], reverse=True)
        _log_table(
            "🛡️ 盈利保护状态",
            [
                "交易对",
                "1R价幅/占比",
                "峰值",
                "当前(R/含杠杆)",
                "真实棘轮",
                "目标止损价",
                "现价距目标",
                "停滞根数",
                f"{self.settings['holding_timeframe']}趋势",
                "无进展退出",
                "影子退出",
            ],
            [row for _, row, _ in rows],
            style="magenta",
            row_styles=[style for _, _, style in rows],
            caption="与持仓明细同周期打印; R在入场时冻结; 峰值恢复使用trade.max_rate; "
            "停滞只统计完整持仓周期K线; 现价距目标为正表示仍在止损价上方",
        )

    def _profit_position_row(
        self, now: float, pair: str, trade: Trade, record: dict[str, Any]
    ) -> tuple[float, list[str], str] | None:
        current = record.get("current_price")
        detail = getattr(self, "_position_details", {}).get(pair, {})
        mark_fresh = getattr(self, "_position_data_healthy", False) and 0 <= now - float(
            getattr(self, "_last_position_sync", 0.0)
        ) <= float(self.settings["position_stale_seconds"])
        try:
            mark = float(detail.get("markPrice"))
            if mark_fresh and math.isfinite(mark) and mark > 0:
                current = mark
        except (TypeError, ValueError):
            pass
        if type(current) not in (int, float):
            return None
        current_value = float(cast(int | float, current))
        if not math.isfinite(current_value) or current_value <= 0:
            return None
        entry = float(record["entry_price"])
        r_price = record.get("r_price")
        peak = float(record["peak_price"])
        peak_r = self._profit_r_of(record, peak)
        current_r = self._profit_r_of(record, current_value)
        current_ratio = self._profit_ratio_at(trade, current_value)
        candidate = self._profit_lock_target(record, peak)
        target = record.get("execution_lock_stop_price") or candidate
        lock_status = (
            "已武装"
            if record.get("execution_lock_stop_price") is not None
            else "待本轮执行"
            if candidate is not None
            else "R待补"
            if r_price is None
            else "未武装"
        )
        distance = (
            f"{100 * (current_value / float(target) - 1):+.2f}%"
            if target is not None and float(target) > 0
            else "—"
        )
        trend = self._profit_no_progress_trend(pair) or "未知"
        no_progress = (
            "已满足"
            if self._profit_no_progress_at_price(record, current_value)
            else f"待低于{self.settings['profit_no_progress_max_r']:.2f}R"
            if record.get("no_progress_setup")
            else "观察"
        )
        shadow_reason = {
            "ratchet": "棘轮",
            "no_progress": "无进展",
            "stoploss": "原止损",
        }.get(str(record.get("shadow_exit_reason")), "—")
        r_label = (
            f"{float(r_price):.8g}/{100 * float(r_price) / entry:.2f}%"
            if r_price is not None
            else "待补"
        )
        peak_label = f"{peak_r:+.2f}R" if peak_r is not None else f"{peak:.8g}"
        current_label = (
            f"{current_r:+.2f}R/{100 * current_ratio:+.1f}%"
            if current_r is not None and current_ratio is not None
            else "未知"
        )
        style = (
            "red"
            if no_progress == "已满足" or (target is not None and current_value <= float(target))
            else "green"
            if lock_status == "已武装"
            else "yellow"
        )
        return (
            current_ratio if current_ratio is not None else -math.inf,
            [
                pair,
                r_label,
                peak_label,
                current_label,
                lock_status,
                f"{float(target):.8g}" if target is not None else "—",
                distance,
                f"{record['bars_since_new_high']}/{self.settings['profit_no_progress_candles']}",
                trend,
                no_progress,
                shadow_reason,
            ],
            style,
        )

    def _log_profit_shadow_summary(self, now: float, current_time: datetime) -> None:
        totals = getattr(self, "_profit_totals", None)
        if not totals or not totals["closed"]:
            return
        if now - float(getattr(self, "_last_profit_summary", -math.inf)) < float(
            self.settings["status_log_seconds"]
        ):
            return
        self._last_profit_summary = now
        closed = totals["closed"]
        shadow_count = totals["shadow_count"]
        rows = [
            ["已平仓笔数", str(closed), "影子账本累计"],
            [
                "平均实际收益",
                f"{100 * totals['actual_sum'] / closed:.2f}%",
                "保证金口径, 含费用",
            ],
            [
                "平均峰值收益",
                f"{100 * totals['peak_sum'] / closed:.2f}%",
                "持仓期间最高浮盈",
            ],
            [
                "平均回吐",
                f"{100 * totals['giveback_sum'] / closed:.2f}%",
                "峰值 - 实际",
            ],
            [
                "棘轮/动量/止损 影子退出",
                f"{totals['ratchet_exits']}/{totals['no_progress_exits']}/{totals['stop_exits']}",
                "若启用盈利保护本会触发的方式",
            ],
            [
                "曾达到棘轮条件",
                f"{totals['locked']}/{closed}",
                "峰值浮盈曾达 1R",
            ],
        ]
        if shadow_count:
            rows.append(
                [
                    "影子优于实际",
                    f"{totals['shadow_better']}/{shadow_count}",
                    (
                        f"影子均值 {100 * totals['shadow_sum'] / shadow_count:.2f}% "
                        f"vs 实际 {100 * totals['actual_sum'] / closed:.2f}%"
                    ),
                ]
            )
        _log_table(
            "📊 盈利保护反事实汇总",
            ["指标", "数值", "说明"],
            rows,
            style="magenta",
            caption=f"影子账本仅统计, 不改变交易决策 | {current_time.isoformat()}",
        )

    # ------------------------------------------------------------------ 执行路径

    def _profit_lock_stoploss(
        self, pair: str, trade: Trade, current_rate: float, current_time: datetime
    ) -> float | None:
        """返回 custom_stoploss 需要的止损值; None 表示本轮不改动。"""
        record = getattr(self, "_profit_shadow", {}).get(pair)
        if record is None or record.get("trade_id") != trade.id:
            return None
        peak = max(
            float(record["peak_price"]),
            float(getattr(trade, "max_rate", None) or trade.open_rate),
            float(current_rate),
        )
        record["peak_price"] = peak
        record["peak_profit_ratio"] = self._profit_ratio_at(trade, peak)
        record["peak_profit_r"] = self._profit_r_of(record, peak)
        candidate = self._profit_lock_target(record, peak)
        newly_armed = False
        if candidate is not None:
            previous = record.get("execution_lock_stop_price")
            record["execution_lock_stop_price"] = (
                max(float(previous), candidate) if previous is not None else candidate
            )
            if record.get("execution_lock_armed_at") is None:
                record["execution_lock_armed_at"] = current_time.timestamp()
                newly_armed = True
        target = record.get("execution_lock_stop_price")
        if target is None:
            return None
        if float(target) >= float(current_rate):
            if newly_armed:
                logger.warning(
                    "盈利棘轮已按历史峰值武装 %s | 峰值=%.8g 目标=%.8g 当前=%.8g | "
                    "当前已低于目标, 保留锁存并等待价格恢复后挂保护止损",
                    pair,
                    peak,
                    target,
                    current_rate,
                )
            return None
        r_price = record.get("r_price")
        min_step = float(self.settings["profit_lock_min_step_r"])
        current_stop = float(trade.stop_loss or 0.0)
        if r_price and min_step > 0 and float(target) < current_stop + min_step * float(r_price):
            # 减少交易所"先撤后建"的改单次数, 同时避免无谓的裸奔窗口。
            return None
        value = stoploss_from_absolute(
            float(target),
            current_rate=current_rate,
            is_short=False,
            leverage=float(trade.leverage or 1.0),
        )
        if not value or not math.isfinite(float(value)):
            return None
        return float(value)

    def _profit_no_progress_exit(self, pair: str, trade: Trade, current_rate: float) -> bool:
        """custom_exit 侧读取影子账本已算好的动量结论, 不重复计算。"""
        if not self.settings["profit_no_progress_enabled"]:
            return False
        record = getattr(self, "_profit_shadow", {}).get(pair)
        if record is None or record.get("trade_id") != trade.id:
            return False
        return self._profit_no_progress_at_price(record, current_rate)
