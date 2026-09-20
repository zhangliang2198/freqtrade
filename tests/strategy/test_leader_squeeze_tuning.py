"""Configurable scales affect the real score, with invalid configurations rejected."""

import copy

import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
)
from tests.strategy.test_leader_squeeze_entry_heat import PAIR, _frame, _heat, _strategy
from tests.strategy.test_leader_squeeze_score_policy import _apply, _metric, _score_strategy


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("volume_score_full_ratio", 3.0, -2.025),
        ("taker_score_full_ratio", 2.0, -5.2),
        ("oi_score_full_drop", 0.06, 0.0),
        ("momentum_return_weight", 0.5, 2.2),
    ],
)
def test_scoring_scale_changes_only_its_expected_contribution(key, value, expected):
    strategy = _score_strategy()
    before = _apply(strategy, {PAIR: _metric()})[PAIR]
    strategy.settings[key] = value
    strategy._validate_tuning_settings()
    after = _apply(strategy, {PAIR: _metric()})[PAIR]
    assert after - before == pytest.approx(expected)


@pytest.mark.parametrize(
    "key,value",
    [
        ("volume_score_full_ratio", 1.0),
        ("taker_score_full_ratio", float("nan")),
        ("momentum_return_weight", 1.1),
        ("entry_heat_box_candles", 0),
        ("entry_heat_ema_candles", 2000),
        ("entry_heat_cooled_breakout_factor", -1),
        ("replacement_fast_enabled", "false"),
        ("replacement_fast_entry_score", 40),
        ("replacement_fast_score_gap", 9),
        ("replacement_fast_core_score", 98),
        ("replacement_weak_bottom_ratio", 0),
        ("replacement_target_top_ratio", 1.1),
        ("replacement_confirmations", 1.5),
        ("replacement_fast_close_location", 2),
        ("replacement_fast_volume_baseline_candles", 1),
        ("replacement_cooldown_minutes", -1),
        ("replacement_fast_min_age_minutes", float("inf")),
    ],
)
def test_invalid_tuning_fails_validation(key, value):
    strategy = _score_strategy()
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        strategy._validate_tuning_settings()


def test_heat_breakout_relief_and_base_fraction_are_configurable():
    strategy = _strategy(_frame("cooled"))
    assert _heat(strategy)["penalty"] == pytest.approx(0.01)
    strategy.settings["entry_heat_cooled_breakout_factor"] = 1
    assert _heat(strategy)["penalty"] == pytest.approx(0.04)
    strategy.settings["entry_heat_base_fraction"] = 0.5
    assert _heat(strategy)["penalty"] == pytest.approx(0.08)


def test_all_public_settings_validate_and_weights_remain_unchanged():
    config = copy.deepcopy(PUBLIC_CONFIG)
    strategy = _score_strategy()
    strategy.config = config
    strategy.settings = config["leader_squeeze"]
    assert strategy.settings == configured_settings()
    strategy._validate_score_settings()
    strategy._validate_entry_heat_settings()
    strategy._validate_reversal_settings()
    strategy._validate_tuning_settings()


@pytest.mark.parametrize(
    "key,value",
    [
        ("entry_risk_base_score", -1),
        ("entry_risk_premium", -1),
        ("entry_risk_per_trade", 0),
        ("entry_risk_per_trade", 0.06),
        ("entry_risk_initial_stop_enabled", "true"),
        ("entry_risk_correlation_weight", -1),
        ("entry_risk_correlation_full_weight", 0),
        ("entry_risk_correlation_unknown", 1.5),
        ("entry_risk_correlation_window", 4),
        ("entry_risk_correlation_min_overlap", 96),
        ("entry_risk_max_gross_ratio", 0),
        ("entry_risk_max_margin_ratio", 1.5),
        ("entry_risk_cluster_correlation", 1.5),
        ("entry_risk_cluster_max_positions", 0),
        ("entry_setup_min_score", 101),
        ("entry_setup_shortlist_ratio", 0),
        ("entry_setup_min_candidates", 0),
        ("entry_setup_enabled", "true"),
        ("entry_setup_score_points", {"launch": 101}),
        (
            "entry_setup_score_points",
            {
                "launch": 40,
                "continuation": 20,
                "extension": 30,
                "compression": 20,
                "proximity": 15,
            },
        ),
    ],
)
def test_invalid_entry_pipeline_configuration_is_rejected(key, value):
    strategy = _score_strategy()
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        strategy._validate_score_settings()


def test_exposure_ceiling_that_cannot_fund_one_position_is_rejected() -> None:
    """A ceiling below a single equal-sized unit would silently stop all trading."""
    strategy = _score_strategy()
    strategy.settings["entry_risk_max_gross_ratio"] = 0.1

    with pytest.raises(ValueError):
        strategy._validate_score_settings()


@pytest.mark.parametrize(
    "key,value",
    [("entry_setup_launch_candles", 0), ("entry_setup_late_extension_atr", 2.0)],
)
def test_invalid_entry_setup_window_is_rejected(key, value):
    strategy = _strategy(_frame("cooled"))
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        strategy._validate_entry_heat_settings()


def test_new_channel_plan_rechecks_breakout_and_full_capacity_before_buy():
    from unittest.mock import Mock, patch

    from tests.strategy.test_leader_squeeze_dual_rotation import (
        MODULE,
        NOW,
        TARGET,
        _plan,
        _rotation_strategy,
    )

    strategy, trades = _rotation_strategy(weak_score=55, target_score=75, fast_quality=True)
    _plan(strategy, trades, NOW.timestamp())
    assert strategy._rotation_state["channel"] == "fast"
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades):
        assert strategy._confirmation_quality_reason(TARGET) == ""
        strategy._fast_rotation_quality = Mock(return_value=False)
        assert "突破" in strategy._confirmation_quality_reason(TARGET)
    strategy._fast_rotation_quality.return_value = True
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades[:-1]):
        assert "仓位数量" in strategy._confirmation_quality_reason(TARGET)
        strategy._plan_rotation(NOW.timestamp(), NOW)
        assert strategy._rotation_state is None


def test_skipped_bar_restarts_confirmation_instead_of_completing_rotation():
    from tests.strategy.test_leader_squeeze_dual_rotation import NOW, _plan, _rotation_strategy

    strategy, trades = _rotation_strategy()
    _plan(strategy, trades, NOW.timestamp())
    strategy._rotation_bar.return_value += 1800
    strategy._last_score_refresh += 1800
    _plan(strategy, trades, NOW.timestamp() + 1800)
    assert strategy._rotation_seen == 1
    assert strategy._rotation_state is None


def test_candidate_hysteresis_keeps_near_equal_challenger_across_bars():
    from tests.strategy.test_leader_squeeze_dual_rotation import (
        NOW,
        TARGET,
        _plan,
        _rotation_strategy,
    )

    strategy, trades = _rotation_strategy(target_score=55)
    _plan(strategy, trades, NOW.timestamp())
    strategy._scores["NEW"] = 57
    strategy._metrics["NEW"] = strategy._metrics[TARGET].copy()
    for index in range(9):
        pair = f"MID-{index}"
        strategy._scores[pair] = 50
        strategy._metrics[pair] = strategy._metrics[TARGET].copy()
    strategy._rotation_bar.return_value += 900
    strategy._last_score_refresh += 900
    _plan(strategy, trades, NOW.timestamp() + 900)
    assert strategy._rotation_state["target"] == TARGET


def test_rotated_out_pair_cannot_reenter_during_persisted_cooldown():
    from unittest.mock import patch

    from tests.strategy.test_leader_squeeze_score_policy import MODULE, _entry_strategy

    strategy = _entry_strategy({PAIR: 90})
    strategy._risk_state = {"rotation_reentry_until": {PAIR: 2e12}}
    with patch.object(MODULE.time, "time", return_value=1e12):
        strategy._pair_score_current = lambda pair: True
        assert "重新买入冷却" in strategy._entry_quality_reason(PAIR, 50)


@pytest.mark.parametrize(
    "failure", [None, "volume", "taker", "close_location", "overshoot", "core", "stale_taker"]
)
def test_fast_breakout_uses_actual_candle_metrics_and_independent_quality_gates(failure):
    from unittest.mock import Mock

    import pandas as pd

    from tests.strategy.test_leader_squeeze_dual_rotation import TARGET, _rotation_strategy

    strategy, _ = _rotation_strategy()
    del strategy._fast_rotation_quality
    del strategy._candle_metrics
    closes = [100.0] * 19 + [97, 98, 99, 100, 101.5]
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-09-01", periods=24, freq="15min", tz="UTC"),
            "close": closes,
            "high": [c + 1 for c in closes[:-1]] + [102],
            "low": [c - 1 for c in closes[:-1]] + [100],
            "volume": [100.0] * 23 + [400],
        }
    )
    strategy._metrics[TARGET]["taker_ratio"] = 0.9
    strategy._metrics[TARGET]["taker_ratio_latest"] = 1.5
    strategy._metrics[TARGET]["taker_latest_candle_time"] = frame["date"].iloc[-1].timestamp()
    strategy._closed_candles = Mock(return_value=frame)
    if failure == "volume":
        frame.loc[23, "volume"] = 149
    elif failure == "taker":
        strategy._metrics[TARGET]["taker_ratio_latest"] = 1.19
    elif failure == "close_location":
        frame.loc[23, "high"] = 104
    elif failure == "overshoot":
        frame.loc[23, ["close", "high"]] = [106, 107]
    elif failure == "stale_taker":
        strategy._metrics[TARGET]["taker_latest_candle_time"] -= 900
    elif failure == "core":
        strategy.settings["momentum_full_score"] = 0.5
        strategy.settings["replacement_fast_core_score"] = 80
    assert strategy._fast_rotation_quality(TARGET) is (failure is None)
