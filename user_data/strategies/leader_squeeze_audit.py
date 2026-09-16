"""Append-only rotation history in the bot's database, independent of trade transactions."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from leader_squeeze_support import logger
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    insert,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB


metadata = MetaData()
rotation_events = Table(
    "leader_rotation_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("event_id", String(36), nullable=False, unique=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("bot_name", String(100), nullable=False),
    Column("dry_run", Boolean, nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("rotation_token", String(64)),
    Column("channel", String(16)),
    Column("weak_pair", String(100)),
    Column("target_pair", String(100)),
    Column("weak_score", Float),
    Column("target_raw_score", Float),
    Column("target_entry_score", Float),
    Column("score_gap", Float),
    Column("reason", Text, nullable=False),
    Column("snapshot", JSON().with_variant(JSONB, "postgresql"), nullable=False),
)
Index("ix_leader_rotation_events_time", rotation_events.c.occurred_at)
Index(
    "ix_leader_rotation_events_token_time",
    rotation_events.c.rotation_token,
    rotation_events.c.occurred_at,
)
Index(
    "ix_leader_rotation_events_target_time",
    rotation_events.c.target_pair,
    rotation_events.c.occurred_at,
)


def json_safe(value: Any) -> Any:
    """JSONB rejects NaN; missing metrics must remain null, never invented zeroes."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        return json_safe(value.item())
    return str(value)


class RotationJournal:
    """A durable local outbox retries failed inserts without committing the trading session."""

    def __init__(self, engine, spool_path: Path, timeout_ms: int, retry_seconds: float):
        self.engine = engine
        self.spool_path = spool_path
        self.timeout_ms = timeout_ms
        self.retry_seconds = retry_seconds
        self.next_retry = 0.0
        self.pending: list[dict] = []
        self.spool_read_failed = False
        try:
            if spool_path.exists():
                self.pending = [
                    json.loads(line) for line in spool_path.read_text().splitlines() if line
                ]
        except (OSError, ValueError):
            self.spool_read_failed = True
            logger.error("轮换审计暂存文件读取失败, 保留原文件: %s", spool_path)

    def _save_pending(self) -> bool:
        if self.spool_read_failed:
            return False
        try:
            self.spool_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.spool_path.with_suffix(self.spool_path.suffix + ".tmp")
            temporary.write_text(
                "".join(
                    json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
                    for event in self.pending
                )
            )
            temporary.replace(self.spool_path)
            return True
        except OSError:
            logger.error("轮换审计暂存失败, 事件暂存内存; 请检查磁盘和权限: %s", self.spool_path)
            return False

    def record(self, event: dict, now: float) -> None:
        self.pending.append(json_safe(event))
        self._save_pending()
        self.flush(now)

    def flush(self, now: float) -> None:
        if not self.pending or now < self.next_retry:
            return
        try:
            with self.engine.begin() as connection:
                if connection.dialect.name == "postgresql":
                    connection.execute(
                        text("SELECT set_config('statement_timeout', :timeout, true)"),
                        {"timeout": str(self.timeout_ms)},
                    )
                    connection.execute(
                        text("SELECT set_config('lock_timeout', :timeout, true)"),
                        {"timeout": str(self.timeout_ms)},
                    )
                rotation_events.create(connection, checkfirst=True)
                dialect_insert: Any
                if connection.dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as dialect_insert
                elif connection.dialect.name == "sqlite":
                    from sqlalchemy.dialects.sqlite import insert as dialect_insert
                else:
                    dialect_insert = insert
                for event in self.pending:
                    row = {
                        **event,
                        "occurred_at": datetime.fromisoformat(event["occurred_at"]).astimezone(UTC),
                    }
                    statement = dialect_insert(rotation_events).values(**row)
                    if connection.dialect.name in {"postgresql", "sqlite"}:
                        statement = statement.on_conflict_do_nothing(index_elements=["event_id"])
                    connection.execute(statement)
            self.pending.clear()
            self.next_retry = 0.0
            self._save_pending()
        except Exception as exc:
            self.next_retry = now + self.retry_seconds
            # Never stringify driver errors: some contain connection credentials or bound payloads.
            logger.error(
                "轮换审计写库失败 (%s), %s 条事件等待重试; 已有仓位退出继续运行",
                type(exc).__name__,
                len(self.pending),
            )
