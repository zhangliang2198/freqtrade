"""Regression tests for freshness checks used by leader_squeeze_strategy."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    configured_settings,
    configured_strategy,
)


STRATEGY_PATH = (
    Path(__file__).parents[2] / "user_data/strategies/leader_squeeze/leader_squeeze_strategy.py"
)
SPEC = importlib.util.spec_from_file_location("leader_squeeze_strategy_freshness", STRATEGY_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
NOW_SECONDS = NOW.timestamp()


def _candles(
    timeframe: str,
    count: int,
    *,
    close: list[float] | None = None,
    low: list[float] | None = None,
    high: list[float] | None = None,
    volume: list[float] | None = None,
    latest_age_seconds: float | None = None,
    gap_at: int | None = None,
    unclosed: bool = False,
) -> pd.DataFrame:
    seconds = 900 if timeframe == "15m" else 300
    latest_age = seconds if latest_age_seconds is None else latest_age_seconds
    if unclosed:
        latest_age = 0
    latest = NOW - timedelta(seconds=latest_age)
    dates = [latest - timedelta(seconds=seconds * (count - index - 1)) for index in range(count)]
    if gap_at is not None:
        dates[gap_at] -= timedelta(seconds=seconds)
    frame: dict[str, list[object]] = {"date": dates}
    if close is not None:
        frame["close"] = close
    if low is not None:
        frame["low"] = low
    if high is not None:
        frame["high"] = high
    if volume is not None:
        frame["volume"] = volume
    return pd.DataFrame(frame)


def _strategy(frames: dict[str, pd.DataFrame]):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.timeframe = "15m"
    strategy.dp = SimpleNamespace(
        get_pair_dataframe=lambda pair, timeframe: frames.get(timeframe, pd.DataFrame())
    )
    return strategy


def _reversal_15m(
    *,
    close: tuple[float, float] = (97.0, 97.0),
    low: tuple[float, float] = (96.0, 96.0),
    high: tuple[float, float] = (98.0, 98.0),
    latest_age_seconds: float | None = None,
    gap_at: int | None = None,
    unclosed: bool = False,
) -> pd.DataFrame:
    return _candles(
        "15m",
        22,
        close=[100.0] * 20 + list(close),
        low=[99.0] * 20 + list(low),
        high=[101.0] * 20 + list(high),
        latest_age_seconds=latest_age_seconds,
        gap_at=gap_at,
        unclosed=unclosed,
    )


def _flat_15m() -> pd.DataFrame:
    return _candles(
        "15m",
        22,
        close=[100.0] * 22,
        low=[99.0] * 22,
        high=[101.0] * 22,
    )


def test_closed_candles_accepts_fresh_closed_contiguous_required_columns() -> None:
    strategy = _strategy({"15m": _candles("15m", 22, close=[100.0] * 22, volume=[10.0] * 22)})

    result = strategy._closed_candles(
        PAIR,
        "15m",
        22,
        columns=("close", "volume"),
        now=NOW_SECONDS,
    )

    assert result is not None
    assert len(result) == 22
    assert result["date"].iloc[-1] == NOW - timedelta(minutes=15)


def test_closed_candles_rejects_missing_required_column() -> None:
    frame = _candles("15m", 22, close=[100.0] * 22)
    strategy = _strategy({"15m": frame})

    assert (
        strategy._closed_candles(
            PAIR,
            "15m",
            22,
            columns=("close", "volume"),
            now=NOW_SECONDS,
        )
        is None
    )


@pytest.mark.parametrize(
    ("fault", "column", "value"),
    [
        ("gap", "close", None),
        ("nan close", "close", float("nan")),
        ("zero close", "close", 0.0),
        ("nan high", "high", float("nan")),
        ("zero low", "low", 0.0),
        ("nan volume", "volume", float("nan")),
        ("negative volume", "volume", -1.0),
    ],
)
def test_closed_candles_rejects_gaps_and_invalid_values(fault, column, value) -> None:
    frame = _candles(
        "15m",
        22,
        close=[100.0] * 22,
        high=[101.0] * 22,
        low=[99.0] * 22,
        volume=[10.0] * 22,
        gap_at=20 if fault == "gap" else None,
    )
    if value is not None:
        frame.loc[20, column] = value
    strategy = _strategy({"15m": frame})

    assert (
        strategy._closed_candles(
            PAIR,
            "15m",
            22,
            columns=("close", "high", "low", "volume"),
            now=NOW_SECONDS,
        )
        is None
    )


def test_closed_candles_rejects_stale_data() -> None:
    frame = _candles("15m", 22, close=[100.0] * 22, latest_age_seconds=2 * 900 + 31)
    strategy = _strategy({"15m": frame})

    assert strategy._closed_candles(PAIR, "15m", 22, now=NOW_SECONDS) is None


def test_confirmed_15m_support_break_triggers_without_remote_metrics() -> None:
    strategy = _strategy({"15m": _reversal_15m()})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert strategy._timeframe_reversed(PAIR, "15m")


def test_unclosed_15m_candle_cannot_complete_two_candle_confirmation() -> None:
    strategy = _strategy({"15m": _reversal_15m(unclosed=True)})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert not strategy._timeframe_reversed(PAIR, "15m")


def test_expired_15m_does_not_trigger() -> None:
    strategy = _strategy({"15m": _reversal_15m(latest_age_seconds=2 * 900 + 31)})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert not strategy._timeframe_reversed(PAIR, "15m")


@pytest.mark.parametrize("missing_column", ["high", "low", "close"])
def test_missing_15m_reversal_column_blocks_exit(missing_column: str) -> None:
    frame = _reversal_15m().drop(columns=missing_column)
    strategy = _strategy({"15m": frame})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert not strategy._timeframe_reversed(PAIR, "15m")


def test_noncontiguous_15m_reversal_data_blocks_exit() -> None:
    strategy = _strategy({"15m": _reversal_15m(gap_at=19)})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert not strategy._timeframe_reversed(PAIR, "15m")


def test_5m_wick_cannot_trigger_15m_reversal() -> None:
    five_minute_wick = _candles(
        "5m",
        2,
        close=[100.0, 100.0],
        low=[100.0, 80.0],
        high=[101.0, 101.0],
    )
    strategy = _strategy({"15m": _flat_15m(), "5m": five_minute_wick})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert not strategy._timeframe_reversed(PAIR, "15m")


def test_one_15m_close_below_support_does_not_trigger() -> None:
    strategy = _strategy({"15m": _reversal_15m(close=(97.0, 100.0))})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert not strategy._timeframe_reversed(PAIR, "15m")


def test_15m_lower_wick_without_close_confirmation_does_not_trigger() -> None:
    strategy = _strategy(
        {"15m": _reversal_15m(close=(100.0, 100.0), low=(96.0, 96.0), high=(101.0, 101.0))}
    )

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MODULE.time, "time", lambda: NOW_SECONDS)
        assert not strategy._timeframe_reversed(PAIR, "15m")
