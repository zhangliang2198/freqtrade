import importlib
import importlib.util
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tests.strategy.leader_squeeze_test_helpers import (
    PUBLIC_CONFIG,
    configured_settings,
    configured_strategy,
)


DATA = importlib.import_module("leader_squeeze_helpers")


STRATEGY_PATH = (
    Path(__file__).parents[2] / "user_data/strategies/leader_squeeze/leader_squeeze_strategy.py"
)
SPEC = importlib.util.spec_from_file_location(
    "leader_squeeze_strategy_partial_metrics", STRATEGY_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"
NOW = 5_000.0
REMOVED_SHORT_RATIO_PATHS = {
    "globalLongShortAccountRatio",
    "topLongShortPositionRatio",
}


class _Response:
    def __init__(self, payload, failure=None):
        self._payload = payload
        self._failure = failure

    def raise_for_status(self):
        if callable(self._failure):
            self._failure()
        if isinstance(self._failure, Exception):
            raise self._failure

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payloads, failures):
        self.headers = {}
        self.payloads = payloads
        self.failures = failures
        self.paths: list[str] = []
        self.close = Mock()

    def get(self, url, **kwargs):
        path = url.rsplit("/", 1)[-1]
        self.paths.append(path)
        return _Response(self.payloads[path], self.failures.get(path))


def _payloads(
    *,
    taker_timestamp: int = 3_600_000,
    oi_timestamp: int = 4_500_000,
) -> dict[str, object]:
    return {
        "takerlongshortRatio": [
            {"buyVol": "1.2", "sellVol": "1", "timestamp": taker_timestamp},
        ],
        "openInterestHist": [
            {
                "sumOpenInterest": str(value),
                "timestamp": oi_timestamp - (4 - index) * 900_000,
            }
            for index, value in enumerate((101, 100, 99, 98, 97))
        ],
    }


def _strategy_and_session(*, payloads=None, failures=None):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.config = {**PUBLIC_CONFIG, "exchange": {}}
    strategy.settings = configured_settings()
    strategy.settings["weights"]["oi_squeeze"] = 0.03
    strategy.settings["taker_window_candles"] = 1
    strategy._market_id = Mock(return_value="BTCUSDT")
    session = _Session(payloads or _payloads(), failures or {})
    return strategy, session


def _fetch(strategy, session, clock, *, exit_only=False):
    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(MODULE.time, "time", side_effect=lambda: clock[0]),
    ):
        return strategy._fetch_pair_metrics(PAIR, exit_only=exit_only)


def test_score_refresh_does_not_request_adl_and_can_score_the_result() -> None:
    strategy, session = _strategy_and_session()
    metric = _fetch(strategy, session, [NOW])
    metric.update(
        {
            "momentum": 0.03,
            "trend_continuity": 1.0,
            "volume_ratio": 2.0,
            "volume_activity_ratio": 3.0,
        }
    )
    strategy._liquidation_score = Mock(return_value=0.0)
    strategy._market_id = Mock(return_value="BTCUSDT")

    strategy._apply_scores(NOW, {PAIR: metric}, {PAIR: metric})

    assert "symbolAdlRisk" not in session.paths
    assert "adl_risk_score" not in metric
    assert not REMOVED_SHORT_RATIO_PATHS.intersection(session.paths)
    assert "short_share" not in metric
    assert metric["oi_change"] == pytest.approx(98 / 101 - 1)
    assert strategy._scores[PAIR] > float(strategy.settings["entry_slot_score_thresholds"][0])


@pytest.mark.parametrize("failed_path", ["takerlongshortRatio", "openInterestHist"])
def test_required_exit_metric_failure_raises_and_never_returns_partial_metric(failed_path) -> None:
    strategy, session = _strategy_and_session(
        failures={failed_path: RuntimeError("required data down")}
    )
    with pytest.raises((ValueError, RuntimeError)):
        _fetch(strategy, session, [NOW])

    assert session.close.call_count == 1
    assert not REMOVED_SHORT_RATIO_PATHS.intersection(session.paths)


def test_invalid_required_oi_value_raises_and_closes_session() -> None:
    payloads = _payloads()
    payloads["openInterestHist"] = [
        {"sumOpenInterest": "not-a-number", "timestamp": 900_000},
        {"sumOpenInterest": "97", "timestamp": 900_000},
    ]
    strategy, session = _strategy_and_session(payloads=payloads)
    with pytest.raises((ValueError, RuntimeError)):
        _fetch(strategy, session, [NOW])

    assert session.close.call_count == 1
    assert not REMOVED_SHORT_RATIO_PATHS.intersection(session.paths)


def test_transient_metric_request_is_retried_once() -> None:
    strategy, session = _strategy_and_session()
    payloads = _payloads()
    session.get = Mock(
        side_effect=[
            DATA.requests.ConnectionError("temporary"),
            _Response(payloads["takerlongshortRatio"]),
            _Response(payloads["openInterestHist"]),
        ]
    )
    with patch.object(DATA.time, "sleep") as sleep:
        metric = _fetch(strategy, session, [NOW])

    assert metric["taker_ratio"] > 0
    assert session.get.call_count == 3
    sleep.assert_called_once_with(strategy.settings["metric_retry_backoff_seconds"])


def test_consume_accepts_fresh_exit_only_result_without_scoring() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._score_result_lock = threading.Lock()
    strategy._score_result = (
        NOW,
        [PAIR],
        {PAIR: {"taker_ratio": 0.9, "oi_change": 0.01, "_exit_valid_until": NOW + 60}},
    )
    strategy._exit_metrics = {}
    strategy._candle_metrics = Mock(return_value=None)
    strategy._apply_scores = Mock()

    assert not strategy._consume_score_refresh(NOW)
    assert strategy._exit_metrics[PAIR]["taker_ratio"] == pytest.approx(0.9)
    assert strategy._apply_scores.call_count == 0


def test_consume_discards_expired_exit_only_result() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy._score_result_lock = threading.Lock()
    strategy._score_result = (
        NOW,
        [PAIR],
        {PAIR: {"taker_ratio": 0.9, "oi_change": 0.01, "_exit_valid_until": NOW - 1}},
    )
    strategy._exit_metrics = {}
    strategy._candle_metrics = Mock(return_value=None)
    strategy._apply_scores = Mock()

    assert not strategy._consume_score_refresh(NOW)
    assert PAIR not in strategy._exit_metrics
    assert strategy._apply_scores.call_count == 0
