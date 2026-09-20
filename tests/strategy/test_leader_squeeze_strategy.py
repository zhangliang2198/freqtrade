import importlib
import json
import logging
import math
import re
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from freqtrade.persistence import PairLocks
from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)


DATA = importlib.import_module("leader_squeeze_helpers")
SUPPORT = DATA


STRATEGY_PATH = (
    Path(__file__).parents[2] / "user_data/strategies/leader_squeeze/leader_squeeze_strategy.py"
)
SPEC = importlib.util.spec_from_file_location("leader_squeeze_strategy", STRATEGY_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


def _fetch_pair_metrics_fixture() -> tuple[dict[str, float], dict[str, str]]:
    payloads = {
        "takerlongshortRatio": [{"buyVol": "1.2", "sellVol": "1", "timestamp": 3_600_000}],
        "openInterestHist": [
            {"sumOpenInterest": str(value), "timestamp": timestamp}
            for value, timestamp in zip(
                (101, 100, 99, 98, 97),
                (900_000, 1_800_000, 2_700_000, 3_600_000, 4_500_000),
                strict=True,
            )
        ],
    }
    sessions = []

    class Response:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Session:
        def __init__(self):
            self.headers = {}
            sessions.append(self)

        def get(self, url, **kwargs):
            return Response(payloads[url.rsplit("/", 1)[-1]])

        def close(self):
            return None

    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "exchange": {"ccxt_config": {}}}
    strategy.settings = configured_settings()
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(_api=SimpleNamespace(market_id=lambda pair: "BTCUSDT"))
    )

    with (
        patch.object(DATA.requests, "Session", Session),
        patch.object(MODULE.time, "time", return_value=5_000.0),
    ):
        strategy.settings["taker_window_candles"] = 1
        metrics = strategy._fetch_pair_metrics("BTC/USDT:USDT")

    return metrics, sessions[0].headers


ETH_TEST_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _eth_frame(
    closes: list[float | None],
    *,
    latest_offset_minutes: float = 15,
    gap_at: int | None = None,
) -> pd.DataFrame:
    latest = ETH_TEST_NOW - timedelta(minutes=latest_offset_minutes)
    dates = [
        latest - timedelta(minutes=15 * (len(closes) - index - 1)) for index in range(len(closes))
    ]
    if gap_at is not None:
        dates[gap_at] -= timedelta(minutes=15)
    numeric = pd.Series(closes, dtype="float64")
    opening = numeric.shift(1).fillna(numeric)
    return pd.DataFrame(
        {
            "date": dates,
            "open": opening,
            "high": pd.concat([opening, numeric], axis=1).max(axis=1) + 1.0,
            "low": pd.concat([opening, numeric], axis=1).min(axis=1) - 1.0,
            "close": numeric,
            "volume": 1.0,
        }
    )


def _eth_trend_closes(direction: str) -> list[float]:
    if direction == "up":
        return [100.0] * 84 + [100.0 + 0.5 * index for index in range(1, 17)]
    if direction == "down":
        return [100.0] * 84 + [100.0 - 0.25 * index for index in range(1, 17)]
    if direction == "flat":
        return [100.0] * 100
    if direction == "crash":
        # 收盘 68.00 < EMA20 - 3.0xATR (83.17 - 10.02 = 73.14), 触发急跌熔断。
        return [100.0] * 84 + [100.0 - 2.0 * index for index in range(1, 17)]
    raise ValueError(direction)


def _eth_gate_strategy(frame: pd.DataFrame) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)
    return strategy


def _fresh_score_metric(**values) -> dict[str, float]:
    return {
        "momentum": 0.05,
        "trend_continuity": 1.0,
        "_score_valid_until": 1e12,
        "_exit_valid_until": 1e12,
        **values,
    }


def _entry_ready_strategy(
    now: float, *, entry_heat_max_penalty: float = 0
) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    # These fixtures exercise the existing entry, rotation, and execution
    # policies.  Heat-aware entry tests provide their own 15-day history.
    strategy.settings["entry_heat_max_penalty"] = entry_heat_max_penalty
    strategy.settings["entry_setup_enabled"] = bool(entry_heat_max_penalty)
    strategy._eth_entries_allowed = lambda current_time: True
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._entry_slot_available = Mock(return_value=True)
    strategy._data_healthy = True
    strategy._score_leaders = ["BTC/USDT:USDT"]
    strategy._metrics = {"BTC/USDT:USDT": _fresh_score_metric()}
    strategy._scores = {"BTC/USDT:USDT": 90.0}
    strategy._last_good_data = now
    strategy._last_score_refresh = now
    strategy._liquidation_connected = threading.Event()
    strategy._liquidation_connected.set()
    strategy._liquidation_last_message = now
    strategy._position_data_healthy = True
    strategy._last_position_sync = now
    strategy._external_pairs = set()
    strategy._daily_blocked = False
    strategy._account_stopped = False
    strategy._market_data_healthy = True
    strategy._market_down = False
    strategy._entry_pairs = {"BTC/USDT:USDT"}
    return strategy


def _status_strategy() -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "stake_currency": "USDT"}
    strategy.settings = configured_settings()
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy.settings["entry_setup_enabled"] = False
    strategy._entry_block_reason = "ETH拦截: ETH 下跌"
    strategy._entry_pairs = {"BTC/USDT:USDT"}
    strategy._entry_decisions = {"BTC/USDT:USDT": "入选第1仓: 形态80.0 强度80.0>=40.0"}
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._last_status_signature = None
    strategy._last_status_log = float("-inf")
    strategy._data_healthy = True
    strategy._last_good_data = 900.0
    strategy._score_pending = False
    strategy._next_score_refresh = 1200.0
    strategy._position_data_healthy = True
    strategy._last_position_sync = 990.0
    strategy._liquidation_connected = threading.Event()
    strategy._liquidation_connected.set()
    strategy._liquidation_last_message = 995.0
    strategy._market_data_healthy = True
    strategy._market_down = False
    strategy._scores = {"BTC/USDT:USDT": 80.0}
    strategy._external_pairs = {"ETH/USDT:USDT"}
    strategy._position_details = {}
    strategy._risk_state = {}
    strategy._daily_blocked = False
    strategy._account_stopped = False
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy.dp = SimpleNamespace(_exchange=Mock())
    strategy.wallets = SimpleNamespace(get_all_positions=Mock(return_value={}))
    return strategy


def test_score_weights() -> None:
    weights = configured_settings()["weights"]
    assert sum(weights.values()) == 1.0
    assert weights["momentum"] == 0.44
    assert weights["volume"] == 0.27
    assert weights["taker_buy"] == 0.26
    assert weights["liquidation"] == 0.0
    assert weights["oi_squeeze"] == 0.0
    assert weights["funding"] == 0.03
    assert "adl_risk" not in weights
    assert len(weights) == 6


def test_cleanup_before_bot_start_is_safe() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)

    strategy.ft_bot_cleanup()


def test_candle_metrics_uses_one_hour_and_three_15m_changes() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range(
                end=datetime.now(UTC) - timedelta(minutes=15), periods=24, freq="15min"
            ),
            "close": [100.0] * 20 + [101.0, 102.0, 103.0, 104.0],
            "volume": [100.0] * 24,
        }
    )
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    # Keep this focused candle fixture compact while the production setting
    # uses a full seven-day activity baseline.
    strategy.settings["volume_activity_baseline_candles"] = 20
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)

    metrics = strategy._candle_metrics("BTC/USDT:USDT")

    assert metrics is not None
    assert metrics["trend_continuity"] == 1.0
    assert metrics["momentum"] == pytest.approx(104 / 100 - 1)


@pytest.mark.parametrize(
    ("direction", "expected"),
    [("up", True), ("flat", True), ("down", True), ("crash", False)],
)
def test_eth_gate_blocks_only_on_a_fast_atr_break(direction: str, expected: bool) -> None:
    """缓慢走弱(15m 与 1h 同时低于 EMA)不再拦截, 只有急跌熔断才拦截。

    实测(14天/122币选币池, 剔除预热): 双周期走弱拦截 25.1% 的时间却占用
    22.5% 的期望收益, 而急跌只占 1.4%; 被拦窗口的下行分位与放行窗口几乎
    相同, 只损失上行。故只保留急跌熔断。
    """
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes(direction)))

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp()) is expected


def test_eth_gate_allows_15m_pullback_while_1h_ema_is_not_falling() -> None:
    closes = [100.0 + 0.05 * index for index in range(98)] + [102.0, 101.0]
    strategy = _eth_gate_strategy(_eth_frame(closes))

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert strategy._eth_trend == "15m走弱/1h整理"


def test_eth_gate_blocks_single_fast_atr_break_without_waiting_for_1h() -> None:
    """急跌分支只作为极端错位熔断, 门槛为 EMA - eth_fast_atr_buffer x ATR。"""
    closes = _eth_trend_closes("up")
    closes[-1] = 85.0
    strategy = _eth_gate_strategy(_eth_frame(closes))

    assert not strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert strategy._eth_trend == "15m急跌"
    assert f"{float(strategy.settings['eth_fast_atr_buffer']):.1f}xATR" in (
        strategy._eth_block_reason
    )


def _eth_context(**values) -> dict:
    return {
        "date": ETH_TEST_NOW - timedelta(minutes=15),
        "close": 100.0,
        "ema": 100.0,
        "slope": 0.0,
        "atr": 10.0,
        "falling": False,
        "rising": False,
        "weakening": False,
        "state": "整理",
        **values,
    }


def test_eth_gate_does_not_block_when_only_1h_is_weak() -> None:
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("flat")))
    strategy._eth_timeframe_context = Mock(
        side_effect=[
            _eth_context(close=101.0, ema=100.0, slope=1.0, rising=True, state="上涨"),
            _eth_context(
                close=95.0,
                ema=100.0,
                slope=-1.0,
                falling=True,
                weakening=True,
                state="走弱",
            ),
        ]
    )

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert strategy._eth_trend == "15m上涨/1h走弱"


@pytest.mark.parametrize("falling", [True, False])
def test_eth_fast_break_requires_strict_threshold_and_falling_ema(falling: bool) -> None:
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("flat")))
    threshold = 100.0 - float(strategy.settings["eth_fast_atr_buffer"]) * 10.0
    # A close exactly at EMA100 - buffer * ATR10 must not trigger, even with a falling EMA.
    # With a flat EMA, a price below the threshold must not trigger either.
    close = threshold if falling else threshold - 1.0
    strategy._eth_timeframe_context = Mock(
        side_effect=[
            _eth_context(close=close, slope=-1.0 if falling else 0.0, falling=falling),
            _eth_context(),
        ]
    )

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())


def test_eth_fast_break_atr_excludes_the_signal_candle() -> None:
    frame = _eth_frame(_eth_trend_closes("up"))
    frame.loc[frame.index[-1], ["high", "low", "close"]] = [150.0, 85.0, 85.0]
    strategy = _eth_gate_strategy(frame)

    context = strategy._eth_timeframe_context("15m", 2, ETH_TEST_NOW.timestamp())

    assert context is not None
    assert context["atr"] == pytest.approx(strategy._wilder_atr(frame.iloc[:-1]))


@pytest.mark.parametrize(
    ("close", "expected"),
    [
        # 实测(14天/999根15m): 1.5xATR 门槛拦掉的窗口, ETH 后续 8h 反而 +0.94%,
        # 且 4h 最低仅 -0.78% —— 它拦的是超卖反弹而非崩盘延续。放宽到 3.0xATR。
        (80.0, True),
        (65.0, False),
    ],
)
def test_fast_break_calibration_only_blocks_extreme_dislocation(
    close: float, expected: bool
) -> None:
    """EMA100/ATR10 下: 旧门槛 1.5xATR=85.0, 新门槛 3.0xATR=70.0。"""
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("flat")))
    strategy._eth_timeframe_context = Mock(
        side_effect=[
            _eth_context(close=close, slope=-1.0, falling=True),
            _eth_context(),
        ]
    )

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp()) is expected


def test_eth_cooldown_blocks_a_fixed_number_of_bars_then_resumes() -> None:
    """急跌后按 eth_cooldown_candles 根固定冷却, 不等待 EMA 斜率转正。

    实测(14天/122币选币池): 等斜率转正会让 27 根急跌事件产生 35% 的拦截时间,
    而被拦窗口的前10龙头下行分位(p10 -4.08% / p25 -2.34%)与放行窗口
    (-4.20% / -2.37%)几乎相同, 只把 p90 从 +17.86% 砍到 +14.15%。
    """
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("flat")))
    strategy._risk_state = {}
    bars = int(strategy.settings["eth_cooldown_candles"])
    step = timedelta(minutes=15)

    def context_at_bar(index: int, **values):
        return _eth_context(date=ETH_TEST_NOW + index * step, **values)

    def recovered(index: int):
        return context_at_bar(index, close=108.0, ema=100.0, slope=1.0, rising=True)

    # 第 0 根急跌 -> 进入固定长度冷却
    strategy._eth_timeframe_context = Mock(
        side_effect=[
            context_at_bar(0, close=65.0, slope=-1.0, falling=True),
            context_at_bar(0),
        ]
    )
    assert not strategy._eth_entries_allowed((ETH_TEST_NOW + step).timestamp())
    assert strategy._eth_trend == "15m急跌"
    assert strategy._eth_cooldown_until == pytest.approx((ETH_TEST_NOW + bars * step).timestamp())
    assert strategy._risk_state["eth_entry_blocked"] is True
    assert strategy._risk_state["eth_cooldown_until"] == strategy._eth_cooldown_until

    # 冷却期内即使 ETH 已经恢复上涨, 仍然拦截
    for index in (1, bars - 1):
        strategy._eth_timeframe_context = Mock(side_effect=[recovered(index), recovered(index)])
        assert not strategy._eth_entries_allowed((ETH_TEST_NOW + (index + 1) * step).timestamp())
        assert strategy._eth_trend == "急跌冷却中"

    # 冷却到期后立即恢复, 不需要额外的 EMA 结构确认
    expired = bars
    strategy._eth_timeframe_context = Mock(side_effect=[recovered(expired), recovered(expired)])
    assert strategy._eth_entries_allowed((ETH_TEST_NOW + (expired + 1) * step).timestamp())
    assert strategy._eth_cooldown_until is None
    assert strategy._risk_state["eth_entry_blocked"] is False


def test_eth_cooldown_is_saved_immediately_and_survives_a_restart(tmp_path) -> None:
    """冷却状态写进风控状态文件, 重启后不会立刻解除拦截。"""
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("flat")))
    strategy._state_path = tmp_path / "leader_squeeze_state.live.json"
    strategy._risk_state = {"account_stopped": False, "peak_equity": 1_000.0}
    strategy._risk_state_load_failed = False
    strategy._risk_state_save_failed = False
    strategy._eth_timeframe_context = Mock(
        side_effect=[
            _eth_context(close=65.0, slope=-1.0, falling=True),
            _eth_context(),
        ]
    )
    assert not strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    persisted = strategy._risk_state["eth_cooldown_until"]
    assert persisted is not None
    saved = json.loads(strategy._state_path.read_text())
    assert saved["eth_entry_blocked"] is True
    assert saved["eth_cooldown_until"] == pytest.approx(persisted)

    restarted = _eth_gate_strategy(_eth_frame(_eth_trend_closes("flat")))
    restarted._state_path = strategy._state_path
    restarted._risk_state_load_failed = False
    restarted._risk_state = restarted._load_risk_state()
    restarted._eth_blocked = restarted._risk_state["eth_entry_blocked"]
    restarted._eth_cooldown_until = float(restarted._risk_state["eth_cooldown_until"])
    restarted._eth_timeframe_context = Mock(
        side_effect=[_eth_context(close=108.0, ema=100.0, slope=1.0, rising=True)] * 2
    )

    assert not restarted._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert restarted._eth_trend == "急跌冷却中"


def test_eth_cooldown_repeats_extend_the_deadline() -> None:
    """冷却期内再次急跌, 冷却窗口从新的急跌 K 线重新起算。"""
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("flat")))
    strategy._risk_state = {}
    step = timedelta(minutes=15)
    bars = int(strategy.settings["eth_cooldown_candles"])

    strategy._eth_timeframe_context = Mock(
        side_effect=[
            _eth_context(date=ETH_TEST_NOW, close=65.0, slope=-1.0, falling=True),
            _eth_context(date=ETH_TEST_NOW),
        ]
    )
    assert not strategy._eth_entries_allowed((ETH_TEST_NOW + step).timestamp())
    first = strategy._eth_cooldown_until

    later = ETH_TEST_NOW + 4 * step
    strategy._eth_timeframe_context = Mock(
        side_effect=[
            _eth_context(date=later, close=60.0, slope=-1.0, falling=True),
            _eth_context(date=later),
        ]
    )
    assert not strategy._eth_entries_allowed((later + step).timestamp())
    extended = strategy._eth_cooldown_until
    assert extended > first
    assert extended == pytest.approx((later + bars * step).timestamp())

    # 交易所短暂返回更旧的已收盘 K 线时, 不得缩短已经延长的冷却。
    earlier = ETH_TEST_NOW + 2 * step
    strategy._eth_timeframe_context = Mock(
        side_effect=[
            _eth_context(date=earlier, close=60.0, slope=-1.0, falling=True),
            _eth_context(date=earlier),
        ]
    )
    assert not strategy._eth_entries_allowed((later + step).timestamp())
    assert strategy._eth_cooldown_until == extended


def test_stale_eth_cooldown_from_state_file_self_heals() -> None:
    """状态文件里的过期冷却不会永久拦截, 且会被清掉。"""
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("up")))
    strategy._risk_state = {}
    strategy._eth_blocked = True
    strategy._eth_cooldown_until = (ETH_TEST_NOW - timedelta(hours=3)).timestamp()
    strategy._eth_timeframe_context = Mock(
        side_effect=[_eth_context(close=108.0, ema=100.0, slope=1.0, rising=True)] * 2
    )

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert strategy._eth_cooldown_until is None
    assert strategy._risk_state["eth_cooldown_until"] is None
    assert strategy._risk_state["eth_entry_blocked"] is False


def test_eth_gate_stays_blocked_when_cooldown_clear_cannot_be_saved() -> None:
    """冷却清除无法落盘时继续拦截, 不得先记录放行再由下单门禁拒绝。"""
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("up")))
    expired = (ETH_TEST_NOW - timedelta(hours=3)).timestamp()
    strategy._risk_state = {
        "account_stopped": False,
        "peak_equity": 1_000.0,
        "eth_entry_blocked": True,
        "eth_cooldown_until": expired,
    }
    strategy._eth_blocked = True
    strategy._eth_cooldown_until = expired

    def fail_save() -> bool:
        strategy._risk_state_save_failed = True
        return False

    strategy._save_risk_state = Mock(side_effect=fail_save)
    strategy._eth_timeframe_context = Mock(
        side_effect=[_eth_context(close=108.0, ema=100.0, slope=1.0, rising=True)] * 2
    )

    assert not strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert strategy._eth_trend == "状态保存失败"
    assert "保存失败" in strategy._eth_block_reason


def test_bot_start_restores_the_eth_cooldown_from_the_state_file(tmp_path) -> None:
    """冷却截止时间随状态文件恢复, 重启后不会立刻解除拦截。"""
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "max_open_trades": 11,
        "dry_run": False,
        "runmode": "live",
        "user_data_dir": str(tmp_path),
        "stake_currency": "USDT",
    }
    deadline = ETH_TEST_NOW.timestamp() + 7_200
    strategy._load_risk_state = Mock(
        return_value={"eth_entry_blocked": True, "eth_cooldown_until": deadline}
    )
    strategy._sync_external_pairs = Mock()
    strategy._initialize_rotation_audit = Mock()

    with patch.object(MODULE.threading, "Thread"):
        strategy.bot_start()

    assert strategy._eth_blocked is True
    assert strategy._eth_cooldown_until == pytest.approx(deadline)


def test_missing_eth_cooldown_candles_fails_at_configuration_time() -> None:
    """缺少该键必须在启动时报错, 不能落进 _eth_entries_allowed 的 except 里静默封禁。"""
    from leader_squeeze_helpers import configure_strategy

    config = {
        **PUBLIC_CONFIG,
        "leader_squeeze": {
            key: value
            for key, value in configured_settings().items()
            if key != "eth_cooldown_candles"
        },
    }
    strategy = configured_strategy(LeaderSqueezeStrategy)

    with pytest.raises(ValueError, match="eth_cooldown_candles"):
        configure_strategy(strategy, config)


def test_eth_gate_ignores_an_unclosed_candle() -> None:
    frame = _eth_frame(_eth_trend_closes("crash"))
    frame = pd.concat(
        [frame, _eth_frame([1_000.0], latest_offset_minutes=0)],
        ignore_index=True,
    )
    strategy = _eth_gate_strategy(frame)

    # 未收盘的 1000.0 若被计入, 收盘价会远高于阈值而放行; 仍然拦截即证明被忽略。
    assert not strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())


@pytest.mark.parametrize(("age_seconds", "expected"), [(20, True), (31, False)])
def test_eth_gate_applies_data_grace_to_candle_freshness(age_seconds: int, expected: bool) -> None:
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("up"), latest_offset_minutes=30))
    strategy.settings["data_grace_seconds"] = 30

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp() + age_seconds) is expected


def test_eth_gate_rejects_missing_and_non_contiguous_candles() -> None:
    missing = _eth_gate_strategy(_eth_frame(_eth_trend_closes("up")[:91]))
    non_contiguous = _eth_gate_strategy(_eth_frame(_eth_trend_closes("up"), gap_at=10))

    assert not missing._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert not non_contiguous._eth_entries_allowed(ETH_TEST_NOW.timestamp())


@pytest.mark.parametrize("bad_close", [float("nan"), None])
def test_eth_gate_rejects_non_finite_close(bad_close: float | None) -> None:
    closes: list[float | None] = _eth_trend_closes("up")
    closes[5] = bad_close

    assert not _eth_gate_strategy(_eth_frame(closes))._eth_entries_allowed(ETH_TEST_NOW.timestamp())


def test_eth_gate_rejects_data_provider_errors() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.dp = SimpleNamespace(
        get_pair_dataframe=Mock(side_effect=RuntimeError("exchange unavailable"))
    )

    assert not strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())


def test_informative_pairs_subscribe_to_eth_outside_the_whitelist() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(current_whitelist=lambda: ["BTC/USDT:USDT"])

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        informative = strategy.informative_pairs()

    assert (strategy.ETH_PAIR, "15m") in informative


def test_eth_gate_rejects_existing_signal_and_final_entry_confirmation() -> None:
    strategy = _eth_gate_strategy(_eth_frame(_eth_trend_closes("crash")))
    strategy._entry_pairs = {"BTC/USDT:USDT"}
    signal_frame = pd.DataFrame({"close": [100.0], "enter_long": [1]})

    with patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()):
        analyzed = strategy.populate_entry_trend(signal_frame.copy(), {"pair": "BTC/USDT:USDT"})
        confirmed = strategy.confirm_trade_entry(
            pair="BTC/USDT:USDT",
            order_type="market",
            amount=1.0,
            rate=100.0,
            time_in_force="GTC",
            current_time=ETH_TEST_NOW,
            entry_tag="old_signal",
            side="long",
        )

    assert analyzed["enter_long"].iloc[-1] == 0
    assert not confirmed


def test_eth_blocked_loop_keeps_risk_checks_but_skips_new_work(caplog) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._last_position_sync = time.time()
    strategy._sync_external_pairs = Mock()
    strategy.dp = SimpleNamespace(
        get_pair_dataframe=Mock(return_value=_eth_frame(_eth_trend_closes("crash"))),
        current_whitelist=list,
        current_selection_whitelist=list,
    )
    strategy._consume_score_refresh = Mock(return_value=True)
    strategy._start_score_refresh = Mock()
    strategy._refresh_risk_state = Mock()
    strategy._sync_rotation_state = Mock()
    strategy._plan_rotation = Mock()
    strategy._select_entries = Mock(return_value=set())
    strategy._log_strategy_status = Mock()
    strategy._entry_pairs = {"OLD"}
    strategy._rotation_pair = "WEAK"
    strategy._rotation_target = "TARGET"
    strategy._rotation_candidate = ("WEAK", "TARGET")
    strategy._rotation_seen = 2
    strategy._eth_last_log_reason = None
    strategy._eth_last_log_time = 0.0
    strategy._next_score_refresh = 0.0
    strategy._score_pending = False

    with (
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
        patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()),
    ):
        strategy.bot_loop_start(ETH_TEST_NOW)

    strategy._refresh_risk_state.assert_called_once_with(ETH_TEST_NOW)
    strategy._start_score_refresh.assert_called_once_with(ETH_TEST_NOW.timestamp(), exit_only=True)
    strategy._consume_score_refresh.assert_called_once_with(
        ETH_TEST_NOW.timestamp(), allow_scoring=False
    )
    strategy._plan_rotation.assert_not_called()
    assert strategy._entry_pairs == set()
    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None
    assert strategy._rotation_candidate is None
    assert strategy._rotation_seen == 0

    def messages():
        return [
            record.getMessage() for record in caplog.records if "ETH 15m" in record.getMessage()
        ]

    assert len(messages()) == 1
    assert "急跌" in messages()[0]
    assert "已有仓位继续止损和退出" in messages()[0]
    for seconds, expected_count in [(5, 1), (299, 1), (300, 2)]:
        with (
            caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
            patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp() + seconds),
        ):
            strategy.bot_loop_start(ETH_TEST_NOW)
        assert len(messages()) == expected_count

    def run_loop(frame, seconds: int) -> None:
        strategy.dp.get_pair_dataframe.return_value = frame
        strategy._next_score_refresh = float("inf")
        with (
            caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
            patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp() + seconds),
        ):
            strategy.bot_loop_start(ETH_TEST_NOW)

    run_loop(pd.DataFrame(), 305)
    assert "数据缺失、过期或无效" in messages()[-1]

    # 急跌冷却未到期时, 即使 ETH 已经转涨也继续拦截。
    run_loop(_eth_frame(_eth_trend_closes("up")), 305)
    assert "急跌冷却" in messages()[-1]

    # 冷却到期后才放行。
    strategy._eth_cooldown_until = None
    run_loop(_eth_frame(_eth_trend_closes("up")), 305)
    assert "不拦截" in messages()[-1]


@pytest.mark.parametrize(
    ("dry_run", "runmode", "state_file"),
    [
        (True, "dry_run", "leader_squeeze_state.json"),
        (False, "live", "leader_squeeze_state.live.json"),
    ],
)
def test_bot_start_isolates_state_file_by_mode_without_network(
    tmp_path, dry_run: bool, runmode: str, state_file: str
) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "max_open_trades": 11,
        "dry_run": dry_run,
        "runmode": runmode,
        "user_data_dir": str(tmp_path),
    }
    strategy._sync_external_pairs = Mock()
    strategy._load_risk_state = Mock(return_value={"eth_entry_blocked": True})
    strategy._initialize_rotation_audit = Mock()

    with patch.object(MODULE.threading, "Thread") as thread:
        strategy.bot_start()

    setting = "state_file_dry_run" if dry_run else "state_file_live"
    assert strategy._state_path == tmp_path / PUBLIC_CONFIG["leader_squeeze"][setting]
    assert strategy._state_path.name == state_file
    assert strategy._eth_blocked is True
    strategy._sync_external_pairs.assert_called_once()
    thread.assert_not_called()


def _risk_state_strategy(tmp_path: Path) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._state_path = tmp_path / "leader_squeeze_state.live.json"
    strategy._risk_state_load_failed = False
    return strategy


def test_missing_risk_state_file_allows_first_initialization_and_save(tmp_path) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "max_open_trades": 11,
        "dry_run": False,
        "runmode": "live",
        "user_data_dir": str(tmp_path),
        "stake_currency": "USDT",
    }
    strategy._sync_external_pairs = Mock()
    strategy._initialize_rotation_audit = Mock()

    with patch.object(MODULE.threading, "Thread"):
        strategy.bot_start()

    assert strategy._risk_state == {}
    assert strategy._risk_state_load_failed is False
    strategy.wallets = SimpleNamespace(
        get_all_positions=Mock(return_value={}),
        get_total=Mock(return_value=1_000.0),
    )
    strategy.dp = SimpleNamespace(send_msg=Mock())
    strategy._refresh_risk_state(ETH_TEST_NOW)

    assert strategy._state_path.exists()
    saved = json.loads(strategy._state_path.read_text())
    assert saved["peak_equity"] == 1_000.0
    assert saved["account_stopped"] is False


@pytest.mark.parametrize(
    "raw_state",
    [
        "{",
        "{}",
        "[]",
        json.dumps({"peak_equity": -1.0, "account_stopped": False}),
        json.dumps({"peak_equity": float("nan"), "account_stopped": False}),
        json.dumps({"peak_equity": True, "account_stopped": False}),
        json.dumps({"peak_equity": 1_000.0, "account_stopped": False, "day_start_equity": 0.0}),
        json.dumps({"peak_equity": 1_000.0, "account_stopped": False, "last_equity": float("inf")}),
        json.dumps({"peak_equity": 1_000.0, "account_stopped": "false"}),
        json.dumps(
            {
                "peak_equity": 1_000.0,
                "account_stopped": False,
                "eth_entry_blocked": "true",
            }
        ),
        json.dumps(
            {
                "peak_equity": 1_000.0,
                "account_stopped": False,
                "eth_cooldown_until": "soon",
            }
        ),
        json.dumps(
            {
                "peak_equity": 1_000.0,
                "account_stopped": False,
                "eth_cooldown_until": float("nan"),
            }
        ),
        json.dumps(
            {
                "peak_equity": 1_000.0,
                "account_stopped": False,
                "eth_cooldown_until": float("inf"),
            }
        ),
        json.dumps(
            {
                "peak_equity": 1_000.0,
                "account_stopped": False,
                "eth_cooldown_until": -1.0,
            }
        ),
        json.dumps(
            {
                "peak_equity": 1_000.0,
                "account_stopped": False,
                "eth_cooldown_until": 1e12,
            }
        ),
    ],
)
def test_invalid_risk_state_is_rejected_and_latches_load_failure(tmp_path, raw_state) -> None:
    strategy = _risk_state_strategy(tmp_path)
    strategy._state_path.write_text(raw_state)

    assert strategy._load_risk_state() == {}
    assert strategy._risk_state_load_failed is True


def test_risk_state_permission_error_is_rejected_and_logged(tmp_path, caplog) -> None:
    strategy = _risk_state_strategy(tmp_path)

    with (
        patch.object(Path, "read_text", side_effect=PermissionError("denied")),
        caplog.at_level(logging.ERROR, logger="leader_squeeze_strategy"),
    ):
        assert strategy._load_risk_state() == {}

    assert strategy._risk_state_load_failed is True
    assert "风控状态读取失败" in caplog.records[-1].getMessage()
    assert caplog.records[-1].levelno >= logging.ERROR


def test_failed_risk_state_blocks_entries_and_never_overwrites_original_file(tmp_path) -> None:
    strategy = _entry_ready_strategy(ETH_TEST_NOW.timestamp())
    strategy._state_path = tmp_path / "leader_squeeze_state.live.json"
    original = "{not-valid-json"
    strategy._state_path.write_text(original)
    strategy._risk_state_load_failed = False
    strategy._risk_state = strategy._load_risk_state()

    assert strategy._risk_state_load_failed is True
    strategy.config = {**PUBLIC_CONFIG, "stake_currency": "USDT"}
    strategy.wallets = SimpleNamespace(
        get_all_positions=Mock(return_value={}),
        get_total=Mock(return_value=1_000.0),
    )
    strategy._refresh_risk_state(ETH_TEST_NOW)
    strategy._risk_state = {"peak_equity": 1_000.0, "account_stopped": False}
    strategy._save_risk_state()

    assert strategy._entries_allowed(ETH_TEST_NOW.timestamp()) is False
    assert "风控状态读取失败" in strategy._entry_block_reason
    assert strategy._state_path.read_text() == original
    strategy.wallets.get_total.assert_not_called()


def test_custom_exit_keeps_trend_reversal_available_after_risk_state_load_failure() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._risk_state_load_failed = True
    strategy._account_stopped = False
    strategy._market_down = False
    strategy._rotation_pair = None
    strategy._exit_log_reasons = {}
    strategy._trend_reversed = Mock(return_value=True)

    reason = strategy.custom_exit(
        "BTC/USDT:USDT",
        SimpleNamespace(),
        ETH_TEST_NOW,
        100.0,
        -0.01,
    )

    assert reason == "trend_reversal"


def test_legacy_account_stop_is_ignored_on_restart(tmp_path) -> None:
    state_path = tmp_path / PUBLIC_CONFIG["leader_squeeze"]["state_file_live"]
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "day": ETH_TEST_NOW.date().isoformat(),
                "day_start_equity": 1_000.0,
                "peak_equity": 1_000.0,
                "last_equity": 900.0,
                "account_stopped": True,
            }
        )
    )
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "max_open_trades": 11,
        "dry_run": False,
        "runmode": "live",
        "user_data_dir": str(tmp_path),
        "stake_currency": "USDT",
    }
    strategy._sync_external_pairs = Mock()
    strategy._initialize_rotation_audit = Mock()

    with patch.object(MODULE.threading, "Thread"):
        strategy.bot_start()

    assert strategy._risk_state_load_failed is False
    assert strategy._risk_state["peak_equity"] == 1_000.0
    assert strategy._account_stopped is False


def test_eth_allowed_log_shows_uptrend_values_and_is_throttled(caplog) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._last_position_sync = ETH_TEST_NOW.timestamp() + 3_600
    strategy._sync_external_pairs = Mock()
    strategy.dp = SimpleNamespace(
        get_pair_dataframe=Mock(return_value=_eth_frame(_eth_trend_closes("up"))),
        current_whitelist=list,
        current_selection_whitelist=list,
    )
    strategy._consume_score_refresh = Mock(return_value=False)
    strategy._advance_score_refresh = Mock()
    strategy._start_score_refresh = Mock()
    strategy._refresh_risk_state = Mock()
    strategy._sync_rotation_state = Mock()
    strategy._plan_rotation = Mock()
    strategy._select_entries = Mock(return_value=set())
    strategy._log_strategy_status = Mock()
    strategy._entry_pairs = set()
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy._eth_last_log_reason = None
    strategy._eth_last_log_time = 0.0
    strategy._next_score_refresh = float("inf")

    def messages():
        return [record for record in caplog.records if "ETH 15m" in record.getMessage()]

    with caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"):
        for seconds in (0, 299, 300):
            with patch.object(
                MODULE.time,
                "time",
                return_value=ETH_TEST_NOW.timestamp() + seconds,
            ):
                strategy.bot_loop_start(ETH_TEST_NOW)
            assert len(messages()) == (1 if seconds < 300 else 2)

    message = messages()[0].getMessage()
    assert "不拦截" in message
    assert "当前趋势=双周期上涨" in message
    assert "15m=上涨" in message
    assert "1h=上涨" in message
    assert "EMA20=" in message
    assert "已收盘=" in message


@pytest.mark.parametrize(
    ("gate", "expected_reason"),
    [
        ("score_data", "行情评分数据不完整"),
        ("score_age", "评分数据过期"),
        ("position_data", "仓位同步失败"),
        ("position_age", "仓位数据过期"),
        ("manual_sync", "手动仓位对账不可用"),
        ("external_unmanaged", "检测到框架未接管的外部仓位"),
        ("external_reconciling", "外部仓位正在框架对账"),
        ("market_data", "龙头K线覆盖不足"),
        ("market_down", "龙头市场普跌"),
    ],
)
def test_actual_entry_rejects_each_global_gate(gate: str, expected_reason: str) -> None:
    now = ETH_TEST_NOW.timestamp()
    strategy = _entry_ready_strategy(now)
    if gate == "score_data":
        strategy._data_healthy = False
    elif gate == "score_age":
        strategy._last_good_data = now - strategy.settings["score_refresh_seconds"] - 31
    elif gate == "position_data":
        strategy._position_data_healthy = False
    elif gate == "position_age":
        strategy._last_position_sync = now - 61
    elif gate == "manual_sync":
        strategy._manual_sync_healthy = False
    elif gate == "external_unmanaged":
        strategy.config["manual_position_sync"] = {"enabled": False, "import_positions": False}
        strategy._external_pairs = {"ETH/USDT:USDT"}
    elif gate == "external_reconciling":
        strategy.config["manual_position_sync"] = {"enabled": True, "import_positions": True}
        strategy._external_pairs = {"ETH/USDT:USDT"}
        strategy._manual_sync_blocked_pairs = {"ETH/USDT:USDT"}
    elif gate == "market_data":
        strategy._market_data_healthy = False
    else:
        strategy._market_down = True

    with patch.object(MODULE.time, "time", return_value=now):
        allowed = strategy.confirm_trade_entry(
            pair="BTC/USDT:USDT",
            order_type="market",
            amount=1.0,
            rate=100.0,
            time_in_force="GTC",
            current_time=ETH_TEST_NOW,
            entry_tag=None,
            side="long",
        )

    assert not allowed
    assert expected_reason in strategy._entry_block_reason


def test_entries_allowed_records_all_failed_global_reasons() -> None:
    now = ETH_TEST_NOW.timestamp()
    strategy = _entry_ready_strategy(now)
    strategy._data_healthy = False
    strategy._position_data_healthy = False

    assert not strategy._entries_allowed(now)
    assert strategy._entry_block_reason == "行情评分数据不完整; 仓位同步失败"


def test_select_entries_records_each_pair_decision_without_changing_selection() -> None:
    now = time.time()
    strategy = _entry_ready_strategy(now)
    strategy.settings["max_positions"] = 2
    strategy._scores = {
        "HELD": 110.0,
        "NO_TREND": 100.0,
        "UNSAFE": 99.0,
        "LOW": 39.0,
        "GOOD": 90.0,
        "EXTRA": 80.0,
    }
    strategy._metrics = {pair: _fresh_score_metric() for pair in strategy._scores}
    strategy._score_leaders = list(strategy._scores)
    strategy._metrics["NO_TREND"]["momentum"] = 0.0
    strategy._metrics["NO_TREND"]["trend_continuity"] = 0.0
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._execution_is_safe = lambda pair: pair != "UNSAFE"

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[SimpleNamespace(pair="HELD")]):
        selected = strategy._select_entries()

    assert selected == {"GOOD"}
    assert strategy._entry_decisions == {
        "HELD": "已持仓",
        "NO_TREND": "上涨条件不足: 1h涨幅=0.00%, 上涨连续性=0%",
        "UNSAFE": "盘口安全检查未通过",
        "LOW": "本轮剩余名额已用完",
        "GOOD": "入选第2仓: 形态关闭 强度90.0>=41.0",
        "EXTRA": "本轮剩余名额已用完",
    }
    strategy._scores = {"LOW": 39.0}
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[SimpleNamespace(pair="HELD")]):
        assert strategy._select_entries() == set()
    assert strategy._entry_decisions["LOW"] == "强度评分 39.0 < 第2仓门槛 41.0"


def test_status_logging_reads_cached_holding_state_without_network_or_decision_changes(
    caplog,
) -> None:
    strategy = _status_strategy()
    strategy._scores = {"BTC/USDT:USDT": 80.0}
    strategy._entry_pairs = {"BTC/USDT:USDT"}
    strategy._entry_decisions = {"BTC/USDT:USDT": "入选"}
    strategy._position_details = {"ETH/USDT:USDT": {"entryPrice": 2_000, "leverage": 3}}
    strategy.wallets.get_all_positions.return_value = {
        "BTC/USDT:USDT": SimpleNamespace(
            side="long", position=2.0, leverage=5, unrealized_pnl=1.25
        ),
        "ETH/USDT:USDT": SimpleNamespace(
            side="long", position=1.0, leverage=3, unrealized_pnl=-0.5
        ),
    }
    db_trade = SimpleNamespace(
        pair="BTC/USDT:USDT",
        open_rate=100.0,
        leverage=5,
        stoploss_or_liquidation=90.0,
        has_open_sl_orders=True,
    )
    before = (strategy._entry_block_reason, strategy._entry_pairs.copy(), strategy._scores.copy())

    with (
        caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[db_trade]),
    ):
        strategy._log_strategy_status(1_000.0)
        first_count = len(caplog.records)
        strategy._log_strategy_status(1_299.0)
        assert len(caplog.records) == first_count
        strategy._log_strategy_status(1_300.0)

    messages = [record for record in caplog.records if "🧭 策略状态" in record.getMessage()]
    holding = [record for record in caplog.records if "📦 持仓明细" in record.getMessage()]
    assert len(messages) == 2
    assert len(holding) == 2
    assert all("2000" in record.getMessage() for record in holding)
    for record in holding:
        table = record.strategy_log_table
        assert [cell.plain for cell in table.columns[0]._cells] == [
            "BTC/USDT:USDT",
            "ETH/USDT:USDT",
        ]
        assert [row.style for row in table.rows] == ["green", "red"]
        assert "\x1b" not in record.getMessage()
    selection = [record for record in caplog.records if "📊 评分综合明细" in record.getMessage()]
    assert len(selection) == 2
    assert "BTC/USDT:USDT" in selection[0].getMessage()
    assert "入选" in selection[0].getMessage()
    assert strategy._entry_block_reason == before[0]
    assert strategy._entry_pairs == before[1]
    assert strategy._scores == before[2]
    assert strategy.dp._exchange.mock_calls == []
    assert strategy.wallets.get_all_positions.call_count == 2


@pytest.mark.parametrize("invalid_seconds", [0, -1, float("inf"), float("nan"), "invalid"])
def test_invalid_status_log_period_fails_before_network_or_state_access(
    tmp_path, invalid_seconds
) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "dry_run": False,
        "runmode": "live",
        "user_data_dir": str(tmp_path),
        "leader_squeeze": {**configured_settings(), "status_log_seconds": invalid_seconds},
    }
    strategy._load_risk_state = Mock(return_value={})
    strategy._sync_external_pairs = Mock()

    with pytest.raises(ValueError):
        strategy.bot_start()

    strategy._load_risk_state.assert_not_called()
    strategy._sync_external_pairs.assert_not_called()


def test_trend_continuity_increases_the_confidence_score() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._liquidation_score = lambda symbol, now: 0.0
    strategy._market_id = lambda pair: pair
    metrics = {
        "TRENDING": {
            "momentum": 0.10,
            "trend_continuity": 1.0,
            "volume_ratio": 2.0,
            "volume_activity_ratio": 3.0,
            "taker_ratio": 1.2,
            "taker_ratio_latest": 1.2,
            "oi_change": -0.01,
        },
        "CHOPPY": {
            "momentum": 0.10,
            "trend_continuity": 0.0,
            "volume_ratio": 2.0,
            "volume_activity_ratio": 3.0,
            "taker_ratio": 1.2,
            "taker_ratio_latest": 1.2,
            "oi_change": -0.01,
        },
    }

    strategy._apply_scores(1.0, metrics, metrics)

    assert strategy._scores["TRENDING"] > strategy._scores["CHOPPY"]


def test_apply_scores_logs_each_component_in_chinese(caplog) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.settings["raw_metrics_log_enabled"] = True
    strategy._score_selection = ["LEADER"]
    strategy._liquidation_score = lambda symbol, now: 0.25
    strategy._market_id = lambda pair: pair
    metrics = {
        "LEADER": {
            "momentum": 0.10,
            "trend_continuity": 1.0,
            "volume_ratio": 2.0,
            "volume_activity_ratio": 3.0,
            "taker_ratio": 1.2,
            "taker_ratio_latest": 1.2,
            "oi_change": -0.01,
            "_funding_valid_until": 100.0,
            "funding_rate": -0.009,
            "funding_interval_hours": 8.0,
            "funding_rate_hourly": -0.009 / 8,
            "funding_floor": -0.02,
            "funding_floor_hourly": -0.02 / 8,
            "funding_cap": 0.02,
            "funding_next_time": 2000.0,
        },
        "FOLLOWER": {
            "momentum": 0.05,
            "trend_continuity": 1.0,
            "volume_ratio": 1.5,
            "volume_activity_ratio": 2.0,
            "taker_ratio": 1.0,
            "taker_ratio_latest": 1.0,
            "oi_change": -0.02,
        },
    }

    with caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"):
        strategy._apply_scores(1.0, metrics, metrics)
        assert not any(hasattr(record, "strategy_log_table") for record in caplog.records)
        # The score pass only stores a snapshot.  The status pass owns the
        # rendered table so it can show the decisions from this selection.
        strategy._entry_decisions = {
            "LEADER": "本轮筛选后拦截",
            "FOLLOWER": "本轮筛选后入选",
        }
        assert strategy._consume_score_report(report_now=1.0)
        assert not strategy._consume_score_report(report_now=1.0)

    table_logs = [record for record in caplog.records if hasattr(record, "strategy_log_table")]
    assert len(table_logs) == 2
    component_logs = [record.getMessage() for record in table_logs]
    primary_labels = (
        "买入评分",
        "原评分",
        "加权分项(动/放/买/费)",
        "热度/形态(涨幅/偏离/折扣/阶段分)",
        "趋势(持仓/背景)",
        "筛选结果",
    )
    detail_labels = (
        "原始指标(动/量/买)",
        "资金费率(本期/每h/8h/限/位/调/结)",
    )
    assert all(label in component_logs[0] for label in primary_labels)
    assert all(label in component_logs[1] for label in detail_labels)
    for message in component_logs:
        assert all(pair in message for pair in metrics)
        assert "\x1b" not in message
    score_table = table_logs[0].strategy_log_table
    detail_table = table_logs[1].strategy_log_table
    assert [cell.plain for cell in score_table.columns[1]._cells] == ["LEADER", "FOLLOWER"]
    assert [cell.plain for cell in score_table.columns[7]._cells] == [
        "本轮筛选后拦截",
        "榜外持仓 | 本轮筛选后入选",
    ]
    assert "本批评分 2 个 = 本轮选币 1 个 + 榜外持仓监控 1 个" in score_table.caption.plain
    for index, pair in enumerate(("LEADER", "FOLLOWER")):
        assert float(score_table.columns[3]._cells[index].plain) == pytest.approx(
            strategy._scores[pair], abs=0.05
        )
        component_total = sum(
            float(value)
            for value in re.findall(r"\d+\.\d+", score_table.columns[4]._cells[index].plain)
        )
        assert component_total == pytest.approx(strategy._scores[pair], abs=0.15)
    assert "行情不足/禁止" in component_logs[0]
    assert "不可用/过期" in component_logs[1]
    assert "-0.90000%" in component_logs[1]
    assert "-0.11250%" in component_logs[1]
    assert "45%" in component_logs[1]
    assert "1.35" in component_logs[1]
    assert "01-01 08:33" in detail_table.columns[3]._cells[0].plain

    caplog.clear()
    strategy.settings["raw_metrics_log_enabled"] = False
    strategy._score_report_dirty = True
    with caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"):
        assert strategy._consume_score_report(report_now=1.0)
    table_logs = [record for record in caplog.records if hasattr(record, "strategy_log_table")]
    assert len(table_logs) == 1
    assert "评分综合明细" in table_logs[0].getMessage()
    assert "原始指标与资金费率" not in table_logs[0].getMessage()


def test_raw_metrics_log_switch_requires_boolean() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings["raw_metrics_log_enabled"] = "false"

    with pytest.raises(ValueError, match="raw_metrics_log_enabled"):
        SUPPORT.validate_runtime_settings(strategy)


@pytest.mark.parametrize("width", [80, 140])
def test_log_table_wraps_long_cells_without_truncation(caplog, width) -> None:
    from io import StringIO

    from rich.cells import cell_len
    from rich.console import Console

    pair = "龙虾/USDT:USDT"
    long_reason = "交易对或全局多单交易锁生效; 等待下一轮评估"
    with caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"):
        SUPPORT._log_table(
            "选币结果",
            ["排名", "交易对", "筛选结果"],
            [["1", pair, long_reason], ["2", "[red]literal[/red]", "无"]],
        )
    output = StringIO()
    Console(file=output, width=width, color_system=None).print(
        caplog.records[-1].strategy_log_table
    )
    rendered = output.getvalue()
    assert pair in rendered
    assert "[red]literal[/red]" in rendered
    assert "…" not in rendered
    assert all(cell_len(line) <= width for line in rendered.splitlines())
    assert long_reason in caplog.records[-1].getMessage()


def test_market_down_requires_eight_of_ten_leaders_and_sufficient_coverage() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    leaders = [f"L{index}" for index in range(10)]
    candles = {pair: {"momentum": -0.01} for pair in leaders[:7]}

    strategy._update_market_state(leaders, candles)

    assert not strategy._market_data_healthy
    assert not strategy._market_down

    candles["L7"] = {"momentum": 0.0}
    strategy._update_market_state(leaders, candles)

    assert strategy._market_data_healthy
    assert strategy._market_down

    candles["L7"]["momentum"] = 0.01
    strategy._update_market_state(leaders, candles)

    assert strategy._market_data_healthy
    assert not strategy._market_down


def test_market_emergency_exits_an_existing_trade() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._account_stopped = False
    strategy._market_down = True
    strategy._market_emergency = True
    strategy._market_valid_until = time.time() + 300

    assert (
        strategy.custom_exit(
            "BTC/USDT:USDT",
            SimpleNamespace(),
            datetime.now(UTC),
            100.0,
            0.0,
        )
        == "market_emergency"
    )


def test_progressive_slot_floors_accept_only_candidates_for_their_next_slot() -> None:
    now = time.time()
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy.settings["entry_setup_enabled"] = False
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._scores = {
        "DOWN": 110.0,
        "FADING": 105.0,
        "A": 90.0,
        "B": 60.0,
        "C": 41.99,
    }
    strategy._metrics = {pair: _fresh_score_metric() for pair in strategy._scores}
    strategy._score_leaders = list(strategy._scores)
    strategy._metrics["DOWN"]["momentum"] = -0.01
    strategy._metrics["FADING"]["trend_continuity"] = 1 / 3
    strategy._external_pairs = set()
    strategy._data_healthy = True
    strategy._last_good_data = now
    strategy._daily_blocked = False
    strategy._account_stopped = False
    strategy._market_data_healthy = True
    strategy._eth_entries_allowed = lambda now: True
    strategy._liquidation_connected = type("Connected", (), {"is_set": lambda self: True})()
    strategy._liquidation_last_message = now
    strategy._position_data_healthy = True
    strategy._last_position_sync = now
    strategy._execution_is_safe = lambda pair: True

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {"A", "B"}
        strategy._scores["C"] = 42.0
        assert strategy._select_entries() == {"A", "B", "C"}

        strategy._scores = {"LOW": 39.0}
        strategy._metrics = {"LOW": _fresh_score_metric()}
        strategy._score_leaders = ["LOW"]
        assert strategy._select_entries() == set()


def test_liquidation_worker_accepts_only_usdm_buy_and_uses_filled_quantity() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.config = {**PUBLIC_CONFIG, "exchange": {"ccxt_config": {}}}
    strategy._stop_event = threading.Event()
    strategy._liquidation_connected = threading.Event()
    strategy._liquidation_started = 0.0
    strategy._liquidation_lock = threading.Lock()
    strategy._liquidations = defaultdict(deque)

    def event(market_type: int, side: str, original_quantity: str, filled_quantity: str):
        return {
            "stream": "!forceOrder@arr",
            "data": {
                "st": market_type,
                "o": {
                    "s": "BTCUSDT",
                    "S": side,
                    "ap": "100",
                    "q": original_quantity,
                    "z": filled_quantity,
                },
            },
        }

    payloads = iter(
        [
            event(2, "BUY", "100", "2"),
            event(1, "SELL", "100", "3"),
            event(1, "BUY", "100", "4"),
        ]
    )

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def recv(self, timeout):
            try:
                return json.dumps(next(payloads))
            except StopIteration:
                strategy._stop_event.set()
                raise TimeoutError

    with patch.object(DATA, "connect", return_value=FakeSocket()):
        strategy._liquidation_worker()

    events = list(strategy._liquidations["BTCUSDT"])
    assert len(events) == 1
    assert events[0][1] == pytest.approx(400.0)


def test_taker_metric_freshness_uses_the_fifteen_minute_period_end() -> None:
    metrics, headers = _fetch_pair_metrics_fixture()

    assert metrics["taker_ratio"] == pytest.approx(1.2)
    assert "adl_risk_score" not in metrics
    assert "X-MBX-APIKEY" not in headers


@pytest.mark.parametrize(
    "interruption",
    [None, "no_challenger", "no_held", "blocked", "stale_challenger", "unsafe_book", "unavailable"],
)
def test_rotation_confirmation_requires_adjacent_closed_candles(interruption) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._entries_allowed = lambda now: True
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._persist_rotation = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy.settings = configured_settings()
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy.settings["entry_setup_enabled"] = False
    strategy.settings["replacement_confirmations"] = 2
    strategy.settings["replacement_fast_enabled"] = False
    strategy.settings["max_positions"] = 1
    bar = 1_800_000.0
    strategy._rotation_bar = Mock(side_effect=lambda pair: bar)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy.settings["replacement_cooldown_minutes"] = 0
    strategy._scores = {"WEAK": 40.0, "CHALLENGER": 100.0}
    strategy._metrics = {
        "CHALLENGER": _fresh_score_metric(),
        "WEAK": _fresh_score_metric(),
    }
    strategy._external_pairs = set()
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy._rotation_score_snapshot = 0.0
    strategy._last_rotation = 0.0
    strategy._last_score_refresh = 12345.0
    strategy._position_first_seen = {}
    strategy._rotation_holding_weak = lambda pair: True
    current_time = datetime.now(UTC)
    weak_trade = type(
        "TradeStub",
        (),
        {
            "id": 1,
            "pair": "WEAK",
            "is_short": False,
            "open_date_utc": current_time - timedelta(hours=1),
        },
    )()
    now = time.time() + 3600

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak_trade]):
        strategy._plan_rotation(now, current_time)
        assert strategy._rotation_seen == 1
        assert strategy._rotation_pair is None

        strategy._plan_rotation(now + 1, current_time + timedelta(seconds=1))
        assert strategy._rotation_pair is None

        if interruption:
            strategy._last_score_refresh += 900
            bar += 900
            original_scores = strategy._scores.copy()
            if interruption == "no_challenger":
                strategy._scores = {"WEAK": 40.0}
            elif interruption == "blocked":
                strategy._entries_allowed = lambda now: False
                strategy._entry_block_reason = "仓位同步失败"
            elif interruption == "stale_challenger":
                strategy._candle_metrics = Mock(return_value=None)
            elif interruption == "unsafe_book":
                strategy._execution_is_safe.return_value = False
            elif interruption == "unavailable":
                strategy._entry_pair_available.return_value = False
            with patch.object(
                MODULE.Trade,
                "get_open_trades",
                return_value=[] if interruption == "no_held" else [weak_trade],
            ):
                strategy._plan_rotation(now + 300, current_time + timedelta(minutes=15))
            assert strategy._rotation_seen == 0
            assert strategy._rotation_candidate is None
            strategy._scores = original_scores
            strategy._entries_allowed = lambda now: True
            strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
            strategy._trend_reversed = Mock(return_value=False)
            strategy._execution_is_safe.return_value = True
            strategy._entry_pair_available.return_value = True

        strategy._last_score_refresh += 900
        bar += 900
        strategy._plan_rotation(now + 900, current_time + timedelta(minutes=15))
        if interruption:
            assert strategy._rotation_seen == 1
            assert strategy._rotation_pair is None
            strategy._last_score_refresh += 900
            bar += 900
            strategy._plan_rotation(now + 1800, current_time + timedelta(minutes=30))
    assert strategy._rotation_pair == "WEAK"
    assert strategy._rotation_target == "CHALLENGER"


@pytest.mark.parametrize("safe", [False, True])
def test_rotation_never_sells_before_buy_and_preserves_other_exits(safe) -> None:
    strategy = _entry_ready_strategy(time.time())
    strategy._rotation_pair, strategy._rotation_target = "WEAK", "TARGET"
    strategy._metrics.update({"WEAK": _fresh_score_metric(), "TARGET": _fresh_score_metric()})
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._execution_is_safe = Mock(return_value=safe)
    strategy._trend_reversed = Mock(return_value=False)

    reason = strategy.custom_exit("WEAK", SimpleNamespace(), ETH_TEST_NOW, 100.0, 0.0)

    assert reason is None
    strategy._execution_is_safe.assert_not_called()
    strategy._trend_reversed.return_value = True
    assert (
        strategy.custom_exit("WEAK", SimpleNamespace(), ETH_TEST_NOW, 100.0, 0.0)
        == "trend_reversal"
    )


@pytest.mark.parametrize("amount,allowed", [(0.25, True), (2.0, False)])
def test_actual_entry_rechecks_book_with_actual_quantity(amount, allowed) -> None:
    strategy = _entry_ready_strategy(time.time())
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy.wallets = SimpleNamespace(get_total_stake_amount=Mock(return_value=100.0))
    exchange = SimpleNamespace(
        fetch_l2_order_book=Mock(return_value={"bids": [[99.99, 1]], "asks": [[100, 1]]})
    )
    strategy.dp = SimpleNamespace(_exchange=exchange)
    strategy._execution_order_book("BTC/USDT:USDT")

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert (
            strategy.confirm_trade_entry(
                "BTC/USDT:USDT", "market", amount, 100.0, "GTC", ETH_TEST_NOW, None, "long"
            )
            is allowed
        )
    exchange.fetch_l2_order_book.assert_called_once_with("BTC/USDT:USDT", 20)
    strategy.wallets.get_total_stake_amount.assert_not_called()
    if not allowed:
        assert strategy._entry_block_reason == "前20档卖盘深度不足"


@pytest.mark.parametrize(
    "locked_pair,side,allowed",
    [("TARGET", "long", False), ("*", "long", False), ("*", "*", False), ("TARGET", "short", True)],
)
def test_rotation_buy_respects_framework_pair_and_global_locks(
    monkeypatch, locked_pair, side, allowed
) -> None:
    monkeypatch.setattr(PairLocks, "use_db", False)
    monkeypatch.setattr(PairLocks, "locks", [])
    monkeypatch.setattr(PairLocks, "timeframe", "5m")
    PairLocks.lock_pair(
        locked_pair, ETH_TEST_NOW + timedelta(minutes=10), now=ETH_TEST_NOW, side=side
    )
    strategy = _entry_ready_strategy(time.time())
    del strategy._entry_pair_available
    strategy.dp = SimpleNamespace(current_whitelist=lambda: ["TARGET"])
    strategy._closed_candles = Mock(
        return_value=pd.DataFrame({"date": [ETH_TEST_NOW - timedelta(minutes=15)]})
    )
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._execution_is_safe = Mock(return_value=True)
    strategy._trend_reversed = Mock(return_value=False)
    strategy._metrics.update({"WEAK": _fresh_score_metric(), "TARGET": _fresh_score_metric()})
    strategy._rotation_pair, strategy._rotation_target = "WEAK", "TARGET"

    assert strategy._entry_pair_available("TARGET") is allowed
    assert strategy.custom_exit("WEAK", SimpleNamespace(), ETH_TEST_NOW, 100.0, 0.0) is None
    strategy._execution_is_safe.assert_not_called()
    if not allowed:
        assert "交易锁生效" in strategy._pair_entry_block_reason


@pytest.mark.parametrize("failure", ["absent", "lock_error", "whitelist_error", "candles"])
def test_unavailable_target_cannot_be_selected_bought_or_trigger_rotation(failure) -> None:
    strategy = _entry_ready_strategy(time.time())
    del strategy._entry_pair_available
    pair = "BTC/USDT:USDT"
    strategy._scores = {pair: 100.0}
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._closed_candles = Mock(
        return_value=pd.DataFrame({"date": [ETH_TEST_NOW - timedelta(minutes=15)]})
    )
    strategy.dp = SimpleNamespace(current_whitelist=Mock(return_value=[pair]))
    strategy.is_pair_locked = Mock(return_value=False)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy._trend_reversed = Mock(return_value=False)
    if failure == "absent":
        strategy.dp.current_whitelist.return_value = []
    elif failure == "lock_error":
        strategy.is_pair_locked.side_effect = RuntimeError("lock read failed")
    elif failure == "whitelist_error":
        strategy.dp.current_whitelist.side_effect = RuntimeError("pairlist read failed")
    else:
        strategy._closed_candles.return_value = None
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == set()
    assert not strategy.confirm_trade_entry(
        pair, "market", 1.0, 100.0, "GTC", ETH_TEST_NOW, None, "long"
    )
    strategy._rotation_pair, strategy._rotation_target = "WEAK", pair
    assert strategy.custom_exit("WEAK", SimpleNamespace(), ETH_TEST_NOW, 100.0, 0.0) is None
    strategy._execution_is_safe.assert_not_called()


@pytest.mark.parametrize("weak_still_held", [False, True])
def test_pending_rotation_clears_unavailable_target_before_next_score(weak_still_held) -> None:
    strategy = _entry_ready_strategy(time.time())
    strategy._rotation_pair = "WEAK" if weak_still_held else None
    strategy._rotation_target = "TARGET"
    strategy._rotation_candidate, strategy._rotation_seen = ("WEAK", "TARGET"), 1
    strategy._entry_pair_available.return_value = False
    strategy._plan_rotation(time.time(), ETH_TEST_NOW)
    assert strategy._rotation_pair is strategy._rotation_target is None
    assert strategy._rotation_candidate is None
    assert strategy._rotation_seen == 0


@pytest.mark.parametrize(
    "book",
    [
        {"bids": [[99, 10]], "asks": [[100, 10]]},  # Excessive spread.
        {"bids": [[100, 10]], "asks": [[100, 0.1], [101, 10]]},  # Excessive slippage.
        {"bids": [[float("nan"), 10]], "asks": [[100, 10]]},
        {"bids": [[101, 10]], "asks": [[100, 10]]},  # Crossed book.
        {"bids": [[100, 10]], "asks": [[100, 0.1], [99, 10]]},  # Unsorted asks.
        {"bids": [], "asks": []},
    ],
)
def test_execution_guard_rejects_unsafe_or_invalid_books(book) -> None:
    strategy = _entry_ready_strategy(time.time())
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(fetch_l2_order_book=Mock(return_value=book))
    )
    assert not strategy._execution_is_safe("BTC/USDT:USDT", amount=1.0)


def test_rotation_does_not_treat_an_unscored_held_pair_as_zero() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._entries_allowed = lambda now: True
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy.settings = configured_settings()
    strategy.settings["replacement_cooldown_minutes"] = 0
    strategy._scores = {"CHALLENGER": 100.0}
    strategy._metrics = {
        "CHALLENGER": _fresh_score_metric(),
    }
    strategy._external_pairs = set()
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy._rotation_score_snapshot = 0.0
    strategy._last_rotation = 0.0
    strategy._last_score_refresh = 12345.0
    strategy._position_first_seen = {}
    strategy._rotation_holding_weak = lambda pair: True
    current_time = datetime.now(UTC)
    weak_trade = SimpleNamespace(
        pair="UNSCORED",
        is_short=False,
        open_date_utc=current_time - timedelta(hours=1),
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak_trade]):
        strategy._plan_rotation(time.time() + 3600, current_time)

    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None


def test_rotation_target_requires_the_strictest_slot_score() -> None:
    now = time.time()
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy.settings["entry_setup_enabled"] = False
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._scores = {"TARGET": 60.0}
    strategy._metrics = {"TARGET": _fresh_score_metric()}
    strategy._score_leaders = ["TARGET"]
    strategy._rotation_target = "TARGET"
    strategy._external_pairs = set()
    strategy._data_healthy = True
    strategy._last_good_data = now
    strategy._daily_blocked = False
    strategy._account_stopped = False
    strategy._market_data_healthy = True
    strategy._eth_entries_allowed = lambda now: True
    strategy._liquidation_connected = type("Connected", (), {"is_set": lambda self: True})()
    strategy._liquidation_last_message = now
    strategy._position_data_healthy = True
    strategy._last_position_sync = now
    strategy._execution_is_safe = lambda pair: True
    open_trades = [SimpleNamespace(pair=f"HELD-{index}") for index in range(4)]

    with patch.object(MODULE.Trade, "get_open_trades", return_value=open_trades):
        assert strategy._select_entries() == {"TARGET"}

        strategy._scores["TARGET"] = 44.0
        assert strategy._select_entries() == set()


def test_rotation_before_buy_is_cancelled_if_weak_exits_independently() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._rotation_pair = "WEAK"
    strategy._rotation_target = "TARGET"
    strategy._external_pairs = set()
    strategy._scores = {"TARGET": 60.0}
    strategy._next_score_refresh = float("inf")
    strategy._position_data_healthy = True
    strategy._persist_rotation = Mock(return_value=True)
    strategy._rotation_state = {
        "weak": "WEAK",
        "target": "TARGET",
        "token": "test",
        "phase": "buy",
        "amount": 0.0,
        "weak_trade_id": None,
    }

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        strategy._sync_rotation_state()

    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None
    assert strategy._rotation_state is None


def test_timeframe_reversal_low_level_uses_15m_structure_data() -> None:
    from tests.strategy.test_leader_squeeze_freshness import NOW_SECONDS, _reversal_15m

    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(get_pair_dataframe=Mock(return_value=_reversal_15m()))
    strategy.settings = configured_settings()
    with patch.object(MODULE.time, "time", return_value=NOW_SECONDS):
        assert strategy._timeframe_reversed("BTC/USDT:USDT", "15m")
    strategy.dp.get_pair_dataframe.assert_called_once_with("BTC/USDT:USDT", "15m")


def test_score_network_refresh_is_background_and_includes_held_pairs() -> None:
    started = threading.Event()
    release = threading.Event()
    captured = []

    def fetch_metrics(pairs):
        captured.extend(pairs)
        started.set()
        release.wait(2)
        return {}

    strategy = configured_strategy(LeaderSqueezeStrategy)
    leaders = [f"L{index}" for index in range(20)]
    strategy.dp = SimpleNamespace(
        current_whitelist=lambda: [*leaders, "DB"],
        current_selection_whitelist=lambda: leaders.copy(),
    )
    strategy._external_pairs = {"EXT"}
    strategy._data_healthy = False
    strategy._score_pending = False
    strategy._score_result = None
    strategy._score_result_lock = threading.Lock()
    strategy._fetch_market_metrics = fetch_metrics
    db_trade = SimpleNamespace(pair="DB")

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[db_trade]):
        strategy._start_score_refresh(1.0)

    assert started.wait(1)
    assert strategy._score_pending
    assert strategy._score_result is None
    release.set()
    for _ in range(100):
        if not strategy._score_pending:
            break
        time.sleep(0.01)

    assert set(captured) == set(leaders) | {"DB", "EXT"}
    assert strategy._score_result[1] == leaders
    assert strategy._score_selection == leaders


def test_score_refresh_scores_held_pairs_and_requires_eighty_percent_of_leaders() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    leaders = [f"L{index}" for index in range(10)]
    remote = {
        "taker_ratio": 1.2,
        "taker_ratio_latest": 1.2,
        "oi_change": -0.01,
        "_exit_valid_until": 1000.0,
        "_score_valid_until": 1000.0,
    }
    candle = {
        "momentum": 0.05,
        "trend_continuity": 1.0,
        "volume_ratio": 2.0,
        "volume_activity_ratio": 3.0,
        "_candle_valid_until": 1000.0,
    }
    metrics = {pair: remote.copy() for pair in [*leaders[:8], "HELD"]}
    strategy._score_result = (1.0, leaders, metrics)
    strategy._score_result_lock = threading.Lock()
    strategy._candle_metrics = lambda pair: candle.copy()
    strategy._liquidation_score = lambda symbol, now: 0.0
    strategy._market_id = lambda pair: pair
    strategy._data_healthy = False

    assert strategy._consume_score_refresh(1.0)
    assert strategy._market_data_healthy
    assert "HELD" in strategy._scores

    strategy._score_result = (
        2.0,
        leaders,
        {pair: remote.copy() for pair in leaders[:7]},
    )

    assert not strategy._consume_score_refresh(2.0)
    assert not strategy._data_healthy


@pytest.mark.parametrize("fault", ["stale", "gap", "missing_date", "nan", "negative_volume"])
def test_bad_candles_cannot_refresh_scores(fault) -> None:
    now = ETH_TEST_NOW.timestamp()
    frame = pd.DataFrame(
        {
            "date": pd.date_range(
                end=ETH_TEST_NOW - timedelta(minutes=15), periods=24, freq="15min"
            ),
            "close": [100.0] * 24,
            "volume": [10.0] * 24,
        }
    )
    if fault == "stale":
        frame["date"] -= timedelta(days=1)
    elif fault == "gap":
        frame.loc[20, "date"] -= timedelta(minutes=15)
    elif fault == "missing_date":
        frame = frame.drop(columns="date")
    elif fault == "nan":
        frame.loc[23, "close"] = float("nan")
    else:
        frame.loc[23, "volume"] = -1
    strategy = _entry_ready_strategy(now)
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)
    strategy._score_result_lock = threading.Lock()
    strategy._score_result = (now, ["BTC"], {"BTC": {}})
    strategy._apply_scores = Mock()
    strategy._rotation_candidate, strategy._rotation_seen = ("WEAK", "BTC"), 1
    with patch.object(MODULE.time, "time", return_value=now):
        assert not strategy._consume_score_refresh(now)
    strategy._apply_scores.assert_not_called()
    assert not strategy._data_healthy
    assert not strategy._market_data_healthy
    assert strategy._rotation_seen == 0


def test_candle_metrics_ignore_unclosed_candle() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.date_range(end=ETH_TEST_NOW, periods=25, freq="15min"),
            "close": [100.0] * 24 + [1000.0],
            "volume": [10.0] * 25,
        }
    )
    strategy = _entry_ready_strategy(ETH_TEST_NOW.timestamp())
    strategy.settings["volume_activity_baseline_candles"] = 20
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)
    with patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()):
        assert strategy._candle_metrics("BTC")["momentum"] == 0.0


def test_blocked_entries_cancel_pending_rotation_without_new_scores() -> None:
    now = ETH_TEST_NOW.timestamp()
    strategy = _entry_ready_strategy(now)
    strategy._rotation_pair, strategy._rotation_target = "WEAK", "TARGET"
    strategy._rotation_candidate, strategy._rotation_seen = ("WEAK", "TARGET"), 1
    strategy._last_score_refresh = strategy._rotation_score_snapshot = now
    strategy._position_data_healthy = False
    strategy._plan_rotation(now, ETH_TEST_NOW)
    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None
    assert strategy._rotation_candidate is None
    assert strategy._rotation_seen == 0


@pytest.mark.parametrize("equity", [940.0, 890.0, 500.0])
def test_daily_loss_and_peak_drawdown_are_statistics_only(equity) -> None:
    now = ETH_TEST_NOW.timestamp()
    strategy = _entry_ready_strategy(now)
    strategy._account_stopped = True  # Legacy flag must not gate entries either.
    strategy.config = {**PUBLIC_CONFIG, "stake_currency": "USDT"}
    strategy.wallets = SimpleNamespace(
        get_all_positions=dict,
        get_total=lambda currency: equity,
    )
    strategy.dp = SimpleNamespace(send_msg=Mock())
    strategy._risk_state = {
        "day": ETH_TEST_NOW.date().isoformat(),
        "day_start_equity": 1000.0,
        "peak_equity": 1000.0,
        "daily_blocked": True,
        "account_stopped": True,
    }
    strategy._save_risk_state = Mock()
    strategy._refresh_risk_state(ETH_TEST_NOW)
    assert "daily_blocked" not in strategy._risk_state
    assert strategy._risk_state["account_stopped"] is False
    assert strategy._entries_allowed(now)
    assert strategy._risk_state["day_start_equity"] == 1000.0
    assert strategy._risk_state["peak_equity"] == 1000.0
    assert strategy._risk_state["last_equity"] == equity
    strategy.dp.send_msg.assert_not_called()
    strategy._save_risk_state.assert_called_once()


def test_risk_state_periodic_checkpoint_is_throttled() -> None:
    strategy = _entry_ready_strategy(ETH_TEST_NOW.timestamp())
    strategy.config = {**PUBLIC_CONFIG, "stake_currency": "USDT"}
    strategy.wallets = SimpleNamespace(get_all_positions=dict, get_total=lambda currency: 1000.0)
    strategy._risk_state = {
        "day": ETH_TEST_NOW.date().isoformat(),
        "day_start_equity": 1000.0,
        "peak_equity": 1000.0,
        "account_stopped": False,
    }
    strategy._last_risk_state_checkpoint = -math.inf
    strategy._save_risk_state = Mock(return_value=True)

    with patch.object(MODULE.time, "monotonic", side_effect=[100.0, 120.0, 161.0]):
        strategy._refresh_risk_state(ETH_TEST_NOW)
        strategy._refresh_risk_state(ETH_TEST_NOW)
        strategy._refresh_risk_state(ETH_TEST_NOW)

    assert strategy._save_risk_state.call_count == 2


def test_custom_exit_blocks_entries_and_alerts_after_configured_failures(caplog) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._market_exit_required = Mock(side_effect=RuntimeError("broken"))
    strategy.dp = SimpleNamespace(send_msg=Mock())
    pair = "BTC/USDT:USDT"
    limit = strategy.settings["exit_evaluation_failure_limit"]

    with caplog.at_level(logging.ERROR, logger="leader_squeeze_strategy"):
        for _ in range(limit + 1):
            assert strategy.custom_exit(pair, SimpleNamespace(), ETH_TEST_NOW, 100.0, 0.0) is None

    assert strategy._exit_evaluation_failures[pair] == limit + 1
    assert "退出评估异常" in caplog.records[-1].getMessage()
    strategy.dp.send_msg.assert_called_once()
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[SimpleNamespace(pair=pair)]):
        assert strategy._exit_evaluation_block_reason()


def test_closed_trade_clears_stale_exit_evaluation_failure() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    pair = "BTC/USDT:USDT"
    strategy._exit_evaluation_failures = {pair: strategy.settings["exit_evaluation_failure_limit"]}
    strategy._external_pairs = set()

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._exit_evaluation_block_reason() is None

    assert pair not in strategy._exit_evaluation_failures


def test_exit_evaluation_failure_gate_survives_trade_lookup_error() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._exit_evaluation_failures = {
        "BTC/USDT:USDT": strategy.settings["exit_evaluation_failure_limit"]
    }
    strategy._warn_data_unavailable = Mock()

    with patch.object(MODULE.Trade, "get_open_trades", side_effect=RuntimeError("database")):
        reason = strategy._exit_evaluation_block_reason()

    assert reason == "退出评估连续失败且持仓复核异常, 暂停新开仓"
    strategy._warn_data_unavailable.assert_called_once()


def test_bot_loop_revokes_stale_entry_authorization_before_failure() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._entry_pairs = {"BTC/USDT:USDT"}
    strategy._prune_pending_entry_scores = Mock(side_effect=RuntimeError("broken"))

    with pytest.raises(RuntimeError, match="broken"):
        strategy.bot_loop_start(ETH_TEST_NOW)

    assert strategy._entry_pairs == set()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_clamp_rejects_non_finite_values(value) -> None:
    assert LeaderSqueezeStrategy._clamp(value, 0.2, 0.8) == 0.2


def test_eth_blocked_refresh_only_fetches_held_exit_metrics() -> None:
    strategy = _entry_ready_strategy(1000.0)
    strategy.dp = SimpleNamespace(
        current_whitelist=Mock(side_effect=AssertionError("no candidates"))
    )
    strategy._external_pairs = {"EXT"}
    strategy._score_result_lock = threading.Lock()
    strategy._score_result = None
    strategy._scores = {"OLD": 80.0}
    strategy._apply_scores = Mock()
    metrics = {
        pair: {"taker_ratio": 0.9, "oi_change": 0.01, "_exit_valid_until": 1200.0}
        for pair in ("DB", "EXT")
    }
    strategy._fetch_market_metrics = Mock(return_value=metrics)
    with (
        patch.object(MODULE.Trade, "get_open_trades", return_value=[SimpleNamespace(pair="DB")]),
        patch.object(
            MODULE.threading,
            "Thread",
            side_effect=lambda target, **kwargs: SimpleNamespace(start=target),
        ),
        patch.object(MODULE.time, "time", return_value=1900.0),
    ):
        strategy._start_score_refresh(1000.0, exit_only=True)
    strategy._fetch_market_metrics.assert_called_once_with(["DB", "EXT"], exit_only=True)
    assert not strategy._consume_score_refresh(1000.0, allow_scoring=False)
    assert strategy._exit_metrics == metrics
    assert strategy._scores == {"OLD": 80.0}
    strategy._apply_scores.assert_not_called()
    assert strategy._next_score_refresh == 1170.0


def test_inflight_score_result_cannot_rank_after_eth_becomes_blocked() -> None:
    strategy = _entry_ready_strategy(1000.0)
    strategy._score_result_lock = threading.Lock()
    metric = {"taker_ratio": 0.9, "oi_change": 0.01, "_exit_valid_until": 1200.0}
    strategy._score_result = (1000.0, ["NEW"], {"NEW": metric})
    strategy._apply_scores = Mock()
    assert not strategy._consume_score_refresh(1000.0, allow_scoring=False)
    strategy._apply_scores.assert_not_called()
    assert strategy._exit_metrics["NEW"] == metric


def test_exit_metrics_update_even_when_score_coverage_fails() -> None:
    strategy = _entry_ready_strategy(1000.0)
    strategy._score_result_lock = threading.Lock()
    metric = {"taker_ratio": 0.9, "oi_change": 0.01, "_exit_valid_until": 1200.0}
    strategy._score_result = (1000.0, ["MISSING"], {"HELD": metric})
    strategy._candle_metrics = Mock(return_value=None)
    assert not strategy._consume_score_refresh(1000.0)
    assert strategy._exit_metrics["HELD"] == metric
    assert not strategy._data_healthy


def test_exit_only_http_skips_disabled_oi_and_removed_crowding_endpoints() -> None:
    strategy = _entry_ready_strategy(1000.0)
    strategy.config = {**PUBLIC_CONFIG, "exchange": {}}
    strategy._market_id = lambda pair: "BTCUSDT"
    payloads = {
        "takerlongshortRatio": [{"buyVol": "0.9", "sellVol": "1", "timestamp": 3_600_000}],
        "openInterestHist": [
            {"sumOpenInterest": str(value), "timestamp": timestamp}
            for value, timestamp in zip(
                (100, 101, 102, 103, 104),
                (900_000, 1_800_000, 2_700_000, 3_600_000, 4_500_000),
                strict=True,
            )
        ],
    }
    session = Mock()
    session.get.side_effect = lambda url, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: payloads[url.rsplit("/", 1)[-1]]
    )
    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(MODULE.time, "time", return_value=5000.0),
    ):
        strategy.settings["taker_window_candles"] = 1
        metric = strategy._fetch_pair_metrics("BTC", exit_only=True)
    assert metric["taker_ratio"] == 0.9
    assert metric["oi_change"] == 0.0
    assert metric["_exit_valid_until"] == 4500 + strategy.settings["remote_metric_max_age_seconds"]
    assert session.get.call_count == 1
    session.close.assert_called_once()


def test_expired_market_down_and_legacy_account_stop_do_not_exit() -> None:
    strategy = _entry_ready_strategy(1000.0)
    strategy._rotation_pair = None
    strategy._trend_reversed = Mock(return_value=False)
    strategy._update_market_state(
        ["BTC"], {"BTC": {"momentum": -0.1, "_candle_valid_until": 999.0}}
    )
    assert strategy._market_down
    with patch.object(MODULE.time, "time", return_value=1000.0):
        assert strategy.custom_exit("BTC", SimpleNamespace(), ETH_TEST_NOW, 100.0, 0.0) is None
        strategy._account_stopped = True
        assert strategy.custom_exit("BTC", SimpleNamespace(), ETH_TEST_NOW, 100.0, -0.5) is None


def test_fresh_scores_cannot_open_a_pair_with_stale_candles() -> None:
    now = ETH_TEST_NOW.timestamp()
    strategy = _entry_ready_strategy(now)
    strategy._scores = {"BTC/USDT:USDT": 100.0}
    strategy._metrics = {
        "BTC/USDT:USDT": _fresh_score_metric(momentum=0.1),
    }
    frame = pd.DataFrame(
        {
            "date": pd.date_range(end=ETH_TEST_NOW - timedelta(days=1), periods=24, freq="15min"),
            "close": [100.0] * 24,
            "volume": [10.0] * 24,
        }
    )
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)
    with (
        patch.object(MODULE.time, "time", return_value=now),
        patch.object(MODULE.Trade, "get_open_trades", return_value=[]),
    ):
        assert strategy._select_entries() == set()
        assert not strategy.confirm_trade_entry(
            "BTC/USDT:USDT", "market", 1.0, 100.0, "GTC", ETH_TEST_NOW, None, "long"
        )
        signal = strategy.populate_entry_trend(frame.copy(), {"pair": "BTC/USDT:USDT"})
    assert signal["enter_long"].sum() == 0


def test_candle_warning_is_throttled_to_status_interval(caplog) -> None:
    strategy = _entry_ready_strategy(1000.0)
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: pd.DataFrame())
    with caplog.at_level(logging.WARNING, logger="leader_squeeze_strategy"):
        for now in (1000.0, 1001.0, 1299.0, 1300.0):
            with patch.object(MODULE.time, "time", return_value=now):
                assert strategy._closed_candles("BTC", "5m", 2) is None
    assert (
        len([record for record in caplog.records if "数据不可用 BTC 5m" in record.getMessage()])
        == 2
    )


def test_pending_rotation_is_cancelled_when_target_candles_expire() -> None:
    now = ETH_TEST_NOW.timestamp()
    strategy = _entry_ready_strategy(now)
    strategy._rotation_pair, strategy._rotation_target = "WEAK", "TARGET"
    strategy._metrics.update({"WEAK": _fresh_score_metric(), "TARGET": _fresh_score_metric()})
    strategy._rotation_candidate, strategy._rotation_seen = None, 0
    strategy._candle_metrics = Mock(return_value=None)
    strategy._plan_rotation(now, ETH_TEST_NOW)
    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None


@pytest.mark.parametrize("stale", [False, True])
def test_no_new_high_low_level_requires_current_closed_15m_candles(stale) -> None:
    strategy = _entry_ready_strategy(ETH_TEST_NOW.timestamp())
    strategy.settings["holding_timeframe"] = "15m"
    latest = ETH_TEST_NOW - timedelta(minutes=15, days=int(stale))
    frame = pd.DataFrame(
        {
            "date": pd.date_range(end=latest, periods=4, freq="15min"),
            "high": [100.0, 110.0, 110.0, 105.0],
        }
    )
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)
    with patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp()):
        assert bool(strategy._no_new_high("WEAK")) is not stale
