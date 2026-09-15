import importlib.util
import json
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest


STRATEGY_PATH = Path(__file__).parents[2] / "user_data/strategies/leader_squeeze_strategy.py"
SPEC = importlib.util.spec_from_file_location("leader_squeeze_strategy", STRATEGY_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


def test_minmax_and_weights() -> None:
    assert LeaderSqueezeStrategy._minmax({"a": 1, "b": 3}) == {"a": 0.0, "b": 1.0}
    assert LeaderSqueezeStrategy._minmax({"a": 2, "b": 2}) == {"a": 0.5, "b": 0.5}
    assert sum(LeaderSqueezeStrategy.DEFAULTS["weights"].values()) == 1.0
    assert LeaderSqueezeStrategy.DEFAULTS["weights"]["short_crowding"] == 0.30
    assert LeaderSqueezeStrategy.DEFAULTS["min_short_share"] == 0.30


def test_candle_metrics_rewards_a_continuous_15_minute_rise() -> None:
    frame = pd.DataFrame(
        {
            "close": [100.0] * 17 + [101.0, 102.0, 103.0, 104.0],
            "volume": [100.0] * 21,
        }
    )
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(get_pair_dataframe=lambda pair, timeframe: frame)

    metrics = strategy._candle_metrics("BTC/USDT:USDT")

    assert metrics is not None
    assert metrics["trend_continuity"] == 1.0


def test_trend_continuity_increases_the_confidence_score() -> None:
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.settings = LeaderSqueezeStrategy.DEFAULTS.copy()
    strategy._liquidation_score = lambda symbol, now: 0.0
    strategy._market_id = lambda pair: pair
    metrics = {
        "TRENDING": {
            "short_share": 0.40,
            "momentum": 0.10,
            "trend_continuity": 1.0,
            "volume_ratio": 2.0,
            "taker_ratio": 1.2,
            "oi_change": -0.01,
        },
        "CHOPPY": {
            "short_share": 0.40,
            "momentum": 0.10,
            "trend_continuity": 0.0,
            "volume_ratio": 2.0,
            "taker_ratio": 1.2,
            "oi_change": -0.01,
        },
    }

    strategy._apply_scores(1.0, metrics, metrics)

    assert strategy._scores["TRENDING"] > strategy._scores["CHOPPY"]


def test_selects_two_base_positions_and_only_high_confidence_extras() -> None:
    now = time.time()
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.settings = LeaderSqueezeStrategy.DEFAULTS.copy()
    strategy._scores = {"BLOCKED": 100.0, "A": 90.0, "B": 60.0, "C": 55.0}
    strategy._metrics = {pair: {"short_share": 0.4} for pair in strategy._scores}
    strategy._metrics["BLOCKED"]["short_share"] = 0.29
    strategy._external_pairs = set()
    strategy._data_healthy = True
    strategy._last_good_data = now
    strategy._daily_blocked = False
    strategy._account_stopped = False
    strategy._liquidation_connected = type("Connected", (), {"is_set": lambda self: True})()
    strategy._liquidation_last_message = now
    strategy._position_data_healthy = True
    strategy._last_position_sync = now
    strategy._external_stop_protected = {}
    strategy._execution_is_safe = lambda pair: True

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {"A", "B"}


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
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.config = {"exchange": {"ccxt_config": {}}}
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

    with patch.object(MODULE, "connect", return_value=FakeSocket()):
        strategy._liquidation_worker()

    events = list(strategy._liquidations["BTCUSDT"])
    assert len(events) == 1
    assert events[0][1] == pytest.approx(400.0)


def test_taker_metric_freshness_uses_the_five_minute_period_end() -> None:
    now = 1_000.0
    payloads = {
        "globalLongShortAccountRatio": [{"shortAccount": "0.35", "timestamp": 900_000}],
        "topLongShortPositionRatio": [{"shortAccount": "0.45", "timestamp": 900_000}],
        "takerlongshortRatio": [{"buySellRatio": "1.2", "timestamp": 300_000}],
        "openInterestHist": [
            {"sumOpenInterest": str(value), "timestamp": 900_000} for value in (100, 99, 98, 97)
        ],
    }

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

        def get(self, url, **kwargs):
            return Response(payloads[url.rsplit("/", 1)[-1]])

        def close(self):
            return None

    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.config = {"exchange": {"key": "<REDACTED>", "ccxt_config": {}}}
    strategy.settings = LeaderSqueezeStrategy.DEFAULTS.copy()
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(_api=SimpleNamespace(market_id=lambda pair: "BTCUSDT"))
    )

    with (
        patch.object(MODULE.requests, "Session", Session),
        patch.object(MODULE.time, "time", return_value=now),
    ):
        metrics = strategy._fetch_pair_metrics("BTC/USDT:USDT")

    assert metrics["short_share"] == 0.45


def test_rotation_confirmation_requires_a_new_score_snapshot() -> None:
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.settings = LeaderSqueezeStrategy.DEFAULTS.copy()
    strategy.settings["replacement_confirmations"] = 2
    strategy.settings["replacement_cooldown_minutes"] = 0
    strategy._scores = {"WEAK": 50.0, "CHALLENGER": 100.0}
    strategy._metrics = {"CHALLENGER": {"short_share": 0.40}}
    strategy._external_pairs = set()
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy._rotation_score_snapshot = 0.0
    strategy._last_rotation = 0.0
    strategy._last_score_refresh = 12345.0
    strategy._position_first_seen = {}
    strategy._no_new_high = lambda pair: True
    current_time = datetime.now(UTC)
    weak_trade = type(
        "TradeStub",
        (),
        {
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

        strategy._last_score_refresh += 300
        strategy._plan_rotation(now + 300, current_time + timedelta(minutes=5))
    assert strategy._rotation_pair == "WEAK"
    assert strategy._rotation_target == "CHALLENGER"


def test_rotation_rejects_a_challenger_below_the_short_crowding_floor() -> None:
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.settings = LeaderSqueezeStrategy.DEFAULTS.copy()
    strategy.settings["replacement_cooldown_minutes"] = 0
    strategy._scores = {"WEAK": 50.0, "CHALLENGER": 100.0}
    strategy._metrics = {"CHALLENGER": {"short_share": 0.29}}
    strategy._external_pairs = set()
    strategy._rotation_pair = None
    strategy._rotation_target = None
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy._rotation_score_snapshot = 0.0
    strategy._last_rotation = 0.0
    strategy._last_score_refresh = 12345.0
    strategy._position_first_seen = {}
    strategy._no_new_high = lambda pair: True
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


def test_rotation_target_bypasses_only_the_additional_entry_score() -> None:
    now = time.time()
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.settings = LeaderSqueezeStrategy.DEFAULTS.copy()
    strategy._scores = {"TARGET": 60.0}
    strategy._metrics = {"TARGET": {"short_share": 0.30}}
    strategy._rotation_target = "TARGET"
    strategy._external_pairs = set()
    strategy._data_healthy = True
    strategy._last_good_data = now
    strategy._daily_blocked = False
    strategy._account_stopped = False
    strategy._liquidation_connected = type("Connected", (), {"is_set": lambda self: True})()
    strategy._liquidation_last_message = now
    strategy._position_data_healthy = True
    strategy._last_position_sync = now
    strategy._external_stop_protected = {}
    strategy._execution_is_safe = lambda pair: True
    open_trades = [SimpleNamespace(pair=f"HELD-{index}") for index in range(4)]

    with patch.object(MODULE.Trade, "get_open_trades", return_value=open_trades):
        assert strategy._select_entries() == {"TARGET"}


def test_rotation_target_survives_the_weak_exit_until_the_target_is_held() -> None:
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy._rotation_pair = "WEAK"
    strategy._rotation_target = "TARGET"
    strategy._external_pairs = set()
    strategy._scores = {"TARGET": 60.0}
    strategy._next_score_refresh = float("inf")

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        strategy._sync_rotation_state()

    assert strategy._rotation_pair is None
    assert strategy._rotation_target == "TARGET"
    assert strategy._next_score_refresh == 0.0

    with patch.object(
        MODULE.Trade, "get_open_trades", return_value=[SimpleNamespace(pair="TARGET")]
    ):
        strategy._sync_rotation_state()

    assert strategy._rotation_target is None


def test_trend_reversal_uses_15m_ema_and_5m_lower_low() -> None:
    pair = "BTC/USDT:USDT"
    frame_15m = pd.DataFrame(
        {
            "close": list(range(100, 122)),
            "low": list(range(100, 122)),
        }
    )
    frame_5m = pd.DataFrame(
        {
            "close": list(range(100, 122)),
            "low": list(range(100, 122))[:-1] + [100],
        }
    )

    class DataProviderStub:
        def __init__(self):
            self.calls = []

        def get_pair_dataframe(self, requested_pair, timeframe):
            self.calls.append((requested_pair, timeframe))
            return {"15m": frame_15m, "5m": frame_5m}[timeframe]

    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.dp = DataProviderStub()
    strategy._metrics = {pair: {"taker_ratio": 0.9, "oi_change": 0.01}}

    assert strategy._trend_reversed(pair)
    assert strategy.dp.calls.count((pair, "15m")) == 1
    assert strategy.dp.calls.count((pair, "5m")) == 1


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
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(_api=SimpleNamespace(fetch_open_orders=fetch_open_orders))
    )

    assert strategy._external_stop_orders("BTC/USDT:USDT") == []
    fetch_open_orders.assert_called_once_with("BTC/USDT:USDT", params={"stop": True})


def test_adl_refresh_requests_linear_usdm_positions() -> None:
    fetch_adl = Mock(return_value=[{"symbol": "BTC/USDT:USDT", "rank": 4}])
    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(
        _exchange=SimpleNamespace(_api=SimpleNamespace(fetch_positions_adl_rank=fetch_adl))
    )
    strategy._adl_ranks = {}

    strategy._refresh_adl_ranks()

    fetch_adl.assert_called_once_with(None, params={"subType": "linear"})
    assert strategy._adl_ranks == {"BTC/USDT:USDT": 4.0}


def test_score_network_refresh_is_background_and_includes_held_pairs() -> None:
    started = threading.Event()
    release = threading.Event()
    captured = []

    def fetch_metrics(pairs):
        captured.extend(pairs)
        started.set()
        release.wait(2)
        return {}

    strategy = LeaderSqueezeStrategy.__new__(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(current_whitelist=lambda: ["A", "B"])
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

    assert set(captured) == {"A", "B", "DB", "EXT"}
    assert strategy._score_result[1] == ["A", "B"]
