"""Report calculations are shared briefly; order checks must always see fresh data."""

import importlib
import time
from unittest.mock import Mock

import pytest

from tests.strategy.test_leader_squeeze_multi_timeframe import (
    NOW,
    PAIR,
    hourly_source,
    strategy_for,
)


report_snapshot = importlib.import_module("leader_squeeze_helpers").report_snapshot
decision_snapshot = importlib.import_module("leader_squeeze_helpers").decision_snapshot


@pytest.fixture(autouse=True)
def freeze_clock(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: NOW.timestamp())


def test_report_reuses_context_but_next_report_and_trade_checks_read_again():
    strategy = strategy_for(hourly_source())
    read = strategy.dp.get_pair_dataframe
    strategy.dp.get_pair_dataframe = Mock(side_effect=read)

    @report_snapshot
    def report():
        first = strategy._trend_context(PAIR, "1h")
        assert first["available"]
        assert strategy._trend_context(PAIR, "1h") == first

    report()
    assert strategy.dp.get_pair_dataframe.call_count == 1
    report()
    assert strategy.dp.get_pair_dataframe.call_count == 2
    strategy._trend_context(PAIR, "1h")
    strategy._trend_context(PAIR, "1h")
    assert strategy.dp.get_pair_dataframe.call_count == 4


def test_report_exception_cannot_leave_cache_active():
    strategy = strategy_for(hourly_source())
    read = strategy.dp.get_pair_dataframe
    strategy.dp.get_pair_dataframe = Mock(side_effect=read)

    @report_snapshot
    def report():
        strategy._trend_context(PAIR, "1h")
        raise RuntimeError("report failed")

    with pytest.raises(RuntimeError):
        report()
    strategy._trend_context(PAIR, "1h")
    assert strategy.dp.get_pair_dataframe.call_count == 2


def test_decision_snapshot_reuses_candles_but_next_callback_reads_again():
    strategy = strategy_for(hourly_source())
    read = strategy.dp.get_pair_dataframe
    strategy.dp.get_pair_dataframe = Mock(side_effect=read)

    @decision_snapshot
    def bot_loop():
        strategy._trend_context(PAIR, "1h")
        strategy._trend_context(PAIR, "1h")

    bot_loop()
    assert strategy.dp.get_pair_dataframe.call_count == 1
    strategy._trend_context(PAIR, "1h")
    assert strategy.dp.get_pair_dataframe.call_count == 2
