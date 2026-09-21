"""Retries must not erase a frozen signal cap or weaken existing checks."""

from unittest.mock import Mock

import pandas as pd
import pytest

from tests.strategy.test_leader_squeeze_entry_price_guard import (
    PAIR,
    _book,
    _confirm,
    _set_book,
    strategy,  # noqa: F401 - reuse the isolated source-harness fixture
)


@pytest.mark.parametrize("fault", ["missing", "gap", "unaligned"])
def test_temporary_data_failure_cannot_rebase_same_candle(strategy, fault):
    assert strategy._execution_is_safe(PAIR)
    reference = strategy._entry_price_references[PAIR]
    good = strategy.frame.copy(deep=True)
    if fault == "missing":
        strategy.frame = pd.DataFrame()
    elif fault == "gap":
        strategy.frame = strategy.frame.drop(10)
    else:
        strategy.frame["date"] -= pd.Timedelta(seconds=1)
    assert not strategy._execution_is_safe(PAIR)
    assert strategy._entry_price_references[PAIR] is reference
    # A recovered feed may revise the same bar; it cannot lift the old cap.
    good.loc[good.index[-1], ["close", "high"]] = [104, 105]
    strategy.frame = good
    _set_book(strategy, _book(103))
    assert not strategy._execution_is_safe(PAIR)
    assert reference["close"] == 100
    assert reference["max_price"] == 102
    assert "追价拦截" in strategy._execution_block_reason


def test_invalid_ohlc_on_same_signal_is_not_hidden_by_cached_reference(strategy):
    assert strategy._execution_is_safe(PAIR)
    strategy.frame.loc[5, "high"] = 95
    assert not strategy._execution_is_safe(PAIR)
    assert "K线高低收关系无效" in strategy._execution_block_reason


def test_final_price_check_does_not_recalculate_candles_or_atr(strategy):
    assert strategy._execution_is_safe(PAIR)
    strategy._closed_candles = Mock(side_effect=AssertionError("unexpected candle work"))
    strategy._wilder_atr = Mock(side_effect=AssertionError("unexpected ATR work"))
    assert _confirm(strategy)
    _set_book(strategy, _book(106))
    assert not _confirm(strategy)
    strategy._closed_candles.assert_not_called()
    strategy._wilder_atr.assert_not_called()
    assert "追价拦截" in strategy._entry_block_reason


def test_nonfinite_slippage_limit_cannot_change_old_fail_closed_behavior(strategy):
    strategy.settings["entry_price_guard_enabled"] = False
    strategy.settings["max_slippage_ratio"] = float("nan")
    assert not _confirm(strategy)
    strategy._record_approved_entry_score.assert_not_called()
