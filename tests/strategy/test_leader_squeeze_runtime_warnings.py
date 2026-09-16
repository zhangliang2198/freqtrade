"""Regression tests for runtime freshness and warning behavior."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
)
from tests.strategy.test_leader_squeeze_remote_expiry import (
    NOW,
    PAIR,
    _consume_strategy,
    _metric,
)
from tests.strategy.test_leader_squeeze_strategy import MODULE, _entry_ready_strategy


def test_entries_allowed_reports_first_score_load_without_expiry_reason() -> None:
    strategy = _entry_ready_strategy(NOW)
    strategy._last_good_data = 0.0

    assert not strategy._entries_allowed(NOW)
    assert "首批行情与评分加载中" in strategy._entry_block_reason
    assert "评分数据过期" not in strategy._entry_block_reason


def test_consume_score_refresh_retries_before_the_earliest_metric_deadline() -> None:
    strategy = _consume_strategy(NOW)
    strategy._candle_metrics.return_value = {
        "momentum": 0.05,
        "trend_continuity": 1.0,
        "_candle_valid_until": 1_020.0,
    }
    strategy._score_result = (
        NOW,
        [PAIR],
        {PAIR: _metric(NOW, score_age=200.0, exit_age=200.0)},
    )

    assert strategy._consume_score_refresh(NOW)
    assert strategy._next_score_refresh <= 1_030.0


def test_blocked_score_refresh_retries_before_the_earliest_exit_deadline() -> None:
    strategy = _consume_strategy(NOW)
    metric = _metric(NOW, score_age=-1.0, exit_age=100.0)
    strategy._score_result = (NOW, [PAIR], {PAIR: metric})

    assert not strategy._consume_score_refresh(NOW, allow_scoring=False)
    strategy._advance_score_refresh(NOW, allow_scoring=False)

    assert strategy._next_score_refresh <= metric["_exit_valid_until"] - float(
        strategy.settings["score_retry_seconds"]
    )


@pytest.mark.parametrize(
    ("started", "last_message", "level", "fragment"),
    [
        (0.0, 0.0, logging.INFO, "初始化"),
        (100.0, 100.0, logging.WARNING, "重新预热"),
    ],
)
def test_reset_liquidation_window_logs_initialization_or_rewarm(
    caplog, started: float, last_message: float, level: int, fragment: str
) -> None:
    strategy = _entry_ready_strategy(NOW)
    strategy._liquidation_lock = threading.Lock()
    strategy._liquidations = {}
    strategy._liquidation_started = started
    strategy._liquidation_last_message = last_message

    with caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"):
        strategy._reset_liquidation_window()

    assert any(
        record.levelno == level and fragment in record.getMessage() for record in caplog.records
    )


def test_entry_pair_outside_whitelist_has_specific_reason_without_data_warning(caplog) -> None:
    strategy = _entry_ready_strategy(NOW)
    del strategy._entry_pair_available
    strategy.dp = SimpleNamespace(current_whitelist=list)

    with caplog.at_level(logging.WARNING, logger="leader_squeeze_strategy"):
        assert not strategy._entry_pair_available(PAIR)

    assert strategy._pair_entry_block_reason == "已离开当前交易名单"
    assert not any("数据不可用" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "pending, eth_allowed, last_request, expected",
    [
        (False, True, 900.0, NOW),
        (True, True, 900.0, 1300.0),
        (False, False, 900.0, 1300.0),
        (False, True, 995.0, 1300.0),
    ],
)
def test_lost_coverage_requests_refresh_without_bypassing_throttle(
    pending, eth_allowed, last_request, expected
):
    strategy = _entry_ready_strategy(NOW)
    strategy._metrics = {}
    strategy._score_pending = pending
    strategy._last_score_request = last_request
    strategy._next_score_refresh = 1300.0
    strategy._advance_score_refresh(NOW, allow_scoring=eth_allowed)
    assert strategy._next_score_refresh == expected


def test_rankings_hide_removed_candidates_but_retain_their_position_scores():
    strategy = _entry_ready_strategy(NOW)
    strategy._scores = {PAIR: 50.0, "REMOVED": 80.0}
    strategy._entry_leaders = [PAIR]
    assert strategy._ranked_pairs() == [(PAIR, 50.0)]
    assert strategy._current_score("REMOVED", NOW) == 80.0


def test_disabled_external_exchange_stop_does_not_create_or_cancel_orders():
    strategy = _entry_ready_strategy(NOW)
    strategy.config = {**PUBLIC_CONFIG, "dry_run": False}
    strategy.dp = Mock()
    strategy.order_types["stoploss_on_exchange"] = False
    assert not strategy.order_types["stoploss_on_exchange"]
    assert strategy._ensure_external_stop(PAIR, SimpleNamespace(), NOW)
    assert strategy.dp.mock_calls == []


def test_future_database_trade_time_blocks_new_entries_without_mutating_trade():
    strategy = _entry_ready_strategy(NOW)
    strategy.wallets = SimpleNamespace(get_all_positions=dict)
    strategy._position_first_seen = {}
    strategy._external_stop_last_check = {}
    trade = SimpleNamespace(pair=PAIR, open_date_utc=datetime.fromtimestamp(NOW + 28800, UTC))
    original = trade.open_date_utc
    with (
        patch.object(MODULE.Trade, "get_open_trades", return_value=[trade]),
        patch.object(MODULE.time, "time", return_value=NOW),
    ):
        strategy._sync_external_pairs()
    assert not strategy._entries_allowed(NOW)
    assert "数据库持仓时间异常" in strategy._entry_block_reason
    assert trade.open_date_utc == original


def test_normal_pair_lock_does_not_emit_data_warning(caplog):
    from unittest.mock import Mock

    import pandas as pd

    strategy = _entry_ready_strategy(NOW)
    del strategy._entry_pair_available
    strategy.dp = SimpleNamespace(current_whitelist=lambda: [PAIR])
    strategy._closed_candles = Mock(
        return_value=pd.DataFrame({"date": [pd.Timestamp("2026-01-01", tz="UTC")]})
    )
    strategy.is_pair_locked = Mock(return_value=True)
    with caplog.at_level(logging.WARNING, logger="leader_squeeze_strategy"):
        assert not strategy._entry_pair_available(PAIR)
    assert "交易锁生效" in strategy._pair_entry_block_reason
    assert not any("数据不可用" in record.getMessage() for record in caplog.records)
