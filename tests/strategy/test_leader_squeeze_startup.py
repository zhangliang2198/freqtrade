"""Exercise the resolver -> bot_start -> existing-position exit lifecycle."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from freqtrade.persistence import Trade
from freqtrade.resolvers import StrategyResolver
from freqtrade.util.datetime_helpers import dt_now
from tests.strategy.leader_squeeze_test_helpers import PUBLIC_CONFIG


def test_startup_preserves_normalized_roi_for_existing_position(mocker):
    config = deepcopy(PUBLIC_CONFIG)
    config["user_data_dir"] = Path(__file__).parents[2] / "user_data"
    strategy = StrategyResolver.load_strategy(config)
    expected_roi = strategy.minimal_roi.copy()
    mocker.patch.object(strategy, "_initialize_runtime")
    mocker.patch.object(strategy, "_initialize_rotation_audit")
    mocker.patch.object(strategy, "custom_exit", return_value=None)
    strategy.bot_start()
    now = dt_now()
    trade = Trade(
        pair="BTC/USDT:USDT",
        amount=1,
        open_rate=100,
        open_date=now - timedelta(minutes=30),
        fee_open=0,
        fee_close=0,
        leverage=5,
        is_open=True,
    )
    assert strategy.should_exit(trade, 100, now, enter=False, exit_=False) == []
    assert strategy.minimal_roi == expected_roi
