"""Entry checks must reject on exceptions despite the framework's permissive wrapper."""

import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from freqtrade.strategy.strategy_wrapper import strategy_safe_wrapper
from tests.strategy.test_leader_squeeze_strategy import MODULE, _entry_ready_strategy


@pytest.mark.parametrize("logger_fails", [False, True])
def test_entry_gate_exception_cannot_become_an_approved_order(logger_fails: bool) -> None:
    pair = "BTC/USDT:USDT"
    strategy = _entry_ready_strategy(time.time())
    strategy._entries_allowed = Mock(side_effect=RuntimeError("gate failed"))

    failure = RuntimeError("logger failed") if logger_fails else None
    with patch.object(MODULE.logger, "exception", side_effect=failure):
        approved = strategy_safe_wrapper(strategy.confirm_trade_entry, default_retval=True)(
            pair=pair,
            order_type="market",
            amount=1.0,
            rate=100.0,
            time_in_force="GTC",
            current_time=datetime.now(UTC),
            entry_tag=None,
            side="long",
        )

    assert approved is False


def test_new_manual_position_seen_by_wallet_blocks_same_pair_entry() -> None:
    pair = "BTC/USDT:USDT"
    strategy = _entry_ready_strategy(time.time())
    strategy._position_first_seen = {}
    strategy._entry_block_reason = ""
    strategy._entries_allowed = Mock(return_value=True)
    strategy._candle_metrics = Mock(return_value={})
    strategy._confirmation_quality_reason = Mock(return_value="")
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy._audit_entry_confirmation = Mock()
    strategy._record_approved_entry_score = Mock()
    strategy.wallets = SimpleNamespace(
        get_all_positions=lambda: {pair: SimpleNamespace(position=1.0, leverage=5.0)}
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        approved = strategy.confirm_trade_entry(
            pair, "market", 1.0, 100.0, "GTC", datetime.now(UTC), None, "long"
        )

    assert not approved
    assert pair in strategy._external_pairs
    strategy._record_approved_entry_score.assert_not_called()
