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
    return strategy.custom_stake_amount(
        "BTC/USDT:USDT", datetime.now(UTC), 100, 165, minimum, maximum, 5, None, "long"
    )


def test_ten_entries_and_rotation_use_equal_total_capital_budget():
    strategy = configured_strategy(LeaderSqueezeStrategy)
    wallets = Wallets.__new__(Wallets)
    wallets._config = {"tradable_balance_ratio": 0.99}
    wallets._stake_currency = "USDT"
    strategy.wallets = wallets
    values = []
    for count in range(11):
        tied = count * 79.2
        wallets.get_free = Mock(return_value=1000 - tied)
        with patch.object(Trade, "total_open_trades_stakes", return_value=tied):
            values.append(stake(strategy, maximum=990 - tied))
    assert values == [pytest.approx(79.2)] * 11


@pytest.mark.parametrize("maximum,minimum", [(79, 5), (990, 80), (0, 5), (float("nan"), 5)])
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


@pytest.mark.parametrize("ratio", [0, -0.1, float("nan"), True, 0.2])
def test_ratio_must_allow_normal_positions_and_buy_first_rotation(ratio):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings["stake_ratio"] = ratio
    with pytest.raises(ValueError, match="stake_ratio"):
        strategy._validate_score_settings()
