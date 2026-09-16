"""Regression tests for the independent slow 15m reversal branch."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from tests.strategy.leader_squeeze_test_helpers import (
    configured_settings,
    configured_strategy,
)
from tests.strategy.test_leader_squeeze_strategy import MODULE, LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _strategy(frame: pd.DataFrame) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = {
        **configured_settings(),
        "reversal_slow_candles": 5,
        "reversal_slow_atr_drop": 1.0,
    }
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)
    strategy._trend_exit_details = {}
    return strategy


def _frame(
    *,
    closes: list[float] | None = None,
    unclosed: bool = False,
    pivot_low: float | None = 95.0,
) -> pd.DataFrame:
    closes = closes or [100.0] * 60 + [99.4, 98.8, 98.2, 97.6, 97.0]
    high = [value + 1.0 for value in closes]
    low = [value - 1.0 for value in closes]
    if pivot_low is not None:
        low[50] = pivot_low
    dates = list(
        pd.date_range(
            end=pd.Timestamp(NOW - timedelta(minutes=15)),
            periods=len(closes),
            freq="15min",
        )
    )
    if unclosed:
        dates[-1] = pd.Timestamp(NOW)
    return pd.DataFrame({"date": dates, "close": closes, "high": high, "low": low})


def _reversed(frame: pd.DataFrame) -> tuple[LeaderSqueezeStrategy, bool]:
    strategy = _strategy(frame)
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        result = strategy._timeframe_reversed(PAIR, "15m")
    return strategy, result


def test_slow_decline_triggers_without_breaking_structural_support() -> None:
    strategy, result = _reversed(_frame())

    assert result
    details = strategy._trend_exit_details[PAIR]
    assert details.startswith("15m持续走弱")
    assert not details.startswith("15m结构破位")
    assert not details.startswith("15m急跌破位")


def test_slow_decline_accumulates_across_sub_atr_five_candle_windows() -> None:
    closes = [100.0] * 60 + [99.9 - 0.1 * index for index in range(25)]
    frame = _frame(closes=closes, pivot_low=None)

    # Each five-candle window drops less than one ATR, but the uninterrupted
    # move below EMA20 eventually exceeds one ATR from its starting close.
    assert frame["close"].iloc[-6] - frame["close"].iloc[-1] < 2.0
    strategy, result = _reversed(frame)

    assert result
    assert "15m持续走弱" in strategy._trend_exit_details[PAIR]


def test_slow_decline_requires_five_recent_closes_below_ema() -> None:
    frame = _frame(closes=[100.0] * 60 + [99.0, 98.5, 98.0, 97.5])

    _, result = _reversed(frame)

    assert not result


def test_recovery_above_ema_clears_the_previous_decline() -> None:
    closes = (
        [100.0] * 60
        + [99.9 - 0.1 * index for index in range(25)]
        + [98.0, 98.5, 99.0, 99.5, 100.0, 100.5, 101.0, 101.0, 101.0, 101.0]
        + [99.5, 99.4, 99.3, 99.2, 99.1]
    )
    frame = _frame(closes=closes, pivot_low=None)
    ema20 = frame["close"].ewm(span=20, adjust=False).mean()

    assert (frame["close"].iloc[-5:] < ema20.iloc[-5:]).all()
    assert ema20.iloc[-1] < ema20.iloc[-6]
    assert frame["close"].iloc[-6] - frame["close"].iloc[-1] < 2.0
    _, result = _reversed(frame)

    assert not result


def test_recent_five_candles_recovering_below_ema_do_not_trigger() -> None:
    closes = [100.0] * 60 + [99.9 - 0.1 * index for index in range(25)]
    closes += [97.8, 97.9, 98.0, 98.1, 98.2]
    frame = _frame(closes=closes, pivot_low=None)
    ema20 = frame["close"].ewm(span=20, adjust=False).mean()

    assert (frame["close"].iloc[-5:] < ema20.iloc[-5:]).all()
    assert frame["close"].iloc[-1] > frame["close"].iloc[-5]
    assert ema20.iloc[-1] < ema20.iloc[-6]
    _, result = _reversed(frame)

    assert not result


def test_slow_decline_does_not_trigger_when_drop_is_below_atr() -> None:
    _, result = _reversed(_frame(closes=[100.0] * 60 + [99.8, 99.6, 99.4, 99.2, 99.0]))

    assert not result


def test_slow_decline_does_not_trigger_while_ema_is_rising() -> None:
    frame = _frame(closes=[100.0] * 60 + [103.0, 103.0, 103.0, 103.0, 97.0])
    ema20 = frame["close"].ewm(span=20, adjust=False).mean()

    assert ema20.iloc[-1] > ema20.iloc[-6]
    _, result = _reversed(frame)

    assert not result


def test_slow_decline_does_not_trigger_when_latest_close_recovers_above_ema() -> None:
    frame = _frame(closes=[100.0] * 60 + [99.4, 98.8, 98.2, 97.6, 101.0])
    ema20 = frame["close"].ewm(span=20, adjust=False).mean()

    assert frame["close"].iloc[-1] > ema20.iloc[-1]
    _, result = _reversed(frame)

    assert not result


def test_unclosed_latest_slow_candle_does_not_count_for_confirmation() -> None:
    _, result = _reversed(
        _frame(closes=[100.0] * 60 + [99.4, 98.8, 98.2, 97.6, 80.0], unclosed=True)
    )

    assert not result
