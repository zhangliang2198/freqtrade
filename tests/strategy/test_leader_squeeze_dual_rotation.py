"""Focused coverage for normal and fast leader rotation channels."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tests.strategy.test_leader_squeeze_strategy import (
    ETH_TEST_NOW,
    MODULE,
    LeaderSqueezeStrategy,
    _entry_ready_strategy,
    _fresh_score_metric,
)


WEAK = "WEAK/USDT:USDT"
TARGET = "TARGET/USDT:USDT"
NOW = ETH_TEST_NOW
PERIOD = 15 * 60


def _trade(pair: str, age_minutes: float, trade_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=trade_id,
        pair=pair,
        is_short=False,
        open_date_utc=NOW - timedelta(minutes=age_minutes),
    )


def _rotation_strategy(
    *,
    weak_score: float = 40.0,
    target_score: float = 60.0,
    held_count: int = 5,
    weak_age_minutes: float = 60.0,
    fast_quality: bool = False,
) -> tuple[LeaderSqueezeStrategy, list[SimpleNamespace]]:
    scores = {WEAK: weak_score, TARGET: target_score}
    trades = [_trade(WEAK, weak_age_minutes, 1)]
    for index in range(1, held_count):
        pair = f"HELD-{index}/USDT:USDT"
        scores[pair] = 70.0
        trades.append(_trade(pair, 120.0, index + 1))

    strategy = _entry_ready_strategy(NOW.timestamp())
    strategy.settings.update(
        {
            "replacement_entry_score": 50.0,
            "replacement_weak_score": 45.0,
            "replacement_score_gap": 10.0,
            "replacement_fast_enabled": True,
            "replacement_fast_entry_score": 60.0,
            "replacement_fast_score_gap": 15.0,
            "replacement_fast_confirmations": 1,
            "replacement_fast_min_age_minutes": 15,
            "replacement_fast_cooldown_minutes": 15,
            "replacement_fast_core_score": 40.0,
            "replacement_min_age_minutes": 30,
            "replacement_cooldown_minutes": 30,
        }
    )
    strategy._entries_allowed = Mock(return_value=True)
    strategy._scores = scores
    strategy._score_leaders = list(scores)
    strategy._metrics = {pair: _fresh_score_metric() for pair in scores}
    strategy._last_score_refresh = 1000.0
    strategy._rotation_score_snapshot = -1.0
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._rotation_state = None
    strategy._rotation_candidate = None
    strategy._rotation_candidate_bar = None
    strategy._rotation_candidate_channel = None
    strategy._rotation_seen = 0
    strategy._last_rotation = 0.0
    strategy._risk_state = {}
    strategy._external_pairs = set()
    strategy._position_first_seen = {}
    strategy._entry_quality_reason = Mock(return_value="")
    strategy._pair_score_current = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._rotation_holding_weak = Mock(return_value=True)
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy._fast_rotation_quality = Mock(return_value=fast_quality)
    strategy._rotation_bar = Mock(return_value=NOW.timestamp())
    strategy._persist_rotation = Mock(return_value=True)
    return strategy, trades


def _plan(
    strategy: LeaderSqueezeStrategy,
    trades: list[SimpleNamespace],
    now: float,
    current_time=NOW,
) -> None:
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades):
        strategy._plan_rotation(now, current_time)


def test_rotation_score_channels_apply_heat_adjusted_floor_and_old_weak_floor() -> None:
    strategy, _ = _rotation_strategy(weak_score=44.0, target_score=70.0)
    discounted = {TARGET: 49.0}
    strategy._entry_score = lambda pair: discounted.get(pair, strategy._scores[pair])
    strategy._current_score = lambda pair: strategy._scores[pair]

    assert not strategy._rotation_scores_qualify(WEAK, TARGET, "normal")

    discounted[TARGET] = 54.0
    assert strategy._rotation_scores_qualify(WEAK, TARGET, "normal")

    strategy._scores[WEAK] = 52.0
    discounted[TARGET] = 67.0
    assert not strategy._rotation_scores_qualify(WEAK, TARGET, "normal")
    assert strategy._rotation_scores_qualify(WEAK, TARGET, "fast")
    strategy._rotation_state = {"channel": "fast"}
    assert strategy._rotation_scores_qualify(WEAK, TARGET)


def test_fast_rotation_quality_requires_a_closed_breakout_and_core_score() -> None:
    closes = [100.0] * 20 + [101.5]
    frame = pd.DataFrame(
        {
            "date": pd.date_range(
                end=pd.Timestamp(NOW) - pd.Timedelta(minutes=15),
                periods=len(closes),
                freq="15min",
            ),
            "close": closes,
            "high": [101.0] * 20 + [102.0],
            "low": [99.0] * 20 + [100.0],
            "volume": [100.0] * 20 + [150.0],
        }
    )
    strategy, _ = _rotation_strategy(held_count=5)
    strategy.__dict__.pop("_fast_rotation_quality")
    strategy._metrics[TARGET].update(
        {
            "taker_ratio": 1.5,
            "taker_ratio_latest": 1.5,
            "_score_valid_until": 1e12,
            "_exit_valid_until": 1e12,
        }
    )
    strategy._candle_metrics = Mock(
        return_value={
            "momentum": 0.03,
            "trend_continuity": 1.0,
            "volume_ratio": 2.0,
            "volume_activity_ratio": 3.0,
            "_candle_valid_until": 1e12,
        }
    )
    strategy._metrics[TARGET]["taker_latest_candle_time"] = frame["date"].iloc[-1].timestamp()
    strategy._closed_candles = Mock(return_value=frame)
    strategy._pair_score_current = Mock(return_value=True)

    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert strategy._fast_rotation_quality(TARGET)

    frame.loc[frame.index[-1], "close"] = 100.5
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert not strategy._fast_rotation_quality(TARGET)


def test_rotation_does_not_use_a_free_slot() -> None:
    strategy, trades = _rotation_strategy(held_count=1, weak_age_minutes=60)
    strategy.settings["max_positions"] = 5

    _plan(strategy, trades, NOW.timestamp())

    assert strategy._rotation_state is None
    assert strategy._rotation_candidate is None
    assert strategy._rotation_seen == 0


def test_same_closed_bar_after_a_score_retry_does_not_add_confirmation() -> None:
    strategy, trades = _rotation_strategy(held_count=5, weak_age_minutes=60)
    bar = NOW.timestamp()
    strategy._rotation_bar.return_value = bar

    _plan(strategy, trades, NOW.timestamp(), NOW)
    assert strategy._rotation_seen == 1
    assert strategy._rotation_candidate == (WEAK, TARGET)

    strategy._last_score_refresh += 30.0
    _plan(strategy, trades, NOW.timestamp() + 30.0, NOW + timedelta(seconds=30))

    assert strategy._rotation_state is None
    assert strategy._rotation_seen == 1
    assert strategy._rotation_candidate == (WEAK, TARGET)


def test_normal_rotation_requires_two_adjacent_closed_bars() -> None:
    strategy, trades = _rotation_strategy(held_count=5, weak_age_minutes=60)
    first_bar = NOW.timestamp() - PERIOD
    strategy._rotation_bar.return_value = first_bar

    _plan(strategy, trades, NOW.timestamp(), NOW)
    assert strategy._rotation_seen == 1
    assert strategy._rotation_state is None

    strategy._last_score_refresh += 900.0
    strategy._rotation_bar.return_value = NOW.timestamp()
    _plan(strategy, trades, NOW.timestamp() + 900.0, NOW + timedelta(minutes=15))

    assert strategy._rotation_state is not None
    assert strategy._rotation_state["channel"] == "normal"
    assert strategy._rotation_state["signal_bar"] == pytest.approx(NOW.timestamp())


def test_normal_confirmation_is_cleared_when_heat_discount_lowers_target_score() -> None:
    strategy, trades = _rotation_strategy(held_count=5, weak_age_minutes=60, target_score=70)
    discounted = {TARGET: 55.0}
    strategy._entry_score = lambda pair: discounted.get(pair, strategy._scores[pair])
    strategy._rotation_bar.return_value = NOW.timestamp() - PERIOD

    _plan(strategy, trades, NOW.timestamp(), NOW)
    assert strategy._rotation_seen == 1

    discounted[TARGET] = 49.0
    strategy._last_score_refresh += 900.0
    strategy._rotation_bar.return_value = NOW.timestamp()
    _plan(strategy, trades, NOW.timestamp() + 900.0, NOW + timedelta(minutes=15))

    assert strategy._rotation_state is None
    assert strategy._rotation_candidate is None
    assert strategy._rotation_seen == 0


def test_fast_rotation_can_replace_a_still_acceptable_old_score() -> None:
    strategy, trades = _rotation_strategy(
        weak_score=55.0,
        target_score=75.0,
        held_count=5,
        weak_age_minutes=20,
        fast_quality=True,
    )
    strategy._last_rotation = NOW.timestamp() - timedelta(minutes=20).total_seconds()

    _plan(strategy, trades, NOW.timestamp(), NOW)

    assert strategy._rotation_state is not None
    assert strategy._rotation_state["channel"] == "fast"
    assert strategy._rotation_state["weak"] == WEAK


def test_fast_rotation_requires_breakout_quality_when_old_score_is_still_high() -> None:
    strategy, trades = _rotation_strategy(
        weak_score=55.0,
        target_score=75.0,
        held_count=5,
        weak_age_minutes=20,
        fast_quality=False,
    )

    _plan(strategy, trades, NOW.timestamp(), NOW)

    assert strategy._rotation_state is None
    assert strategy._rotation_candidate is None
    assert strategy._rotation_seen == 0


def test_fast_and_normal_rotation_have_independent_cooldowns() -> None:
    fast, fast_trades = _rotation_strategy(
        weak_score=55.0,
        target_score=75.0,
        held_count=5,
        weak_age_minutes=20,
        fast_quality=True,
    )
    fast._last_rotation = NOW.timestamp() - timedelta(minutes=20).total_seconds()
    _plan(fast, fast_trades, NOW.timestamp(), NOW)
    assert fast._rotation_state is not None
    assert fast._rotation_state["channel"] == "fast"

    normal, normal_trades = _rotation_strategy(
        weak_score=40.0,
        target_score=65.0,
        held_count=5,
        weak_age_minutes=60,
        fast_quality=False,
    )
    normal._last_rotation = NOW.timestamp() - timedelta(minutes=20).total_seconds()
    _plan(normal, normal_trades, NOW.timestamp(), NOW)
    assert normal._rotation_state is None
    assert normal._rotation_candidate is None
