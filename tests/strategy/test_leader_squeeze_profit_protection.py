"""Profit protection: the read-only shadow ledger plus the gated ratchet and momentum stop.

The shadow ledger must remain read-only.  The production execution gates are
enabled, while individual tests still cover their disabled paths explicitly.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
)
from tests.strategy.test_leader_squeeze_strategy import (
    MODULE,
    LeaderSqueezeStrategy,
    _entry_ready_strategy,
)


PAIR = "BTC/USDT:USDT"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
FLAT = (100.5, 99.5, 100.0)
ARM = [FLAT] * 38 + [(110.0, 99.0, 108.0)]
ENTRY = 100.0
LEVERAGE = 5.0
FEE_FLOOR_TARGET = ENTRY * (1 + 0.0025)


def _frame(hours, shift=0):
    """展开 1h 序列 (high, low, close) 为对齐的 15m K 线。

    shift 以整小时前移整段历史, 用于模拟"又一根 1h K 线收盘"; 影子账本以
    holding_timeframe(1h) 为回放粒度, 所以必须整小时推进才能产生新 K 线。
    """
    highs, lows, closes = [], [], []
    for high, low, close in hours:
        for _ in range(4):
            highs.append(high)
            lows.append(low)
            closes.append(close)
    total = len(closes)
    return pd.DataFrame(
        {
            "date": pd.date_range(end=NOW + shift * HOUR, periods=total, freq="15min")
            - pd.Timedelta(minutes=15),
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": 100.0,
        }
    )


class _Trade:
    """最小 Trade 替身; calc_profit_ratio 不含费用, 因此断言用简单杠杆公式。"""

    def __init__(
        self,
        pair=PAIR,
        entry=ENTRY,
        leverage=LEVERAGE,
        trade_id=1,
        stop_loss=None,
        open_hours_ago=1,
        max_rate=None,
    ):
        self.pair = pair
        self.open_rate = entry
        self.leverage = leverage
        self.id = trade_id
        self.open_date_utc = NOW - timedelta(hours=open_hours_ago)
        self.is_short = False
        self.max_rate = entry if max_rate is None else max_rate
        self.stop_loss = entry * (1 - 1.0 / leverage) if stop_loss is None else stop_loss

    def calc_profit_ratio(self, price):
        return (float(price) / self.open_rate - 1.0) * self.leverage


def _strategy(frame, tmp_path, **settings):
    strategy = _entry_ready_strategy(NOW.timestamp())
    strategy.settings = configured_settings()
    strategy.settings.update(settings)
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=frame))
    strategy.config = {**PUBLIC_CONFIG, "user_data_dir": str(tmp_path), "dry_run": True}
    strategy._profit_shadow = {}
    strategy._profit_pending_archives = {}
    strategy._profit_totals = None
    strategy._last_profit_summary = -math.inf
    strategy._profit_lock_failures = 0
    strategy._risk_state = {}
    strategy._data_warning_times = {}
    strategy._exit_log_reasons = {}
    return strategy


def _shadow_file(tmp_path):
    return tmp_path / "strategies/leader_squeeze/runtime/profit_shadow.jsonl"


def _update(strategy, trades, clock=NOW):
    # _closed_candles 用 time.time() 判定"已收盘", 必须与构造的 K 线同一时钟。
    with (
        patch.object(MODULE.time, "time", return_value=clock.timestamp()),
        patch.object(MODULE.Trade, "get_open_trades", return_value=list(trades)),
    ):
        strategy._update_profit_shadow(clock.timestamp(), clock)


def _armed_strategy(tmp_path, **settings):
    """跑一根把浮盈推过 1R 的 K 线, 返回已武装棘轮的策略与记录。"""
    strategy = _strategy(_frame(ARM), tmp_path, **settings)
    # _trend_candles keeps 23 complete 1h buckets.  Put the entry before that
    # window so the final ARM bucket is genuinely post-entry history.
    trade = _Trade(open_hours_ago=22)
    _update(strategy, [trade])
    return strategy, trade


def _ratchet_record(strategy, trade, *, r_price=2.0, peak_price=ENTRY):
    """Install a deterministic R-based execution record for hook tests."""
    record = strategy._new_profit_record(trade, r_price / 1.5)
    record.update(
        r_price=r_price,
        peak_price=peak_price,
        progress_high_price=peak_price,
        current_price=peak_price,
        shadow_stop_price=ENTRY * 0.8,
    )
    strategy._profit_shadow = {PAIR: record}
    return record


# ------------------------------------------------------------------ R 单位


def test_r_price_scales_entry_atr_and_clamps_to_the_configured_band(tmp_path):
    strategy = _strategy(None, tmp_path)
    assert strategy._profit_r_price(ENTRY, 2.0) == pytest.approx(3.0)
    # ATR 过小 -> 抬到下限, 避免棘轮几乎一开仓就武装
    assert strategy._profit_r_price(ENTRY, 0.01) == pytest.approx(ENTRY * 0.008)
    # ATR 过大 -> 压到上限
    assert strategy._profit_r_price(ENTRY, 100.0) == pytest.approx(ENTRY * 0.12)
    assert strategy._profit_r_price(ENTRY, None) is None
    assert strategy._profit_r_price(0.0, 1.0) is None


def test_r_price_uses_the_configured_multiple(tmp_path):
    strategy = _strategy(None, tmp_path, profit_r_atr_multiple=3.0)
    assert strategy._profit_r_price(ENTRY, 2.0) == pytest.approx(6.0)


# ------------------------------------------------------------------ 影子账本


def test_shadow_records_peak_profit_and_giveback_then_archives_to_jsonl(tmp_path):
    strategy = _strategy(_frame([FLAT] * 39 + [(130.0, 99.0, 105.0)]), tmp_path)
    trade = _Trade()
    strategy._closed_profit_evidence = Mock(
        return_value={
            "actual_profit_ratio": -0.10,
            "actual_close_price": 98.0,
            "actual_closed_at": NOW.timestamp(),
            "actual_profit_source": "framework",
        }
    )
    _update(strategy, [trade])
    record = strategy._profit_shadow[PAIR]
    # Reconstructed records are archived but excluded from the in-memory
    # aggregate; mark this fixture as an entry-fill sample for the totals.
    record["context_source"] = "entry_fill"
    assert record["peak_price"] == pytest.approx(130.0)
    assert record["peak_profit_ratio"] == pytest.approx(1.5)
    assert record["last_profit_ratio"] == pytest.approx(0.25)
    assert record["r_price"] == pytest.approx(1.5 * record["entry_atr"])

    _update(strategy, [])
    assert PAIR not in strategy._profit_shadow
    assert strategy._profit_totals["closed"] == 1
    assert strategy._profit_totals["giveback_sum"] == pytest.approx(1.60)
    archived = json.loads(_shadow_file(tmp_path).read_text().strip())
    assert archived["pair"] == PAIR
    assert archived["actual_profit_ratio"] == pytest.approx(-0.10)
    assert archived["giveback_ratio"] == pytest.approx(1.60)
    assert archived["duration_minutes"] == pytest.approx(60.0)


@pytest.mark.parametrize(
    ("peak_r", "expected_lock_r"),
    [(1.0, 0.125), (2.0, 0.5), (3.0, 1.5), (5.0, 3.5)],
)
def test_shadow_ratchet_locks_expected_r_levels(tmp_path, peak_r, expected_lock_r):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade(max_rate=ENTRY)
    record = _ratchet_record(strategy, trade, r_price=2.0)
    peak = ENTRY + peak_r * record["r_price"]
    strategy._simulate_profit_bar(
        record,
        trade,
        peak,
        peak,
        peak,
        ENTRY,
        record["entry_atr"],
        None,
    )
    assert record["shadow_lock_stop_price"] == pytest.approx(
        ENTRY + expected_lock_r * record["r_price"]
    )
    assert strategy._profit_r_of(record, record["shadow_lock_stop_price"]) == pytest.approx(
        expected_lock_r
    )


def test_shadow_reports_a_plain_stoploss_exit_when_never_armed(tmp_path):
    strategy = _strategy(_frame([FLAT] * 39 + [(100.5, 75.0, 78.0)]), tmp_path)
    _update(strategy, [_Trade()])
    record = strategy._profit_shadow[PAIR]
    assert record["shadow_lock_stop_price"] is None
    assert record["shadow_exit_reason"] == "stoploss"
    assert record["shadow_exit_price"] == pytest.approx(ENTRY * (1 - 1.0 / LEVERAGE))


def test_shadow_stop_touch_is_conservative_within_a_bar(tmp_path):
    """同一根K线先判断原止损, 不假设先冲高后回落。"""
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade(max_rate=ENTRY + 4.0)
    record = _ratchet_record(strategy, trade, r_price=2.0, peak_price=ENTRY + 4.0)
    record["shadow_lock_stop_price"] = ENTRY + 1.0
    record["shadow_stop_price"] = ENTRY + 1.0
    strategy._simulate_profit_bar(
        record,
        trade,
        ENTRY + 10.0,
        ENTRY + 0.5,
        ENTRY + 9.0,
        ENTRY,
        record["entry_atr"],
        None,
    )
    assert record["shadow_exit_reason"] == "ratchet"
    assert record["shadow_exit_price"] == pytest.approx(ENTRY + 1.0)
    assert record["shadow_exit_price"] < ENTRY + 10.0 - 1.5 * record["r_price"]


def test_shadow_no_progress_exit_uses_the_real_trend_context(tmp_path):
    descending = [(100.0 - i * 0.5, 98.0 - i * 0.5, 99.5 - i * 0.5) for i in range(1, 9)]
    strategy = _strategy(_frame([FLAT] * 39 + descending), tmp_path)
    trade = _Trade(open_hours_ago=8)
    strategy._profit_shadow = {
        PAIR: strategy._new_profit_record(trade, 1.0, context_source="entry_fill")
    }
    _update(strategy, [trade])
    record = strategy._profit_shadow[PAIR]
    assert record["shadow_exit_reason"] == "no_progress"
    assert record["no_progress"] is True


def test_shadow_is_skipped_when_disabled(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_shadow_enabled=False)
    _update(strategy, [_Trade()])
    assert strategy._profit_shadow == {}
    assert not _shadow_file(tmp_path).exists()


def test_disabled_shadow_does_not_capture_entry_context(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_shadow_enabled=False)
    strategy._profit_entry_atr = Mock(return_value=2.0)
    strategy._capture_profit_entry_context(_Trade())
    assert strategy._profit_shadow == {}
    strategy._profit_entry_atr.assert_not_called()


def test_shadow_rebuilds_a_missing_record_from_the_open_trade(tmp_path):
    """重启后内存为空时, 由未平仓仓位自动重建而不是丢统计。"""
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    strategy._profit_shadow = {}
    _update(strategy, [_Trade()])
    assert strategy._profit_shadow[PAIR]["entry_price"] == pytest.approx(ENTRY)
    assert strategy._profit_shadow[PAIR]["trade_id"] == 1


def test_reconstructed_record_restarts_the_no_progress_clock(tmp_path):
    """A persisted peak has no timestamp, so pre-restart bars cannot prove a stall."""
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade(open_hours_ago=10, max_rate=110.0)
    _update(strategy, [trade])
    record = strategy._profit_shadow[PAIR]
    assert record["peak_price"] == pytest.approx(110.0)
    assert record["bars_seen"] > 0
    assert record["bars_since_new_high"] == 0
    assert record["progress_tracking_from_ts"] == pytest.approx(NOW.timestamp())


def test_invalid_same_trade_record_is_replaced_when_the_entry_fill_arrives(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade()
    strategy._profit_shadow = {PAIR: {"trade_id": trade.id, "entry_price": ENTRY}}
    strategy._profit_entry_atr = Mock(return_value=2.0)

    strategy._capture_profit_entry_context(trade)

    record = strategy._profit_shadow[PAIR]
    assert record["context_source"] == "entry_fill"
    assert record["r_price"] == pytest.approx(3.0)
    assert strategy._valid_profit_record(PAIR, record) is True


def test_missing_entry_atr_is_retried_without_overwriting_a_frozen_r(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade()
    strategy._profit_entry_atr = Mock(side_effect=[None, 2.0, 9.0])
    strategy._capture_profit_entry_context(trade)
    assert strategy._profit_shadow[PAIR]["r_price"] is None

    _update(strategy, [trade])
    record = strategy._profit_shadow[PAIR]
    assert record["entry_atr"] == pytest.approx(2.0)
    assert record["r_price"] == pytest.approx(3.0)

    _update(strategy, [trade], NOW + HOUR)
    assert record["entry_atr"] == pytest.approx(2.0)
    assert record["r_price"] == pytest.approx(3.0)
    assert strategy._profit_entry_atr.call_count == 2


def test_shadow_replaces_a_record_when_the_trade_id_changes(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    strategy._profit_shadow[PAIR] = {"trade_id": 99, "entry_price": 50.0, "peak_price": 50.0}
    _update(strategy, [_Trade(trade_id=7)])
    assert strategy._profit_shadow[PAIR]["trade_id"] == 7
    assert strategy._profit_shadow[PAIR]["entry_price"] == pytest.approx(ENTRY)


def test_shadow_ignores_all_candles_before_the_trade_opened(tmp_path):
    strategy = _strategy(_frame([(130.0, 70.0, 90.0)] + [FLAT] * 39), tmp_path)
    _update(strategy, [_Trade(open_hours_ago=1)])
    record = strategy._profit_shadow[PAIR]
    assert record["bars_seen"] == 1
    assert record["peak_price"] == pytest.approx(100.5)
    assert record["shadow_lock_stop_price"] is None
    assert record["shadow_exit_price"] is None


def test_corrupt_current_version_record_is_rebuilt_instead_of_raising(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    record = strategy._new_profit_record(_Trade(), 1.0)
    record.pop("pair")
    strategy._profit_shadow = {PAIR: record}
    _update(strategy, [_Trade()])
    assert strategy._profit_shadow[PAIR]["pair"] == PAIR
    assert strategy._profit_shadow[PAIR]["version"] == strategy._PROFIT_RECORD_VERSION


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("entry_atr", -1.0),
        ("r_price", -1.0),
        ("shadow_stop_price", 0.0),
        ("execution_lock_stop_price", -1.0),
    ],
)
def test_semantically_invalid_profit_record_is_rejected(tmp_path, key, value):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    record = strategy._new_profit_record(_Trade(), 1.0)
    record[key] = value
    assert strategy._valid_profit_record(PAIR, record) is False


def test_version_two_record_migrates_without_reusing_the_old_progress_clock(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    record = strategy._new_profit_record(_Trade(), 1.0)
    record.update(
        version=2,
        peak_price=110.0,
        bars_since_new_high=7,
        no_progress_setup=True,
        no_progress=True,
    )
    record.pop("progress_high_price")

    assert strategy._valid_profit_record(PAIR, record) is True
    assert record["version"] == strategy._PROFIT_RECORD_VERSION
    assert record["context_source"] == "reconstructed"
    assert record["progress_high_price"] == pytest.approx(110.0)
    assert record["bars_since_new_high"] == 0
    assert record["no_progress_setup"] is False
    assert record["no_progress"] is False


def test_reopened_pair_keeps_the_closed_trade_pending_until_profit_is_verified(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    old = strategy._new_profit_record(_Trade(trade_id=1), 1.0, context_source="entry_fill")
    strategy._profit_shadow = {PAIR: old}
    strategy._closed_profit_evidence = Mock(return_value=None)
    _update(strategy, [_Trade(trade_id=2)])
    assert strategy._profit_shadow[PAIR]["trade_id"] == 2
    assert strategy._profit_pending_archives["1"] is old


def test_failed_archive_write_keeps_the_record_for_retry(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    record = strategy._new_profit_record(_Trade(), 1.0, context_source="entry_fill")
    strategy._profit_shadow = {PAIR: record}
    strategy._closed_profit_evidence = Mock(
        return_value={
            "actual_profit_ratio": 0.1,
            "actual_close_price": 102.0,
            "actual_closed_at": NOW.timestamp(),
            "actual_profit_source": "framework",
        }
    )
    strategy._append_profit_shadow = Mock(return_value=False)
    _update(strategy, [])
    assert PAIR not in strategy._profit_shadow
    assert strategy._profit_pending_archives["1"] is record


def test_archive_retry_is_idempotent_after_a_crash_before_checkpoint(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    record = strategy._new_profit_record(_Trade(), 1.0, context_source="entry_fill")
    record["archive_key"] = "trade:1"
    assert strategy._append_profit_shadow(record) is True
    assert strategy._append_profit_shadow(record) is True
    assert len(_shadow_file(tmp_path).read_text().splitlines()) == 1


@pytest.mark.parametrize(
    "outcome", [float("inf"), float("-inf"), float("nan"), ZeroDivisionError()]
)
def test_non_finite_profit_ratio_is_rejected(tmp_path, outcome):
    """Invalid ratios must stay out of persistent aggregate samples."""
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade()
    if isinstance(outcome, Exception):
        trade.calc_profit_ratio = Mock(side_effect=outcome)
    else:
        trade.calc_profit_ratio = Mock(return_value=outcome)
    assert strategy._profit_ratio_at(trade, ENTRY) is None


# ------------------------------------------------------------------ 只读保证


def test_shadow_ledger_is_read_only_when_both_gates_are_off(tmp_path):
    strategy, trade = _armed_strategy(
        tmp_path,
        profit_lock_enabled=False,
        profit_no_progress_enabled=False,
    )
    assert strategy.settings["profit_lock_enabled"] is False
    assert strategy.settings["profit_no_progress_enabled"] is False
    assert strategy._profit_shadow[PAIR]["shadow_lock_stop_price"] is not None
    strategy._profit_shadow[PAIR]["no_progress"] = True

    assert strategy.custom_stoploss(PAIR, trade, NOW, 108.0, 0.4, False) is None
    strategy._market_exit_required = Mock(return_value=False)
    strategy._rotation_exit_allowed = Mock(return_value=False)
    strategy._trend_reversed = Mock(return_value=False)
    assert strategy.custom_exit(PAIR, trade, NOW, 108.0, 0.4) is None


def test_custom_stoploss_hook_is_enabled_on_the_strategy_class():
    """钩子必须始终注册, 否则关闭开关时框架不会回调, 打开后也不会生效。"""
    assert LeaderSqueezeStrategy.use_custom_stoploss is True


# ------------------------------------------------------------------ 保本棘轮


def test_custom_stoploss_returns_none_before_one_r(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_lock_enabled=True)
    _update(strategy, [_Trade()])
    assert strategy._profit_shadow[PAIR]["shadow_lock_stop_price"] is None
    assert strategy.custom_stoploss(PAIR, _Trade(), NOW, 100.2, 0.01, False) is None


def test_custom_stoploss_arms_from_persisted_peak_below_current_one_r(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_lock_enabled=True)
    trade = _Trade(max_rate=ENTRY + 2.0)
    record = _ratchet_record(strategy, trade, r_price=2.0)
    value = strategy.custom_stoploss(PAIR, trade, NOW, ENTRY + 0.5, 0.0, False)
    assert value is not None
    assert record["execution_lock_armed_at"] is not None
    assert record["execution_lock_stop_price"] == pytest.approx(ENTRY + 0.25)
    # 框架公式: stop = current_rate * (1 - |value| / leverage)
    stop = (ENTRY + 0.5) * (1 - abs(value) / LEVERAGE)
    assert stop == pytest.approx(ENTRY + 0.25)


def test_custom_stoploss_uses_the_r_based_peak_trail(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_lock_enabled=True)
    trade = _Trade(max_rate=ENTRY + 10.0)
    record = _ratchet_record(strategy, trade, r_price=2.0)
    value = strategy.custom_stoploss(PAIR, trade, NOW, ENTRY + 8.0, 0.0, False)
    assert value is not None
    stop = (ENTRY + 8.0) * (1 - abs(value) / LEVERAGE)
    assert stop == pytest.approx(record["execution_lock_stop_price"])
    assert stop == pytest.approx(ENTRY + 7.0)
    assert strategy._profit_r_of(record, stop) == pytest.approx(3.5)
    assert record["peak_profit_ratio"] == pytest.approx(0.5)
    assert record["peak_profit_r"] == pytest.approx(5.0)


def test_custom_stoploss_skips_updates_below_the_minimum_step(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_lock_enabled=True)
    # 目标101, 当前止损100.95, 小于0.1R的改单步长 -> 不改单。
    trade = _Trade(stop_loss=ENTRY + 0.95, max_rate=ENTRY + 4.0)
    record = _ratchet_record(strategy, trade, r_price=2.0)
    assert strategy.custom_stoploss(PAIR, trade, NOW, ENTRY + 4.0, 0.0, False) is None
    assert record["execution_lock_stop_price"] == pytest.approx(ENTRY + 1.0)


def test_custom_stoploss_ignores_a_target_above_the_current_rate(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_lock_enabled=True)
    trade = _Trade(max_rate=ENTRY + 4.0)
    record = _ratchet_record(strategy, trade, r_price=2.0)
    # 当前价低于目标价时不返回无效止损, 但必须保留已武装目标。
    assert strategy.custom_stoploss(PAIR, trade, NOW, ENTRY, 0.0, False) is None
    assert record["execution_lock_stop_price"] == pytest.approx(ENTRY + 1.0)
    assert strategy.custom_stoploss(PAIR, trade, NOW, ENTRY + 2.0, 0.0, False) is not None


def test_custom_stoploss_ignores_untracked_pairs(tmp_path):
    strategy, _ = _armed_strategy(tmp_path, profit_lock_enabled=True)
    other = _Trade(pair="ETH/USDT:USDT")
    assert strategy.custom_stoploss("ETH/USDT:USDT", other, NOW, 108.0, 0.4, False) is None


def test_custom_stoploss_swallows_errors_and_counts_them(tmp_path):
    strategy, trade = _armed_strategy(tmp_path, profit_lock_enabled=True)
    strategy._profit_lock_stoploss = Mock(side_effect=RuntimeError("boom"))
    assert strategy.custom_stoploss(PAIR, trade, NOW, 108.0, 0.4, False) is None
    assert strategy._profit_lock_failures == 1


def test_profit_position_table_shows_each_live_protection_state(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade(max_rate=110.0)
    record = _ratchet_record(strategy, trade, r_price=2.0, peak_price=110.0)
    record["execution_lock_stop_price"] = 107.0
    record["bars_since_new_high"] = 3
    strategy._position_details = {PAIR: {"markPrice": "108"}}
    strategy._profit_no_progress_trend = Mock(return_value="weakening")

    log_table = Mock()
    with patch.dict(
        strategy._log_profit_position_table.__func__.__globals__, {"_log_table": log_table}
    ):
        strategy._log_profit_position_table(NOW.timestamp(), {PAIR: trade})

    assert log_table.call_args.args[0] == "🛡️ 盈利保护状态"
    row = log_table.call_args.args[2][0]
    assert row[0] == PAIR
    assert row[4] == "已武装"
    assert row[5] == "107"
    assert row[7] == "3/8"
    assert row[8] == "weakening"


# ------------------------------------------------------------------ 动量止损


@pytest.mark.parametrize(
    ("bars_since_new_high", "trend_state", "expected"),
    [
        (8, "consolidating", False),
        (8, "weakening", True),
        (7, "weakening", False),
        (8, "up", False),
    ],
)
def test_no_progress_requires_eight_post_high_bars_and_weakening_trend(
    tmp_path, bars_since_new_high, trend_state, expected
):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    record = {
        "r_price": 3.0,
        "entry_price": ENTRY,
        "bars_since_new_high": bars_since_new_high,
    }
    assert strategy._profit_no_progress_setup(record, trend_state) is expected


def test_no_progress_is_false_without_an_r_unit(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    record = {"r_price": None, "entry_price": ENTRY, "no_progress_setup": True}
    assert strategy._profit_no_progress_at_price(record, ENTRY) is False


def test_progress_high_requires_a_meaningful_rise_before_resetting_stall(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade(open_hours_ago=10)
    record = strategy._new_profit_record(trade, 2.0, context_source="entry_fill")
    record.update(
        r_price=2.0,
        peak_price=100.5,
        progress_high_price=100.5,
        progress_tracking_from_ts=0.0,
        bars_since_new_high=0,
    )
    highs = [100.6, 100.7, 100.8, 100.9, 100.9, 100.8, 100.9, 100.8]
    for index, high in enumerate(highs):
        record["last_bar_ts"] = index
        strategy._simulate_profit_bar(
            record,
            trade,
            high,
            99.0,
            100.1,
            ENTRY,
            2.0,
            "weakening" if index == 7 else None,
        )
    assert record["peak_price"] == pytest.approx(100.9)
    assert record["progress_high_price"] == pytest.approx(100.5)
    assert record["bars_since_new_high"] == 8
    assert record["no_progress_setup"] is True

    record["last_bar_ts"] += 1
    strategy._simulate_profit_bar(
        record,
        trade,
        101.1,
        101.0,
        101.05,
        ENTRY,
        2.0,
        "weakening",
    )
    assert record["progress_high_price"] == pytest.approx(101.1)
    assert record["bars_since_new_high"] == 0
    assert record["no_progress_setup"] is False


def test_shadow_ratchet_exit_does_not_freeze_the_no_progress_lane(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    trade = _Trade(open_hours_ago=10)
    record = strategy._new_profit_record(trade, 2.0, context_source="entry_fill")
    record.update(
        peak_price=110.0,
        progress_high_price=110.0,
        progress_tracking_from_ts=0.0,
        bars_since_new_high=7,
        shadow_exit_price=FEE_FLOOR_TARGET,
        shadow_exit_reason="ratchet",
    )
    strategy._simulate_profit_bar(
        record,
        trade,
        109.0,
        99.0,
        100.1,
        ENTRY,
        2.0,
        "weakening",
    )
    assert record["shadow_exit_reason"] == "ratchet"
    assert record["bars_since_new_high"] == 8
    assert record["no_progress_setup"] is True
    assert record["no_progress"] is True


def test_custom_exit_reports_leader_no_progress_when_enabled(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_no_progress_enabled=True)
    strategy._profit_shadow = {
        PAIR: {
            "entry_price": ENTRY,
            "r_price": 3.0,
            "trade_id": 1,
            "no_progress_setup": True,
        }
    }
    strategy._market_exit_required = Mock(return_value=False)
    strategy._rotation_exit_allowed = Mock(return_value=False)
    strategy._trend_reversed = Mock(return_value=False)
    assert strategy.custom_exit(PAIR, _Trade(), NOW, ENTRY + 0.1, 0.0) == "leader_no_progress"


def test_custom_exit_rechecks_no_progress_against_the_current_rate(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_no_progress_enabled=True)
    strategy._profit_shadow = {
        PAIR: {
            "entry_price": ENTRY,
            "r_price": 3.0,
            "trade_id": 1,
            "no_progress_setup": True,
        }
    }
    strategy._market_exit_required = Mock(return_value=False)
    strategy._rotation_exit_allowed = Mock(return_value=False)
    strategy._trend_reversed = Mock(return_value=False)
    trade = _Trade()
    assert strategy.custom_exit(PAIR, trade, NOW, ENTRY + 2.0, 0.0) is None
    assert strategy.custom_exit(PAIR, trade, NOW, ENTRY + 0.1, 0.0) == "leader_no_progress"


def test_no_progress_exit_yields_to_the_stronger_reasons(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_no_progress_enabled=True)
    strategy._profit_shadow = {PAIR: {"no_progress": True}}
    strategy._market_exit_required = Mock(return_value=False)
    strategy._rotation_exit_allowed = Mock(return_value=False)
    strategy._trend_reversed = Mock(return_value=True)
    strategy._trend_exit_rule = Mock(return_value="多周期趋势退出")
    assert strategy.custom_exit(PAIR, _Trade(), NOW, ENTRY, 0.0) == "trend_reversal"


def test_no_progress_exit_ignores_pairs_without_a_shadow_record(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_no_progress_enabled=True)
    strategy._profit_shadow = {}
    assert strategy._profit_no_progress_exit(PAIR, _Trade(), ENTRY) is False


# ------------------------------------------------------------------ 配置校验


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("profit_r_atr_multiple", 0.0),
        ("profit_r_atr_multiple", -1.0),
        ("profit_lock_arm_r", 0.0),
        ("profit_lock_fee_buffer", -0.001),
        ("profit_lock_fee_buffer", 0.2),
        ("profit_lock_trail_r", -1.0),
        ("profit_lock_min_step_r", -1.0),
        ("profit_no_progress_new_high_r", 0.0),
        ("profit_no_progress_new_high_r", -1.0),
        ("profit_no_progress_max_r", float("nan")),
        ("profit_no_progress_max_r", -0.1),
        ("profit_no_progress_max_r", 1.0),
        ("profit_r_min_pct", 0.0),
        ("profit_r_max_pct", 0.9),
        ("profit_shadow_file_live", ""),
        ("profit_shadow_file_live", 123),
    ],
)
def test_invalid_profit_settings_are_rejected(tmp_path, key, value):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path)
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        MODULE.validate_runtime_settings(strategy)


def test_profit_protection_requires_the_shadow_ledger(tmp_path):
    strategy = _strategy(_frame([FLAT] * 40), tmp_path, profit_lock_enabled=True)
    strategy.settings["profit_shadow_enabled"] = False
    with pytest.raises(ValueError, match="profit_shadow_enabled"):
        MODULE.validate_runtime_settings(strategy)


def test_production_config_enables_profit_protection(tmp_path):
    """生产配置开启影子账本及两道盈利保护执行闸门。"""
    settings = configured_settings()
    assert settings["profit_shadow_enabled"] is True
    assert settings["profit_lock_enabled"] is True
    assert settings["profit_no_progress_enabled"] is True
    assert settings["profit_lock_trail_r"] == pytest.approx(1.5)
    assert settings["profit_lock_min_step_r"] == pytest.approx(0.1)
    assert settings["profit_no_progress_candles"] == 8
    assert settings["profit_no_progress_new_high_r"] == pytest.approx(0.25)
