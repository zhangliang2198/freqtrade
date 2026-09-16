"""Closed-candle weekly volume activity survives a launch without freezing its baseline."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tests.strategy.leader_squeeze_test_helpers import configured_strategy
from tests.strategy.test_leader_squeeze_strategy import MODULE, LeaderSqueezeStrategy


NOW = pd.Timestamp("2026-09-16 12:00:00", tz="UTC")
PAIR = "BTC/USDT:USDT"


def volume_strategy(volumes):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    frame = pd.DataFrame(
        {
            "date": pd.date_range(
                end=NOW - pd.Timedelta(minutes=15), periods=len(volumes), freq="15min"
            ),
            "close": 100.0,
            "volume": volumes,
        }
    )
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=frame))
    return strategy, frame


def metric_and_points(volumes):
    strategy, _ = volume_strategy(volumes)
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        metric = strategy._candle_metrics(PAIR)
    assert metric is not None
    _, volume, _ = strategy._price_components({**metric, "taker_ratio": 1.0})
    return metric, 100 * strategy.settings["weights"]["volume"] * volume


@pytest.mark.parametrize("bars", [3, 12, 22, 48])
def test_weekly_activity_keeps_points_after_launch_volume_moderates(bars):
    metric, points = metric_and_points([100.0] * 700 + [1000.0] + [500.0] * bars)
    assert metric["volume_recent_mean"] == 500
    assert metric["volume_activity_ratio"] >= 3
    assert 10.5 <= points <= 15
    if bars >= 22:
        assert metric["volume_ratio"] <= 1
        assert points == pytest.approx(10.5)


def test_short_and_weekly_baselines_exclude_all_three_signal_candles():
    metric, points = metric_and_points([100.0] * 700 + [500.0] * 3)
    assert metric["volume_short_baseline"] == 100
    assert metric["volume_activity_baseline"] == 100
    assert metric["volume_ratio"] == metric["volume_activity_ratio"] == 5
    assert points == pytest.approx(15)


def test_volume_retreat_removes_activity_points_and_weekly_baseline_eventually_adapts():
    _, faded = metric_and_points([100.0] * 700 + [1000.0] + [500.0] * 48 + [100.0] * 3)
    _, adapted = metric_and_points([100.0] * 700 + [500.0] * 675)
    assert faded == adapted == 0


def test_single_launch_spike_alone_does_not_keep_points_after_leaving_recent_window():
    _, points = metric_and_points([100.0] * 700 + [1000.0] + [100.0] * 3)
    assert points == 0


def test_forming_candle_does_not_change_either_volume_ratio():
    strategy, frame = volume_strategy([100.0] * 700 + [500.0] * 3)
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        before = strategy._candle_metrics(PAIR)
        frame.loc[len(frame)] = [NOW, 100, 1e12]
        assert strategy._candle_metrics(PAIR) == before


def test_missing_weekly_history_cannot_be_scored_using_a_shorter_baseline():
    strategy, _ = volume_strategy([100.0] * 674)
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert strategy._candle_metrics(PAIR) is None


def test_zero_reference_volume_does_not_award_infinite_activity():
    _, points = metric_and_points([0.0] * 700 + [500.0] * 3)
    assert points == 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("volume_activity_weight", -0.1),
        ("volume_activity_weight", 1.1),
        ("volume_activity_full_ratio", 1.0),
        ("volume_activity_baseline_candles", 20),
        ("volume_activity_baseline_candles", 1.5),
    ],
)
def test_invalid_activity_configuration_is_rejected(key, value):
    strategy, _ = volume_strategy([100.0] * 700)
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        strategy._validate_tuning_settings()
        from leader_squeeze_config import validate_runtime_settings

        validate_runtime_settings(strategy)


def test_startup_history_must_cover_weekly_reference_plus_recent_window():
    strategy, _ = volume_strategy([100.0] * 700)
    strategy.startup_candle_count = 674
    with pytest.raises(ValueError, match="volume baselines"):
        from leader_squeeze_config import validate_runtime_settings

        validate_runtime_settings(strategy)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("share", [0.49, 0.50, 0.51])
def test_short_share_filter_is_optional_without_bypassing_other_entry_checks(enabled, share):
    strategy, _ = volume_strategy([100.0] * 700)
    strategy.settings["short_share_filter_enabled"] = enabled
    strategy._pair_score_current = Mock(return_value=True)
    strategy._metrics = {PAIR: {"short_share": share}}
    strategy._candle_metrics = Mock(return_value={"momentum": 0.02, "trend_continuity": 1.0})
    strategy._entry_score = Mock(return_value=80)
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    reason = strategy._entry_quality_reason(PAIR, 50)
    if enabled and share <= 0.5:
        assert "空头占比" in reason
    else:
        assert reason == ""
        strategy._entry_score.return_value = 30
        assert "门槛" in strategy._entry_quality_reason(PAIR, 50)


def test_short_share_filter_requires_boolean_configuration():
    strategy, _ = volume_strategy([100.0] * 700)
    assert strategy.settings["short_share_filter_enabled"] is False
    strategy.settings["short_share_filter_enabled"] = "false"
    with pytest.raises(ValueError, match="short_share_filter_enabled"):
        from leader_squeeze_config import validate_runtime_settings

        validate_runtime_settings(strategy)
