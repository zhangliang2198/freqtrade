"""Offline source-level regressions; never instantiate a bot or contact an exchange.

Compile the actual method bodies into an isolated harness so this safety test can
also run with --noconftest when only pandas and pytest are available. This covers
callback control flow, not full Freqtrade startup/MRO or exchange integration.
"""

from __future__ import annotations

import ast
import logging
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest


ROOT = Path(__file__).parents[2]
PAIR = "BTC/USDT:USDT"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC).timestamp()


def _load_harness(clock):
    selections = {
        "execution": ("LeaderExecutionMixin", {
            "_entry_price_reference", "_execution_is_safe", "_execution_order_book",
            "_external_exit_rate",
        }),
        "strategy": ("LeaderSqueezeStrategy", {"confirm_trade_entry"}),
        "data": ("LeaderDataMixin", {"_closed_candles"}),
        "trend": ("LeaderTrendMixin", {"_wilder_atr"}),
    }
    methods = {}
    namespace = {
        "math": math, "time": clock, "datetime": datetime, "UTC": UTC,
        "timedelta": timedelta, "DataFrame": pd.DataFrame,
        "timeframe_to_seconds": lambda tf: {"15m": 900, "1h": 3600}[tf],
        "logger": logging.getLogger(__name__), "LOG_GOOD": {}, "LOG_WARN": {},
        "report_cached": lambda fn: fn,
    }
    for module, (class_name, names) in selections.items():
        path = ROOT / "user_data/strategies" / f"leader_squeeze_{module}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                   and node.name == class_name)
        nodes = [node for node in cls.body if isinstance(node, ast.FunctionDef)
                 and node.name in names]
        assert {node.name for node in nodes} == names
        source = ast.Module(body=[ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations")], level=0,
        ), *nodes], type_ignores=[])
        exec(compile(ast.fix_missing_locations(source), str(path), "exec"), namespace)
        methods.update({name: namespace[name] for name in names})
    return type("EntryGuardHarness", (), methods)()


def _book(price=101.0, size=100.0):
    return {"bids": [[price * 0.9999, size]], "asks": [[price, size]]}


@pytest.fixture
def strategy():
    clock = SimpleNamespace(time=Mock(return_value=NOW), monotonic=Mock(return_value=100.0))
    item = _load_harness(clock)
    item.clock = clock
    item.timeframe = "15m"
    item.ENTRY_HEAT_HISTORY_CANDLES = 1441
    item.ORDER_BOOK_MAX_AGE_SECONDS = 5.0
    item.settings = {
        "atr_period": 14, "data_grace_seconds": 30,
        "order_book_depth": 20, "max_spread_ratio": 0.001,
        "max_slippage_ratio": 0.0025, "stake_ratio": 0.1, "leverage": 5,
        "entry_heat_max_penalty": 0,
    }  # Omitted guard keys MUST default to hard enforcement.
    item.frame = pd.DataFrame({
        "date": pd.date_range(end=pd.Timestamp(NOW - 900, unit="s", tz="UTC"),
                              periods=32, freq="15min"),
        "close": 100.0, "high": 101.0, "low": 99.0, "volume": 100.0,
    })
    item.dp = SimpleNamespace(get_pair_dataframe=Mock(side_effect=lambda *a: item.frame))
    item._exchange = SimpleNamespace(fetch_l2_order_book=Mock(return_value=_book()),
                                     get_rate=Mock(return_value=106.0))
    item._wallets = SimpleNamespace(get_total_stake_amount=Mock(return_value=100.0))
    item._warn_data_unavailable = Mock()
    item._entry_pairs = {PAIR}
    item._external_pairs = set()
    item._entries_allowed = Mock(return_value=True)
    item._candle_metrics = Mock(return_value={"momentum": 0.05})
    item._confirmation_quality_reason = Mock(return_value="")
    item._entry_pair_available = Mock(return_value=True)
    item._entry_slot_available = Mock(return_value=True)
    item._prepare_rotation_buy = Mock(return_value=True)
    item._record_approved_entry_score = Mock()
    item._audit_entry_confirmation = Mock()
    return item


def _confirm(strategy, amount=0.25):
    return strategy.confirm_trade_entry(
        PAIR, "market", amount, 101.0, "GTC", datetime.fromtimestamp(NOW, UTC), None, "long",
    )


def _set_book(strategy, book):
    strategy._order_book_cache = {}
    strategy._exchange.fetch_l2_order_book.return_value = book


@pytest.mark.parametrize("price,allowed", [(99, True), (101, True), (102, True),
                                            (102.001, False), (106, False)])
def test_preview_enforces_default_one_atr_cap(strategy, price, allowed):
    _set_book(strategy, _book(price))
    assert strategy._execution_is_safe(PAIR) is allowed
    assert strategy._entry_price_references[PAIR]["max_price"] == 102
    if not allowed:
        assert "追价拦截" in strategy._execution_block_reason


def test_tight_spread_and_low_book_slippage_do_not_allow_six_percent_chase(strategy):
    book = {"bids": [[105.95, 100]], "asks": [[106, 6], [106.1, 4]]}
    assert strategy._execution_is_safe(PAIR)
    _set_book(strategy, book)
    assert not strategy._execution_is_safe(PAIR, amount=10)
    assert "106.04" in strategy._execution_block_reason
    assert "3.020ATR" in strategy._execution_block_reason


def test_actual_quantity_vwap_not_only_best_ask_is_checked(strategy):
    _set_book(strategy, {"bids": [[101.94, 100]], "asks": [[101.95, 1], [102.15, 100]]})
    assert strategy._execution_is_safe(PAIR)  # Preview needs < 1 unit.
    assert not strategy._execution_is_safe(PAIR, amount=3)
    assert "追价拦截" in strategy._execution_block_reason


@pytest.mark.parametrize("rotation", [False, True])
def test_confirm_blocks_before_rotation_state_or_approved_score_is_written(strategy, rotation):
    strategy._rotation_target = PAIR if rotation else None
    assert strategy._execution_is_safe(PAIR)
    _set_book(strategy, _book(106))
    assert not _confirm(strategy)
    strategy._prepare_rotation_buy.assert_not_called()
    strategy._record_approved_entry_score.assert_not_called()
    assert strategy._audit_entry_confirmation.call_args.args[1] is False
    assert "追价拦截" in strategy._entry_block_reason


@pytest.mark.parametrize("rotation", [False, True])
def test_confirm_allows_within_cap_and_preserves_rotation_flow(strategy, rotation):
    strategy._rotation_target = PAIR if rotation else None
    assert strategy._execution_is_safe(PAIR)
    assert _confirm(strategy)
    assert strategy._prepare_rotation_buy.call_count == int(rotation)
    strategy._record_approved_entry_score.assert_called_once()
    strategy._exchange.fetch_l2_order_book.assert_called_once_with(PAIR, 20)


def test_confirmation_without_selection_never_creates_a_new_reference(strategy):
    assert not _confirm(strategy)
    strategy._exchange.fetch_l2_order_book.assert_not_called()
    assert "信号基准缺失或过期" in strategy._entry_block_reason


def test_same_candle_and_repeated_selection_cannot_raise_cap(strategy):
    assert strategy._execution_is_safe(PAIR)
    strategy.frame.loc[strategy.frame.index[-1], ["close", "high"]] = [104, 105]
    strategy.settings["entry_price_max_deviation_atr"] = 10
    _set_book(strategy, _book(103))
    assert not strategy._execution_is_safe(PAIR)
    assert strategy._entry_price_references[PAIR]["close"] == 100
    assert strategy._entry_price_references[PAIR]["max_price"] == 102


def test_tightening_cannot_be_undone_inside_same_signal(strategy):
    assert strategy._execution_is_safe(PAIR)
    strategy.settings["entry_price_max_deviation_atr"] = 0.5
    assert _confirm(strategy)
    strategy.settings["entry_price_max_deviation_atr"] = 3
    _set_book(strategy, _book(101.5))
    assert not _confirm(strategy)
    assert strategy._entry_price_references[PAIR]["max_price"] == 101


@pytest.mark.parametrize("elapsed", [900, 905, 931, -901])
def test_expiry_and_clock_rollback_fail_closed_without_grace(strategy, elapsed):
    assert strategy._execution_is_safe(PAIR)
    strategy.clock.time.return_value = NOW + elapsed
    assert not _confirm(strategy)
    assert PAIR not in strategy._entry_price_references


def test_new_candle_requires_selection_not_confirmation_to_reanchor(strategy):
    assert strategy._execution_is_safe(PAIR)
    strategy.clock.time.return_value = NOW + 900
    row = {"date": pd.Timestamp(NOW, unit="s", tz="UTC"), "close": 102.0,
           "high": 103.0, "low": 101.0, "volume": 100.0}
    strategy.frame = pd.concat([strategy.frame, pd.DataFrame([row])], ignore_index=True)
    assert not _confirm(strategy)
    _set_book(strategy, _book(103))
    assert strategy._execution_is_safe(PAIR)
    assert strategy._entry_price_references[PAIR]["close"] == 102
    assert _confirm(strategy)


def test_book_request_crossing_candle_boundary_cannot_refresh_anchor(strategy):
    def fetch(*args):
        strategy.clock.time.return_value = NOW + 900
        return _book()
    strategy._exchange.fetch_l2_order_book.side_effect = fetch
    assert not strategy._execution_is_safe(PAIR)
    assert "信号基准缺失或过期" in strategy._execution_block_reason


@pytest.mark.parametrize("bad", ["missing", "short", "gap", "nan", "bad_ohlc", "zero_atr"])
def test_unusable_reference_history_rejects_entry(strategy, bad):
    if bad == "missing":
        strategy.frame = pd.DataFrame()
    elif bad == "short":
        strategy.frame = strategy.frame.tail(15)
    elif bad == "gap":
        strategy.frame = strategy.frame.drop(10)
    elif bad == "nan":
        strategy.frame.loc[5, "high"] = float("nan")
    elif bad == "bad_ohlc":
        strategy.frame.loc[5, "high"] = 95
    else:
        strategy.frame[["high", "low"]] = 100.0
    assert not strategy._execution_is_safe(PAIR)
    strategy._exchange.fetch_l2_order_book.assert_not_called()


def test_signal_spike_is_excluded_from_atr_and_unclosed_candle_is_ignored(strategy):
    strategy.frame.loc[31, ["high", "low"]] = [300, 1]
    row = {"date": pd.Timestamp(NOW, unit="s", tz="UTC"), "close": 1000.0,
           "high": 1001.0, "low": 999.0, "volume": 100.0}
    strategy.frame = pd.concat([strategy.frame, pd.DataFrame([row])], ignore_index=True)
    assert strategy._execution_is_safe(PAIR)
    reference = strategy._entry_price_references[PAIR]
    assert reference["close"] == 100
    assert reference["atr"] == 2
    assert reference["max_price"] == 102


@pytest.mark.parametrize("value", [True, False, None, "1", 0, -1, float("inf"), float("nan")])
def test_invalid_atr_multiplier_fails_closed(strategy, value):
    strategy.settings["entry_price_max_deviation_atr"] = value
    assert not strategy._execution_is_safe(PAIR)


@pytest.mark.parametrize("value", [1, None, "true"])
def test_invalid_enable_flag_fails_closed(strategy, value):
    strategy.settings["entry_price_guard_enabled"] = value
    assert not strategy._execution_is_safe(PAIR)


def test_explicit_disable_retains_existing_execution_checks(strategy):
    strategy.settings["entry_price_guard_enabled"] = False
    strategy.frame = pd.DataFrame()
    _set_book(strategy, _book(106))
    assert _confirm(strategy)
    strategy.dp.get_pair_dataframe.assert_not_called()
    _set_book(strategy, {"bids": [[90, 10]], "asks": [[106, 10]]})
    assert not _confirm(strategy)
    assert "价差" in strategy._entry_block_reason


@pytest.mark.parametrize("failure", ["spread", "depth", "slippage", "timeout", "slow"])
def test_original_order_book_rejections_remain_effective(strategy, failure):
    if failure == "spread":
        _set_book(strategy, {"bids": [[99, 100]], "asks": [[101, 100]]})
    elif failure == "depth":
        _set_book(strategy, _book(size=0.001))
    elif failure == "slippage":
        _set_book(strategy, {"bids": [[99.99, 100]], "asks": [[100, 0.001], [101, 100]]})
    elif failure == "timeout":
        strategy._exchange.fetch_l2_order_book.side_effect = TimeoutError("offline")
    else:
        strategy.clock.monotonic.side_effect = [100.0, 105.0]
    assert not strategy._execution_is_safe(PAIR)


def test_post_book_global_recheck_still_blocks_even_when_price_passes(strategy):
    assert strategy._execution_is_safe(PAIR)
    strategy._entries_allowed.side_effect = [True, False]
    strategy._entry_block_reason = "账户状态已变化"
    assert not _confirm(strategy)
    strategy._record_approved_entry_score.assert_not_called()


def test_exit_price_path_is_not_subject_to_entry_guard(strategy):
    strategy.config = {"exit_pricing": {"use_order_book": True, "order_book_top": 1}}
    strategy.frame = pd.DataFrame()
    _set_book(strategy, _book(106))
    assert strategy._external_exit_rate(PAIR, "long") == 106
    strategy.dp.get_pair_dataframe.assert_not_called()
