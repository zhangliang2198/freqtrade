from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)
from tests.strategy.test_leader_squeeze_strategy import (
    ETH_TEST_NOW,
    MODULE,
    LeaderSqueezeStrategy,
    _entry_ready_strategy,
)


PAIR = "BTC/USDT:USDT"


def _strategy():
    strategy = _entry_ready_strategy(ETH_TEST_NOW.timestamp())
    strategy.config = {
        **PUBLIC_CONFIG,
        "exit_pricing": {"use_order_book": True, "order_book_top": 1},
    }
    strategy._candle_metrics = Mock(return_value={"momentum": 0.05, "trend_continuity": 1.0})
    strategy._trend_reversed = Mock(return_value=False)
    strategy.wallets = SimpleNamespace(get_total_stake_amount=Mock(return_value=100.0))
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(
            fetch_l2_order_book=Mock(return_value={"bids": [[99.99, 1]], "asks": [[100, 1]]}),
            get_rate=Mock(return_value=79.0),
        )
    )
    return strategy


def _confirm(strategy, amount=0.25):
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        return strategy.confirm_trade_entry(
            PAIR, "market", amount, 100.0, "GTC", ETH_TEST_NOW, None, "long"
        )


def test_selection_and_actual_quantity_check_reuse_book_without_network():
    strategy = _strategy()
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.time, "monotonic", return_value=100.0),
    ):
        assert strategy._execution_is_safe(PAIR)
        assert strategy._execution_is_safe(PAIR)
        assert _confirm(strategy)
        # 同一盘口必须按实际数量重新计算, 不能缓存上一次的通过结论。
        assert not _confirm(strategy, amount=2.0)
    strategy._exchange.fetch_l2_order_book.assert_called_once_with(PAIR, 20)
    assert strategy._entry_block_reason == "前20档卖盘深度不足"


@pytest.mark.parametrize("age", [None, 5.0, 6.0, -1.0])
def test_confirmation_refreshes_missing_expired_or_clock_reversed_cache_once(age):
    strategy = _strategy()
    with patch.object(MODULE.time, "monotonic", return_value=100.0):
        if age is not None:
            strategy._execution_order_book(PAIR)
    strategy._exchange.fetch_l2_order_book.reset_mock()
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.time, "monotonic", return_value=100.0 + (age or 0)),
    ):
        assert _confirm(strategy)
    strategy._exchange.fetch_l2_order_book.assert_called_once_with(PAIR, 20)


def test_confirmation_rejects_failed_refresh_instead_of_using_expired_book():
    strategy = _strategy()
    with patch.object(MODULE.time, "monotonic", return_value=100.0):
        strategy._execution_order_book(PAIR)
    strategy._exchange.fetch_l2_order_book.reset_mock()
    strategy._exchange.fetch_l2_order_book.side_effect = TimeoutError("offline")
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.time, "monotonic", return_value=106.0),
    ):
        assert not _confirm(strategy)
    strategy._exchange.fetch_l2_order_book.assert_called_once_with(PAIR, 20)
    assert "offline" in strategy._entry_block_reason
    assert not strategy._order_book_cache


def test_confirmation_rechecks_gates_after_book_refresh():
    strategy = _strategy()

    def fetch(pair, limit):
        strategy._position_data_healthy = False
        return {"bids": [[99.99, 1]], "asks": [[100, 1]]}

    strategy._exchange.fetch_l2_order_book.side_effect = fetch
    with (
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
        patch.object(MODULE.time, "monotonic", return_value=100.0),
    ):
        assert not _confirm(strategy)
    assert "仓位同步失败" in strategy._entry_block_reason
    strategy._exchange.fetch_l2_order_book.assert_called_once_with(PAIR, 20)


def test_expired_cache_is_removed_and_failed_refresh_never_serves_old_book():
    strategy = _strategy()
    with patch.object(MODULE.time, "monotonic", return_value=100.0):
        strategy._execution_order_book(PAIR)
        strategy._execution_order_book("UNRANKED")
    strategy._exchange.fetch_l2_order_book.side_effect = TimeoutError("offline")
    with patch.object(MODULE.time, "monotonic", return_value=106.0):
        assert not strategy._execution_is_safe(PAIR)
        assert strategy._order_book_cache == {}
        assert not strategy._execution_is_safe(PAIR, cached_only=True)
    assert strategy._exchange.fetch_l2_order_book.call_count == 3


def test_slow_book_response_is_not_cached_or_used():
    strategy = _strategy()
    with patch.object(MODULE.time, "monotonic", side_effect=[100.0, 105.0]):
        assert not strategy._execution_is_safe(PAIR)
    assert strategy._order_book_cache == {}
    assert "盘口请求耗时超过5秒" in strategy._execution_block_reason


@pytest.mark.parametrize("limit", [None, 0, 20, 20.5, True, "21", float("nan")])
def test_missing_rotation_slot_fails_before_state_access_or_threads(limit):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "runmode": "live"}
    if limit is not None:
        strategy.config["max_open_trades"] = limit
    else:
        strategy.config.pop("max_open_trades", None)
    strategy._load_risk_state = Mock(return_value={})
    strategy._sync_external_pairs = Mock()
    with patch.object(MODULE.threading, "Thread") as thread:
        with pytest.raises(ValueError, match="one extra buy-first rotation slot"):
            strategy.bot_start()
    strategy._load_risk_state.assert_not_called()
    strategy._sync_external_pairs.assert_not_called()
    thread.assert_not_called()


@pytest.mark.parametrize("limit", [21, 22, -1, float("inf")])
def test_rotation_slot_accepts_sufficient_or_framework_unlimited_capacity(tmp_path, limit):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "max_open_trades": limit, "user_data_dir": tmp_path}
    strategy._load_risk_state = Mock(return_value={})
    strategy._sync_external_pairs = Mock()
    strategy._initialize_rotation_audit = Mock()
    strategy.bot_start()
    assert strategy.settings["max_positions"] == 20


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, float("inf")])
def test_invalid_strategy_capacity_fails_early(limit):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "max_open_trades": 21,
        "leader_squeeze": {**configured_settings(), "max_positions": limit},
    }
    with pytest.raises(ValueError, match="max_positions must be an integer within"):
        strategy.bot_start()


def test_depth_preview_uses_total_capital_not_smaller_remaining_balance():
    strategy = _strategy()
    strategy.wallets.get_total_stake_amount.return_value = 1000
    strategy.wallets.get_available_stake_amount = Mock(return_value=100)
    # The book has one unit at 100: old remaining-balance sizing needed 0.5,
    # but equal total-capital sizing needs 5 units and must reject this depth.
    assert not strategy._execution_is_safe(PAIR)
    assert strategy._execution_block_reason == "前20档卖盘深度不足"
    strategy.wallets.get_available_stake_amount.assert_not_called()
