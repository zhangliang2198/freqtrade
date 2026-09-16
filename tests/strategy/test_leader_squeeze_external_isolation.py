import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from tests.strategy.leader_squeeze_test_helpers import configured_settings, configured_strategy


STRATEGY_PATH = Path(__file__).parents[2] / "user_data/strategies/leader_squeeze_strategy.py"
SPEC = importlib.util.spec_from_file_location(
    "leader_squeeze_strategy_external_isolation", STRATEGY_PATH
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
LeaderSqueezeStrategy = MODULE.LeaderSqueezeStrategy


def _strategy() -> LeaderSqueezeStrategy:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings = configured_settings()
    strategy.config = {"dry_run": False}
    strategy._external_pairs = ["A", "B"]
    strategy._external_stop_protected = {"A": True, "B": False}
    strategy._external_stop_last_check = {}
    strategy._external_exit_requested = {}
    strategy._external_hard_stop_hit = Mock(return_value=False)
    strategy._trend_reversed = Mock(return_value=False)
    strategy._ensure_external_stop = Mock(return_value=True)
    strategy._market_is_down = Mock(return_value=False)
    strategy._account_stopped = False
    strategy._rotation_pair = None
    strategy._cancel_external_stops = Mock()

    positions = {
        "A": SimpleNamespace(side="long", position=1.0, leverage=5.0),
        "B": SimpleNamespace(side="long", position=2.0, leverage=5.0),
    }
    strategy.wallets = SimpleNamespace(get_all_positions=Mock(return_value=positions))
    exchange = SimpleNamespace(
        get_rate=Mock(side_effect=lambda pair, **kwargs: 100.0 if pair == "A" else 200.0),
        create_order=Mock(return_value={"status": "open"}),
    )
    strategy.dp = SimpleNamespace(_exchange=exchange, send_msg=Mock())
    return strategy


def _has_error_for(caplog, pair: str) -> bool:
    return any(
        record.levelno >= logging.ERROR and pair in record.getMessage() for record in caplog.records
    )


def test_legacy_account_stop_does_not_liquidate_external_positions() -> None:
    strategy = _strategy()
    strategy._account_stopped = True

    strategy._manage_external_positions(1_000.0)

    strategy.dp._exchange.create_order.assert_not_called()
    assert strategy._ensure_external_stop.call_count == 2


def test_external_hard_stop_error_does_not_skip_later_position(caplog) -> None:
    strategy = _strategy()

    def hard_stop(pair: str, side: str) -> bool:
        if pair == "A":
            raise TimeoutError("price feed timeout")
        return False

    strategy._external_hard_stop_hit.side_effect = hard_stop

    with caplog.at_level(logging.ERROR, logger="leader_squeeze_strategy"):
        strategy._manage_external_positions(1_000.0)

    assert strategy._external_stop_protected["A"] is False
    assert strategy._external_stop_protected["B"] is True
    # A fails before stop maintenance, while B must still be maintained.
    assert [call.args[0] for call in strategy._ensure_external_stop.call_args_list] == ["B"]
    assert strategy._ensure_external_stop.call_args[0][2] == 1_000.0
    assert _has_error_for(caplog, "A")


def test_external_trend_error_does_not_skip_later_position(caplog) -> None:
    strategy = _strategy()

    def trend(pair: str) -> bool:
        if pair == "A":
            raise RuntimeError("trend data unavailable")
        return False

    strategy._trend_reversed.side_effect = trend

    with caplog.at_level(logging.ERROR, logger="leader_squeeze_strategy"):
        strategy._manage_external_positions(1_000.0)

    assert strategy._external_stop_protected["A"] is False
    assert strategy._external_stop_protected["B"] is True
    assert [call.args[0] for call in strategy._ensure_external_stop.call_args_list] == ["B"]
    assert _has_error_for(caplog, "A")


def test_external_exit_order_error_does_not_skip_later_position(caplog) -> None:
    strategy = _strategy()
    strategy._external_hard_stop_hit.return_value = True

    def create_order(**kwargs):
        if kwargs["pair"] == "A":
            raise RuntimeError("order rejected")
        return {"status": "closed"}

    strategy.dp._exchange.create_order.side_effect = create_order

    with caplog.at_level(logging.ERROR, logger="leader_squeeze_strategy"):
        strategy._manage_external_positions(1_000.0)

    create_calls = strategy.dp._exchange.create_order.call_args_list
    assert [call.kwargs["pair"] for call in create_calls] == ["A", "B"]
    assert create_calls[1].kwargs["reduceOnly"] is True
    assert create_calls[1].kwargs["amount"] == 2.0
    assert _has_error_for(caplog, "A")


def test_external_positions_keep_original_stop_maintenance_when_healthy() -> None:
    strategy = _strategy()

    strategy._manage_external_positions(1_000.0)

    assert [call.args[0] for call in strategy._external_hard_stop_hit.call_args_list] == ["A", "B"]
    assert [call.args[0] for call in strategy._trend_reversed.call_args_list] == ["A", "B"]
    assert [call.args[0] for call in strategy._ensure_external_stop.call_args_list] == ["A", "B"]
    assert strategy._external_stop_protected == {"A": True, "B": True}
    strategy.dp._exchange.create_order.assert_not_called()
