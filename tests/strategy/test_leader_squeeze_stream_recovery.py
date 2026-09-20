import importlib.util
import json
import threading
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import patch

import leader_squeeze_helpers as DATA
import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)


STRATEGY_PATH = (
    Path(__file__).parents[2] / "user_data/strategies/leader_squeeze/leader_squeeze_strategy.py"
)
SPEC = importlib.util.spec_from_file_location("leader_squeeze_strategy", STRATEGY_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


def _strategy() -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "exchange": {"ccxt_config": {}}}
    strategy.settings = configured_settings()
    strategy.settings["liquidation_warmup_score"] = 0.5
    strategy._stop_event = threading.Event()
    strategy._liquidation_connected = threading.Event()
    strategy._liquidation_started = 0.0
    strategy._liquidation_last_message = 0.0
    strategy._liquidation_lock = threading.Lock()
    strategy._liquidations = defaultdict(deque)
    return strategy


def _event(symbol: str = "BTCUSDT") -> dict:
    return {
        "stream": "!forceOrder@arr",
        "data": {
            "st": 1,
            "o": {"s": symbol, "S": "BUY", "ap": "100", "z": "1"},
        },
    }


class _Socket:
    def __init__(self, strategy, messages, clock):
        self._strategy = strategy
        self._messages = iter(messages)
        self._clock = clock

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def recv(self, timeout):
        try:
            timestamp, payload, stop = next(self._messages)
        except StopIteration:
            self._clock[0] += self._strategy.settings["liquidation_stream_max_age_seconds"] + 1
            raise TimeoutError
        self._clock[0] = timestamp
        if callable(payload):
            payload = payload()
        if stop:
            self._strategy._stop_event.set()
        return json.dumps(payload)


def test_worker_reconnect_rewarms_liquidation_window() -> None:
    strategy = _strategy()
    strategy._liquidation_started = 100.0
    strategy._liquidation_last_message = 100.0
    strategy._liquidations["OLDUSDT"].append((100.0, 1.0))
    clock = [0.0]
    first = _Socket(strategy, [(1_000.0, _event("BTCUSDT"), False)], clock)
    second = _Socket(strategy, [(5_000.0, _event("BTCUSDT"), True)], clock)

    with (
        patch.object(DATA, "connect", side_effect=[first, second]),
        patch.object(MODULE.time, "time", side_effect=lambda: clock[0]),
        patch.object(strategy._stop_event, "wait", return_value=False),
    ):
        strategy._liquidation_worker()

    assert strategy._liquidation_started == 5_000.0
    assert strategy._liquidation_last_message == 5_000.0
    assert "OLDUSDT" not in strategy._liquidations
    assert list(strategy._liquidations["BTCUSDT"]) == [(5_000.0, 100.0)]
    assert strategy._liquidation_score("BTCUSDT", 8_599.0) == pytest.approx(0.5)


def test_worker_rewarms_after_heartbeat_gap_without_socket_disconnect() -> None:
    strategy = _strategy()
    strategy.settings["liquidation_stream_max_age_seconds"] = 15
    clock = [0.0]
    messages = [
        (1_000.0, _event("BTCUSDT"), False),
        (1_016.0, _event("BTCUSDT"), True),
    ]

    with (
        patch.object(DATA, "connect", return_value=_Socket(strategy, messages, clock)),
        patch.object(MODULE.time, "time", side_effect=lambda: clock[0]),
    ):
        strategy._liquidation_worker()

    assert strategy._liquidation_started == 1_016.0
    assert strategy._liquidation_last_message == 1_016.0
    assert list(strategy._liquidations["BTCUSDT"]) == [(1_016.0, 100.0)]
    assert strategy._liquidation_score("BTCUSDT", 4_615.0) == pytest.approx(0.5)


def test_valid_heartbeat_prunes_all_symbols_and_empty_keys() -> None:
    strategy = _strategy()
    clock = [1_000.0]
    now = 1_005.0

    def add_expired_events():
        strategy._liquidations["NEVER_SCORED"].append((now - 3_601.0, 1.0))
        strategy._liquidations["LEFT_RANKING"].extend([(now - 3_601.0, 2.0), (now - 10.0, 3.0)])
        strategy._liquidations["EMPTY"]
        return {"stream": "!markPrice@arr@1s", "data": []}

    messages = [
        (1_000.0, _event("BTCUSDT"), False),
        (now, add_expired_events, True),
    ]
    with (
        patch.object(DATA, "connect", return_value=_Socket(strategy, messages, clock)),
        patch.object(MODULE.time, "time", side_effect=lambda: clock[0]),
    ):
        strategy._liquidation_worker()

    assert "NEVER_SCORED" not in strategy._liquidations
    assert "EMPTY" not in strategy._liquidations
    assert list(strategy._liquidations["LEFT_RANKING"]) == [(now - 10.0, 3.0)]


def test_liquidation_score_does_not_create_unknown_symbol() -> None:
    strategy = _strategy()
    strategy._liquidation_started = 1.0

    assert "UNKNOWNUSDT" not in strategy._liquidations
    assert strategy._liquidation_score("UNKNOWNUSDT", 7_200.0) == pytest.approx(0.0)
    assert "UNKNOWNUSDT" not in strategy._liquidations


def test_mature_liquidation_window_rejects_dust_and_covers_full_fifteen_minutes() -> None:
    strategy = _strategy()
    strategy._liquidation_started = 1.0
    strategy._liquidations["DUST"].append((7200.0, 1.0))
    assert strategy._liquidation_score("DUST", 7200.0) == 0.0
    strategy._liquidations["BURST"].append((7200.0, 5000.0))
    assert strategy._liquidation_score("BURST", 7200.0) == 1.0
    assert strategy._liquidation_score("BURST", 8099.0) == 1.0
    assert strategy._liquidation_score("BURST", 8101.0) == 0.0
    assert strategy._liquidation_score("BURST", 10801.0) == 0.0


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"stream": "!forceOrder@arr", "data": {"st": 1, "o": None}},
        {
            "stream": "!forceOrder@arr",
            "data": {
                "st": 1,
                "o": {"s": "BTCUSDT", "S": "BUY", "ap": object(), "z": "1"},
            },
        },
        {
            "stream": "!forceOrder@arr",
            "data": {
                "st": 1,
                "o": {"s": "BTCUSDT", "S": "BUY", "ap": "nan", "z": "1"},
            },
        },
        {
            "stream": "!forceOrder@arr",
            "data": {
                "st": 1,
                "o": {"s": "BTCUSDT", "S": "BUY", "ap": "1e308", "z": "1e308"},
            },
        },
        {
            "stream": "!forceOrder@arr",
            "data": {
                "st": 1,
                "o": {"s": ["BTCUSDT"], "S": "BUY", "ap": "100", "z": "1"},
            },
        },
    ],
)
def test_malformed_liquidation_payload_is_skipped_without_mutating_window(payload) -> None:
    strategy = _strategy()

    assert strategy._process_liquidation_payload(payload, 1_000.0) is False
    assert not strategy._liquidations


def test_invalid_json_does_not_reconnect_or_reset_window() -> None:
    strategy = _strategy()
    clock = [0.0]

    class RawSocket(_Socket):
        def recv(self, timeout):
            try:
                timestamp, payload, stop = next(self._messages)
            except StopIteration:
                raise AssertionError("worker unexpectedly reconnected")
            self._clock[0] = timestamp
            if stop:
                self._strategy._stop_event.set()
            return payload

    first = RawSocket(
        strategy,
        [(1_000.0, json.dumps(_event()), False), (1_001.0, "{bad", True)],
        clock,
    )
    with (
        patch.object(DATA, "connect", return_value=first) as connect,
        patch.object(MODULE.time, "time", side_effect=lambda: clock[0]),
    ):
        strategy._liquidation_worker()

    connect.assert_called_once()
    assert list(strategy._liquidations["BTCUSDT"]) == [(1_000.0, 100.0)]


def test_single_receive_timeout_keeps_window_until_stream_age_expires() -> None:
    strategy = _strategy()
    clock = [0.0]

    def timeout():
        raise TimeoutError

    messages = [
        (1_000.0, _event(), False),
        (1_005.0, timeout, False),
        (1_006.0, _event(), True),
    ]
    with (
        patch.object(DATA, "connect", return_value=_Socket(strategy, messages, clock)) as connect,
        patch.object(MODULE.time, "time", side_effect=lambda: clock[0]),
    ):
        strategy._liquidation_worker()

    connect.assert_called_once()
    assert list(strategy._liquidations["BTCUSDT"]) == [
        (1_000.0, 100.0),
        (1_006.0, 100.0),
    ]


def test_receive_timeout_after_stream_age_reconnects_and_rewarms() -> None:
    strategy = _strategy()
    clock = [0.0]

    def timeout():
        raise TimeoutError

    first = _Socket(
        strategy,
        [(1_000.0, _event("OLDUSDT"), False), (1_016.0, timeout, False)],
        clock,
    )
    second = _Socket(strategy, [(2_000.0, _event("BTCUSDT"), True)], clock)
    with (
        patch.object(DATA, "connect", side_effect=[first, second]) as connect,
        patch.object(MODULE.time, "time", side_effect=lambda: clock[0]),
        patch.object(strategy._stop_event, "wait", return_value=False),
    ):
        strategy._liquidation_worker()

    assert connect.call_count == 2
    assert "OLDUSDT" not in strategy._liquidations
    assert list(strategy._liquidations["BTCUSDT"]) == [(2_000.0, 100.0)]
