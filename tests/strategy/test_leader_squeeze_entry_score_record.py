"""The holding log must use the approved historical score, never a later score."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freqtrade.persistence import Trade
from tests.conftest import create_mock_trades_usdt
from tests.strategy.leader_squeeze_test_helpers import (
    configured_strategy,
)
from tests.strategy.test_leader_squeeze_entry_heat import MODULE, NOW, PAIR, _frame, _strategy
from tests.strategy.test_leader_squeeze_strategy import LeaderSqueezeStrategy


@pytest.mark.usefixtures("init_persistence")
@pytest.mark.parametrize("tag", ["squeeze_90.0", "rotation_0123456789abcdef"])
def test_approved_entry_score_is_saved_on_fill_and_survives_new_strategy(fee, tag):
    create_mock_trades_usdt(fee)
    trade = Trade.get_open_trades()[0]
    trade.enter_tag = tag
    trade.open_date = NOW + timedelta(seconds=1)
    strategy = _strategy(_frame("cooled"))
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy.confirm_trade_entry(PAIR, "market", 1, 180, "GTC", NOW, tag, "long")
    strategy._scores[PAIR] = 10  # A different score at fill time must not rewrite history.
    strategy.order_filled(
        PAIR, trade, SimpleNamespace(ft_order_side=trade.entry_side, filled=0.5), NOW
    )
    trade_id = trade.id
    Trade.commit()
    Trade.session.expire_all()
    restored = Trade.session.get(Trade, trade_id)
    assert restored.get_custom_data("leader_entry_score") == {
        "score": pytest.approx(90.0),
        "source": "confirmation",
    }
    restarted = configured_strategy(LeaderSqueezeStrategy)
    assert restarted._opening_score_label(restored) == "90.0"
    restarted.order_filled(
        PAIR, restored, SimpleNamespace(ft_order_side=trade.entry_side, filled=0.5), NOW
    )
    assert restarted._opening_score_label(restored) == "90.0"


@pytest.mark.usefixtures("init_persistence")
@pytest.mark.parametrize(
    "fault", ["exit", "old_trade", "different_tag", "restart_before_fill", "empty"]
)
def test_score_snapshot_cannot_attach_to_an_unrelated_order(fee, fault):
    create_mock_trades_usdt(fee)
    trade = Trade.get_open_trades()[0]
    trade.enter_tag = "rotation_same"
    trade.open_date = NOW
    strategy = _strategy(_frame())
    strategy._pending_entry_scores = {
        PAIR: {"score": 75.6, "tag": trade.enter_tag, "confirmed_at": NOW.timestamp()},
    }
    side = trade.entry_side
    if fault == "exit":
        side = trade.exit_side
    elif fault == "old_trade":
        trade.open_date = NOW - timedelta(hours=1)
    elif fault == "different_tag":
        trade.enter_tag = "rotation_other"
    elif fault == "restart_before_fill":
        strategy._pending_entry_scores.clear()
    strategy.order_filled(
        PAIR, trade, SimpleNamespace(ft_order_side=side, filled=0 if fault == "empty" else 0.5), NOW
    )
    assert trade.get_custom_data("leader_entry_score") is None
    assert strategy._opening_score_label(trade) == "未记录"


def test_failed_entry_confirmation_does_not_record_an_opening_score():
    strategy = _strategy(_frame())
    strategy._scores[PAIR] = 10
    with (
        patch.object(MODULE.time, "time", return_value=NOW.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert not strategy.confirm_trade_entry(PAIR, "market", 1, 180, "GTC", NOW, None, "long")
    assert not getattr(strategy, "_pending_entry_scores", {})


def test_missing_new_score_does_not_reuse_an_older_approval_snapshot():
    strategy = _strategy(_frame())
    strategy._pending_entry_scores = {PAIR: {"score": 99.0, "tag": None, "confirmed_at": 0}}
    strategy._scores.clear()
    with patch.object(MODULE.time, "time", return_value=NOW.timestamp()):
        strategy._record_approved_entry_score(PAIR, None)
    assert PAIR not in strategy._pending_entry_scores


def test_pending_scores_cleanup_preserves_open_orders_and_recent_approvals():
    strategy = _strategy(_frame())
    now = NOW.timestamp()
    snapshot = {"score": 50, "tag": None, "confirmed_at": now - 3600}
    strategy._pending_entry_scores = {
        "rejected": dict(snapshot),
        "open": dict(snapshot),
        "recent": {**snapshot, "confirmed_at": now},
    }
    with patch.object(Trade, "get_open_trades", return_value=[SimpleNamespace(pair="open")]):
        strategy._prune_pending_entry_scores(now)
    assert set(strategy._pending_entry_scores) == {"open", "recent"}
