"""Buy decisions must not contradict trend exits on the same closed candles."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tests.strategy.test_leader_squeeze_strategy import (
    ETH_TEST_NOW,
    MODULE,
    _entry_ready_strategy,
)


PAIR = "BTC/USDT:USDT"


def _scenario(branch):
    closes = [100.0] * 116 + [101.0, 102.0, 103.0, 104.0]
    if branch == "confirmed":
        closes[-2:] = [98.0, 98.0]
    elif branch == "fast":
        closes[-1] = 90.0
    candles = pd.DataFrame(
        {
            "date": pd.date_range(
                end=pd.Timestamp(ETH_TEST_NOW) - pd.Timedelta(minutes=15),
                periods=120,
                freq="15min",
            ),
            "close": closes,
            "volume": 100.0,
        }
    )
    candles["high"] = candles["close"] + 0.5
    candles["low"] = candles["close"] - 0.5
    five_minute_wick = candles.tail(2).copy()
    five_minute_wick.loc[five_minute_wick.index[-1], "low"] = 80.0
    strategy = _entry_ready_strategy(ETH_TEST_NOW.timestamp())
    # This test intentionally uses a compact trend fixture; production uses a
    # 7-day activity baseline, so shrink that configurable lookback here while
    # keeping the reversal candles and their purpose unchanged.
    strategy.settings["volume_activity_baseline_candles"] = 96
    # These tests exercise the real candle and trend implementations.
    strategy.__dict__.pop("_candle_metrics", None)
    strategy.__dict__.pop("_trend_reversed", None)
    strategy.__dict__.pop("_higher_entry_reason", None)
    strategy.dp = SimpleNamespace(
        get_pair_dataframe=lambda pair, timeframe: (
            candles if timeframe == "15m" else five_minute_wick
        )
    )
    strategy._execution_is_safe = Mock(return_value=True)
    strategy._rotation_pair = strategy._rotation_target = None
    strategy._exit_metrics = {
        PAIR: {"taker_ratio": 0.8, "oi_change": 0.01, "_exit_valid_until": 1e12}
    }
    return strategy, candles


def _confirm(strategy):
    return strategy.confirm_trade_entry(
        PAIR, "market", 1.0, 104.0, "GTC", ETH_TEST_NOW, None, "long"
    )


@pytest.mark.parametrize("branch", ["confirmed", "fast"])
def test_existing_trend_exit_blocks_selection_and_final_confirmation(branch):
    strategy, _ = _scenario(branch)
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        local = strategy._candle_metrics(PAIR)
        assert local is not None
        strategy._metrics[PAIR].update(local)
        assert strategy._trend_reversed(PAIR)
        assert strategy._select_entries() == set()
        assert strategy._entry_decisions[PAIR]
        assert not _confirm(strategy)
        assert strategy._entry_block_reason
        # No grace period: an existing position still exits immediately.
        assert strategy.custom_exit(PAIR, SimpleNamespace(), ETH_TEST_NOW, 104.0, 0.0) == (
            "trend_reversal"
        )
    strategy._execution_is_safe.assert_not_called()


def test_healthy_uptrend_can_still_enter():
    strategy, _ = _scenario("healthy")
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert not strategy._trend_reversed(PAIR)
        assert strategy._select_entries() == {PAIR}
        assert _confirm(strategy)
        assert strategy.custom_exit(PAIR, SimpleNamespace(), ETH_TEST_NOW, 104.0, 0.0) is None


def test_5m_lower_low_alone_does_not_exit_or_block_entry():
    strategy, _ = _scenario("5m")
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert not strategy._trend_reversed(PAIR)
        assert strategy.custom_exit(PAIR, SimpleNamespace(), ETH_TEST_NOW, 104.0, 0.0) is None
        assert strategy._select_entries() == {PAIR}
        assert _confirm(strategy)


@pytest.mark.parametrize("during_book_fetch", [False, True])
def test_latest_candle_trend_overrides_still_valid_score_snapshot(during_book_fetch):
    strategy, candles = _scenario("healthy")

    def change_trend(*args, **kwargs):
        candles.loc[119, "close"] = 99.0
        candles.loc[119, "low"] = 98.5
        return True

    if during_book_fetch:
        strategy._execution_is_safe.side_effect = change_trend
    else:
        change_trend()
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._metrics[PAIR]["momentum"] > 0  # Earlier score remains valid.
        if not during_book_fetch:
            assert strategy._select_entries() == set()
        assert not _confirm(strategy)
        assert "上涨条件不足" in strategy._entry_block_reason


def test_trend_exit_is_rechecked_after_book_fetch():
    strategy, candles = _scenario("healthy")

    def reverse(*args, **kwargs):
        candles.loc[119, "close"] = 90.0
        candles.loc[119, "low"] = 89.5
        return True

    strategy._execution_is_safe.side_effect = reverse
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert not _confirm(strategy)
        assert strategy._entry_block_reason


def test_rotation_candidate_uses_the_same_trend_gate():
    strategy, _ = _scenario("confirmed")
    strategy._rotation_pair, strategy._rotation_target = "OLD", PAIR
    strategy._rotation_scores_qualify = Mock(return_value=True)
    strategy._prepare_rotation_buy = Mock(return_value=True)
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._select_entries() == set()
        assert not _confirm(strategy)
    strategy._prepare_rotation_buy.assert_not_called()


@pytest.mark.parametrize("fault", ["missing_high", "invalid_ohlc", "21_bars", "24_bars"])
def test_unavailable_reversal_assessment_blocks_entry(fault):
    strategy, candles = _scenario("healthy")
    if fault == "missing_high":
        candles.drop(columns="high", inplace=True)
    elif fault == "invalid_ohlc":
        candles.loc[0, "high"] = 1.0
    else:
        candles.drop(index=candles.index[: -int(fault.split("_")[0])], inplace=True)
        # Keep this case about the reversal lookback.  The real candle score
        # now deliberately requires the production seven-day volume history.
        strategy._candle_metrics = Mock(
            return_value={
                "momentum": 0.05,
                "trend_continuity": 1.0,
                "volume_ratio": 2.0,
                "volume_activity_ratio": 3.0,
                "_candle_valid_until": 1e12,
            }
        )
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._entry_quality_reason(PAIR, 0) == "趋势退出指标不足或无效, 禁止开仓"
        assert strategy._select_entries() == set()
        assert not _confirm(strategy)
        assert strategy.custom_exit(PAIR, SimpleNamespace(), ETH_TEST_NOW, 104.0, 0.0) is None
    strategy._execution_is_safe.assert_not_called()
