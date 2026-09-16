"""Ordinary breadth weakness pauses buying without forcing healthy holdings out."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.strategy.leader_squeeze_test_helpers import configured_settings
from tests.strategy.test_leader_squeeze_strategy import MODULE, _entry_ready_strategy


NOW = 1000.0
PAIR = "BTC/USDT:USDT"


def regime(returns):
    strategy = _entry_ready_strategy(NOW)
    strategy.settings = configured_settings()
    strategy._rotation_exit_allowed = Mock(return_value=False)
    strategy._trend_reversed = Mock(return_value=False)
    leaders = [str(i) for i in range(10)]
    metrics = {
        str(i): {"momentum": value, "_candle_valid_until": NOW + 100}
        for i, value in enumerate(returns)
    }
    strategy._update_market_state(leaders, metrics)
    return strategy


def exit_reason(strategy):
    with patch.object(MODULE.time, "time", return_value=NOW):
        return strategy.custom_exit(PAIR, SimpleNamespace(), datetime.now(UTC), 100, 0)


def test_small_broad_pullback_blocks_buys_but_does_not_force_exit():
    strategy = regime([-0.001] * 8 + [0.01] * 2)
    assert strategy._market_down
    assert not strategy._market_emergency
    assert exit_reason(strategy) is None
    assert not strategy._entries_allowed(NOW)
    assert "市场普跌" in strategy._entry_block_reason
    strategy._trend_reversed.return_value = True
    assert exit_reason(strategy) == "trend_reversal"


def test_severe_breadth_exits_even_without_ordinary_eighty_percent_breadth():
    strategy = regime([-0.03] * 6 + [0.01] * 4)
    assert strategy._market_down and strategy._market_emergency
    assert exit_reason(strategy) == "market_emergency"
    strategy.settings["market_emergency_enabled"] = False
    assert exit_reason(strategy) is None
    assert strategy._market_down


@pytest.mark.parametrize("returns", [[-0.031] * 5, [-0.031] * 5 + [0.01] * 5, [-0.029] * 10])
def test_insufficient_coverage_breadth_or_magnitude_does_not_force_exit(returns):
    strategy = regime(returns)
    assert not strategy._market_emergency
    assert exit_reason(strategy) is None


def test_emergency_expires_and_resets_on_recovery():
    strategy = regime([-0.04] * 10)
    strategy._market_valid_until = NOW - 1
    assert exit_reason(strategy) is None
    assert not strategy._market_emergency
    strategy._update_market_state(
        ["0"], {"0": {"momentum": 0.01, "_candle_valid_until": NOW + 100}}
    )
    assert not strategy._market_down


def test_external_positions_use_the_same_market_emergency_gate():
    from tests.strategy.test_leader_squeeze_external_isolation import _strategy

    strategy = _strategy()
    strategy._market_down = True
    strategy._market_is_down.return_value = True
    strategy._market_emergency = False
    strategy._manage_external_positions(NOW)
    strategy.dp._exchange.create_order.assert_not_called()
    strategy._market_emergency = True
    strategy._manage_external_positions(NOW + 100)
    assert strategy.dp._exchange.create_order.call_count == 2
