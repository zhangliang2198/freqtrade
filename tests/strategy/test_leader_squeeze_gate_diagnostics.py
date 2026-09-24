"""全局闸门拦截时的可观测性: 明细表必须写清原因, 而不是兜底文案"尚未评估"。

另外锁定两条防回归契约:
- 审计快照属于序列化路径, 不得按票刷"数据不可用"警告;
- 覆盖快照按K线桶冻结, 桶内数据补齐后必须重新探测, 否则一次取数延迟会变成
  最长 15 分钟的开仓暂停。
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rich.text import Text

from tests.strategy.leader_squeeze_test_helpers import configured_settings
from tests.strategy.test_leader_squeeze_strategy import (
    MODULE,
    LeaderSqueezeStrategy,
    _entry_ready_strategy,
    _fresh_score_metric,
)


PAIR = "BTC/USDT:USDT"
HELD = "ETH/USDT:USDT"
MISSING = "MISSING/USDT:USDT"
NOW = 1_000.0
GATE = "龙头K线覆盖不足"


def _plain(value: object) -> str:
    return value.plain if isinstance(value, Text) else str(value)


def _blocked_strategy() -> LeaderSqueezeStrategy:
    """闸门关闭、评分池有两只票的固定现场。"""
    strategy = _entry_ready_strategy(NOW)
    strategy.settings = configured_settings()
    strategy._scores = {PAIR: 80.0, HELD: 40.0}
    strategy._metrics = {pair: _fresh_score_metric() for pair in strategy._scores}
    strategy._entries_allowed = Mock(return_value=False)
    strategy._entry_block_reason = GATE
    return strategy


def test_blocked_gate_records_reason_for_every_scored_pair() -> None:
    strategy = _blocked_strategy()
    held_trade = SimpleNamespace(pair=HELD)

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[held_trade]):
        assert strategy._select_entries() == set()

    assert strategy._entry_decisions[PAIR] == f"全局闸门: {GATE}"
    # 持仓票不能被全局原因覆盖: 它本来就不会被筛选。
    assert strategy._entry_decisions[HELD] == "已持仓"


def test_market_candle_coverage_expiry_blocks_entries_before_next_pool_retry() -> None:
    strategy = _entry_ready_strategy(NOW)
    strategy._market_valid_until = NOW + 5

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._entries_allowed(NOW)
        assert not strategy._entries_allowed(NOW + 6)

    assert "龙头K线覆盖不足或过期" in strategy._entry_block_reason


def test_empty_core_snapshot_does_not_bypass_reprobe_throttle_in_bot_loop() -> None:
    strategy = _entry_ready_strategy(NOW)
    strategy._prune_pending_entry_scores = Mock()
    strategy._last_position_sync = NOW + 5
    strategy._sync_external_pairs = Mock()
    strategy._risk_state = {"account_stopped": False}
    strategy._eth_entries_allowed = Mock(return_value=True)
    strategy._eth_trend = "上涨"
    strategy._eth_last_log_reason = "上涨"
    strategy._eth_last_log_time = NOW + 5
    pools = {
        "core": [PAIR],
        "discovery": [],
        "scouts": [],
        "candidates": [],
        "score": [],
        "core_candles": {},
    }
    strategy._pools_for_loop = Mock(return_value=pools)
    strategy._pools_cache = pools
    strategy._core_coverage_probe_at = NOW
    strategy._candle_metrics = Mock(return_value=None)
    strategy._consume_score_refresh = Mock()
    strategy._advance_score_refresh = Mock()
    strategy._next_score_refresh = float("inf")
    strategy._score_pending = False
    strategy._update_profit_shadow = Mock()
    strategy._refresh_risk_state = Mock()
    strategy._sync_rotation_state = Mock()
    strategy._plan_rotation = Mock()
    strategy._select_entries = Mock(return_value=set())
    strategy._log_strategy_status = Mock()

    with patch.object(MODULE.time, "time", return_value=NOW + 5):
        strategy.bot_loop_start(datetime.fromtimestamp(NOW + 5, UTC))

    strategy._candle_metrics.assert_not_called()
    assert not strategy._market_data_healthy


def test_score_table_shows_gate_reason_instead_of_unevaluated(caplog) -> None:
    strategy = _blocked_strategy()
    strategy._entry_decisions = {}
    strategy._current_score = Mock(return_value=80.0)
    strategy._trend_labels = Mock(return_value=("上行", "上行"))
    strategy._entry_heat_metrics = Mock(return_value=None)
    snapshot = {
        "now": NOW,
        "valid": {
            PAIR: _fresh_score_metric(
                score_momentum=1.0, score_volume=1.0, score_taker_buy=1.0, score_funding=0.0
            )
        },
        "scores": {PAIR: 80.0},
        "ranks": {PAIR: "1"},
        "selected": (PAIR,),
    }

    with (
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
    ):
        strategy._render_score_report(snapshot, report_now=NOW)

    records = [record for record in caplog.records if hasattr(record, "strategy_log_table")]
    assert len(records) == 1
    table = records[0].strategy_log_table
    headers = [column.header for column in table.columns]
    decision_column = headers.index("筛选结果")
    assert _plain(table.columns[decision_column]._cells[0]) == GATE
    assert "尚未评估" not in records[0].getMessage()
    assert f"全局开仓={GATE}" in table.caption.plain


def test_score_table_still_prefers_recorded_decisions(caplog) -> None:
    strategy = _blocked_strategy()
    strategy._entry_decisions = {PAIR: "末端过热: 偏离6.1ATR >= 5.0ATR"}
    strategy._current_score = Mock(return_value=80.0)
    strategy._trend_labels = Mock(return_value=("上行", "上行"))
    strategy._entry_heat_metrics = Mock(return_value=None)
    snapshot = {
        "now": NOW,
        "valid": {
            PAIR: _fresh_score_metric(
                score_momentum=1.0, score_volume=1.0, score_taker_buy=1.0, score_funding=0.0
            )
        },
        "scores": {PAIR: 80.0},
        "ranks": {PAIR: "1"},
        "selected": (PAIR,),
    }

    with (
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
    ):
        strategy._render_score_report(snapshot, report_now=NOW)

    records = [record for record in caplog.records if hasattr(record, "strategy_log_table")]
    table = records[0].strategy_log_table
    headers = [column.header for column in table.columns]
    decision_column = headers.index("筛选结果")
    assert _plain(table.columns[decision_column]._cells[0]).startswith("末端过热")


def test_core_coverage_reprobe_fills_only_missing_pairs() -> None:
    strategy = _blocked_strategy()
    fresh = _fresh_score_metric(_candle_valid_until=NOW + 900)
    strategy._core_pairs = [PAIR, HELD, MISSING]
    strategy._pools_cache = {"core_candles": {PAIR: fresh, HELD: fresh}}
    strategy._candle_metrics = Mock(return_value=fresh)

    strategy._reprobe_core_coverage(NOW)

    assert strategy._pools_cache["core_candles"][MISSING] is fresh
    strategy._candle_metrics.assert_called_once_with(MISSING)

    # 节流: score_retry_seconds 之内不再重复探测, 避免每个 5 秒循环扫一遍核心池。
    strategy._candle_metrics.reset_mock()
    strategy._pools_cache["core_candles"].pop(MISSING)
    strategy._reprobe_core_coverage(NOW + 1)
    strategy._candle_metrics.assert_not_called()

    # 间隔到点后重新探测, 覆盖率随分子补齐而恢复, 门槛本身不变。
    strategy._reprobe_core_coverage(NOW + float(strategy.settings["score_retry_seconds"]))
    strategy._update_market_state(strategy._core_pairs, strategy._pools_cache["core_candles"])
    assert strategy._market_data_healthy


def test_core_coverage_reprobe_keeps_gate_shut_when_data_is_still_missing() -> None:
    strategy = _blocked_strategy()
    strategy._core_pairs = [PAIR, HELD, MISSING]
    strategy._pools_cache = {"core_candles": {}}
    strategy._candle_metrics = Mock(return_value=None)

    strategy._reprobe_core_coverage(NOW)
    strategy._update_market_state(strategy._core_pairs, strategy._pools_cache["core_candles"])

    assert not strategy._market_data_healthy
    probed_pairs = [call.args[0] for call in strategy._candle_metrics.call_args_list]
    assert probed_pairs == strategy._core_pairs


def test_audit_snapshot_suppresses_only_its_own_threads_data_warnings(caplog) -> None:
    """快照内的静默只作用于当前上下文: 后台评分线程的告警不能被一起吞掉。"""
    strategy = _blocked_strategy()
    strategy._rotation_journal = Mock()
    strategy._audit_run_id = "test-run"
    strategy._audit_fingerprints = {}
    other_thread_key = "后台线程 评分指标"

    def snapshot() -> dict:
        strategy._warn_data_unavailable(f"{PAIR} 评分指标", "缓存缺失或已过期, 等待新指标")
        worker = threading.Thread(
            target=strategy._warn_data_unavailable,
            args=(other_thread_key, "缓存缺失或已过期, 等待新指标"),
        )
        worker.start()
        worker.join()
        return {"pairs": {}}

    strategy._rotation_snapshot = Mock(side_effect=snapshot)

    with caplog.at_level(logging.WARNING, logger="leader_squeeze_strategy"):
        strategy._record_rotation_event("blocked", GATE, once=False)

    messages = [record.getMessage() for record in caplog.records]
    assert not [message for message in messages if PAIR in message]
    assert [message for message in messages if other_thread_key in message]

    # 快照结束后必须复位, 否则真实决策路径的告警会被一起吞掉。
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="leader_squeeze_strategy"):
        strategy._warn_data_unavailable(f"{PAIR} 评分指标", "缓存缺失或已过期, 等待新指标")
    assert [record for record in caplog.records if "数据不可用" in record.getMessage()]
