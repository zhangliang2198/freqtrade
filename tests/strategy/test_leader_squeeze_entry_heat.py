"""Fifteen-day heat informs entry shape without changing strength scores."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from freqtrade.enums import CandleType
from tests.conftest import get_patched_exchange
from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
)
from tests.strategy.test_leader_squeeze_strategy import (
    ETH_TEST_NOW as NOW,
)
from tests.strategy.test_leader_squeeze_strategy import (
    MODULE,
    _entry_ready_strategy,
)


PAIR = "BTC/USDT:USDT"


def _frame(kind="extended", first=100.0):
    if kind == "extended":
        closes = [first] * 1360 + [100 + 65 * i / 79 for i in range(80)] + [180.0]
    else:
        closes = [first] * 500 + [179.0] * 940 + [180.0]
    volume = [100.0] * 1441
    if kind == "cooled":
        # Launch detection requires a volume-confirmed close above the box.
        volume[-1] = 200.0
    return pd.DataFrame(
        {
            "date": pd.date_range(end=NOW, periods=1441, freq="15min") - pd.Timedelta(minutes=15),
            "close": closes,
            "high": [value + 0.5 for value in closes],
            "low": [value - 0.5 for value in closes],
            "volume": volume,
        }
    )


def _strategy(frame):
    strategy = _entry_ready_strategy(NOW.timestamp())
    strategy.settings.update(
        {
            key: value
            for key, value in configured_settings().items()
            if key.startswith(("entry_heat_", "entry_setup_"))
        }
    )
    strategy._candidate_pairs = [PAIR]
    strategy._occupied_pairs = Mock(return_value=set())
    strategy.settings["entry_setup_enabled"] = True
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=frame))
    strategy._candle_metrics = Mock(return_value={"momentum": 0.05, "trend_continuity": 1.0})
    strategy._trend_reversed = Mock(return_value=False)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy._rotation_pair = strategy._rotation_target = None
    return strategy


def _heat(strategy):
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        return strategy._entry_heat_metrics(PAIR)


def test_same_fifteen_day_return_can_have_different_entry_shape():
    extended_strategy = _strategy(_frame())
    cooled_strategy = _strategy(_frame("cooled"))
    extended = _heat(extended_strategy)
    cooled = _heat(cooled_strategy)
    assert extended["return_15d"] == cooled["return_15d"] == pytest.approx(0.8)
    assert "penalty" not in extended
    assert cooled["cooled_breakout"] == 1
    assert extended_strategy._current_score(PAIR) == cooled_strategy._current_score(PAIR)
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert extended_strategy._entry_setup_metrics(PAIR)["late"] == 1
        assert cooled_strategy._entry_setup_metrics(PAIR)["stage"] == "启动"


def test_recent_appreciation_is_context_and_does_not_change_current_score():
    strategies = [_strategy(_frame(first=price)) for price in (200.0, 150.0, 100.0, 50.0)]
    returns = [_heat(strategy)["return_15d"] for strategy in strategies]
    scores = [strategy._current_score(PAIR) for strategy in strategies]
    assert returns == sorted(returns)
    assert scores == [90.0] * len(strategies)


def test_breakout_relief_requires_close_above_box_and_no_large_overshoot():
    for close in (179.4, 182.0):
        frame = _frame("cooled")
        frame.loc[1440, ["close", "high", "low"]] = [close, close + 0.5, close - 0.5]
        assert _heat(_strategy(frame))["cooled_breakout"] == 0


def test_single_rebound_after_wide_swing_is_not_consolidation():
    frame = _frame("cooled")
    frame.loc[1425, "low"] = 170.0
    assert _heat(_strategy(frame))["cooled_breakout"] == 0


def test_unclosed_spike_cannot_change_heat_and_signal_spike_cannot_inflate_own_atr():
    frame = _frame()
    strategy = _strategy(frame)
    original = _heat(strategy)
    frame.loc[1440, ["high", "low"]] = [1000.0, 1.0]
    assert _heat(strategy) == original
    frame.loc[1441] = {"date": NOW, "high": 1001.0, "low": 1.0, "close": 1000.0, "volume": 100.0}
    assert _heat(strategy) == original


@pytest.mark.parametrize(
    "fault", ["short", "stale", "gap", "invalid_ohlc", "missing_high", "zero_atr"]
)
def test_invalid_history_blocks_new_entry_but_preserves_holding_score(fault):
    frame = _frame()
    if fault == "short":
        frame = frame.iloc[1:]
    elif fault == "stale":
        frame["date"] -= pd.Timedelta(minutes=16)
    elif fault == "gap":
        frame.loc[1000, "date"] -= pd.Timedelta(minutes=15)
    elif fault == "invalid_ohlc":
        frame.loc[1000, "low"] = 1000.0
    elif fault == "missing_high":
        frame = frame.drop(columns="high")
    else:
        frame.loc[:, ["high", "low", "close"]] = 100.0
    strategy = _strategy(frame)
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._current_score(PAIR) == 90
        assert strategy._select_entries() == set()
        assert "15日行情" in strategy._entry_decisions[PAIR]
        assert not strategy.confirm_trade_entry(PAIR, "market", 1, 180, "GTC", NOW, None, "long")
        assert strategy.custom_exit(PAIR, SimpleNamespace(), NOW, 180, 0.5) is None
    strategy._execution_is_safe.assert_not_called()


def test_raw_strength_ranks_candidates_while_late_chase_gate_still_applies():
    strategy = _strategy(_frame())
    strategy._scores = {PAIR: 46.0, "COOL": 44.0}
    strategy._candidate_pairs = [PAIR, "COOL"]
    strategy._metrics["COOL"] = strategy._metrics[PAIR].copy()
    strategy.dp.get_pair_dataframe.side_effect = lambda pair, timeframe: (
        _frame() if pair == PAIR else _frame("cooled")
    )
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._ranked_pairs()[0][0] == PAIR
        assert strategy._select_entries() == {"COOL"}
        assert "末端过热" in strategy._entry_decisions[PAIR]
        assert not strategy.confirm_trade_entry(PAIR, "market", 1, 180, "GTC", NOW, None, "long")


def test_order_confirmation_rechecks_entry_shape_after_selection():
    frame = _frame("cooled")
    strategy = _strategy(frame)
    strategy._scores[PAIR] = 42.0
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        good = strategy._entry_setup_metrics(PAIR)
    late = {**good, "stage": "末端", "late": 1.0, "extension_atr": 6.0}
    setup_calls = iter((good, late))
    strategy._entry_setup_metrics = Mock(side_effect=lambda pair: next(setup_calls))
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._select_entries() == {PAIR}
        strategy._entry_pairs = {PAIR}
        assert not strategy.confirm_trade_entry(PAIR, "market", 1, 180, "GTC", NOW, None, "long")
        assert "末端过热" in strategy._entry_block_reason
    strategy._execution_is_safe.assert_called_once()


def test_rotation_uses_unmodified_strength_scores():
    strategy = _strategy(_frame())
    strategy._scores = {"OLD": 52.0, PAIR: 70.0}
    strategy._metrics["OLD"] = strategy._metrics[PAIR].copy()
    strategy._candidate_pairs = ["OLD", PAIR]
    strategy._rotation_floor = Mock(return_value=40.0)
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert strategy._current_score("OLD") == 52
        assert not strategy._rotation_scores_qualify("OLD", PAIR)
        strategy._scores.update({"OLD": 44.0, PAIR: 60.0})
        assert strategy._rotation_scores_qualify("OLD", PAIR)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("entry_heat_extension_start_atr", -1),
        ("entry_heat_extension_full_atr", 2),
        ("entry_heat_extension_full_atr", 5),
        ("entry_heat_extension_full_atr", float("nan")),
        ("entry_setup_launch_candles", 0),
        ("entry_setup_breakout_volume_multiple", 11),
        ("entry_setup_late_extension_atr", 1),
    ],
)
def test_invalid_heat_configuration_is_rejected(key, value):
    strategy = _strategy(_frame())
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        strategy._validate_entry_heat_settings()


def test_disabled_setup_does_not_require_long_history():
    strategy = _strategy(pd.DataFrame())
    strategy.settings["entry_setup_enabled"] = False
    assert strategy._entry_setup_metrics(PAIR) == {"stage": "中继", "score": 100.0, "late": 0.0}
    strategy.dp.get_pair_dataframe.assert_not_called()


def test_fifteen_day_return_is_not_a_score_discount():
    strategy = _strategy(_frame())

    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert strategy._current_score(PAIR) == 90
        setup = strategy._entry_setup_metrics(PAIR)

    assert setup is not None
    assert setup["late"] == 1
    assert setup["stage"] == "末端"


@pytest.mark.parametrize(
    ("extension", "cooled_breakout", "allowed", "hard_limit"),
    [
        (5.0, 0.0, False, 5.0),
        (5.0, 1.0, True, 6.0),
        (6.0, 1.0, False, 6.0),
    ],
)
def test_cooled_breakout_uses_separate_hard_extension_limit_for_selection_and_confirmation(
    extension, cooled_breakout, allowed, hard_limit
):
    strategy = _strategy(_frame("cooled"))
    strategy._entry_heat_metrics = Mock(
        return_value={
            "extension_atr": extension,
            "box_width_atr": 1.0,
            "cooled_breakout": cooled_breakout,
            "breakout_age_candles": 0.0 if cooled_breakout else float("nan"),
            "breakout_distance_atr": 0.0 if cooled_breakout else float("nan"),
        }
    )
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        setup = strategy._entry_setup_metrics(PAIR)
        assert setup is not None
        assert setup["hard_limit_atr"] == hard_limit
        assert (strategy._select_entries() == {PAIR}) is allowed
        assert (
            strategy.confirm_trade_entry(PAIR, "market", 1, 180, "GTC", NOW, None, "long")
            is allowed
        )

    if not allowed:
        assert f">= {hard_limit:.1f}ATR" in strategy._entry_block_reason


@pytest.mark.parametrize(("close", "allowed"), [(184.4, True), (185.5, False)])
def test_real_cooled_breakout_detection_reaches_the_relaxed_selection_path(close, allowed):
    frame = _frame("cooled")
    frame.loc[1439, ["close", "high", "low"]] = [180.0, 180.5, 179.5]
    frame.loc[1440, ["close", "high", "low"]] = [close, close + 0.5, close - 0.5]
    frame.loc[1439, "volume"] = 200.0
    strategy = _strategy(frame)

    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        heat = strategy._entry_heat_metrics(PAIR)
        assert heat is not None
        assert heat["cooled_breakout"] == 1.0
        assert (strategy._select_entries() == {PAIR}) is allowed

    if allowed:
        assert 5.0 <= heat["extension_atr"] < 6.0
    else:
        assert heat["extension_atr"] >= 6.0
        assert ">= 6.0ATR" in strategy._entry_decisions[PAIR]


def test_long_history_request_fits_binance_futures_startup_limit(mocker, default_conf):
    default_conf.update({"trading_mode": "futures", "candle_type_def": CandleType.FUTURES})
    exchange = get_patched_exchange(mocker, default_conf, exchange="binance")
    assert exchange.ohlcv_candle_limit("15m", CandleType.FUTURES) == 499
    assert (
        exchange.validate_required_startup_candles(PUBLIC_CONFIG["startup_candle_count"], "15m")
        == 3
    )


def test_short_history_still_allows_existing_position_to_exit_on_a_break():
    frame = _frame().tail(112).copy()
    frame.iloc[:-8, frame.columns.get_indexer(["close", "high", "low"])] = [100.0, 101.0, 99.0]
    frame.iloc[-8:, frame.columns.get_indexer(["close", "high", "low"])] = [95.0, 96.0, 94.0]
    strategy = _strategy(frame)
    strategy.__dict__.pop("_trend_reversed")
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert strategy._entry_heat_metrics(PAIR) is None
        assert strategy.custom_exit(PAIR, SimpleNamespace(), NOW, 95, -0.05) == "trend_reversal"


def test_expired_funding_is_removed_from_the_current_score():
    strategy = _strategy(_frame())
    strategy._metrics[PAIR].update(
        {
            "score_funding": 1.0,
            "funding_rate_hourly": -0.01,
            "funding_floor_hourly": -0.01,
            "_funding_valid_until": NOW.timestamp() + 10,
        }
    )
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        assert strategy._current_score(PAIR) == pytest.approx(90)
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp() + 11):
        assert strategy._current_score(PAIR) == pytest.approx(87)


def test_real_candles_allow_a_healthy_entry_with_heat_enabled():
    frame = _frame("cooled")
    frame.loc[1437:1440, "close"] = [179.0, 179.2, 179.4, 180.0]
    strategy = _strategy(frame)
    strategy.__dict__.pop("_candle_metrics")
    strategy.__dict__.pop("_trend_reversed")
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._entry_heat_metrics(PAIR)["cooled_breakout"] == 1
        assert strategy._select_entries() == {PAIR}
        assert strategy.confirm_trade_entry(PAIR, "market", 1, 180, "GTC", NOW, None, "long")


def test_heat_log_shows_shape_context_without_changing_buy_score(caplog):
    strategy = _strategy(_frame())
    strategy._liquidation_score = Mock(return_value=0.5)
    strategy._market_id = lambda pair: pair
    metric = {
        **strategy._metrics[PAIR],
        "volume_ratio": 2.0,
        "volume_activity_ratio": 3.0,
        "taker_ratio": 1.5,
        "taker_ratio_latest": 1.5,
        "oi_change": -0.01,
    }
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        caplog.at_level("INFO", logger="leader_squeeze_strategy"),
    ):
        strategy._apply_scores(NOW.timestamp(), {PAIR: metric}, {PAIR: metric})
        strategy._consume_score_report(report_now=NOW.timestamp())
    score_table = next(
        record.strategy_log_table
        for record in caplog.records
        if "评分综合明细" in record.getMessage()
    )
    heat_cell = score_table.columns[5]._cells[0].plain
    assert "+80.0%" in heat_cell
    assert "偏" in heat_cell
    assert "形" in heat_cell
    assert "折" not in heat_cell
    assert float(score_table.columns[2]._cells[0].plain) == pytest.approx(
        strategy._scores[PAIR], abs=0.05
    )


def test_setup_remains_visible_and_fifteen_day_return_does_not_discount_score(caplog):
    strategy = _strategy(_frame("cooled"))
    strategy._liquidation_score = Mock(return_value=0.5)
    strategy._market_id = lambda pair: pair
    metric = {
        **strategy._metrics[PAIR],
        "volume_ratio": 2.0,
        "volume_activity_ratio": 3.0,
        "taker_ratio": 1.5,
        "taker_ratio_latest": 1.5,
        "oi_change": -0.01,
    }

    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        caplog.at_level("INFO", logger="leader_squeeze_strategy"),
    ):
        strategy._apply_scores(NOW.timestamp(), {PAIR: metric}, {PAIR: metric})
        strategy._consume_score_report(report_now=NOW.timestamp())

    score_table = next(
        record.strategy_log_table
        for record in caplog.records
        if "评分综合明细" in record.getMessage()
    )
    heat_cell = score_table.columns[5]._cells[0].plain
    assert "形" in heat_cell
    assert "折" not in heat_cell
    assert float(score_table.columns[2]._cells[0].plain) == pytest.approx(
        strategy._scores[PAIR], abs=0.05
    )


def test_disabled_setup_is_reported_as_disabled_instead_of_fake_score(caplog):
    strategy = _strategy(_frame())
    strategy.settings["entry_setup_enabled"] = False
    strategy._liquidation_score = Mock(return_value=0.5)
    strategy._market_id = lambda pair: pair
    metric = {
        **strategy._metrics[PAIR],
        "volume_ratio": 2.0,
        "volume_activity_ratio": 3.0,
        "taker_ratio": 1.5,
        "taker_ratio_latest": 1.5,
        "oi_change": -0.01,
    }

    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        caplog.at_level("INFO", logger="leader_squeeze_strategy"),
    ):
        strategy._apply_scores(NOW.timestamp(), {PAIR: metric}, {PAIR: metric})
        strategy._consume_score_report(report_now=NOW.timestamp())

    score_table = next(
        record.strategy_log_table
        for record in caplog.records
        if "评分综合明细" in record.getMessage()
    )
    heat_cell = score_table.columns[5]._cells[0].plain
    assert heat_cell == "—/关闭"
    assert "形中继100" not in heat_cell
