"""Missing rotation entries recover only after repeated flat-account evidence."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.strategy.test_leader_squeeze_buy_first import (
    MODULE,
    TARGET,
    WEAK,
    _state,
    _strategy,
    _trade,
)


NOW = 1200.0


def recovery():
    strategy = _strategy({**_state(phase="buy_pending"), "submitted_at": 1000.0})
    strategy.config = {"dry_run": False}
    strategy._record_rotation_event = Mock()
    api = SimpleNamespace(
        fetch_orders=Mock(return_value=[]), fetch_open_orders=Mock(return_value=[])
    )
    exchange = SimpleNamespace(_api=api, fetch_positions=Mock(return_value=[]))
    strategy.dp = SimpleNamespace(_exchange=exchange)
    return strategy, exchange


def sync(strategy, now=NOW, trades=None):
    with (
        patch.object(MODULE.time, "time", return_value=now),
        patch.object(
            MODULE.Trade,
            "get_open_trades",
            return_value=trades if trades is not None else [_trade(WEAK)],
        ),
    ):
        strategy._sync_rotation_state()


def test_unsubmitted_or_rejected_order_recovers_after_two_checks_without_selling_old_position():
    strategy, exchange = recovery()
    exchange._api.fetch_orders.return_value = [
        {"symbol": TARGET, "status": "rejected", "filled": 0}
    ]
    sync(strategy)
    assert strategy._rotation_state["phase"] == "buy_pending"
    sync(strategy, NOW + 1)
    assert exchange.fetch_positions.call_count == 1
    sync(strategy, NOW + 31)
    assert strategy._rotation_state is None
    assert strategy._rotation_pair is None
    assert strategy._last_rotation == NOW + 31
    assert any(c.args[0] == "recovered" for c in strategy._record_rotation_event.call_args_list)
    exchange._api.fetch_orders.assert_called_with(
        TARGET,
        since=int((1000 - strategy.settings["data_grace_seconds"]) * 1000),
        limit=strategy.settings["rotation_recovery_history_limit"],
        params={"endTime": 1231000},
    )


@pytest.mark.parametrize(
    "hazard",
    [
        "partial",
        "open",
        "conditional",
        "position",
        "truncated",
        "missing_filled",
        "unknown_status",
        "network",
    ],
)
def test_uncertain_or_nonflat_exchange_state_never_recovers(hazard):
    strategy, exchange = recovery()
    if hazard == "partial":
        exchange._api.fetch_orders.return_value = [
            {"symbol": TARGET, "status": "canceled", "filled": 1}
        ]
    elif hazard == "open":
        exchange._api.fetch_open_orders.return_value = [{"id": "pending"}]
    elif hazard == "conditional":
        exchange._api.fetch_open_orders.side_effect = lambda *a, **k: [{"id": "stop"}] if k else []
    elif hazard == "position":
        exchange.fetch_positions.return_value = [{"symbol": TARGET, "contracts": 1}]
    elif hazard == "truncated":
        exchange._api.fetch_orders.return_value = [{}] * strategy.settings[
            "rotation_recovery_history_limit"
        ]
    elif hazard == "missing_filled":
        exchange._api.fetch_orders.return_value = [{"symbol": TARGET, "status": "canceled"}]
    elif hazard == "unknown_status":
        exchange._api.fetch_orders.return_value = [
            {"symbol": TARGET, "status": "unknown", "filled": 0}
        ]
    else:
        exchange._api.fetch_orders.side_effect = TimeoutError
    sync(strategy)
    sync(strategy, NOW + 31)
    assert strategy._rotation_state is not None
    assert strategy._rotation_recovery_probe["count"] == 0


def test_failed_probe_resets_confirmation_and_restart_requires_new_checks():
    strategy, exchange = recovery()
    sync(strategy)
    exchange.fetch_positions.side_effect = TimeoutError
    sync(strategy, NOW + 31)
    assert strategy._rotation_recovery_probe["count"] == 0
    exchange.fetch_positions.side_effect = None
    sync(strategy, NOW + 62)
    assert strategy._rotation_state is not None
    del strategy._rotation_recovery_probe
    sync(strategy, NOW + 93)
    assert strategy._rotation_state is not None
    sync(strategy, NOW + 124)
    assert strategy._rotation_state is None


@pytest.mark.parametrize("submitted", [None, NOW - 10, NOW + 100, 0])
def test_missing_future_or_too_recent_request_boundary_cannot_recover(submitted):
    strategy, exchange = recovery()
    strategy._rotation_state["submitted_at"] = submitted
    sync(strategy)
    assert strategy._rotation_state is not None
    exchange._api.fetch_orders.assert_not_called()


def test_local_target_appearing_during_queries_prevents_clearing_plan():
    strategy, _exchange = recovery()
    with (
        patch.object(MODULE.time, "time", return_value=NOW),
        patch.object(
            MODULE.Trade, "get_open_trades", side_effect=[[_trade(WEAK)], [_trade(TARGET)]]
        ),
    ):
        strategy._sync_rotation_state()
    assert strategy._rotation_state is not None
    assert strategy._rotation_recovery_probe["count"] == 0


def test_dry_run_recovery_never_queries_real_exchange():
    strategy, exchange = recovery()
    strategy.config["dry_run"] = True
    exchange._dry_run_open_orders = {}
    sync(strategy)
    sync(strategy, NOW + 31)
    assert strategy._rotation_state is None
    exchange._api.fetch_orders.assert_not_called()
    exchange._api.fetch_open_orders.assert_not_called()
    exchange.fetch_positions.assert_not_called()


def test_legacy_plan_can_use_persisted_last_rotation_as_submission_boundary():
    strategy, _exchange = recovery()
    strategy._rotation_state.pop("submitted_at")
    strategy._risk_state["last_rotation"] = 1000.0
    sync(strategy)
    sync(strategy, NOW + 31)
    assert strategy._rotation_state is None


def test_recovery_state_is_persisted_without_replacing_the_old_trade(tmp_path):
    import json

    strategy, _exchange = recovery()
    del strategy._persist_rotation
    strategy._state_path = tmp_path / "rotation.json"
    strategy._risk_state.update(account_stopped=False, peak_equity=1000)
    sync(strategy)
    sync(strategy, NOW + 31)
    saved = json.loads(strategy._state_path.read_text())
    assert saved["rotation"] is None
    assert saved["last_rotation"] == NOW + 31


def test_oversized_history_age_requires_review_instead_of_assuming_no_order():
    strategy, exchange = recovery()
    sync(strategy, 1000 + strategy.settings["rotation_recovery_max_age_seconds"] + 1)
    assert strategy._rotation_state is not None
    exchange._api.fetch_orders.assert_not_called()


def test_closed_target_recovers_only_with_matching_closed_trade_and_exchange_fills():
    from datetime import UTC, datetime

    strategy, exchange = recovery()
    orders = [
        SimpleNamespace(order_id="entry", filled=10, ft_is_open=False, status="closed"),
        SimpleNamespace(order_id="exit", filled=10, ft_is_open=False, status="closed"),
    ]
    trade = SimpleNamespace(
        id=42,
        pair=TARGET,
        enter_tag=strategy._rotation_entry_tag(),
        is_open=False,
        is_short=False,
        has_open_orders=False,
        orders=orders,
        open_date_utc=datetime.fromtimestamp(1001, UTC),
        close_date_utc=datetime.fromtimestamp(1100, UTC),
    )
    exchange._api.fetch_orders.return_value = [
        {"id": o.order_id, "symbol": TARGET, "filled": o.filled, "status": "closed"} for o in orders
    ]
    with patch.object(MODULE.Trade, "get_trades_proxy", return_value=[trade]):
        sync(strategy)
        sync(strategy, NOW + 31)
    assert strategy._rotation_state is None
    assert strategy._last_rotation == NOW + 31


@pytest.mark.parametrize("fault", ["tag", "unknown_order", "filled_mismatch", "open_order"])
def test_closed_target_recovery_rejects_unreconciled_fills(fault):
    from datetime import UTC, datetime

    strategy, exchange = recovery()
    order = SimpleNamespace(order_id="entry", filled=10, ft_is_open=False, status="closed")
    trade = SimpleNamespace(
        id=42,
        pair=TARGET,
        enter_tag=strategy._rotation_entry_tag(),
        is_open=False,
        is_short=False,
        has_open_orders=False,
        orders=[order],
        open_date_utc=datetime.fromtimestamp(1001, UTC),
        close_date_utc=datetime.fromtimestamp(1100, UTC),
    )
    remote = {"id": "entry", "symbol": TARGET, "filled": 10, "status": "closed"}
    if fault == "tag":
        trade.enter_tag = "unrelated"
    elif fault == "unknown_order":
        remote["id"] = "other"
    elif fault == "filled_mismatch":
        remote["filled"] = 9
    else:
        order.ft_is_open = True
    exchange._api.fetch_orders.return_value = [remote]
    with patch.object(MODULE.Trade, "get_trades_proxy", return_value=[trade]):
        sync(strategy)
        sync(strategy, NOW + 31)
    assert strategy._rotation_state is not None
