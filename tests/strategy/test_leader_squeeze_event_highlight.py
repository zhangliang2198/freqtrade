"""框架交易事件日志的 emoji 与高亮: 移动止损上移必须醒目且幂等。"""

from __future__ import annotations

import logging

import pytest

from tests.strategy.leader_squeeze_test_helpers import configured_strategy
from tests.strategy.test_leader_squeeze_strategy import LeaderSqueezeStrategy


def _record(message: str, logger_name: str = "freqtrade.freqtradebot") -> logging.LogRecord:
    return logging.LogRecord(logger_name, logging.INFO, __file__, 1, message, (), None)


def _filter():
    from leader_squeeze_helpers import EventHighlightFilter

    return EventHighlightFilter()


@pytest.fixture
def isolated_highlight_filters():
    from leader_squeeze_helpers import _EVENT_HIGHLIGHT_LOGGERS, EventHighlightFilter

    loggers = [logging.getLogger(name) for name in _EVENT_HIGHLIGHT_LOGGERS]
    previous = {logger: logger.filters.copy() for logger in loggers}
    for logger in loggers:
        for item in logger.filters.copy():
            if isinstance(item, EventHighlightFilter):
                logger.removeFilter(item)
    try:
        yield
    finally:
        for logger in loggers:
            for item in logger.filters.copy():
                logger.removeFilter(item)
            for item in previous[logger]:
                logger.addFilter(item)


def test_trailing_stoploss_move_gets_arrow_and_green_style() -> None:
    """取消旧挂单止损以便重新挂单 = 止损上移, 代表又锁住一段利润。"""
    record = _record(
        "正在取消交易对 BTW/USDT:USDT 的当前挂单止损 (orderid:4000001920213659), 以便重新挂单 ..."
    )

    _filter().filter(record)

    assert record.getMessage().startswith("📈")
    assert record.strategy_log_style == "green"


def test_initial_stoploss_keeps_shield_without_style() -> None:
    record = _record("已为 BTW/USDT:USDT 添加 market 止损单。止损价: 0.949, 限价: None")

    _filter().filter(record)

    assert record.getMessage().startswith("🛡️")
    # 首次挂止损不代表盈利, 不能跟着变绿。
    assert not getattr(record, "strategy_log_style", "")


def test_fill_emoji_and_idempotency_are_unchanged() -> None:
    decorator = _filter()
    buy = _record("MARKET_BUY 已成交, Trade(id=226, pair=BTW/USDT:USDT, amount=154)")
    other = _record("Wallets synced.")

    decorator.filter(buy)
    decorator.filter(other)
    assert buy.getMessage().startswith("🟢")
    assert other.getMessage() == "Wallets synced."

    first = buy.getMessage()
    decorator.filter(buy)
    assert buy.getMessage() == first


def test_installer_attaches_exactly_one_filter(isolated_highlight_filters) -> None:
    from leader_squeeze_helpers import EventHighlightFilter, install_event_highlight_filter

    install_event_highlight_filter()
    install_event_highlight_filter()

    attached = logging.getLogger("freqtrade.freqtradebot")
    assert sum(isinstance(item, EventHighlightFilter) for item in attached.filters) == 1


def test_strategy_installs_the_filter_at_startup(isolated_highlight_filters) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._initialize_rotation_audit = lambda: None
    strategy._load_risk_state = dict
    strategy._sync_external_pairs = lambda: None

    strategy.bot_start()

    from leader_squeeze_helpers import EventHighlightFilter

    attached = logging.getLogger("freqtrade.freqtradebot")
    assert any(isinstance(item, EventHighlightFilter) for item in attached.filters)
