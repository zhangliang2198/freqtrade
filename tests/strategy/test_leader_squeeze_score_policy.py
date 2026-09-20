"""Regression tests for the absolute score and entry policy."""

from __future__ import annotations

import copy
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)
from tests.strategy.test_leader_squeeze_strategy import (
    ETH_TEST_NOW,
    MODULE,
    LeaderSqueezeStrategy,
    _entry_ready_strategy,
    _eth_frame,
)


PAIR = "PAIR/USDT:USDT"
WEAK = "WEAK/USDT:USDT"
TARGET = "TARGET/USDT:USDT"


def _score_strategy() -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = {
        **configured_settings(),
        "weights": configured_settings()["weights"].copy(),
    }
    # Score-policy tests assert the pre-existing component arithmetic.  Heat
    # aware entry tests supply a complete 15-day history explicitly.
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy._market_id = lambda pair: pair
    strategy._liquidation_score = lambda symbol, now: 0.0
    return strategy


def _metric(
    *,
    momentum: float = 0.015,
    trend_continuity: float = 2 / 3,
    volume_ratio: float = 1.5,
    volume_activity_ratio: float | None = None,
    taker_ratio: float = 1.2,
    oi_change: float = -0.01,
) -> dict[str, float]:
    # Keep the historical score fixtures equivalent after volume is split into
    # short-term burst and longer-term activity components.
    if volume_activity_ratio is None:
        volume_activity_ratio = 1 + 2 * (volume_ratio - 1)
    return {
        "momentum": momentum,
        "trend_continuity": trend_continuity,
        "volume_ratio": volume_ratio,
        "volume_activity_ratio": volume_activity_ratio,
        "taker_ratio": taker_ratio,
        "taker_ratio_latest": taker_ratio,
        "oi_change": oi_change,
        "_score_valid_until": 1e12,
        "_exit_valid_until": 1e12,
    }


def _apply(
    strategy: LeaderSqueezeStrategy,
    metrics: dict[str, dict[str, float]],
) -> dict[str, float]:
    valid = {pair: item.copy() for pair, item in metrics.items()}
    all_metrics = {pair: item.copy() for pair, item in metrics.items()}
    strategy._apply_scores(1_000.0, valid, all_metrics)
    return strategy._scores


@pytest.mark.parametrize("extra_momentum", [0.30, -0.20])
def test_absolute_momentum_score_is_invariant_to_candidate_extrema(extra_momentum: float) -> None:
    base = _metric(momentum=0.015)
    strategy = _score_strategy()
    before = _apply(strategy, {PAIR: base, "REFERENCE": _metric(momentum=0.01)})[PAIR]

    after = _apply(
        strategy,
        {
            PAIR: base,
            "REFERENCE": _metric(momentum=0.01),
            "EXTREME": _metric(momentum=extra_momentum),
        },
    )[PAIR]

    assert after == pytest.approx(before)


def test_score_weights_prioritize_direct_price_volume_and_buying_evidence() -> None:
    strategy = _score_strategy()
    weights = strategy.settings["weights"]
    assert weights["momentum"] == pytest.approx(0.44)
    assert weights["funding"] == pytest.approx(0.03)
    assert weights["volume"] == pytest.approx(0.27)
    assert weights["taker_buy"] == pytest.approx(0.26)
    assert weights["oi_squeeze"] == pytest.approx(0.0)
    assert "adl_risk" not in weights
    assert len(weights) == 6
    assert sum(weights.values()) == pytest.approx(1.0)
    score = _apply(strategy, {PAIR: _metric()})[PAIR]

    assert score == pytest.approx(47.3666666667)


def test_oi_change_does_not_affect_score_when_component_is_disabled() -> None:
    strategy = _score_strategy()
    rising = _metric(momentum=0.01, oi_change=-0.03)
    unchanged_oi = _metric(momentum=0.01, oi_change=0.0)

    rising_score = _apply(strategy, {PAIR: rising})[PAIR]
    unchanged_oi_score = _apply(strategy, {PAIR: unchanged_oi})[PAIR]

    assert rising_score == pytest.approx(unchanged_oi_score)


def test_strong_price_volume_and_taker_buy_score_without_oi_drop() -> None:
    strategy = _score_strategy()

    score = _apply(
        strategy,
        {
            PAIR: _metric(
                momentum=0.03,
                trend_continuity=1.0,
                volume_ratio=2.0,
                taker_ratio=1.5,
                oi_change=0.0,
            )
        },
    )[PAIR]

    assert score == pytest.approx(97.0)


def test_stronger_price_volume_and_buying_score() -> None:
    strategy = _score_strategy()
    score = _apply(
        strategy,
        {
            PAIR: _metric(momentum=0.02, volume_ratio=1.8, taker_ratio=1.3),
        },
    )[PAIR]

    assert score == pytest.approx(66.5333333333)


def test_oi_squeeze_requires_positive_price_momentum() -> None:
    strategy = _score_strategy()
    weak_score = _apply(strategy, {PAIR: _metric(momentum=0.0, oi_change=-0.03)})[PAIR]
    no_oi_score = _apply(strategy, {PAIR: _metric(momentum=0.0, oi_change=0.0)})[PAIR]

    assert weak_score == pytest.approx(no_oi_score)
    assert weak_score < float(strategy.settings["entry_slot_score_thresholds"][0])


def test_missing_funding_data_defaults_to_zero_and_does_not_block_entry() -> None:
    strategy = _entry_strategy({PAIR: 41.4})

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {PAIR}


def _entry_strategy(scores: dict[str, float]) -> LeaderSqueezeStrategy:
    now = time.time()
    strategy = _entry_ready_strategy(now)
    strategy._scores = scores
    strategy._metrics = {pair: _metric() for pair in scores}
    strategy._score_leaders = list(scores)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy.settings["max_positions"] = 10
    return strategy


@pytest.mark.parametrize(
    "override",
    [
        {"momentum": 0.0},
        {"trend_continuity": 1 / 3},
    ],
)
def test_low_intensity_hard_gates_reject_even_a_100_point_candidate(override) -> None:
    strategy = _entry_strategy({PAIR: 100.0})
    strategy._metrics[PAIR].update(override)

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == set()


@pytest.mark.parametrize("slot_index", range(10))
def test_each_position_uses_its_configured_incremental_strength_floor(slot_index: int) -> None:
    thresholds = configured_settings()["entry_slot_score_thresholds"]
    floor = float(thresholds[slot_index])
    pair = f"SLOT-{slot_index}"
    held = [SimpleNamespace(pair=f"HELD-{index}") for index in range(slot_index)]
    strategy = _entry_strategy({pair: floor})

    with patch.object(MODULE.Trade, "get_open_trades", return_value=held):
        assert strategy._select_entries() == {pair}
        assert strategy._entry_slot_assignments[pair] == slot_index

    strategy = _entry_strategy({pair: floor - 0.01})
    with patch.object(MODULE.Trade, "get_open_trades", return_value=held):
        assert strategy._select_entries() == set()
    assert f"第{slot_index + 1}仓门槛" in strategy._entry_decisions[pair]


def _rotation_strategy(weak_score: float, target_score: float) -> LeaderSqueezeStrategy:
    now = ETH_TEST_NOW.timestamp() + 3_600
    strategy = _entry_strategy({WEAK: weak_score, TARGET: target_score})
    strategy._last_good_data = now
    strategy._last_score_refresh = 1_000.0
    strategy._rotation_score_snapshot = 0.0
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._rotation_state = None
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy._last_rotation = 0.0
    strategy._position_first_seen = {}
    strategy._rotation_holding_weak = Mock(return_value=True)
    strategy._persist_rotation = Mock(return_value=True)
    strategy.settings["replacement_cooldown_minutes"] = 0
    strategy.settings["replacement_min_age_minutes"] = 30
    strategy.settings["replacement_fast_enabled"] = False
    strategy.settings["max_positions"] = 1
    strategy._rotation_bar = Mock(return_value=ETH_TEST_NOW.timestamp() - 900)
    return strategy


@pytest.mark.parametrize(
    ("weak_score", "target_score", "qualifies"),
    [(40.0, 49.0, False), (41.0, 50.0, False), (40.0, 50.0, True)],
)
def test_rotation_target_uses_50_floor_and_10_point_score_gap(
    weak_score: float, target_score: float, qualifies: bool
) -> None:
    strategy = _rotation_strategy(weak_score, target_score)
    current_time = ETH_TEST_NOW
    weak_trade = SimpleNamespace(
        pair=WEAK,
        is_short=False,
        open_date_utc=current_time - timedelta(hours=1),
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak_trade]):
        strategy._plan_rotation(ETH_TEST_NOW.timestamp() + 3_600, current_time)

    assert (strategy._rotation_candidate == (WEAK, TARGET)) is qualifies


def test_eth_downtrend_blocks_select_confirm_and_rotation_even_at_100_points() -> None:
    now = ETH_TEST_NOW.timestamp()
    strategy = _entry_strategy({PAIR: 100.0})
    eth_frame = _eth_frame([100.0] * 20 + [99.0, 98.0])
    strategy.dp = SimpleNamespace(
        get_pair_dataframe=lambda pair, timeframe: eth_frame,
        current_whitelist=lambda: [PAIR],
    )
    strategy._eth_entries_allowed = LeaderSqueezeStrategy._eth_entries_allowed.__get__(strategy)

    with patch.object(MODULE.time, "time", return_value=now):
        with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
            assert strategy._select_entries() == set()
        assert not strategy.confirm_trade_entry(
            pair=PAIR,
            order_type="market",
            amount=1.0,
            rate=100.0,
            time_in_force="GTC",
            current_time=ETH_TEST_NOW,
            entry_tag=None,
            side="long",
        )

        strategy._rotation_pair = WEAK
        strategy._rotation_target = TARGET
        strategy._rotation_candidate = (WEAK, TARGET)
        strategy._rotation_seen = 1
        strategy._last_score_refresh = now
        strategy._plan_rotation(now, ETH_TEST_NOW)

    assert PAIR not in strategy._entry_pairs
    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None
    assert strategy._rotation_candidate is None
    assert strategy._rotation_seen == 0


def test_rotation_does_not_fall_back_when_bottom_ranked_holding_is_too_young() -> None:
    strategy = _rotation_strategy(40.0, 60.0)
    strategy.settings["max_positions"] = 2
    strategy._scores.update({"YOUNG": 20.0, "UNSAFE": 90.0})
    strategy._metrics.update({"YOUNG": _metric(), "UNSAFE": _metric()})
    strategy._execution_is_safe = Mock(side_effect=lambda pair: pair != "UNSAFE")
    trades = [
        SimpleNamespace(
            id=1, pair=WEAK, is_short=False, open_date_utc=ETH_TEST_NOW - timedelta(hours=1)
        ),
        SimpleNamespace(id=2, pair="YOUNG", is_short=False, open_date_utc=ETH_TEST_NOW),
    ]
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades):
        strategy._plan_rotation(ETH_TEST_NOW.timestamp() + 3600, ETH_TEST_NOW)
    assert strategy._rotation_candidate is None
    strategy._execution_is_safe.assert_not_called()


def test_unsubmitted_rotation_is_cancelled_when_score_gap_disappears() -> None:
    strategy = _rotation_strategy(40.0, 60.0)
    strategy._rotation_pair, strategy._rotation_target = WEAK, TARGET
    strategy._rotation_state = {"weak": WEAK, "target": TARGET, "phase": "buy"}
    strategy._scores[WEAK], strategy._scores[TARGET] = 45.0, 51.0
    strategy._plan_rotation(ETH_TEST_NOW.timestamp() + 3600, ETH_TEST_NOW)
    assert strategy._rotation_target is None
    assert strategy._rotation_pair is None
    strategy._persist_rotation.assert_called_once()


@pytest.mark.parametrize("held_count,allowed", [(0, True), (1, True), (10, False)])
def test_confirmation_checks_actual_position_count_after_funding_expires(held_count, allowed):
    strategy = _entry_strategy({PAIR: 46.0})
    strategy._metrics[PAIR].update(
        {
            "score_funding": 1.0,
            "funding_rate_hourly": -0.01,
            "funding_floor_hourly": -0.01,
            "_funding_valid_until": time.time() - 1,
        }
    )
    strategy._entry_pairs = {PAIR}
    trades = [SimpleNamespace(pair=f"HELD-{n}") for n in range(held_count)]
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades):
        assert (
            strategy.confirm_trade_entry(
                PAIR, "market", 1.0, 100.0, "GTC", ETH_TEST_NOW, None, "long"
            )
            is allowed
        )
    if not allowed:
        assert "43.0 < 门槛 54.0" in strategy._entry_block_reason
        strategy._execution_is_safe.assert_not_called()


@pytest.mark.parametrize(
    "flag,value",
    [
        ("_market_down", True),
        ("_risk_state_load_failed", True),
        ("_risk_state_save_failed", True),
        ("_position_data_healthy", False),
        ("_data_healthy", False),
    ],
)
def test_global_risk_gates_cannot_be_bypassed_by_a_high_score(flag, value):
    strategy = _entry_strategy({PAIR: 100.0})
    strategy._entry_pairs = {PAIR}
    setattr(strategy, flag, value)
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == set()
        assert not strategy.confirm_trade_entry(
            PAIR, "market", 1.0, 100.0, "GTC", ETH_TEST_NOW, None, "long"
        )
    strategy._execution_is_safe.assert_not_called()


def test_public_config_matches_strategy_policy_and_keeps_margin_and_risk_limits():
    config = copy.deepcopy(PUBLIC_CONFIG)
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = config
    strategy.settings = {**configured_settings(), **config["leader_squeeze"]}
    strategy._validate_score_settings()
    for key in (
        "entry_slot_score_thresholds",
        "entry_setup_min_score",
        "min_trend_continuity",
        "momentum_full_score",
        "liquidation_min_notional",
        "replacement_score_gap",
        "weights",
    ):
        assert config["leader_squeeze"][key] == configured_settings()[key]
    assert config["margin_mode"] == "cross"
    assert config["max_open_trades"] == 11
    assert strategy.settings["max_positions"] == 10
    assert strategy.settings["stake_ratio"] == 0.08
    assert strategy.settings["leverage"] == 5.0
    assert "max_drawdown_limit" not in strategy.settings
