"""Shared log presentation utilities."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from datetime import timedelta, timezone
from functools import wraps
from io import StringIO
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text


logger = logging.getLogger("leader_squeeze_strategy")
DISPLAY_TZ = timezone(timedelta(hours=8), name="北京时间")
LOG_INFO = {"strategy_log_style": "cyan"}
LOG_GOOD = {"strategy_log_style": "green"}
LOG_WARN = {"strategy_log_style": "yellow"}
LOG_ERROR = {"strategy_log_style": "bold red"}
LOG_SCORE = {"strategy_log_style": "magenta"}

_report_cache: ContextVar[dict | None] = ContextVar("leader_report_cache", default=None)


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

    def __init__(self, title: str, table: Table):
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
    table = Table(
        *headers,
        box=box.SIMPLE_HEAD,
        header_style=f"bold {style}",
        caption=Text(caption) if caption else None,
    )
    for column in table.columns:
        column.overflow = "fold"
    for index, row in enumerate(rows):
        table.add_row(
            *(Text(cell) for cell in row), style=row_styles[index] if row_styles else style
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
    _external_exit_requested: Any
    _external_pairs: Any
    _external_stop_last_check: Any
    _external_stop_protected: Any
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
