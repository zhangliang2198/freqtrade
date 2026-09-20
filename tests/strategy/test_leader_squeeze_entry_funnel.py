"""Entry-funnel contracts: setup quality must precede strength ranking."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.strategy.leader_squeeze_test_helpers import configured_settings
from tests.strategy.test_leader_squeeze_strategy import (
    MODULE,
    LeaderSqueezeStrategy,
    _entry_ready_strategy,
    _fresh_score_metric,
)


TARGET = "TARGET/USDT:USDT"
WEAK = "WEAK/USDT:USDT"


def _setup(*, stage: str = "启动", score: float = 80.0, late: float = 0.0) -> dict:
    return {
        "stage": stage,
        "score": score,
        "late": late,
        "extension_atr": 6.0 if late else 2.0,
    }


def _funnel_strategy(
    scores: dict[str, float], setups: dict[str, dict], *, max_positions: int = 10
) -> LeaderSqueezeStrategy:
    strategy = _entry_ready_strategy(time.time())
    strategy.settings = configured_settings()
    strategy.settings["max_positions"] = max_positions
    # The setup stage is supplied by the test double; disable the underlying
    # 15-day heat fetch so these tests exercise only the funnel contract.
    strategy.settings["entry_heat_max_penalty"] = 0
    strategy._scores = scores
    strategy._score_leaders = list(scores)
    strategy._metrics = {pair: _fresh_score_metric() for pair in scores}
    strategy._candle_metrics = Mock(return_value=_fresh_score_metric())
    strategy._trend_reversed = Mock(return_value=False)
    strategy._higher_entry_reason = Mock(return_value="")
    strategy._entry_pair_available = Mock(return_value=True)
    strategy._execution_is_safe = Mock(return_value=True)
    strategy._entry_setup_metrics = Mock(side_effect=lambda pair: setups[pair])
    strategy._entry_leaders = list(scores)
    return strategy


def test_high_strength_late_chase_is_rejected_by_setup_stage() -> None:
    strategy = _funnel_strategy({TARGET: 100.0}, {TARGET: _setup(stage="末端", late=1.0)})

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == set()

    assert "末端过热" in strategy._entry_decisions[TARGET]
    strategy._execution_is_safe.assert_not_called()


def test_setup_qualified_candidate_still_needs_strength_floor() -> None:
    strategy = _funnel_strategy({TARGET: 39.99}, {TARGET: _setup(score=90.0)})

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == set()

    assert "强度评分" in strategy._entry_decisions[TARGET]
    assert strategy._entry_setup_snapshot[TARGET]["score"] == 90.0
    strategy._execution_is_safe.assert_not_called()


def test_strength_ranking_only_sees_setup_qualified_candidates() -> None:
    strategy = _funnel_strategy(
        {"SAFE": 60.0, "LATE": 100.0},
        {"SAFE": _setup(score=70.0), "LATE": _setup(stage="末端", late=1.0)},
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {"SAFE"}

    assert "末端过热" in strategy._entry_decisions["LATE"]
    assert strategy._entry_decisions["SAFE"].startswith("入选第1仓")


def test_setup_shortlist_keeps_top_forty_percent_with_a_ten_candidate_floor() -> None:
    pairs = [f"PAIR-{index:02d}" for index in range(25)]
    strategy = _funnel_strategy(
        {pair: 100.0 - index for index, pair in enumerate(pairs)},
        {pair: _setup(score=100.0 - index) for index, pair in enumerate(pairs)},
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert len(strategy._select_entries()) == 10

    assert strategy._entry_funnel_rows[2] == ["3 形态短名单", "25", "10", "15", "前40%, 至少10个"]
    assert sum("形态排名未进前40%" in reason for reason in strategy._entry_decisions.values()) == 15


def test_disabling_setup_keeps_every_hard_eligible_candidate_in_shortlist() -> None:
    pairs = [f"PAIR-{index:02d}" for index in range(25)]
    strategy = _funnel_strategy(
        {pair: 100.0 - index for index, pair in enumerate(pairs)},
        {pair: _setup(score=100.0) for pair in pairs},
    )
    strategy.settings["entry_setup_enabled"] = False

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        selected = strategy._select_entries()
        assert len(selected) == 10

    assert strategy._entry_funnel_rows[2] == [
        "3 形态短名单",
        "25",
        "25",
        "0",
        "形态筛选关闭",
    ]
    assert not any("形态排名未进" in reason for reason in strategy._entry_decisions.values())
    assert all("形态关闭" in strategy._entry_decisions[pair] for pair in selected)
    assert all(row[2:4] == ["关闭", "—"] for row in strategy._entry_funnel_candidates)


def test_capacity_cutoff_is_not_reported_as_a_strength_rejection() -> None:
    pairs = [f"PAIR-{index:02d}" for index in range(30)]
    strategy = _funnel_strategy(
        {pair: 100.0 - index for index, pair in enumerate(pairs)},
        {pair: _setup(score=100.0 - index) for index, pair in enumerate(pairs)},
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert len(strategy._select_entries()) == 10

    assert strategy._entry_funnel_rows[3][0:4] == ["4 强度/逐仓门槛", "10", "10", "0"]
    assert strategy._entry_funnel_rows[5] == ["6 容量截断", "12", "10", "2", "本轮可用名额10"]


def test_funnel_log_table_shows_stage_counts_and_final_slot(caplog) -> None:
    strategy = _funnel_strategy({TARGET: 70.0}, {TARGET: _setup(score=80.0)})
    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {TARGET}

    with caplog.at_level(logging.INFO, logger="leader_squeeze_strategy"):
        strategy._log_entry_funnel()

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "入场漏斗" in rendered
    assert "3 形态短名单" in rendered
    assert f"最终候选 {TARGET}" in rendered
    assert "第1仓 启动 形态80.0 强度70.0/门槛40.0" in rendered


def test_confirmation_rechecks_setup_after_selection() -> None:
    setup_state = {"invalid": False}
    good = _setup(score=80.0)
    late = _setup(stage="末端", late=1.0)
    strategy = _funnel_strategy({TARGET: 70.0}, {TARGET: good})
    strategy._entry_setup_metrics.side_effect = lambda pair: (
        late if setup_state["invalid"] else good
    )

    with patch.object(MODULE.Trade, "get_open_trades", return_value=[]):
        assert strategy._select_entries() == {TARGET}
        strategy._entry_pairs = {TARGET}
        setup_state["invalid"] = True
        assert not strategy.confirm_trade_entry(
            TARGET, "market", 1.0, 100.0, "GTC", None, None, "long"
        )

    assert "末端过热" in strategy._entry_block_reason


def test_rotation_target_reuses_setup_hard_gate() -> None:
    held = [SimpleNamespace(pair=f"HELD-{index}") for index in range(10)]
    strategy = _funnel_strategy(
        {WEAK: 20.0, TARGET: 100.0},
        {WEAK: _setup(score=80.0), TARGET: _setup(stage="末端", late=1.0)},
    )
    strategy._rotation_pair = WEAK
    strategy._rotation_target = TARGET
    strategy._rotation_state = {"channel": "normal", "phase": "buy"}

    with patch.object(MODULE.Trade, "get_open_trades", return_value=held):
        assert strategy._select_entries() == set()

    assert "末端过热" in strategy._entry_decisions[TARGET]
    strategy._execution_is_safe.assert_not_called()
