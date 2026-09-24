"""Equal budget per entry uses total trading capital, not remaining free margin."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from freqtrade.persistence import Trade
from freqtrade.wallets import Wallets
from tests.strategy.leader_squeeze_test_helpers import configured_strategy
from tests.strategy.test_leader_squeeze_strategy import LeaderSqueezeStrategy


def stake(strategy, maximum=990, minimum=5):
    strategy._profit_entry_atr = Mock(return_value=2.0)
    return strategy.custom_stake_amount(
        "BTC/USDT:USDT", datetime.now(UTC), 100, 165, minimum, maximum, 5, None, "long"
    )


def test_twenty_entries_and_rotation_use_the_same_fixed_risk_budget():
    strategy = configured_strategy(LeaderSqueezeStrategy)
    wallets = Wallets.__new__(Wallets)
    wallets._config = {"tradable_balance_ratio": 0.99}
    wallets._stake_currency = "USDT"
    strategy.wallets = wallets
    values = []
    for count in range(21):
        tied = count * 39.6
        wallets.get_free = Mock(return_value=1000 - tied)
        with patch.object(Trade, "total_open_trades_stakes", return_value=tied):
            values.append(stake(strategy, maximum=990 - tied))
    # ATR risk is 1.5 * 2 = 3% of price. At 5x leverage, risk sizing would
    # allow 66 margin, but the 4% per-position cap limits it to 39.6.
    assert values == [pytest.approx(39.6)] * 21


@pytest.mark.parametrize("maximum,minimum", [(39.5, 5), (990, 67), (0, 5), (float("nan"), 5)])
def test_invalid_or_insufficient_budget_skips_instead_of_small_or_oversized_entry(maximum, minimum):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.wallets = SimpleNamespace(get_total_stake_amount=lambda: 990)
    assert stake(strategy, maximum, minimum) == 0


def test_wallet_error_prevents_framework_fallback_to_proposed_stake():
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.wallets = SimpleNamespace(
        get_total_stake_amount=Mock(side_effect=RuntimeError("offline"))
    )
    assert stake(strategy) == 0


def test_low_volatility_size_is_capped_by_the_margin_ratio():
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.wallets = SimpleNamespace(get_total_stake_amount=lambda: 990)
    strategy._profit_entry_atr = Mock(return_value=0.01)

    assert strategy.custom_stake_amount(
        "BTC/USDT:USDT", datetime.now(UTC), 100, 165, 5, 990, 5, None, "long"
    ) == pytest.approx(39.6)


def test_missing_entry_volatility_blocks_the_order():
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.wallets = SimpleNamespace(get_total_stake_amount=lambda: 990)
    strategy._profit_entry_atr = Mock(return_value=None)

    assert (
        strategy.custom_stake_amount(
            "BTC/USDT:USDT", datetime.now(UTC), 100, 165, 5, 990, 5, None, "long"
        )
        == 0
    )


def test_disabled_initial_stop_sizes_against_the_global_stop() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings["entry_risk_initial_stop_enabled"] = False
    strategy.wallets = SimpleNamespace(get_total_stake_amount=lambda: 990)
    strategy._profit_entry_atr = Mock(side_effect=AssertionError("ATR is not the active stop"))

    margin = strategy.custom_stake_amount(
        "BTC/USDT:USDT", datetime.now(UTC), 100, 165, 5, 990, 5, None, "long"
    )

    assert margin == pytest.approx(9.9)
    strategy._profit_entry_atr.assert_not_called()


@pytest.mark.parametrize("ratio", [0, -0.1, float("nan"), True, 0.2])
def test_ratio_must_allow_normal_positions_and_buy_first_rotation(ratio):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings["stake_ratio"] = ratio
    with pytest.raises(ValueError, match="stake_ratio"):
        strategy._validate_score_settings()
