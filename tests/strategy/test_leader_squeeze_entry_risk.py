"""Entry risk budget: the strength floor is derived from portfolio risk, not slot ordinal.

The policy under test replaces a hand-tuned per-slot ladder with two independent
controls:

* a **hard** correlation-adjusted exposure ceiling, and
* a **soft** score floor that rises with the share of that ceiling the
  prospective entry would consume.

The floor must depend on how *correlated* a candidate is with the book, so a
clone of the existing holdings is charged more than an independent name.
"""

from __future__ import annotations

import importlib
import math
from datetime import UTC, datetime

import pytest

from tests.strategy.leader_squeeze_test_helpers import configured_settings


MODULE = importlib.import_module("leader_squeeze_helpers")

BASE = 40.0
PREMIUM = 14.0
WEIGHT = 0.5
MAX_POSITIONS = 10
FULL_WEIGHT = 0.75


def _floor(position_count: int, concentration: float) -> float:
    utilization = MODULE.entry_risk_utilization(
        position_count,
        MAX_POSITIONS,
        concentration,
        correlation_weight=WEIGHT,
    )
    return MODULE.entry_risk_score_floor(
        base_score=BASE,
        premium=PREMIUM,
        utilization=utilization,
    )


def test_first_position_pays_only_the_base_score() -> None:
    assert _floor(1, 0.0) == pytest.approx(BASE)


def test_floor_rises_monotonically_with_position_count() -> None:
    floors = [_floor(count, 0.0) for count in range(1, MAX_POSITIONS + 1)]

    assert floors == sorted(floors)
    assert floors[0] == pytest.approx(BASE)
    assert floors[-1] < BASE + PREMIUM


def test_a_full_uncorrelated_book_never_reaches_the_maximum_floor() -> None:
    # Diversification is real risk reduction, so the bar must stay below the
    # fully-concentrated maximum even at the last slot.
    assert _floor(MAX_POSITIONS, 0.0) == pytest.approx(BASE + PREMIUM * (1 / 1.5))


def test_a_full_correlated_book_pays_the_maximum_floor() -> None:
    assert _floor(MAX_POSITIONS, 1.0) == pytest.approx(BASE + PREMIUM)


def test_a_correlated_candidate_is_charged_more_than_an_independent_one() -> None:
    independent = _floor(5, 0.0)
    correlated = _floor(5, 1.0)

    assert correlated > independent


def test_concentration_normalises_by_the_full_weight_correlation() -> None:
    assert MODULE.entry_risk_concentration(
        [FULL_WEIGHT], full_weight=FULL_WEIGHT, unknown=1.0
    ) == pytest.approx(1.0)
    assert MODULE.entry_risk_concentration(
        [FULL_WEIGHT / 2], full_weight=FULL_WEIGHT, unknown=1.0
    ) == pytest.approx(0.5)


def test_an_empty_book_has_nothing_to_be_concentrated_with() -> None:
    assert MODULE.entry_risk_concentration([], full_weight=FULL_WEIGHT, unknown=1.0) == 0.0


def test_negative_correlation_is_not_rewarded_below_zero() -> None:
    assert MODULE.entry_risk_concentration([-0.9], full_weight=FULL_WEIGHT, unknown=1.0) == 0.0


def test_unusable_correlation_data_falls_back_to_the_conservative_value() -> None:
    assert MODULE.entry_risk_concentration(
        [math.nan, math.inf], full_weight=FULL_WEIGHT, unknown=1.0
    ) == pytest.approx(1.0)


def test_each_unusable_correlation_is_charged_conservatively() -> None:
    assert MODULE.entry_risk_concentration(
        [0.0, math.nan], full_weight=FULL_WEIGHT, unknown=1.0
    ) == pytest.approx(2 / 3)


def test_utilization_is_bounded_for_out_of_range_inputs() -> None:
    over = MODULE.entry_risk_utilization(99, MAX_POSITIONS, 5.0, correlation_weight=WEIGHT)
    under = MODULE.entry_risk_utilization(0, MAX_POSITIONS, -5.0, correlation_weight=WEIGHT)

    assert over == pytest.approx(1.0)
    assert under == pytest.approx(0.0)


def test_stake_amount_targets_fixed_loss_and_respects_the_margin_cap() -> None:
    risk_sized = MODULE.entry_risk_stake_amount(
        capital=1_000,
        max_stake_ratio=0.08,
        risk_ratio=0.01,
        stop_fraction=0.04,
        leverage=5,
    )
    capped = MODULE.entry_risk_stake_amount(
        capital=1_000,
        max_stake_ratio=0.08,
        risk_ratio=0.01,
        stop_fraction=0.01,
        leverage=5,
    )

    assert risk_sized == pytest.approx(50.0)
    assert risk_sized * 5 * 0.04 == pytest.approx(10.0)
    assert capped == pytest.approx(80.0)


def test_cluster_size_counts_the_candidate_plus_its_correlated_holdings() -> None:
    assert MODULE.entry_risk_cluster_size([0.9, 0.86, 0.2], threshold=0.85) == 3
    assert MODULE.entry_risk_cluster_size([], threshold=0.85) == 1
    assert MODULE.entry_risk_cluster_size([math.nan, 0.9], threshold=0.85) == 2


def test_exposure_reason_is_silent_inside_the_ceiling() -> None:
    assert (
        MODULE.entry_risk_exposure_reason(
            capital=1_000,
            open_margin=720,
            open_gross=3_600,
            pending_margin=80,
            pending_gross=400,
            max_gross_ratio=4.4,
            max_margin_ratio=0.88,
        )
        == ""
    )


def test_exposure_reason_reports_the_breached_ceiling() -> None:
    reason = MODULE.entry_risk_exposure_reason(
        capital=1_000,
        open_margin=800,
        open_gross=4_000,
        pending_margin=80,
        pending_gross=400,
        max_gross_ratio=4.0,
        max_margin_ratio=0.88,
    )

    assert "名义敞口" in reason

    margin_reason = MODULE.entry_risk_exposure_reason(
        capital=1_000,
        open_margin=800,
        open_gross=4_000,
        pending_margin=80,
        pending_gross=400,
        max_gross_ratio=10.0,
        max_margin_ratio=0.8,
    )
    assert "保证金" in margin_reason


def _closes(returns: list[float], start: float = 100.0) -> list[float]:
    closes = [start]
    for value in returns:
        closes.append(closes[-1] * (1.0 + value))
    return closes


# A held book that oscillates, a clone that tracks it exactly, and a name whose
# returns are exactly uncorrelated with it.
_OSCILLATING = [0.01, -0.01] * 48
_UNCORRELATED = [0.01, -0.01, -0.01, 0.01] * 24
assert len(_UNCORRELATED) == len(_OSCILLATING)


def test_correlation_is_one_for_identical_return_series() -> None:
    series = _closes(_OSCILLATING)

    assert MODULE.entry_risk_correlation(series, series, min_overlap=8) == pytest.approx(1.0)


def test_correlation_is_zero_for_independent_return_series() -> None:
    correlation = MODULE.entry_risk_correlation(
        _closes(_OSCILLATING), _closes(_UNCORRELATED), min_overlap=8
    )

    assert correlation == pytest.approx(0.0, abs=1e-9)


def test_correlation_is_unavailable_without_enough_overlap() -> None:
    assert math.isnan(MODULE.entry_risk_correlation([1.0, 2.0], [1.0, 3.0], min_overlap=8))


def test_correlation_is_unavailable_for_a_flat_series() -> None:
    flat = [100.0] * 20

    assert math.isnan(MODULE.entry_risk_correlation(flat, _closes(_OSCILLATING), min_overlap=8))


# --- Behaviour at the entry-selection seam -----------------------------------

from types import SimpleNamespace  # noqa: E402
from unittest.mock import Mock, patch  # noqa: E402

import pandas as pd  # noqa: E402

from tests.strategy.test_leader_squeeze_score_policy import (  # noqa: E402
    _entry_strategy,
    _metric,
)
from tests.strategy.test_leader_squeeze_strategy import MODULE as STRATEGY_MODULE  # noqa: E402


HELD = "HELD/USDT:USDT"
CLONE = "CLONE/USDT:USDT"
CLONE2 = "CLONE2/USDT:USDT"
FREE = "FREE/USDT:USDT"
SERIES = {
    HELD: _closes(_OSCILLATING),
    CLONE: _closes(_OSCILLATING),
    CLONE2: _closes(_OSCILLATING),
    FREE: _closes(_UNCORRELATED),
}
SERIES_DATES = pd.date_range("2026-09-01", periods=len(SERIES[HELD]), freq="15min", tz="UTC")
# 41.2 clears the independent floor (40 + 14/9/1.5) but not the fully
# correlated one (40 + 14/9) at the second position.
BETWEEN_FLOORS = 41.2


def _risk_strategy(scores: dict[str, float], held: tuple[str, ...] = ()) -> object:
    strategy = _entry_strategy(scores)
    for pair in set(scores) | set(held):
        strategy._metrics.setdefault(pair, _metric())
    strategy._closed_candles = Mock(
        side_effect=lambda pair, timeframe, count, **kwargs: pd.DataFrame(
            {"date": SERIES_DATES[-count:], "close": SERIES[pair][-count:]}
        )
    )
    return strategy


def _held_trades(pairs: tuple[str, ...]) -> list[SimpleNamespace]:
    return [SimpleNamespace(pair=pair) for pair in pairs]


def test_a_candidate_correlated_with_holdings_needs_a_higher_score() -> None:
    clone = _risk_strategy({CLONE: BETWEEN_FLOORS}, held=(HELD,))
    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        assert clone._select_entries() == set()
    assert "风险门槛" in clone._entry_decisions[CLONE]

    free = _risk_strategy({FREE: BETWEEN_FLOORS}, held=(HELD,))
    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        assert free._select_entries() == {FREE}


def test_unavailable_correlation_data_is_charged_conservatively() -> None:
    strategy = _risk_strategy({CLONE: BETWEEN_FLOORS}, held=(HELD,))
    strategy._closed_candles = Mock(return_value=None)

    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        assert strategy._select_entries() == set()


def test_partly_unavailable_correlation_cannot_bypass_the_cluster_limit() -> None:
    strategy = _risk_strategy({CLONE2: 100.0}, held=(HELD, CLONE))
    strategy._entry_risk_correlations = Mock(return_value=[0.0, math.nan])
    strategy.settings["entry_risk_cluster_max_positions"] = 1

    with patch.object(
        STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD, CLONE))
    ):
        assert strategy._select_entries() == set()

    assert "相关簇" in strategy._entry_decisions[CLONE2]


def test_correlation_uses_matching_candle_timestamps() -> None:
    strategy = _risk_strategy({CLONE: 100.0}, held=(HELD,))
    start = datetime(2026, 9, 1, tzinfo=UTC)
    candidate_dates = pd.date_range(start + pd.Timedelta(minutes=15), periods=4, freq="15min")
    holding_dates = pd.date_range(start, periods=4, freq="15min")
    strategy.settings["entry_risk_correlation_min_overlap"] = 2
    strategy._entry_close_series = Mock(
        side_effect={
            CLONE: dict(zip(candidate_dates, [200.0, 100.0, 200.0, 100.0], strict=True)),
            HELD: dict(zip(holding_dates, [100.0, 200.0, 100.0, 200.0], strict=True)),
        }.get
    )

    correlations = strategy._entry_risk_correlations(
        CLONE,
        [HELD],
        {HELD: strategy._entry_close_series(HELD)},
    )

    assert correlations == pytest.approx([1.0])


def test_the_selected_floor_is_recorded_for_the_confirmation_recheck() -> None:
    strategy = _risk_strategy({FREE: 60.0}, held=(HELD,))

    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        assert strategy._select_entries() == {FREE}

    independent_floor = _floor(2, 0.0)
    assert strategy._entry_risk_floor_assignments[FREE] == pytest.approx(independent_floor)


def test_the_gross_exposure_ceiling_blocks_an_otherwise_strong_entry() -> None:
    strategy = _risk_strategy({FREE: 100.0}, held=(HELD,))
    strategy.settings["entry_risk_max_gross_ratio"] = 0.4

    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        assert strategy._select_entries() == set()

    assert "名义敞口" in strategy._entry_decisions[FREE]


def test_the_margin_ceiling_blocks_an_otherwise_strong_entry() -> None:
    strategy = _risk_strategy({FREE: 100.0}, held=(HELD,))
    strategy.settings["entry_risk_max_gross_ratio"] = 10.0
    strategy.settings["entry_risk_max_margin_ratio"] = 0.1

    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        assert strategy._select_entries() == set()

    assert "保证金" in strategy._entry_decisions[FREE]


def test_actual_oversized_position_is_used_by_the_exposure_ceiling() -> None:
    strategy = _risk_strategy({FREE: 100.0}, held=(HELD,))
    strategy.settings["entry_risk_max_gross_ratio"] = 2.8
    strategy.settings["entry_risk_max_margin_ratio"] = 0.9
    strategy.wallets = SimpleNamespace(
        get_total_stake_amount=lambda: 1_000.0,
        get_all_positions=lambda: {
            HELD: SimpleNamespace(collateral=500.0, position=25.0, leverage=5.0)
        },
    )
    strategy._position_details = {HELD: {"notional": 2_500.0}}

    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        assert strategy._select_entries() == set()

    assert "名义敞口" in strategy._entry_decisions[FREE]


def test_a_correlated_cluster_ceiling_blocks_one_more_clone() -> None:
    strategy = _risk_strategy({CLONE2: 100.0}, held=(HELD, CLONE))
    strategy.settings["entry_risk_cluster_max_positions"] = 2

    with patch.object(
        STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD, CLONE))
    ):
        assert strategy._select_entries() == set()

    assert "相关簇" in strategy._entry_decisions[CLONE2]


def test_an_independent_candidate_is_unaffected_by_the_cluster_ceiling() -> None:
    strategy = _risk_strategy({FREE: 100.0}, held=(HELD, CLONE))
    strategy.settings["entry_risk_cluster_max_positions"] = 2

    with patch.object(
        STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD, CLONE))
    ):
        assert strategy._select_entries() == {FREE}


def test_pairs_selected_earlier_in_the_same_round_are_measured_against_each_other() -> None:
    """An empty book plus two co-moving names must not read as free diversification."""
    strategy = _risk_strategy({"OSC-A": 100.0, "OSC-B": 90.0}, held=())
    strategy._closed_candles = Mock(
        side_effect=lambda pair, timeframe, count, **kwargs: pd.DataFrame(
            {"date": SERIES_DATES[-count:], "close": _closes(_OSCILLATING)[-count:]}
        )
    )
    strategy.settings["entry_risk_base_score"] = 40.0
    strategy.settings["entry_risk_premium"] = 20.0
    strategy.settings["max_positions"] = 2

    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {"OSC-A", "OSC-B"}

    # First of two positions pays base; the second joins a fully correlated book
    # and therefore pays the whole premium.
    assert strategy._entry_risk_floor_assignments["OSC-A"] == pytest.approx(40.0)
    assert strategy._entry_risk_floor_assignments["OSC-B"] == pytest.approx(60.0)


def test_a_single_position_book_spends_its_whole_slot_budget() -> None:
    settings = configured_settings()
    utilization = MODULE.entry_risk_utilization(
        1,
        1,
        0.0,
        correlation_weight=float(settings["entry_risk_correlation_weight"]),
    )

    # With room for one position, opening it uses the entire slot budget.
    assert utilization == pytest.approx(1.0 / 1.5)


def test_rotation_confirmation_rechecks_the_live_risk_caps() -> None:
    strategy = _risk_strategy({CLONE: 100.0}, held=(HELD,))
    strategy._rotation_target = CLONE
    strategy._rotation_pair = HELD
    strategy._rotation_scores_qualify = Mock(return_value=True)
    strategy._entry_quality_reason = Mock(return_value="")
    strategy._recheck_entry_risk_floor = Mock(return_value=(54.0, "相关簇 6 > 上限 5"))

    with patch.object(STRATEGY_MODULE.Trade, "get_open_trades", return_value=_held_trades((HELD,))):
        reason = strategy._confirmation_quality_reason(CLONE)

    assert reason == "相关簇 6 > 上限 5"
