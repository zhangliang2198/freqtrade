"""Real 15m OHLC aggregation and multi-timeframe decision boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tests.strategy.leader_squeeze_test_helpers import configured_strategy
from tests.strategy.test_leader_squeeze_strategy import MODULE, LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"
NOW = pd.Timestamp("2026-01-01 12:00:00", tz="UTC")


def hourly_source(closes=None, *, end=NOW):
    """Repeat hourly OHLC across its four quarters, retaining actual source timestamps."""
    closes = closes or [100.0] * 120
    values = [value for value in closes for _ in range(4)]
    return pd.DataFrame(
        {
            "date": pd.date_range(
                end=end - pd.Timedelta(minutes=15), periods=len(values), freq="15min"
            ),
            "open": values,
            "close": values,
            "high": [value + 1 for value in values],
            "low": [value - 1 for value in values],
            "volume": 100.0,
        }
    )


def strategy_for(frame):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=frame))
    strategy._market_is_down = Mock(return_value=False)
    strategy._rotation_exit_allowed = Mock(return_value=False)
    return strategy


@pytest.fixture(autouse=True)
def fixed_clock():
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        yield


def test_complete_utc_buckets_exclude_both_partial_ends_and_forming_candles():
    frame = hourly_source(end=NOW + pd.Timedelta(minutes=30)).iloc[1:].copy()
    # Last two source candles are still in the future at NOW and must disappear.
    frame.loc[frame.index[-2:], ["close", "high"]] = 10000
    strategy = strategy_for(frame)
    hour = strategy._trend_candles(PAIR, "1h", 25)
    background = strategy._trend_candles(PAIR, "4h", 23)
    assert hour["date"].iloc[-1] == NOW - pd.Timedelta(hours=1)
    assert background["date"].iloc[-1] == NOW - pd.Timedelta(hours=4)
    assert hour["high"].max() == 101
    assert background["volume"].iloc[-1] == 1600
    assert hour["date"].iloc[0].minute == 0
    assert all(call.args[1] == "15m" for call in strategy.dp.get_pair_dataframe.call_args_list)


@pytest.mark.parametrize("defect", ["gap", "stale", "alignment", "nan", "invalid_ohlc"])
def test_bad_source_cannot_become_valid_hourly_data(defect):
    frame = hourly_source()
    if defect == "gap":
        frame = frame.drop(index=60)
    elif defect == "stale":
        frame["date"] -= pd.Timedelta(hours=2)
    elif defect == "alignment":
        frame["date"] -= pd.Timedelta(seconds=1)
    elif defect == "nan":
        frame.loc[60, "close"] = float("nan")
    else:
        frame.loc[60, "high"] = 90
    strategy = strategy_for(frame)
    assert strategy._trend_candles(PAIR, "1h", 25) is None
    assert not strategy._rotation_holding_weak(PAIR)
    assert strategy._higher_entry_reason(PAIR)


def test_15m_pullback_does_not_exit_or_rotate_a_healthy_hourly_trend():
    frame = hourly_source([80 + index * 0.2 for index in range(120)])
    # A 75-minute decline is meaningful on the fast chart, but hourly trend remains intact.
    frame.loc[frame.index[-5:], "close"] = [103.0, 102.9, 102.8, 102.7, 102.6]
    frame["high"] = frame["close"] + 0.25
    frame["low"] = frame["close"] - 0.25
    strategy = strategy_for(frame)
    assert strategy._timeframe_reversed(PAIR, "15m") is True
    assert strategy._trend_reversed(PAIR) is False
    assert strategy._no_new_high(PAIR)
    assert not strategy._rotation_holding_weak(PAIR)
    assert strategy.custom_exit(PAIR, SimpleNamespace(), NOW, 101.6, 0.1) is None


def test_trend_reversal_cache_reuses_closed_candle_and_invalidates_on_correction():
    frame = hourly_source()
    strategy = strategy_for(frame)
    strategy._timeframe_reversed = Mock(wraps=strategy._timeframe_reversed)
    strategy._intrabar_reversed = Mock(wraps=strategy._intrabar_reversed)

    assert strategy._trend_reversed(PAIR) is False
    assert strategy._trend_reversed(PAIR) is False
    assert strategy._timeframe_reversed.call_count == 1
    assert strategy._intrabar_reversed.call_count == 1

    frame.loc[frame.index[-1], ["high", "low", "close"]] = [101.5, 99.5, 100.5]
    assert strategy._trend_reversed(PAIR) is False
    assert strategy._timeframe_reversed.call_count == 2
    assert strategy._intrabar_reversed.call_count == 2


@pytest.mark.parametrize("weak_hours, expected", [(4, False), (5, True)])
def test_five_hour_slow_decline_is_independent_of_support_break(weak_hours, expected):
    closes = [100.0] * 120 + [99.4 - 0.6 * index for index in range(weak_hours)]
    frame = hourly_source(closes)
    # A lower confirmed swing support keeps structural/fast exits out of this test.
    frame.loc[len(frame) - 4 * (weak_hours + 10) : len(frame) - 4 * (weak_hours + 9) - 1, "low"] = (
        90
    )
    strategy = strategy_for(frame)
    assert strategy._trend_reversed(PAIR) is expected
    if expected:
        assert "1h持续走弱" in strategy._trend_exit_details[PAIR]


@pytest.mark.parametrize("boundary", [False, True])
def test_15m_crash_uses_hourly_levels_from_before_signal_even_at_hour_boundary(boundary):
    end = NOW if boundary else NOW + pd.Timedelta(minutes=30)
    frame = hourly_source(end=NOW)
    if not boundary:
        extra = frame.tail(2).copy()
        extra["date"] = [NOW, NOW + pd.Timedelta(minutes=15)]
        frame = pd.concat([frame, extra], ignore_index=True)
    frame.loc[frame.index[-1], ["high", "low", "close"]] = [200, 1, 95]
    strategy = strategy_for(frame)
    with patch.object(MODULE.time, "time", return_value=end.timestamp()):
        assert strategy._trend_reversed(PAIR) is True
    detail = strategy._emergency_exit_details[PAIR]
    assert detail["support"] == 99
    assert detail["atr"] == 2
    assert detail["reference_time"] + pd.Timedelta(hours=1) <= detail["signal_time"]
    assert "15m急跌破位/1h支撑" in strategy._trend_exit_details[PAIR]


def test_unclosed_crash_is_ignored_and_emergency_survives_missed_loop_then_recovers():
    frame = hourly_source()
    extra = frame.tail(1).copy()
    extra["date"] = NOW
    extra[["close", "low"]] = [95, 94]
    frame = pd.concat([frame, extra], ignore_index=True)
    strategy = strategy_for(frame)
    assert strategy._trend_reversed(PAIR) is False
    with patch.object(
        MODULE.time, "time", return_value=(NOW + pd.Timedelta(minutes=15)).timestamp()
    ):
        assert strategy._trend_reversed(PAIR) is True
    # Below the old ordinary threshold but above the acute threshold: preserve previous break.
    recovered = extra.copy()
    recovered["date"] = NOW + pd.Timedelta(minutes=15)
    recovered[["close", "low"]] = [97.5, 97]
    frame = pd.concat([frame, recovered], ignore_index=True)
    strategy.dp.get_pair_dataframe.return_value = frame
    with patch.object(
        MODULE.time, "time", return_value=(NOW + pd.Timedelta(minutes=30)).timestamp()
    ):
        assert strategy._trend_reversed(PAIR) is True
        assert strategy._emergency_exit_details[PAIR]["carried"]
        frame.loc[frame.index[-1], "close"] = 100
        assert strategy._trend_reversed(PAIR) is False


def test_hourly_weakness_is_required_for_rotation_and_recovery_revokes_it():
    frame = hourly_source([100.0] * 120 + [99.5, 99.0, 98.5])
    strategy = strategy_for(frame)
    assert strategy._rotation_holding_weak(PAIR)
    assert strategy._holding_rotation_details[PAIR]["pullback_atr"] >= 0.5
    frame.loc[frame.index[-4:], ["close", "high", "low"]] = [101, 102, 100]
    assert not strategy._rotation_holding_weak(PAIR)


def test_weak_hourly_entry_requires_actual_fast_launch_but_4h_is_observation_only():
    frame = hourly_source([100.0] * 120 + [99.5, 99.0, 98.5])
    strategy = strategy_for(frame)
    strategy._current_score = Mock(return_value=59.99)
    strategy._rotation_floor = Mock(return_value=60.0)
    strategy._fast_rotation_quality = Mock(return_value=True)
    assert strategy._higher_entry_reason(PAIR)
    strategy._current_score.return_value = 60
    assert strategy._higher_entry_reason(PAIR) == ""
    assert strategy._higher_entry_details[PAIR]["fast_exception"]
    strategy._fast_rotation_quality.return_value = False
    assert strategy._higher_entry_reason(PAIR)
    # Sufficient hourly history but insufficient 4h history must not itself block entries.
    strategy = strategy_for(hourly_source([100.0] * 30))
    assert strategy._higher_entry_reason(PAIR) == ""
    assert not strategy._multi_timeframe_snapshot(PAIR)["background"]["available"]


def test_missing_hourly_data_blocks_entry_rotation_but_does_not_disable_market_exit():
    strategy = strategy_for(hourly_source([100.0] * 10))
    assert strategy._trend_reversed(PAIR) is None
    assert strategy._higher_entry_reason(PAIR)
    assert not strategy._rotation_holding_weak(PAIR)
    strategy._market_is_down.return_value = True
    strategy._market_emergency = True
    assert strategy.custom_exit(PAIR, SimpleNamespace(), NOW, 100, -0.1) == "market_emergency"


@pytest.mark.parametrize(
    "key,value",
    [
        ("holding_timeframe", "15m"),
        ("holding_timeframe", "7m"),
        ("background_timeframe", "1h"),
        ("holding_timeframe", "oops"),
        ("trend_slope_candles", 0),
        ("eth_fast_atr_buffer", 0),
        ("eth_cooldown_candles", 0),
        ("eth_cooldown_candles", -1),
        ("eth_cooldown_candles", "8"),
        ("reversal_emergency_memory_candles", True),
        ("reversal_intrabar_atr_buffer", 0.1),
        ("replacement_weak_atr_drop", float("nan")),
    ],
)
def test_invalid_multi_timeframe_configuration_is_rejected(key, value):
    from leader_squeeze_helpers import validate_runtime_settings

    strategy = strategy_for(hourly_source())
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        validate_runtime_settings(strategy)


def test_real_config_covers_aggregation_windows_without_changing_score_weights():
    from leader_squeeze_helpers import validate_runtime_settings

    strategy = strategy_for(hourly_source())
    validate_runtime_settings(strategy)
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy.settings["entry_setup_enabled"] = False
    # Isolate the higher-timeframe history guard from the independent weekly volume guard.
    strategy.settings["volume_activity_baseline_candles"] = 30
    strategy.startup_candle_count = 100
    with pytest.raises(ValueError, match="higher timeframe"):
        validate_runtime_settings(strategy)


def test_pending_rotation_rechecks_real_hourly_weakness_before_buy():
    from tests.strategy.test_leader_squeeze_dual_rotation import (
        TARGET,
        WEAK,
        _rotation_strategy,
    )

    strategy, trades = _rotation_strategy(weak_score=40, target_score=65, fast_quality=True)
    strategy.__dict__.pop("_rotation_holding_weak", None)
    weak_frame = hourly_source([100.0] * 120 + [99.5, 99.0, 98.5])
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=weak_frame))
    strategy._entry_quality_reason = Mock(return_value="")
    strategy._last_rotation = 0
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades):
        strategy._plan_rotation(NOW.timestamp(), NOW)
        assert strategy._rotation_state["weak"] == WEAK
        assert strategy._rotation_state["target"] == TARGET
        assert strategy._rotation_state["channel"] == "fast"
        assert strategy._pending_rotation_reason(NOW.timestamp()) == ""
        weak_frame.loc[weak_frame.index[-4:], ["close", "high", "low"]] = [101, 102, 100]
        assert "小时趋势已恢复" in strategy._pending_rotation_reason(NOW.timestamp())
        strategy._plan_rotation(NOW.timestamp() + 5, NOW)
        assert strategy._rotation_state is None


def test_confirmed_hourly_exit_cannot_be_bypassed_by_a_high_entry_score():
    from tests.strategy.test_leader_squeeze_strategy import _entry_ready_strategy

    frame = hourly_source([100.0] * 120 + [95.0, 95.0])
    strategy = _entry_ready_strategy(NOW.timestamp())
    strategy.__dict__.pop("_trend_reversed", None)
    strategy.__dict__.pop("_higher_entry_reason", None)
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=frame))
    strategy._candle_metrics = Mock(return_value={"momentum": 0.05, "trend_continuity": 1.0})
    strategy._current_score = Mock(return_value=90)
    strategy._fast_rotation_quality = Mock(return_value=True)
    reason = strategy._entry_quality_reason(PAIR, 50)
    assert reason == f"趋势退出: {strategy._trend_exit_rule(PAIR)}, 禁止开仓"
    assert "破位" in reason
    assert "ATR" not in reason
    strategy._fast_rotation_quality.assert_not_called()


def test_audit_snapshot_retains_closed_hourly_and_background_inputs():
    strategy = strategy_for(hourly_source())
    strategy._scores = {PAIR: 65}
    strategy._current_score = Mock(return_value=65)
    strategy._pair_score_current = Mock(return_value=True)
    strategy._entry_heat_metrics = Mock(return_value={"penalty": 0.1})
    strategy._metrics = {}
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        snapshot = strategy._rotation_snapshot()
    mtf = snapshot["pairs"][PAIR]["multi_timeframe"]
    assert mtf["holding"]["timeframe"] == "1h"
    assert mtf["background"]["timeframe"] == "4h"
    assert mtf["holding"]["last_closed_candle"]["date"] == "2026-01-01T11:00:00+00:00"
    assert mtf["background"]["last_closed_candle"]["date"] == "2026-01-01T08:00:00+00:00"
