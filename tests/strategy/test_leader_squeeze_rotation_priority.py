"""Rotation hysteresis must preserve the configured entry priority."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.strategy.leader_squeeze_test_helpers import configured_strategy
from tests.strategy.test_leader_squeeze_strategy import MODULE, LeaderSqueezeStrategy


def test_fresher_breakout_beats_previous_rotation_candidate() -> None:
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings["max_positions"] = 1
    strategy._rotation_in_flight = Mock(return_value=False)
    strategy._entries_allowed = Mock(return_value=True)
    strategy._rotation_score_snapshot = 0.0
    strategy._last_score_refresh = 1.0
    strategy._rotation_target = None
    strategy._rotation_pair = None
    strategy._rotation_candidate = ("HELD", "OLD")
    strategy._rotation_seen = 1
    strategy._rotation_candidate_bar = 0.0
    strategy._rotation_candidate_channel = "normal"
    strategy._last_rotation = 0.0
    strategy._scores = {"HELD": 30.0, "OLD": 80.0, "NEW": 70.0}
    strategy._entry_setup_snapshot = {
        "OLD": {"stage": "启动", "breakout_age_candles": 1.0},
        "NEW": {"stage": "启动", "breakout_age_candles": 0.0},
    }
    strategy.is_trade_exit_allowed = Mock(return_value=True)
    strategy._occupied_pairs = Mock(return_value={"HELD"})
    strategy._rotation_challengers = Mock(return_value=[("NEW", 70.0), ("OLD", 80.0)])
    strategy._pair_score_current = Mock(return_value=True)
    strategy._current_score = Mock(return_value=30.0)
    strategy._candle_metrics = Mock(return_value={"volume_activity_ratio": 2.0})
    strategy._find_rotation_candidate = Mock(return_value=None)
    held = SimpleNamespace(pair="HELD", is_short=False)

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[held]):
        strategy._evaluate_rotation(1_800_030.0, datetime.fromtimestamp(1_800_030, UTC))

    challengers = strategy._find_rotation_candidate.call_args.args[-1]
    assert challengers[0][0] == "NEW"
