"""Contract tests for remote metric freshness in leader_squeeze_strategy."""

from __future__ import annotations

import importlib.util
import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import leader_squeeze_data as DATA
import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)


STRATEGY_PATH = Path(__file__).parents[2] / "user_data/strategies/leader_squeeze_strategy.py"
SPEC = importlib.util.spec_from_file_location(
    "leader_squeeze_strategy_remote_expiry", STRATEGY_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"
NOW = 1_000.0


def _metric(now: float = NOW, *, score_age: float = 300.0, exit_age: float = 300.0):
    """Return a complete metric payload suitable for score consumption."""
    return {
        "short_share": 0.60,
        "short_account_share": 0.60,
        "short_position_share": 0.60,
        "taker_ratio": 1.20,
        "oi_change": -0.01,
        "momentum": 0.05,
        "trend_continuity": 1.0,
        "volume_ratio": 2.0,
        "volume_activity_ratio": 3.0,
        "_score_valid_until": now + score_age,
        "_exit_valid_until": now + exit_age,
    }


@pytest.mark.parametrize(
    "metric",
    [
        {},
        {"_score_valid_until": None, "_exit_valid_until": NOW + 1},
        {"_score_valid_until": float("nan"), "_exit_valid_until": NOW + 1},
        {"_score_valid_until": float("inf"), "_exit_valid_until": NOW + 1},
        {"_score_valid_until": "1001", "_exit_valid_until": NOW + 1},
        {"_score_valid_until": NOW - 1, "_exit_valid_until": NOW + 1},
        {"_score_valid_until": NOW + 1, "_exit_valid_until": None},
        {"_score_valid_until": NOW + 1, "_exit_valid_until": float("nan")},
        {"_score_valid_until": NOW + 1, "_exit_valid_until": float("inf")},
        {"_score_valid_until": NOW + 1, "_exit_valid_until": "1001"},
        {"_score_valid_until": NOW + 1, "_exit_valid_until": NOW - 1},
    ],
)
def test_metrics_current_rejects_missing_invalid_or_expired_deadlines(metric) -> None:
    assert not LeaderSqueezeStrategy._metrics_current(metric, NOW)


@pytest.mark.parametrize(
    "metric",
    [
        {},
        {"_exit_valid_until": None},
        {"_exit_valid_until": float("nan")},
        {"_exit_valid_until": float("inf")},
        {"_exit_valid_until": "1001"},
        {"_exit_valid_until": NOW - 1},
    ],
)
def test_metrics_current_exit_mode_still_rejects_invalid_exit_deadline(metric) -> None:
    # Exit-only refreshes do not need score fields, but still need a valid expiry.
    assert not LeaderSqueezeStrategy._metrics_current(metric, NOW, exit_only=True)


def test_metrics_current_exit_mode_accepts_fresh_exit_metric_without_score_deadline() -> None:
    metric = {"_exit_valid_until": NOW}

    assert LeaderSqueezeStrategy._metrics_current(metric, NOW, exit_only=True)
    assert not LeaderSqueezeStrategy._metrics_current(metric, NOW)


def _consume_strategy(now: float = NOW) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._score_result_lock = threading.Lock()
    strategy._exit_metrics = {}
    strategy._data_healthy = True
    strategy._market_data_healthy = True
    strategy._rotation_candidate = None
    strategy._rotation_seen = 0
    strategy._candle_metrics = Mock(
        return_value={
            "momentum": 0.05,
            "trend_continuity": 1.0,
            "_candle_valid_until": now + 60,
        }
    )
    strategy._update_market_state = Mock()
    strategy._required_leader_count = Mock(return_value=1)
    strategy._apply_scores = Mock()
    strategy._next_score_refresh = 0.0
    return strategy


def test_consume_expired_score_does_not_apply_scores_but_updates_fresh_exit_cache() -> None:
    strategy = _consume_strategy()
    metric = _metric(score_age=-1.0, exit_age=60.0)
    strategy._score_result = (NOW, [PAIR], {PAIR: metric})

    assert not strategy._consume_score_refresh(NOW)
    strategy._apply_scores.assert_not_called()
    assert strategy._exit_metrics[PAIR] == metric
    assert strategy._data_healthy is False


def test_consume_fresh_score_applies_scores_normally() -> None:
    strategy = _consume_strategy()
    metric = _metric(score_age=60.0, exit_age=60.0)
    strategy._score_result = (NOW, [PAIR], {PAIR: metric})

    assert strategy._consume_score_refresh(NOW)
    strategy._apply_scores.assert_called_once()
    assert strategy._data_healthy is True


def _fetch_strategy(payloads: dict[str, object]) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "exchange": {"ccxt_config": {}}}
    strategy.settings = configured_settings()
    strategy.settings["taker_window_candles"] = 1
    strategy._market_id = lambda pair: "BTCUSDT"

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.headers = {}
            self.calls = []
            strategy._session = self

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response(payloads[url.rsplit("/", 1)[-1]])

        def close(self):
            return None

    strategy._test_session = Session
    return strategy


def _full_payloads() -> dict[str, object]:
    return {
        # The taker source is intentionally oldest.  Its 15m period ends at 1000s.
        "takerlongshortRatio": [{"buyVol": "1.2", "sellVol": "1", "timestamp": 100_000}],
        "openInterestHist": [
            {"sumOpenInterest": str(value), "timestamp": 1_000_000} for value in (100, 99, 98, 97)
        ],
        "globalLongShortAccountRatio": [{"shortAccount": "0.35", "timestamp": 1_000_000}],
        "topLongShortPositionRatio": [{"shortAccount": "0.45", "timestamp": 1_000_000}],
    }


def _fetch_with_payloads(payloads: dict[str, object], now: float) -> dict[str, float]:
    strategy = _fetch_strategy(payloads)
    with (
        patch.object(DATA.requests, "Session", strategy._test_session),
        patch.object(MODULE.time, "time", return_value=now),
    ):
        return strategy._fetch_pair_metrics(PAIR)


def test_fetch_score_deadline_uses_earliest_remote_source() -> None:
    metrics = _fetch_with_payloads(_full_payloads(), NOW)
    remote_max_age = configured_settings()["remote_metric_max_age_seconds"]

    # Taker period_end is 900s after its 100s timestamp; it is the earliest source.
    assert metrics["_exit_valid_until"] == pytest.approx(1000 + remote_max_age)
    assert metrics["_score_valid_until"] == pytest.approx(1000 + remote_max_age)
    assert "adl_risk_score" not in metrics


def test_fetch_requests_use_the_15_minute_period() -> None:
    strategy = _fetch_strategy(_full_payloads())

    with (
        patch.object(DATA.requests, "Session", strategy._test_session),
        patch.object(MODULE.time, "time", return_value=NOW),
    ):
        strategy._fetch_pair_metrics(PAIR)

    period_calls = [
        call for call in strategy._session.calls if "period" in call[1].get("params", {})
    ]
    assert period_calls
    assert all(call[1]["params"]["period"] == "15m" for call in period_calls)
    oi_call = next(
        call for call in strategy._session.calls if call[0].endswith("/openInterestHist")
    )
    assert oi_call[1]["params"]["limit"] == 4


def test_fetching_identical_payload_does_not_extend_deadlines() -> None:
    payloads = _full_payloads()
    first = _fetch_with_payloads(payloads, NOW)
    second = _fetch_with_payloads(payloads, NOW + 100)

    assert second["_exit_valid_until"] == first["_exit_valid_until"]
    assert second["_score_valid_until"] == first["_score_valid_until"]


def test_fetch_result_without_adl_response_has_valid_score_deadline() -> None:
    metric = _fetch_with_payloads(_full_payloads(), NOW)
    assert LeaderSqueezeStrategy._metrics_current(metric, NOW)
    assert "adl_risk_score" not in metric


def test_pair_score_current_requires_fresh_score_and_exit_deadlines() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._metrics = {PAIR: _metric(score_age=60.0, exit_age=60.0)}

    assert strategy._pair_score_current(PAIR, NOW)
    strategy._metrics[PAIR]["_score_valid_until"] = NOW - 1
    assert not strategy._pair_score_current(PAIR, NOW)
    strategy._metrics[PAIR]["_score_valid_until"] = NOW + 60
    strategy._metrics[PAIR]["_exit_valid_until"] = NOW - 1
    assert not strategy._pair_score_current(PAIR, NOW)


def _entry_gate_strategy(now: float = NOW) -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._eth_entries_allowed = lambda current_time: True
    strategy._data_healthy = True
    strategy._last_good_data = now
    strategy._liquidation_connected = threading.Event()
    strategy._liquidation_connected.set()
    strategy._liquidation_last_message = now
    strategy._position_data_healthy = True
    strategy._last_position_sync = now
    strategy._external_pairs = set()
    strategy._external_stop_protected = {}
    strategy._risk_state_load_failed = False
    strategy._account_stopped = False
    strategy._market_data_healthy = True
    strategy._market_down = False
    return strategy


def test_entries_allowed_requires_eighty_percent_of_current_score_metrics() -> None:
    strategy = _entry_gate_strategy()
    leaders = [f"L{index}" for index in range(5)]
    strategy._score_leaders = leaders
    strategy._metrics = {pair: _metric() for pair in leaders[:4]}

    assert strategy._entries_allowed(NOW)

    strategy._metrics[leaders[0]]["_score_valid_until"] = NOW - 1
    assert not strategy._entries_allowed(NOW)


def test_select_entries_rejects_pair_with_expired_remote_score() -> None:
    strategy = _entry_gate_strategy()
    strategy._entries_allowed = lambda now: True
    strategy._scores = {PAIR: 100.0}
    strategy._metrics = {PAIR: _metric(score_age=-1.0, exit_age=60.0)}
    strategy._external_pairs = set()
    strategy._rotation_target = None
    strategy._candle_metrics = Mock(return_value={"momentum": 0.1})
    strategy._has_absolute_uptrend = Mock(return_value=True)
    strategy._execution_is_safe = Mock(return_value=True)
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == set()
    strategy._execution_is_safe.assert_not_called()


def test_confirm_trade_entry_rejects_pair_with_expired_remote_score() -> None:
    strategy = _entry_gate_strategy()
    strategy._entries_allowed = lambda now: True
    strategy._entry_pairs = {PAIR}
    strategy._external_pairs = set()
    strategy._metrics = {PAIR: _metric(score_age=-1.0, exit_age=60.0)}
    strategy._candle_metrics = Mock(return_value={"momentum": 0.1})

    assert not strategy.confirm_trade_entry(
        PAIR,
        "market",
        1.0,
        100.0,
        "GTC",
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        None,
        "long",
    )
