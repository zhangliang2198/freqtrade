import importlib.util
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from freqtrade.exceptions import OperationalException
from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)


STRATEGY_PATH = (
    Path(__file__).parents[2] / "user_data/strategies/leader_squeeze/leader_squeeze_strategy.py"
)
SPEC = importlib.util.spec_from_file_location("leader_squeeze_buy_first", STRATEGY_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


WEAK = "WEAK/USDT:USDT"
TARGET = "TARGET/USDT:USDT"
OTHER = "OTHER/USDT:USDT"


def _state(*, phase: str = "buy", amount: float = 10.0, weak_trade_id: int | None = 1) -> dict:
    return {
        "weak": WEAK,
        "target": TARGET,
        "token": "rotation-token",
        "phase": phase,
        "amount": amount,
        "weak_trade_id": weak_trade_id,
    }


def _order(
    *,
    side: str = "buy",
    filled: float = 0.0,
    status: str = "open",
    is_open: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        ft_order_side=side,
        filled=filled,
        status=status,
        ft_is_open=is_open,
    )


def _trade(
    pair: str,
    *,
    trade_id: int = 1,
    tag: str = "",
    amount: float = 10.0,
    is_open: bool = True,
    has_open_orders: bool = False,
    orders: list[SimpleNamespace] | None = None,
    is_short: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=trade_id,
        pair=pair,
        enter_tag=tag,
        is_short=is_short,
        is_open=is_open,
        amount=amount,
        has_open_orders=has_open_orders,
        entry_side="buy",
        exit_side="sell",
        orders=orders or [],
    )


def _strategy(state: dict | None = None) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = {**configured_settings(), "max_positions": 5}
    strategy._external_pairs = set()
    strategy._rotation_state = state
    strategy._rotation_pair = state["weak"] if state else None
    strategy._rotation_target = state["target"] if state else None
    strategy._entry_block_reason = ""
    strategy._risk_state = {}
    strategy._persist_rotation = Mock(return_value=True)
    strategy._position_data_healthy = True
    strategy._warn_data_unavailable = Mock()
    return strategy


def _confirm_ready_strategy(state: dict) -> LeaderSqueezeStrategy:
    strategy = _strategy(state)
    strategy._entry_pairs = {TARGET}
    strategy._entries_allowed = Mock(return_value=True)
    strategy._candle_metrics = Mock(return_value={})
    strategy._pair_score_current = Mock(return_value=True)
    strategy._entry_quality_reason = Mock(return_value="")
    strategy._rotation_scores_qualify = Mock(return_value=True)
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(amount_to_contract_precision=lambda pair, amount: amount)
    )
    strategy.wallets = SimpleNamespace(
        get_total_stake_amount=lambda: 1_000.0,
        get_all_positions=lambda: {
            trade.pair: SimpleNamespace(collateral=80.0, position=0.0, leverage=5.0)
            for trade in MODULE.Trade.get_open_trades()
        },
    )
    return strategy


def test_only_matching_rotation_target_may_use_the_temporary_sixth_slot() -> None:
    strategy = _strategy(_state())
    occupied = [_trade(WEAK)] + [_trade(f"HELD-{index}") for index in range(1, 5)]

    with patch.object(MODULE.Trade, "get_open_trades", return_value=occupied):
        assert strategy._entry_slot_available(TARGET, "rotation_rotation-token")
        assert not strategy._entry_slot_available(TARGET, "ordinary-entry")
        assert not strategy._entry_slot_available(OTHER, None)


def test_rotation_target_is_rejected_when_it_would_be_the_seventh_position() -> None:
    strategy = _strategy(_state())
    occupied = [_trade(WEAK)] + [_trade(f"HELD-{index}") for index in range(1, 6)]

    with patch.object(MODULE.Trade, "get_open_trades", return_value=occupied):
        assert not strategy._entry_slot_available(TARGET, "rotation_rotation-token")


def test_ordinary_entries_cannot_use_sixth_slot_or_reuse_a_canceled_rotation_tag() -> None:
    strategy = _strategy()
    with patch.object(
        MODULE.Trade, "get_open_trades", return_value=[_trade(str(i)) for i in range(5)]
    ):
        assert not strategy._entry_slot_available(OTHER, None)
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._entry_slot_available(OTHER, None)
        assert not strategy._entry_slot_available(TARGET, "rotation_old-token")


def test_confirm_saves_to_disk_before_allowing_one_buy_and_rejects_duplicate(tmp_path) -> None:
    strategy = _confirm_ready_strategy(_state())
    del strategy._persist_rotation
    strategy._state_path = tmp_path / "state.json"
    strategy._last_rotation = 1000.0
    strategy._risk_state = {"account_stopped": False, "peak_equity": 1000.0}
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[_trade(WEAK)]):
        args = (
            TARGET,
            "market",
            3.25,
            100.0,
            "GTC",
            datetime.now(UTC),
            "rotation_rotation-token",
            "long",
        )
        assert strategy.confirm_trade_entry(*args)
        assert not strategy.confirm_trade_entry(*args)
    saved = strategy._load_risk_state()
    assert saved["rotation"]["phase"] == "buy_pending"
    assert saved["rotation"]["amount"] == 3.25
    strategy._execution_is_safe.assert_called_once()


def test_rotation_uses_exchange_quantity_precision_for_completion() -> None:
    strategy = _confirm_ready_strategy(_state())
    strategy.dp._exchange.amount_to_contract_precision = Mock(return_value=3.2)
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[_trade(WEAK)]):
        assert strategy.confirm_trade_entry(
            TARGET,
            "market",
            3.25678,
            100.0,
            "GTC",
            datetime.now(UTC),
            "rotation_rotation-token",
            "long",
        )
    assert strategy._rotation_state["amount"] == 3.2
    target = _trade(
        TARGET,
        tag="rotation_rotation-token",
        amount=3.2,
        orders=[_order(filled=3.2, status="closed", is_open=False)],
    )
    assert strategy._rotation_trade_filled(target)


def test_rotation_precision_failure_denies_entry_instead_of_raising_to_framework() -> None:
    strategy = _confirm_ready_strategy(_state())
    strategy.dp._exchange.amount_to_contract_precision = Mock(
        side_effect=RuntimeError("unknown market")
    )
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[_trade(WEAK)]):
        assert not strategy.confirm_trade_entry(
            TARGET,
            "market",
            3.25,
            100.0,
            "GTC",
            datetime.now(UTC),
            "rotation_rotation-token",
            "long",
        )
    strategy._persist_rotation.assert_not_called()


@pytest.mark.parametrize("complete", [False, True])
def test_eth_block_does_not_erase_submitted_rotation_or_prevent_confirmed_old_exit(
    complete,
) -> None:
    strategy = _strategy(_state(phase="buy_pending"))
    now = time.time()
    strategy._last_position_sync = now
    strategy._sync_external_pairs = Mock()
    strategy._eth_entries_allowed = Mock(return_value=False)
    strategy._eth_block_reason = "ETH 下跌"
    strategy._eth_trend_summary = "ETH 下跌"
    strategy._eth_last_log_reason, strategy._eth_last_log_time = None, 0.0
    strategy._entry_pairs = {OTHER}
    strategy._rotation_candidate, strategy._rotation_seen = None, 0
    strategy._consume_score_refresh = Mock()
    strategy.dp = SimpleNamespace(current_whitelist=list, current_selection_whitelist=list)
    strategy._next_score_refresh = float("inf")
    strategy._score_pending = False
    strategy._refresh_risk_state = Mock()
    strategy._plan_rotation = Mock()
    strategy._select_entries = Mock(return_value=set())
    strategy._log_strategy_status = Mock()
    target = _trade(
        TARGET,
        tag="rotation_rotation-token",
        orders=[
            _order(
                filled=10 if complete else 5,
                status="closed" if complete else "canceled",
                is_open=False,
            )
        ],
    )
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[_trade(WEAK), target]):
        strategy.bot_loop_start(datetime.now(UTC))
        assert strategy._rotation_exit_allowed(WEAK) is complete
    assert strategy._rotation_pair == WEAK
    assert strategy._rotation_state["phase"] == ("sell" if complete else "review")
    strategy._plan_rotation.assert_not_called()


def test_unimported_external_old_position_cancels_rotation_without_direct_exit() -> None:
    strategy = _strategy(_state(phase="buy_pending", weak_trade_id=None))
    strategy._external_pairs = {WEAK}
    strategy._position_data_healthy = True
    strategy._persist_rotation = Mock(return_value=True)
    strategy._record_rotation_event = Mock()

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        strategy._sync_rotation_state()

    assert strategy._rotation_state is None
    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None
    strategy._record_rotation_event.assert_called_with(
        "cancelled", "旧仓尚未完成框架对账, 撤销轮换授权"
    )


def test_completed_rotation_is_cleared_and_cannot_sell_a_new_trade_in_same_pair() -> None:
    strategy = _strategy(_state(phase="sell", weak_trade_id=1))
    target = _trade(
        TARGET,
        tag="rotation_rotation-token",
        orders=[_order(filled=10, status="closed", is_open=False)],
    )
    with patch.object(
        MODULE.Trade, "get_open_trades", return_value=[_trade(WEAK, trade_id=99), target]
    ):
        assert not strategy._rotation_exit_allowed(WEAK)
    assert strategy._rotation_state is None
    assert not strategy._rotation_in_flight()


def test_confirm_entry_persists_buy_pending_with_the_actual_amount() -> None:
    strategy = _confirm_ready_strategy(_state())

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[_trade(WEAK)]):
        allowed = strategy.confirm_trade_entry(
            pair=TARGET,
            order_type="market",
            amount=3.25,
            rate=100.0,
            time_in_force="GTC",
            current_time=datetime.now(UTC),
            entry_tag="rotation_rotation-token",
            side="long",
        )

    assert allowed
    assert strategy._rotation_state["phase"] == "buy_pending"
    assert strategy._rotation_state["amount"] == pytest.approx(3.25)
    strategy._persist_rotation.assert_called_once_with()


def test_confirm_entry_rejects_when_buy_pending_cannot_be_saved() -> None:
    state = _state()
    strategy = _confirm_ready_strategy(state)
    strategy._persist_rotation = Mock(return_value=False)

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[_trade(WEAK)]):
        allowed = strategy.confirm_trade_entry(
            pair=TARGET,
            order_type="market",
            amount=3.25,
            rate=100.0,
            time_in_force="GTC",
            current_time=datetime.now(UTC),
            entry_tag="rotation_rotation-token",
            side="long",
        )

    assert not allowed
    assert strategy._rotation_state["phase"] == "buy_pending"
    assert strategy._rotation_state["amount"] == pytest.approx(3.25)


@pytest.mark.parametrize(
    ("trade", "expected"),
    [
        (
            _trade(
                TARGET,
                tag="rotation_rotation-token",
                has_open_orders=True,
                orders=[_order(filled=0.0, status="open", is_open=True)],
            ),
            False,
        ),
        (
            _trade(
                TARGET,
                tag="rotation_rotation-token",
                amount=5.0,
                orders=[_order(filled=5.0, status="canceled", is_open=False)],
            ),
            False,
        ),
        (
            _trade(
                TARGET,
                tag="rotation_rotation-token",
                orders=[_order(filled=10.0, status="closed", is_open=False)],
            ),
            True,
        ),
        (
            _trade(
                TARGET,
                tag="different-token",
                orders=[_order(filled=10.0, status="closed", is_open=False)],
            ),
            False,
        ),
        (
            _trade(
                TARGET,
                tag="rotation_rotation-token",
                orders=[
                    _order(filled=10.0, status="closed", is_open=False),
                    _order(side="sell", filled=1.0, status="closed", is_open=False),
                ],
            ),
            False,
        ),
    ],
)
def test_rotation_trade_requires_a_full_clean_entry_fill(
    trade: SimpleNamespace, expected: bool
) -> None:
    strategy = _strategy(_state(phase="buy_pending"))

    assert strategy._rotation_trade_filled(trade) is expected


def test_missing_target_never_allows_old_position_to_be_sold() -> None:
    strategy = _strategy(_state(phase="buy_pending"))
    weak = _trade(WEAK, trade_id=1)

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak]):
        strategy._sync_rotation_state()
        assert not strategy._rotation_exit_allowed(WEAK)

    assert strategy._rotation_state["phase"] == "buy_pending"
    assert strategy._rotation_pair == WEAK
    assert strategy._rotation_target == TARGET


def test_partial_canceled_target_moves_to_review_without_selling_old_position() -> None:
    strategy = _strategy(_state(phase="buy_pending"))
    weak = _trade(WEAK, trade_id=1)
    target = _trade(
        TARGET,
        trade_id=2,
        tag="rotation_rotation-token",
        amount=5.0,
        orders=[_order(filled=5.0, status="canceled", is_open=False)],
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak, target]):
        strategy._sync_rotation_state()
        assert strategy._rotation_state["phase"] == "review"
        assert not strategy._rotation_exit_allowed(WEAK)


def test_only_a_complete_target_fill_transitions_to_sell_and_allows_exit() -> None:
    strategy = _strategy(_state(phase="buy_pending"))
    weak = _trade(WEAK, trade_id=1)
    target = _trade(
        TARGET,
        trade_id=2,
        tag="rotation_rotation-token",
        orders=[_order(filled=10.0, status="closed", is_open=False)],
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak, target]):
        strategy._sync_rotation_state()
        assert strategy._rotation_state["phase"] == "sell"
        assert strategy._rotation_exit_allowed(WEAK)


def test_wrong_tag_is_not_a_completed_rotation_target() -> None:
    strategy = _strategy(_state(phase="buy_pending"))
    weak = _trade(WEAK, trade_id=1)
    target = _trade(
        TARGET,
        trade_id=2,
        tag="ordinary-entry",
        orders=[_order(filled=10.0, status="closed", is_open=False)],
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak, target]):
        strategy._sync_rotation_state()

    assert strategy._rotation_state["phase"] == "review"
    assert not strategy._rotation_trade_filled(target)


def test_failed_old_position_exit_keeps_all_new_entries_blocked() -> None:
    strategy = _strategy(_state(phase="sell"))
    weak = _trade(WEAK, trade_id=1)
    target = _trade(
        TARGET,
        trade_id=2,
        tag="rotation_rotation-token",
        orders=[_order(filled=10.0, status="closed", is_open=False)],
    )
    held = [weak, target, _trade("HELD-3"), _trade("HELD-4"), _trade("HELD-5")]

    with patch.object(MODULE.Trade, "get_open_trades", return_value=held):
        assert strategy._rotation_exit_allowed(WEAK)
        assert not strategy._entry_slot_available(OTHER, None)


def test_bot_start_restores_rotation_state_and_cooldown(tmp_path: Path) -> None:
    state = _state(phase="buy_pending", amount=2.5, weak_trade_id=17)
    payload = {
        "account_stopped": False,
        "peak_equity": 1000.0,
        "day_start_equity": 1000.0,
        "last_equity": 990.0,
        "last_rotation": 1234.5,
        "rotation": state,
    }
    state_path = tmp_path / PUBLIC_CONFIG["leader_squeeze"]["state_file_dry_run"]
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(payload))
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "max_open_trades": 6,
        "user_data_dir": str(tmp_path),
        "dry_run": True,
        "runmode": "backtest",
    }
    strategy._sync_external_pairs = Mock()
    strategy._initialize_rotation_audit = Mock()

    with pytest.raises(
        OperationalException, match=r"requires live or dry_run mode.*no historical data source"
    ):
        strategy.bot_start()


@pytest.mark.parametrize(
    "bad_rotation",
    [
        {**_state(), "phase": "unknown"},
        {**_state(), "token": ""},
        {**_state(phase="buy_pending"), "amount": 0.0},
        {**_state(), "weak_trade_id": 0},
    ],
)
def test_invalid_persisted_rotation_state_blocks_loading(
    tmp_path: Path, bad_rotation: dict
) -> None:
    payload = {
        "account_stopped": False,
        "peak_equity": 1000.0,
        "day_start_equity": 1000.0,
        "last_equity": 1000.0,
        "last_rotation": 0.0,
        "rotation": bad_rotation,
    }
    path = tmp_path / "leader_squeeze_state.json"
    path.write_text(json.dumps(payload))
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._state_path = path
    strategy._risk_state_load_failed = False

    assert strategy._load_risk_state() == {}
    assert strategy._risk_state_load_failed


def test_persisted_rotation_cannot_sell_manual_import_when_management_disabled():
    strategy = _strategy(_state(phase="sell"))
    weak = _trade(WEAK)
    weak.enter_tag = "manual_import"
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak]):
        strategy._sync_rotation_state()
    assert strategy._rotation_state is None
    assert strategy._rotation_pair is None
