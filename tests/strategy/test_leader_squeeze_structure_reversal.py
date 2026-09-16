"""15m reversal exits distinguish wicks, confirmed breaks and sharp selloffs."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    configured_settings,
    configured_strategy,
)
from tests.strategy.test_leader_squeeze_freshness import NOW, NOW_SECONDS, _reversal_15m
from tests.strategy.test_leader_squeeze_strategy import MODULE, LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"


def _strategy(frame):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=frame))
    strategy._market_is_down = Mock(return_value=False)
    strategy._rotation_exit_allowed = Mock(return_value=False)
    return strategy


@pytest.mark.parametrize(
    ("closes", "expected", "branch"),
    [
        ((100.0, 100.0), False, ""),  # Both wicks can pierce support and recover.
        ((100.0, 97.0), False, ""),  # Ordinary break requires two closed candles.
        ((98.0, 98.0), False, ""),  # Touching the buffered level is not a break.
        ((97.0, 97.0), True, "结构破位"),
        ((100.0, 95.0), True, "急跌破位"),  # Deep selloff need not wait another 15m.
        ((100.0, 96.0), False, ""),  # Exact fast threshold still needs confirmation.
    ],
)
def test_wick_confirmation_and_fast_break_boundaries(closes, expected, branch):
    frame = _reversal_15m(close=closes, low=(94.0, 94.0), high=(101.0, 101.0))
    history = frame.iloc[:3].copy()
    history["date"] -= pd.Timedelta(minutes=45)
    frame = pd.concat([history, frame], ignore_index=True)
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        # Repeated bot loops on one candle must not count as extra confirmations.
        for _ in range(3):
            assert strategy._timeframe_reversed(PAIR, "15m") is expected
    if expected:
        detail = strategy._trend_exit_details[PAIR]
        assert branch in detail
        assert "ATR14=2" in detail
        assert "普通阈值=98" in detail
        assert "急跌阈值=96" in detail
    else:
        assert PAIR not in strategy._trend_exit_details


def test_uses_latest_confirmed_swing_low_not_a_remote_old_low():
    frame = _reversal_15m(close=(103.0, 103.0), low=(102.0, 102.0), high=(104.0, 104.0))
    frame.loc[:19, ["high", "low", "close"]] = [110.0, 108.0, 109.0]
    frame.loc[0, "low"] = 90.0
    frame.loc[14, ["high", "low", "close"]] = [109.0, 105.0, 107.0]
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        assert strategy._timeframe_reversed(PAIR, "15m")
    assert "波段支撑=105" in strategy._trend_exit_details[PAIR]


def test_break_candles_cannot_expand_their_own_atr_buffer():
    frame = _reversal_15m(low=(1.0, 1.0), high=(200.0, 200.0))
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        assert strategy._timeframe_reversed(PAIR, "15m")
    assert "ATR14=2" in strategy._trend_exit_details[PAIR]


def test_unclosed_crash_cannot_change_closed_structure_signal():
    frame = _reversal_15m(close=(100.0, 100.0), high=(101.0, 101.0))
    frame.loc[len(frame)] = {"date": NOW, "high": 101.0, "low": 49.0, "close": 50.0}
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        assert not strategy._timeframe_reversed(PAIR, "15m")


def test_fast_break_custom_exit_logs_levels_and_recovery_clears_signal(caplog):
    frame = _reversal_15m(close=(100.0, 95.0), low=(99.0, 94.0), high=(101.0, 100.0))
    strategy = _strategy(frame)
    # Keep this logging boundary test on the extracted legacy 15m algorithm.
    strategy._trend_reversed = lambda pair: strategy._timeframe_reversed(pair, "15m")
    with (
        patch.object(MODULE.time, "time", return_value=NOW_SECONDS),
        caplog.at_level("INFO", logger="leader_squeeze_strategy"),
    ):
        assert strategy.custom_exit(PAIR, SimpleNamespace(), NOW, 95.0, -0.05) == "trend_reversal"
        assert "急跌破位" in caplog.text
        assert "区间支撑=99" in caplog.text
        frame.loc[21, "close"] = 100.0
        assert strategy.custom_exit(PAIR, SimpleNamespace(), NOW, 100.0, 0.0) is None
    assert PAIR not in strategy._trend_exit_details


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("reversal_confirm_candles", 1),
        ("reversal_confirm_candles", True),
        ("reversal_lookback_candles", 4),
        ("reversal_atr_buffer", -0.1),
        ("reversal_atr_buffer", float("nan")),
        ("reversal_fast_atr_buffer", 0.5),
        ("reversal_fast_atr_buffer", float("inf")),
        ("reversal_slow_candles", 2),
        ("reversal_slow_candles", 4.5),
        ("reversal_slow_atr_drop", 0),
        ("reversal_slow_atr_drop", float("nan")),
    ],
)
def test_reversal_parameters_reject_unsafe_or_invalid_values(key, value):
    strategy = _strategy(_reversal_15m())
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        strategy._validate_reversal_settings()


def test_cannot_override_strategy_back_to_5m():
    strategy = _strategy(_reversal_15m())
    strategy.timeframe = "5m"
    with pytest.raises(ValueError, match="strategy timeframe must match config timeframe"):
        strategy._validate_reversal_settings()


def test_zero_atr_cannot_turn_a_tiny_dip_into_a_fast_exit():
    frame = _reversal_15m()
    frame.loc[:19, ["high", "low", "close"]] = 100.0
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        assert not strategy._timeframe_reversed(PAIR, "15m")


def test_invalid_ohlc_cannot_produce_a_reversal_signal():
    frame = _reversal_15m()
    frame.loc[0, "high"] = 98.0  # Below both low and close.
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        assert not strategy._timeframe_reversed(PAIR, "15m")


@pytest.mark.parametrize("wide_break_candle", [False, True])
def test_break_remains_actionable_after_missed_cycles_without_price_recovery(wide_break_candle):
    for bars in range(1, 16):
        closes = [100.0] * 60 + [95.0] * bars
        frame = pd.DataFrame(
            {
                "date": pd.date_range(end=NOW, periods=len(closes), freq="15min")
                - pd.Timedelta(minutes=15),
                "close": closes,
                "high": [value + 1 for value in closes],
                "low": [value - 1 for value in closes],
            }
        )
        if wide_break_candle:
            frame.loc[60, ["high", "low"]] = [150.0, 50.0]
        # Recreate the strategy with rolling history to model a fresh restart.
        strategy = _strategy(frame.tail(60))
        with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
            assert strategy._timeframe_reversed(PAIR, "15m"), (
                f"Missed exit after {bars} closed bars"
            )


def test_reclaimed_support_cancels_historical_break():
    closes = [100.0] * 60 + [95.0, 100.0, 98.0, 98.0, 98.0]
    frame = pd.DataFrame(
        {
            "date": pd.date_range(end=NOW, periods=len(closes), freq="15min")
            - pd.Timedelta(minutes=15),
            "close": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
        }
    )
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        assert strategy._timeframe_reversed(PAIR, "15m") is False
