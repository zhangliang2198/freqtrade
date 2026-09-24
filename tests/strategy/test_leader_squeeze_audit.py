"""Audit persistence must be inspectable, replayable and independent of trade commits."""

import copy
import importlib
import json
from datetime import UTC, datetime
from unittest.mock import Mock, patch
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from tests.strategy.leader_squeeze_test_helpers import PUBLIC_CONFIG, configured_strategy
from tests.strategy.test_leader_squeeze_dual_rotation import (
    MODULE,
    NOW,
    TARGET,
    WEAK,
    _rotation_strategy,
)
from tests.strategy.test_leader_squeeze_strategy import LeaderSqueezeStrategy


AUDIT = importlib.import_module("leader_squeeze_helpers")
CONFIG = importlib.import_module("leader_squeeze_helpers")
RotationJournal, rotation_events = AUDIT.RotationJournal, AUDIT.rotation_events
configure_strategy, validate_runtime_settings = (
    CONFIG.configure_strategy,
    CONFIG.validate_runtime_settings,
)


@pytest.fixture
def journal(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'audit.sqlite'}")
    result = RotationJournal(engine, tmp_path / "pending.jsonl", 2000, 30)
    yield result
    engine.dispose()


def _event():
    return {
        "event_id": str(uuid4()),
        "occurred_at": datetime.now(UTC).isoformat(),
        "run_id": str(uuid4()),
        "bot_name": "test",
        "dry_run": True,
        "event_type": "evaluation",
        "rotation_token": None,
        "channel": "normal",
        "weak_pair": WEAK,
        "target_pair": TARGET,
        "weak_score": 40,
        "target_raw_score": 70,
        "target_entry_score": 56,
        "score_gap": 16,
        "reason": "分差通过",
        "snapshot": {"missing": float("nan")},
    }


def _rows(journal):
    with journal.engine.connect() as connection:
        return (
            connection.execute(select(rotation_events).order_by(rotation_events.c.id))
            .mappings()
            .all()
        )


def test_postgres_table_uses_jsonb_and_timezone_aware_time():
    ddl = str(CreateTable(rotation_events).compile(dialect=postgresql.dialect()))
    assert "snapshot JSONB" in ddl
    assert "TIMESTAMP WITH TIME ZONE" in ddl
    assert "UNIQUE (event_id)" in ddl


def test_write_roundtrip_and_replay_are_idempotent(journal):
    event = _event()
    journal.record(event, 100)
    assert not journal.pending
    rows = _rows(journal)
    assert len(rows) == 1
    assert rows[0]["snapshot"]["missing"] is None
    assert rows[0]["target_entry_score"] == 56
    # Simulate commit success followed by process death before deleting the outbox.
    journal.spool_path.write_text(json.dumps({**event, "snapshot": {"missing": None}}) + "\n")
    recovered = RotationJournal(journal.engine, journal.spool_path, 2000, 30)
    recovered.flush(200)
    assert len(_rows(journal)) == 1
    assert recovered.spool_path.read_text() == ""


def test_db_failure_is_spooled_and_retried_after_restart(journal):
    event = _event()
    with patch.object(journal.engine, "begin", side_effect=RuntimeError("private-db-url")):
        journal.record(event, 100)
    assert journal.pending
    assert event["event_id"] in journal.spool_path.read_text()
    recovered = RotationJournal(journal.engine, journal.spool_path, 2000, 30)
    recovered.flush(200)
    assert len(_rows(journal)) == 1
    assert not recovered.pending


def test_audit_does_not_commit_a_separate_trade_transaction(journal):
    other = Table("business", MetaData(), Column("id", Integer, primary_key=True))
    other.create(journal.engine)
    connection = journal.engine.connect()
    transaction = connection.begin()
    # A read-only open transaction models the bot's pending ORM unit of work.
    connection.execute(select(other))
    journal.record(_event(), 100)
    assert transaction.is_active
    transaction.rollback()
    connection.close()
    assert len(_rows(journal)) == 1


def test_real_decision_snapshot_contains_rejections_heat_config_and_no_credentials(journal):
    strategy, trades = _rotation_strategy(weak_score=40, target_score=48)
    for trade in trades:
        trade.open_rate, trade.amount, trade.leverage = 100, 1, 5
    strategy._opening_score_label = Mock(return_value="41.4")
    strategy._rotation_journal = journal
    strategy._audit_run_id = str(uuid4())
    strategy.config["exchange"] = {"key": "DO-NOT-STORE", "secret": "DO-NOT-STORE"}
    strategy.config["db_url"] = "DO-NOT-STORE"
    strategy._closed_candles = Mock(
        return_value=pd.DataFrame(
            {
                "date": [pd.Timestamp(NOW)],
                "close": [100],
                "high": [101],
                "low": [99],
                "volume": [100],
            }
        )
    )
    strategy._entry_quality_reason = Mock(return_value="评分48低于动态风险门槛")
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades):
        strategy._plan_rotation(NOW.timestamp(), NOW)
        strategy._plan_rotation(NOW.timestamp() + 5, NOW)
    rows = _rows(journal)
    assert len(rows) == 1
    snapshot = rows[0]["snapshot"]
    assert "snapshot_error" not in snapshot
    assert snapshot["configuration"]["leader_squeeze"]["replacement_score_gap"] == 10
    assert snapshot["pairs"][TARGET]["entry_score"] == 48
    assert any(
        check.get("reason") == "评分48低于动态风险门槛" for check in snapshot["decision"]["checks"]
    )
    assert "DO-NOT-STORE" not in json.dumps(snapshot)
    assert len(snapshot["holdings"]) == 5


def test_lifecycle_events_correlate_using_rotation_token(journal):
    strategy, trades = _rotation_strategy(weak_score=55, target_score=75, fast_quality=True)
    strategy._rotation_journal = journal
    strategy._audit_run_id = str(uuid4())
    strategy._rotation_snapshot = Mock(
        return_value={
            "pairs": {WEAK: {"raw_score": 55}, TARGET: {"raw_score": 75, "entry_score": 75}}
        }
    )
    with patch.object(MODULE.Trade, "get_open_trades", return_value=trades):
        strategy._plan_rotation(NOW.timestamp(), NOW)
        token = strategy._rotation_state["token"]
        strategy._rotation_state["phase"] = "buy_pending"
        strategy._record_rotation_event("entry_approved", "授权提交", {"requested_amount": 1})
        strategy._clear_rotation("模拟成交完成", event_type="completed")
    events = {row["event_type"]: row for row in _rows(journal)}
    assert {
        "candidate_observed",
        "plan_created",
        "evaluation",
        "entry_approved",
        "completed",
    } <= events.keys()
    assert all(
        events[k]["rotation_token"] == token
        for k in ("plan_created", "entry_approved", "completed")
    )


def test_config_has_no_code_fallback_and_framework_values_are_available_before_start():
    config = copy.deepcopy(PUBLIC_CONFIG)
    strategy = LeaderSqueezeStrategy(config)
    assert strategy.timeframe == config["timeframe"]
    assert strategy.startup_candle_count == config["startup_candle_count"]
    assert not hasattr(LeaderSqueezeStrategy, "DEFAULTS")
    del config["leader_squeeze"]["replacement_score_gap"]
    with pytest.raises(ValueError, match="replacement_score_gap"):
        configure_strategy(strategy, config)


def test_candidate_pool_configuration_contract():
    volume, contract_filter, underlying_filter, *_, final = PUBLIC_CONFIG["pairlists"]
    assert volume["method"] == "VolumePairList"
    assert volume["number_assets"] == 1000
    assert volume["min_value"] == 3_000_000
    assert (
        volume["min_value"]
        <= PUBLIC_CONFIG["leader_squeeze"]["liquidity_discovery_min_quote_volume"]
    )
    assert contract_filter["info_compare_value"] == "PERPETUAL"
    assert underlying_filter["info_compare_value"] == "COIN"
    assert final["method"] == "SpreadFilter"


@pytest.mark.parametrize(
    "key,value",
    [
        ("atr_period", 0),
        ("oi_sample_count", 1),
        ("rotation_audit_enabled", "false"),
        ("profit_lock_arm_r", -1),
        ("score_candle_close_delay_seconds", 900),
    ],
)
def test_invalid_new_runtime_settings_are_rejected(key, value):
    strategy = configured_strategy(LeaderSqueezeStrategy)
    strategy.settings[key] = value
    with pytest.raises(ValueError):
        validate_runtime_settings(strategy)
