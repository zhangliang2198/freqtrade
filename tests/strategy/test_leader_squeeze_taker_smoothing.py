from __future__ import annotations

import copy
import importlib
from unittest.mock import patch

import pytest

from tests.strategy.leader_squeeze_test_helpers import PUBLIC_CONFIG


DATA = importlib.import_module("leader_squeeze_data")
LeaderDataMixin = DATA.LeaderDataMixin

PAIR = "BTC/USDT:USDT"
NOW = 4_000.0
PERIOD_MS = 900_000
TAKER_TIMESTAMPS = [1_200_000, 2_100_000, 3_000_000]


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Session:
    def __init__(self, payloads):
        self.headers = {}
        self.payloads = payloads
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payloads[url.rsplit("/", 1)[-1]])

    def close(self):
        return None


def _payloads(rows, *, oi_timestamp: int = 3_900_000):
    return {
        "takerlongshortRatio": rows,
        "openInterestHist": [
            {"sumOpenInterest": str(value), "timestamp": oi_timestamp}
            for value in (100, 99, 98, 97)
        ],
    }


def _rows(volumes, timestamps=TAKER_TIMESTAMPS):
    return [
        {"buyVol": str(buy), "sellVol": str(sell), "timestamp": timestamp}
        for timestamp, (buy, sell) in zip(timestamps, volumes, strict=True)
    ]


def _strategy_and_session(payloads):
    strategy = LeaderDataMixin.__new__(LeaderDataMixin)
    strategy.config = copy.deepcopy(PUBLIC_CONFIG)
    strategy.config["exchange"] = {"ccxt_config": {}}
    strategy.settings = copy.deepcopy(PUBLIC_CONFIG["leader_squeeze"])
    strategy.settings["taker_window_candles"] = 3
    strategy.timeframe = "15m"
    strategy._market_id = lambda pair: "BTCUSDT"
    return strategy, _Session(payloads)


def _fetch(payloads, *, now: float = NOW):
    strategy, session = _strategy_and_session(payloads)
    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(DATA.time, "time", return_value=now),
    ):
        metric = strategy._fetch_pair_metrics(PAIR, exit_only=True)
    return metric, session


def test_taker_ratio_sums_volumes_and_keeps_latest_ratio() -> None:
    metric, session = _fetch(_payloads(_rows([(100, 100), (20, 100), (13, 10)])))

    assert metric["taker_ratio"] == pytest.approx(133 / 210)
    assert metric["taker_ratio_latest"] == pytest.approx(1.3)
    assert metric["_exit_valid_until"] == pytest.approx(
        3_900 + PUBLIC_CONFIG["leader_squeeze"]["remote_metric_max_age_seconds"]
    )
    taker_call = next(call for call in session.calls if call[0].endswith("/takerlongshortRatio"))
    assert taker_call[1]["params"]["limit"] == 3


@pytest.mark.parametrize(
    "volumes, expected",
    [
        ([(0, 0), (0, 0), (0, 0)], 1.0),
        ([(0, 0), (0, 0), (5, 0)], 1.5),
    ],
)
def test_taker_zero_sell_volume_has_finite_defined_ratio(volumes, expected) -> None:
    metric, _ = _fetch(_payloads(_rows(volumes)))

    assert metric["taker_ratio"] == pytest.approx(expected)
    assert metric["taker_ratio_latest"] == pytest.approx(expected)


@pytest.mark.parametrize(
    "rows",
    [
        [{"buySellRatio": "1.2", "timestamp": timestamp} for timestamp in TAKER_TIMESTAMPS],
        [
            {"buyVol": "-1", "sellVol": "2", "timestamp": timestamp}
            for timestamp in TAKER_TIMESTAMPS
        ],
        [
            {"buyVol": "nan", "sellVol": "2", "timestamp": timestamp}
            for timestamp in TAKER_TIMESTAMPS
        ],
    ],
)
def test_taker_rejects_old_field_and_invalid_volumes(rows) -> None:
    strategy, session = _strategy_and_session(_payloads(rows))

    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(DATA.time, "time", return_value=NOW),
        pytest.raises((KeyError, ValueError)),
    ):
        strategy._fetch_pair_metrics(PAIR, exit_only=True)


@pytest.mark.parametrize(
    "timestamps",
    [
        [1_200_000, 2_100_000, 3_100_000],  # gap
        [1_200_000, 2_100_000, 2_100_000],  # duplicate
        [2_400_000, 3_300_000, 4_200_000],  # latest candle is not closed
    ],
)
def test_taker_rejects_gap_duplicate_or_unclosed_candles(timestamps) -> None:
    rows = _rows([(1, 1), (1, 1), (1, 1)], timestamps)
    strategy, session = _strategy_and_session(_payloads(rows))

    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(DATA.time, "time", return_value=NOW),
        pytest.raises(ValueError),
    ):
        strategy._fetch_pair_metrics(PAIR, exit_only=True)


def test_taker_requires_the_configured_number_of_candles() -> None:
    rows = _rows([(1, 1), (1, 1)], TAKER_TIMESTAMPS[:2])
    strategy, session = _strategy_and_session(_payloads(rows))

    with (
        patch.object(DATA.requests, "Session", return_value=session),
        patch.object(DATA.time, "time", return_value=NOW),
        pytest.raises(ValueError, match="insufficient taker candles"),
    ):
        strategy._fetch_pair_metrics(PAIR, exit_only=True)


def test_aggregate_volume_overflow_is_rejected():
    with pytest.raises(ValueError, match="aggregate"):
        _fetch(_payloads(_rows([(1e308, 0)] * 3)))
