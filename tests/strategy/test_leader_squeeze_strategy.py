import importlib.util
import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import leader_squeeze_data as DATA
import leader_squeeze_support as SUPPORT
import pandas as pd
import pytest

from freqtrade.persistence import PairLocks
from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)


STRATEGY_PATH = Path(__file__).parents[2] / "user_data/strategies/leader_squeeze_strategy.py"
SPEC = importlib.util.spec_from_file_location("leader_squeeze_strategy", STRATEGY_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


def _fetch_pair_metrics_fixture(
    short_account: float = 0.35,
    short_position: float = 0.45,
) -> tuple[dict[str, float], dict[str, str]]:
    payloads = {
        "globalLongShortAccountRatio": [{"shortAccount": str(short_account), "timestamp": 900_000}],
        "topLongShortPositionRatio": [{"shortAccount": str(short_position), "timestamp": 900_000}],
        "takerlongshortRatio": [{"buyVol": "1.2", "sellVol": "1", "timestamp": 100_000}],
        "openInterestHist": [
            {"sumOpenInterest": str(value), "timestamp": 900_000} for value in (100, 99, 98, 97)
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
        patch.object(MODULE.time, "time", return_value=1_000.0),
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
    return pd.DataFrame({"date": dates, "close": closes})


def _eth_gate_strategy(frame: pd.DataFrame) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)
    return strategy


def _fresh_score_metric(**values) -> dict[str, float]:
    return {
        "short_share": 0.60,
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
    strategy._external_stop_protected = {}
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
    strategy._entry_block_reason = "ETH拦截: ETH 下跌"
    strategy._entry_pairs = {"BTC/USDT:USDT"}
    strategy._entry_decisions = {"BTC/USDT:USDT": "入选: 评分 80.0 >= 45.0"}
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
    strategy._external_stop_protected = {"ETH/USDT:USDT": True}
    strategy._position_details = {}
    strategy._risk_state = {}
    strategy._daily_blocked = False
    strategy._account_stopped = False
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy.dp = SimpleNamespace(_exchange=Mock())
    strategy.wallets = SimpleNamespace(get_all_positions=Mock(return_value={}))
    return strategy


def test_weights_and_default_crowding_floor() -> None:
    weights = configured_settings()["weights"]
    assert sum(weights.values()) == 1.0
    assert weights["short_crowding"] == 0.20
    assert weights["momentum"] == 0.32
    assert weights["volume"] == 0.15
    assert weights["taker_buy"] == 0.15
    assert weights["liquidation"] == 0.05
    assert weights["oi_squeeze"] == 0.10
    assert weights["funding"] == 0.03
    assert "adl_risk" not in weights
    assert len(weights) == 7
    assert configured_settings()["min_short_share"] == 0.50


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
    ("closes", "expected"),
    [
        ([100.0] * 20 + [101.0, 102.0], True),
        ([100.0] * 20 + [99.0, 98.0], False),
        ([100.0] * 20 + [99.0, 100.0], True),
        ([100.0] * 22, True),
        ([100.0] * 19 + [101.0, 102.0], False),
    ],
)
def test_eth_gate_requires_twenty_two_closed_candles_and_two_below_ema(
    closes: list[float], expected: bool
) -> None:
    strategy = _eth_gate_strategy(_eth_frame(closes))

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp()) is expected


def test_eth_gate_ignores_an_unclosed_candle() -> None:
    frame = _eth_frame([100.0] * 20 + [99.0, 98.0])
    frame = pd.concat(
        [frame, pd.DataFrame({"date": [ETH_TEST_NOW], "close": [1_000.0]})],
        ignore_index=True,
    )
    strategy = _eth_gate_strategy(frame)

    assert not strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp())


@pytest.mark.parametrize(
    ("latest_offset_minutes", "expected"),
    [(30 + 20 / 60, True), (30 + 31 / 60, False)],
)
def test_eth_gate_applies_data_grace_to_candle_freshness(
    latest_offset_minutes: float, expected: bool
) -> None:
    strategy = _eth_gate_strategy(
        _eth_frame([100.0] * 20 + [101.0, 102.0], latest_offset_minutes=latest_offset_minutes)
    )
    strategy.settings["data_grace_seconds"] = 30

    assert strategy._eth_entries_allowed(ETH_TEST_NOW.timestamp()) is expected


def test_eth_gate_rejects_missing_and_non_contiguous_candles() -> None:
    missing = _eth_gate_strategy(_eth_frame([100.0] * 21))
    non_contiguous = _eth_gate_strategy(_eth_frame([100.0] * 20 + [101.0, 102.0], gap_at=10))

    assert not missing._eth_entries_allowed(ETH_TEST_NOW.timestamp())
    assert not non_contiguous._eth_entries_allowed(ETH_TEST_NOW.timestamp())


@pytest.mark.parametrize("bad_close", [float("nan"), None])
def test_eth_gate_rejects_non_finite_close(bad_close: float | None) -> None:
    closes: list[float | None] = [100.0] * 20 + [101.0, 102.0]
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
    strategy = _eth_gate_strategy(_eth_frame([100.0] * 20 + [99.0, 98.0]))
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


def test_eth_blocked_loop_keeps_risk_and_external_management_but_skips_new_work(caplog) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._last_position_sync = time.time()
    strategy._sync_external_pairs = Mock()
    strategy.dp = SimpleNamespace(
        get_pair_dataframe=Mock(return_value=_eth_frame([100.0] * 20 + [99.0, 98.0])),
        current_whitelist=list,
    )
    strategy._consume_score_refresh = Mock(return_value=True)
    strategy._start_score_refresh = Mock()
    strategy._refresh_risk_state = Mock()
    strategy._sync_rotation_state = Mock()
    strategy._plan_rotation = Mock()
    strategy._manage_external_positions = Mock()
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
    strategy._manage_external_positions.assert_called_once()
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
    assert "ETH 下跌" in messages()[0]
    assert "已有仓位继续止损和退出" in messages()[0]
    for seconds, expected_count in [(5, 1), (299, 1), (300, 2)]:
        with (
            caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
            patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp() + seconds),
        ):
            strategy.bot_loop_start(ETH_TEST_NOW)
        assert len(messages()) == expected_count

    for frame, expected_message in [
        (pd.DataFrame(), "数据缺失、过期或无效"),
        (_eth_frame([100.0] * 22), "不拦截"),
    ]:
        strategy.dp.get_pair_dataframe.return_value = frame
        strategy._next_score_refresh = float("inf")
        with (
            caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"),
            patch.object(MODULE.time, "time", return_value=ETH_TEST_NOW.timestamp() + 305),
        ):
            strategy.bot_loop_start(ETH_TEST_NOW)
        assert expected_message in messages()[-1]


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
        "max_open_trades": 6,
        "dry_run": dry_run,
        "runmode": runmode,
        "user_data_dir": str(tmp_path),
    }
    strategy._sync_external_pairs = Mock()
    strategy._load_risk_state = Mock(return_value={})
    strategy._initialize_rotation_audit = Mock()

    with patch.object(MODULE.threading, "Thread") as thread:
        strategy.bot_start()

    assert strategy._state_path == tmp_path / state_file
    strategy._sync_external_pairs.assert_called_once()
    thread.assert_called_once()
    thread.return_value.start.assert_called_once()


def _risk_state_strategy(tmp_path: Path) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._state_path = tmp_path / "leader_squeeze_state.live.json"
    strategy._risk_state_load_failed = False
    return strategy


def test_missing_risk_state_file_allows_first_initialization_and_save(tmp_path) -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {
        **PUBLIC_CONFIG,
        "max_open_trades": 6,
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
    state_path = tmp_path / "leader_squeeze_state.live.json"
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
        "max_open_trades": 6,
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
        get_pair_dataframe=Mock(return_value=_eth_frame([100.0] * 20 + [101.0, 102.0])),
        current_whitelist=list,
    )
    strategy._consume_score_refresh = Mock(return_value=False)
    strategy._advance_score_refresh = Mock()
    strategy._start_score_refresh = Mock()
    strategy._refresh_risk_state = Mock()
    strategy._sync_rotation_state = Mock()
    strategy._plan_rotation = Mock()
    strategy._manage_external_positions = Mock()
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
    assert "当前趋势=上涨" in message
    assert "前根收盘=101.0000" in message
    assert "最新收盘=102.0000" in message
    assert "EMA20=" in message


@pytest.mark.parametrize(
    ("gate", "expected_reason"),
    [
        ("score_data", "行情评分数据不完整"),
        ("score_age", "评分数据过期"),
        ("stream", "强平数据流断开"),
        ("stream_age", "强平流心跳过期"),
        ("position_data", "仓位同步失败"),
        ("position_age", "仓位数据过期"),
        ("external_stop", "外部仓位止损未确认"),
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
    elif gate == "stream":
        strategy._liquidation_connected.clear()
    elif gate == "stream_age":
        strategy._liquidation_last_message = now - 16
    elif gate == "position_data":
        strategy._position_data_healthy = False
    elif gate == "position_age":
        strategy._last_position_sync = now - 61
    elif gate == "external_stop":
        strategy._external_pairs = {"ETH/USDT:USDT"}
        strategy._external_stop_protected = {"ETH/USDT:USDT": False}
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
    strategy.settings["short_share_filter_enabled"] = True
    strategy._scores = {
        "HELD": 110.0,
        "CROWD": 105.0,
        "NO_TREND": 100.0,
        "UNSAFE": 99.0,
        "LOW": 39.0,
        "GOOD": 90.0,
        "EXTRA": 80.0,
    }
    strategy._metrics = {pair: _fresh_score_metric() for pair in strategy._scores}
    strategy._score_leaders = list(strategy._scores)
    strategy._metrics["CROWD"]["short_share"] = 0.50
    strategy._metrics["NO_TREND"]["momentum"] = 0.0
    strategy._metrics["NO_TREND"]["trend_continuity"] = 0.0
    strategy._metrics["LOW"]["short_share"] = 0.60
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._execution_is_safe = lambda pair: pair != "UNSAFE"

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[SimpleNamespace(pair="HELD")]):
        selected = strategy._select_entries()

    assert selected == {"GOOD"}
    assert strategy._entry_decisions == {
        "HELD": "已持仓",
        "CROWD": "空头占比 50.0% <= 50.0%",
        "NO_TREND": "上涨条件不足: 1h涨幅=0.00%, 上涨连续性=0%",
        "UNSAFE": "盘口安全检查未通过",
        "LOW": "本轮剩余名额已用完",
        "GOOD": "入选: 评分 90.0 >= 40.0",
        "EXTRA": "本轮剩余名额已用完",
    }
    strategy._scores = {"LOW": 39.0}
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[SimpleNamespace(pair="HELD")]):
        assert strategy._select_entries() == set()
    assert strategy._entry_decisions["LOW"] == "评分 39.0 < 门槛 40.0"


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
    selection = [record for record in caplog.records if "🎯 选币结果" in record.getMessage()]
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
            "short_share": 0.60,
            "momentum": 0.10,
            "trend_continuity": 1.0,
            "volume_ratio": 2.0,
            "volume_activity_ratio": 3.0,
            "taker_ratio": 1.2,
            "taker_ratio_latest": 1.2,
            "oi_change": -0.01,
        },
        "CHOPPY": {
            "short_share": 0.60,
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
    strategy._score_selection = ["LEADER"]
    strategy._liquidation_score = lambda symbol, now: 0.25
    strategy._market_id = lambda pair: pair
    metrics = {
        "LEADER": {
            "short_share": 0.65,
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
            "short_share": 0.60,
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

    table_logs = [record for record in caplog.records if hasattr(record, "strategy_log_table")]
    assert len(table_logs) == 4
    component_logs = [record.getMessage() for record in table_logs]
    labels = (
        "原评分",
        "轮换还需小时趋势走弱",
        "来源",
        "空头人数",
        "空头持仓量",
        "最终取高",
        "动量",
        "放量",
        "短期量比",
        "持续量比",
        "主动买",
        "强平",
        "OI",
        "15日涨幅",
        "偏离EMA96/ATR",
        "整理突破",
        "评分折扣",
        "买入评分",
        "1h趋势",
        "4h背景",
    )
    assert all(label in "\n".join(component_logs) for label in labels)
    for message in component_logs:
        assert all(pair in message for pair in metrics)
        assert "\x1b" not in message
    score_table = table_logs[0].strategy_log_table
    assert [cell.plain for cell in score_table.columns[1]._cells] == ["LEADER", "FOLLOWER"]
    assert [cell.plain for cell in score_table.columns[3]._cells] == ["本轮选币", "持仓监控"]
    assert "本批评分 2 个 = 本轮选币 1 个 + 榜外持仓监控 1 个" in score_table.caption.plain
    for index, pair in enumerate(("LEADER", "FOLLOWER")):
        total = float(score_table.columns[2]._cells[index].plain)
        component_total = sum(
            float(score_table.columns[column]._cells[index].plain) for column in range(4, 11)
        )
        assert total == pytest.approx(component_total, abs=0.15)
        assert total == pytest.approx(strategy._scores[pair], abs=0.05)
    assert "行情不足/无效" in component_logs[1]
    assert "不可用/已过期" in component_logs[3]
    assert "-0.90000%" in component_logs[3]
    assert "-0.11250%" in component_logs[3]
    assert "45.0%" in component_logs[3]
    assert "1.35" in component_logs[3]
    assert "01-01 08:33:20" in component_logs[3]


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


def test_selects_two_base_positions_and_only_high_confidence_extras() -> None:
    now = time.time()
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy.settings["short_share_filter_enabled"] = True
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._scores = {
        "DOWN": 110.0,
        "FADING": 105.0,
        "BLOCKED": 100.0,
        "A": 90.0,
        "B": 60.0,
        "C": 44.99,
    }
    strategy._metrics = {pair: _fresh_score_metric() for pair in strategy._scores}
    strategy._score_leaders = list(strategy._scores)
    strategy._metrics["DOWN"]["momentum"] = -0.01
    strategy._metrics["FADING"]["trend_continuity"] = 1 / 3
    strategy._metrics["BLOCKED"]["short_share"] = 0.50
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
    strategy._external_stop_protected = {}
    strategy._execution_is_safe = lambda pair: True

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {"A", "B"}
        strategy._scores["C"] = 45.0
        assert strategy._select_entries() == {"A", "B", "C"}

        strategy._scores = {"LOW": 39.0}
        strategy._metrics = {"LOW": _fresh_score_metric()}
        strategy._score_leaders = ["LOW"]
        assert strategy._select_entries() == set()


def test_detects_only_real_reduce_only_stop_orders() -> None:
    assert LeaderSqueezeStrategy._is_protective_stop(
        {
            "side": "sell",
            "amount": 2.0,
            "info": {"reduceOnly": True, "stopPrice": "10"},
        },
        "long",
        2.0,
    )
    assert not LeaderSqueezeStrategy._is_protective_stop(
        {
            "side": "sell",
            "amount": 2.0,
            "info": {"reduceOnly": True, "stopPrice": "0"},
        },
        "long",
        2.0,
    )


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

    assert metrics["short_share"] == 0.45
    assert "adl_risk_score" not in metrics
    assert "X-MBX-APIKEY" not in headers


@pytest.mark.parametrize(
    ("short_account", "short_position", "expected_short_share"),
    [(0.60, 0.45, 0.60), (0.35, 0.65, 0.65)],
)
def test_short_share_uses_the_higher_account_or_position_ratio(
    short_account: float,
    short_position: float,
    expected_short_share: float,
) -> None:
    metrics, _ = _fetch_pair_metrics_fixture(
        short_account=short_account, short_position=short_position
    )

    assert metrics["short_share"] == expected_short_share


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


def test_rotation_rejects_a_challenger_at_the_short_crowding_floor() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy._entries_allowed = lambda now: True
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy.settings = configured_settings()
    strategy.settings["short_share_filter_enabled"] = True
    strategy.settings["replacement_cooldown_minutes"] = 0
    strategy._scores = {"WEAK": 40.0, "CHALLENGER": 100.0}
    strategy._metrics = {
        "CHALLENGER": _fresh_score_metric(short_share=0.50),
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
    weak_trade = SimpleNamespace(
        pair="WEAK",
        is_short=False,
        open_date_utc=current_time - timedelta(hours=1),
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[weak_trade]):
        strategy._plan_rotation(time.time() + 3600, current_time)

    assert strategy._rotation_pair is None
    assert strategy._rotation_target is None


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


def test_rotation_target_requires_the_additional_entry_score() -> None:
    now = time.time()
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._candle_metrics = Mock(side_effect=lambda pair: strategy._metrics[pair])
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._scores = {"TARGET": 60.0}
    strategy._metrics = {"TARGET": _fresh_score_metric(short_share=0.56)}
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
    strategy._external_stop_protected = {}
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


def test_protective_stop_requires_correct_direction_and_quantity() -> None:
    stop_checker = LeaderSqueezeStrategy._is_protective_stop
    order = {
        "side": "sell",
        "amount": 2.0,
        "info": {"reduceOnly": True, "stopPrice": "90"},
    }
    assert stop_checker(order, "long", 2.0)
    assert not stop_checker({**order, "side": "buy"}, "long", 2.0)
    assert not stop_checker({**order, "amount": 1.0}, "long", 2.0)


def test_external_stops_use_binance_conditional_order_api() -> None:
    fetch_open_orders = Mock(return_value=[])
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(_api=SimpleNamespace(fetch_open_orders=fetch_open_orders))
    )

    assert strategy._external_stop_orders("BTC/USDT:USDT") == []
    fetch_open_orders.assert_called_once_with("BTC/USDT:USDT", params={"stop": True})


def test_adl_refresh_requests_linear_usdm_positions() -> None:
    fetch_adl = Mock(return_value=[{"symbol": "BTC/USDT:USDT", "rank": 4}])
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "dry_run": False}
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(_api=SimpleNamespace(fetch_positions_adl_rank=fetch_adl))
    )
    strategy._adl_ranks = {}

    strategy._refresh_adl_ranks()

    fetch_adl.assert_called_once_with(None, params={"subType": "linear"})
    assert strategy._adl_ranks == {"BTC/USDT:USDT": 4.0}


def test_adl_refresh_skips_positions_in_dry_run() -> None:
    fetch_adl = Mock()
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "dry_run": True}
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(_api=SimpleNamespace(fetch_positions_adl_rank=fetch_adl))
    )
    strategy._adl_ranks = {}

    strategy._refresh_adl_ranks()

    fetch_adl.assert_not_called()
    assert strategy._adl_ranks == {}


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
    assert strategy._score_result[1] == [*leaders, "DB"]
    assert strategy._score_selection == leaders


def test_score_refresh_scores_held_pairs_and_requires_eighty_percent_of_leaders() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    leaders = [f"L{index}" for index in range(10)]
    remote = {
        "short_share": 0.60,
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
    strategy._score_result = (now, ["BTC"], {"BTC": {"short_share": 0.6}})
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
        patch.object(MODULE.time, "time", return_value=1000.0),
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


def test_exit_only_http_uses_source_timestamps_and_no_adl_or_crowding_endpoints() -> None:
    strategy = _entry_ready_strategy(1000.0)
    strategy.config = {**PUBLIC_CONFIG, "exchange": {}}
    strategy._market_id = lambda pair: "BTCUSDT"
    payloads = {
        "takerlongshortRatio": [{"buyVol": "0.9", "sellVol": "1", "timestamp": 100_000}],
        "openInterestHist": [
            {"sumOpenInterest": str(value), "timestamp": 900_000} for value in (100, 101, 102, 103)
        ],
    }
    session = Mock()
    session.get.side_effect = lambda url, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: payloads[url.rsplit("/", 1)[-1]]
    )
    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(MODULE.time, "time", return_value=1000.0),
    ):
        strategy.settings["taker_window_candles"] = 1
        metric = strategy._fetch_pair_metrics("BTC", exit_only=True)
    assert metric["taker_ratio"] == 0.9
    assert metric["oi_change"] == pytest.approx(0.03)
    assert metric["_exit_valid_until"] == 900 + strategy.settings["remote_metric_max_age_seconds"]
    assert session.get.call_count == 2
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
