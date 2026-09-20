"""Offline regression tests for optional funding-rate scoring."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

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
SPEC = importlib.util.spec_from_file_location("leader_squeeze_funding", STRATEGY_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"
OTHER = "ETH/USDT:USDT"
NOW = 1_000_000.0


def _strategy() -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = {
        **configured_settings(),
        "weights": configured_settings()["weights"].copy(),
    }
    strategy.config = {
        **PUBLIC_CONFIG,
        "exchange": {"key": "must-not-be-used", "ccxt_config": {}},
    }
    strategy._market_id = lambda pair: f"{pair.split('/', 1)[0]}USDT"
    return strategy


def _info(hours: int = 8, floor: float = -0.016, cap: float = 0.016) -> dict[str, str]:
    return {
        "symbol": "BTCUSDT",
        "fundingIntervalHours": str(hours),
        "adjustedFundingRateFloor": str(floor),
        "adjustedFundingRateCap": str(cap),
    }


def _rate(
    *,
    hours: int = 8,
    value: float = -0.008,
    sampled_at: float = NOW - 60,
    next_time: float | None = None,
) -> dict[str, str | int]:
    return {
        "symbol": "BTCUSDT",
        "time": int(sampled_at * 1000),
        "lastFundingRate": str(value),
        "nextFundingTime": int(
            (sampled_at + hours * 3600) * 1000 if next_time is None else next_time * 1000
        ),
    }


@pytest.mark.parametrize(
    ("hours", "rate", "floor", "expected_rate_hourly", "expected_floor_hourly"),
    [
        (8, -0.008, -0.016, -0.001, -0.002),
        (4, -0.004, -0.008, -0.001, -0.002),
        (1, -0.001, -0.002, -0.001, -0.002),
    ],
)
def test_funding_rate_and_floor_are_normalized_to_hourly_units(
    hours: int,
    rate: float,
    floor: float,
    expected_rate_hourly: float,
    expected_floor_hourly: float,
) -> None:
    strategy = _strategy()

    metric = strategy._parse_funding_metric(
        _info(hours, floor, abs(floor)),
        _rate(hours=hours, value=rate),
        NOW,
        NOW - 1,
    )

    assert metric["funding_rate_hourly"] == pytest.approx(expected_rate_hourly)
    assert metric["funding_floor_hourly"] == pytest.approx(expected_floor_hourly)
    assert metric["funding_cap_hourly"] == pytest.approx(-expected_floor_hourly)


def test_equivalent_hourly_rate_and_floor_have_the_same_funding_score() -> None:
    strategy = _strategy()
    eight_hour = strategy._parse_funding_metric(
        _info(8, -0.016, 0.016), _rate(hours=8, value=-0.008), NOW, NOW - 1
    )
    four_hour = strategy._parse_funding_metric(
        _info(4, -0.008, 0.008), _rate(hours=4, value=-0.004), NOW, NOW - 1
    )

    assert strategy._funding_score(eight_hour, NOW) == pytest.approx(0.5)
    assert strategy._funding_score(four_hour, NOW) == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("hourly_rate", "expected_score"),
    [(0.0, 0.0), (-0.001, 0.5), (-0.002, 1.0), (-0.003, 1.0)],
)
def test_more_negative_funding_scores_more_and_caps_at_three_points(
    hourly_rate: float, expected_score: float
) -> None:
    strategy = _strategy()
    metric = {
        "funding_rate_hourly": hourly_rate,
        "funding_floor_hourly": -0.002,
        "_funding_valid_until": NOW + 60,
    }

    score = strategy._funding_score(metric, NOW)

    assert score == pytest.approx(expected_score)
    assert 100 * strategy.settings["weights"]["funding"] * score <= 3.0


def test_positive_funding_rate_penalizes_long_score_and_caps_at_three_points() -> None:
    strategy = _strategy()

    metric = {
        "funding_rate_hourly": 0.001,
        "funding_floor_hourly": -0.002,
        "funding_cap_hourly": 0.002,
        "_funding_valid_until": NOW + 60,
    }
    assert strategy._funding_score(metric, NOW) == pytest.approx(-0.5)
    metric["funding_rate_hourly"] = 0.003
    assert strategy._funding_score(metric, NOW) == pytest.approx(-1.0)


def test_missing_funding_data_has_no_bonus_and_keeps_core_score_valid() -> None:
    strategy = _strategy()
    strategy._scores = {PAIR: 41.4}
    strategy._metrics = {PAIR: {"_score_valid_until": NOW + 60, "_exit_valid_until": NOW + 60}}

    assert strategy._funding_score({}, NOW) == 0.0
    assert strategy._current_score(PAIR, NOW) == pytest.approx(41.4)
    assert strategy._pair_score_current(PAIR, NOW)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


def test_funding_fetch_uses_two_public_requests_without_api_key_and_keeps_good_pairs() -> None:
    good_info = _info()
    good_info["symbol"] = "BTCUSDT"
    bad_info = _info()
    bad_info["symbol"] = "XRPUSDT"
    bad_info["fundingIntervalHours"] = "not-a-number"
    missing_info_rate = _rate()
    missing_info_rate["symbol"] = "ETHUSDT"
    good_rate = _rate()
    bad_rate = _rate()
    bad_rate["symbol"] = "XRPUSDT"
    missing_info_rate["lastFundingRate"] = "-0.001"
    payloads = [
        [good_info, bad_info],
        [good_rate, bad_rate, missing_info_rate],
    ]
    session = Mock()
    session.headers = {}
    session.get.side_effect = [_Response(payload) for payload in payloads]
    strategy = _strategy()

    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(MODULE.time, "time", return_value=NOW),
    ):
        result = strategy._fetch_funding_metrics([PAIR, OTHER, "XRP/USDT:USDT"])

    assert set(result) == {PAIR}
    assert session.get.call_count == 2
    assert session.headers == {}
    assert all("X-MBX-APIKEY" not in call.kwargs for call in session.get.call_args_list)
    session.close.assert_called_once()


def test_funding_fetch_network_failure_returns_empty_without_blocking() -> None:
    session = Mock()
    session.headers = {}
    session.get.side_effect = OSError("network down")
    strategy = _strategy()

    with patch.object(DATA.requests, "Session", return_value=session):
        assert strategy._fetch_funding_metrics([PAIR, OTHER]) == {}

    assert session.get.call_count == 1
    session.close.assert_called_once()


def test_funding_fetch_retries_one_transient_request_error() -> None:
    session = Mock()
    session.headers = {}
    session.get.side_effect = [
        DATA.requests.ConnectionError("temporary"),
        _Response([_info()]),
        _Response([_rate()]),
    ]
    strategy = _strategy()

    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(DATA.time, "sleep") as sleep,
        patch.object(MODULE.time, "time", return_value=NOW),
    ):
        result = strategy._fetch_funding_metrics([PAIR])

    assert set(result) == {PAIR}
    assert session.get.call_count == 3
    sleep.assert_called_once_with(strategy.settings["metric_retry_backoff_seconds"])
    session.close.assert_called_once()


def test_old_future_and_post_settlement_funding_data_do_not_score() -> None:
    strategy = _strategy()
    funding_max_age = float(strategy.settings["score_refresh_seconds"]) + float(
        strategy.settings["data_grace_seconds"]
    )
    old_rate = _rate(sampled_at=NOW - funding_max_age - 1)
    with pytest.raises(ValueError):
        strategy._parse_funding_metric(_info(), old_rate, NOW, NOW - 1)

    future_rate = _rate(sampled_at=NOW + 1)
    with pytest.raises(ValueError):
        strategy._parse_funding_metric(_info(), future_rate, NOW, NOW - 1)

    valid = strategy._parse_funding_metric(_info(), _rate(), NOW, NOW - 1)
    assert strategy._funding_score(valid, valid["funding_next_time"]) == 0.0


@pytest.mark.parametrize(("stored", "funding_score"), [(53.0, 1.0), (47.0, -1.0)])
def test_expired_funding_removes_signed_adjustment_from_current_score(
    stored: float, funding_score: float
) -> None:
    strategy = _strategy()
    strategy._scores = {PAIR: stored}
    metric = {
        "score_funding": funding_score,
        "funding_rate_hourly": -0.002,
        "funding_floor_hourly": -0.002,
        "_funding_valid_until": NOW - 1,
        "_score_valid_until": NOW + 900,
        "_exit_valid_until": NOW + 900,
    }
    strategy._metrics = {PAIR: metric}

    assert strategy._current_score(PAIR, NOW) == pytest.approx(50.0)
    assert strategy._pair_score_current(PAIR, NOW)
