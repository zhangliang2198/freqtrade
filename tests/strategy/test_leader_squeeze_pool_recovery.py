"""Late candle data must refresh the candidate pool within the same bar."""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from tests.strategy.leader_squeeze_test_helpers import configured_strategy
from tests.strategy.test_leader_squeeze_strategy import MODULE, LeaderSqueezeStrategy


PAIR = "BTC/USDT:USDT"
OTHER_PAIR = "ETH/USDT:USDT"
NOW = 1_800_030.0


def _pool_strategy() -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.dp = SimpleNamespace(current_selection_whitelist=lambda: [PAIR])
    strategy._occupied_pairs = Mock(return_value=set())
    strategy._scout_local_score = Mock(return_value=50.0)
    strategy._liquidity_quote_volume = Mock(return_value=20_000_000.0)
    return strategy


def test_candidate_pool_recovers_after_all_candles_were_missing() -> None:
    strategy = _pool_strategy()
    fresh = {
        "momentum": 0.05,
        "trend_continuity": 1.0,
        "_candle_valid_until": NOW + 900,
    }
    strategy._candle_metrics = Mock(side_effect=[None, fresh])

    with patch.object(MODULE.time, "time", side_effect=[NOW, NOW + 30]):
        first = strategy._pools_for_loop()
        second = strategy._pools_for_loop()

    assert first["candidates"] == []
    assert second["candidates"] == [PAIR]


def test_candidate_pool_refreshes_when_cached_candle_expires() -> None:
    strategy = _pool_strategy()
    old = {
        "momentum": -0.01,
        "trend_continuity": 1.0,
        "_candle_valid_until": NOW + 5,
    }
    fresh = {
        "momentum": 0.05,
        "trend_continuity": 1.0,
        "_candle_valid_until": NOW + 900,
    }
    strategy._candle_metrics = Mock(side_effect=[old, fresh])

    with patch.object(MODULE.time, "time", side_effect=[NOW, NOW + 30]):
        first = strategy._pools_for_loop()
        second = strategy._pools_for_loop()

    assert first["candidates"] == []
    assert second["candidates"] == [PAIR]


def test_temporary_candle_failure_is_not_cached_for_the_whole_bar() -> None:
    class Source:
        timeframe = "15m"
        settings = {"score_candle_close_delay_seconds": 30}

        def __init__(self) -> None:
            self.calls = 0

        @MODULE.candle_cached
        def value(self):
            self.calls += 1
            return None if self.calls == 1 else 42

    source = Source()
    with patch.object(MODULE.time, "time", return_value=NOW):
        assert source.value() is None
        assert source.value() == 42


def test_below_discovery_liquidity_does_not_trigger_candle_probe_or_retry() -> None:
    strategy = _pool_strategy()
    strategy._liquidity_quote_volume.return_value = 2_000_000.0
    strategy._candle_metrics = Mock()

    with patch.object(MODULE.time, "time", side_effect=[NOW, NOW + 30]):
        first = strategy._pools_for_loop()
        second = strategy._pools_for_loop()

    assert first["candidates"] == second["candidates"] == []
    assert not first["incomplete"]
    strategy._candle_metrics.assert_not_called()
    assert strategy._liquidity_quote_volume.call_count == 1


def test_missing_candle_retry_keeps_valid_turnover_cache() -> None:
    strategy = _pool_strategy()
    reads: list[str] = []

    @MODULE.candle_cached
    def cached_volume(self, pair: str) -> float:
        reads.append(pair)
        return 20_000_000.0

    strategy._liquidity_quote_volume = MethodType(cached_volume, strategy)
    strategy._candle_metrics = Mock(return_value=None)
    clock = [NOW]
    with patch.object(MODULE.time, "time", side_effect=lambda: clock[0]):
        assert strategy._pools_for_loop()["incomplete"]
        clock[0] += 30
        assert strategy._pools_for_loop()["incomplete"]

    assert reads == [PAIR]
    assert strategy._candle_metrics.call_count == 2


def test_pool_cache_ignores_whitelist_order_with_same_members() -> None:
    strategy = _pool_strategy()
    strategy.dp.current_selection_whitelist = Mock(
        side_effect=[[PAIR, OTHER_PAIR], [PAIR, OTHER_PAIR], [OTHER_PAIR, PAIR], [OTHER_PAIR, PAIR]]
    )
    strategy._candle_metrics = Mock(
        return_value={
            "momentum": 0.05,
            "trend_continuity": 1.0,
            "_candle_valid_until": NOW + 900,
        }
    )

    with patch.object(MODULE.time, "time", side_effect=[NOW, NOW + 30]):
        strategy._pools_for_loop()
        strategy._pools_for_loop()

    assert strategy._candle_metrics.call_count == 2
