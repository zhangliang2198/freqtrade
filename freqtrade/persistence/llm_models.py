"""
LLM Decision Logging Models

Database models for logging LLM trading decisions and performance metrics.
"""

import logging
from datetime import datetime
from typing import ClassVar, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from freqtrade.persistence.base import ModelBase, SessionType

logger = logging.getLogger(__name__)


class LLMDecision(ModelBase):
    """
    LLM Decision Log Table

    Records every LLM decision made during trading, including:
    - Request context
    - Model response
    - Performance metrics
    - Cost tracking
    """

    __tablename__ = "llm_decisions"
    __allow_unmapped__ = True

    session: ClassVar[SessionType]

    # Indexes for common queries
    __table_args__ = (
        Index("ix_llm_decisions_pair_created", "pair", "created_at"),
        Index("ix_llm_decisions_strategy_point", "strategy", "decision_point"),
        Index("ix_llm_decisions_success", "success"),
    )

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Relationship to trades table
    trade_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("trades.id"), nullable=True, index=True
    )

    # Trading context
    pair: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Decision point
    decision_point: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Possible values: 'entry', 'exit', 'stake', 'adjust_position', 'leverage'

    # LLM configuration
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Request and response (optional, controlled by config)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Parsed decision results
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    # Possible values depend on decision_point:
    # - entry: 'buy', 'sell', 'hold'
    # - exit: 'exit', 'hold'
    # - stake: 'adjust', 'default'
    # - adjust_position: 'add', 'reduce', 'no_change'
    # - leverage: 'adjust', 'default'

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Decision parameters (JSON string)
    parameters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Example: '{"stake_multiplier": 1.5, "leverage": 3.0}'

    # Performance metrics
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Status
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    def __repr__(self):
        return (
            f"LLMDecision(id={self.id}, pair={self.pair}, "
            f"decision_point={self.decision_point}, decision={self.decision}, "
            f"confidence={self.confidence}, success={self.success})"
        )

    @classmethod
    def get_recent_decisions(
        cls,
        session: SessionType,
        strategy: Optional[str] = None,
        decision_point: Optional[str] = None,
        limit: int = 100
    ):
        """
        Get recent LLM decisions

        Args:
            session: Database session
            strategy: Optional strategy name filter
            decision_point: Optional decision point filter
            limit: Maximum number of results

        Returns:
            List of LLMDecision objects
        """
        query = session.query(cls)

        if strategy:
            query = query.filter(cls.strategy == strategy)
        if decision_point:
            query = query.filter(cls.decision_point == decision_point)

        return query.order_by(cls.created_at.desc()).limit(limit).all()

    @classmethod
    def get_success_rate(
        cls,
        session: SessionType,
        strategy: Optional[str] = None,
        decision_point: Optional[str] = None
    ) -> float:
        """
        Calculate LLM success rate

        Args:
            session: Database session
            strategy: Optional strategy name filter
            decision_point: Optional decision point filter

        Returns:
            Success rate as a percentage (0.0-100.0)
        """
        query = session.query(cls)

        if strategy:
            query = query.filter(cls.strategy == strategy)
        if decision_point:
            query = query.filter(cls.decision_point == decision_point)

        total = query.count()
        if total == 0:
            return 0.0

        success = query.filter(cls.success == True).count()
        return (success / total) * 100

    @classmethod
    def get_total_cost(
        cls,
        session: SessionType,
        strategy: Optional[str] = None
    ) -> float:
        """
        Calculate total LLM cost

        Args:
            session: Database session
            strategy: Optional strategy name filter

        Returns:
            Total cost in USD
        """
        from sqlalchemy import func

        query = session.query(func.sum(cls.cost_usd))

        if strategy:
            query = query.filter(cls.strategy == strategy)

        result = query.filter(cls.success == True).scalar()
        return float(result or 0.0)


class LLMPerformanceMetric(ModelBase):
    """
    LLM Performance Metrics Table

    Aggregated statistics for LLM performance analysis.
    Typically populated by a periodic aggregation task.
    """

    __tablename__ = "llm_performance_metrics"
    __allow_unmapped__ = True

    session: ClassVar[SessionType]

    __table_args__ = (
        Index(
            "ix_llm_perf_unique",
            "strategy",
            "decision_point",
            "time_bucket",
            unique=True
        ),
    )

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Dimensions
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    decision_point: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    time_bucket: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # Time bucket for aggregation (e.g., hourly or daily)

    # Call statistics
    total_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Performance statistics
    avg_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    p95_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p99_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Cost statistics
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Decision quality
    avg_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    decision_distribution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON string: {"buy": 10, "hold": 5, "sell": 2}

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    def __repr__(self):
        return (
            f"LLMPerformanceMetric(strategy={self.strategy}, "
            f"decision_point={self.decision_point}, time_bucket={self.time_bucket}, "
            f"total_calls={self.total_calls}, avg_latency={self.avg_latency_ms}ms)"
        )


class LLMStrategySnapshot(ModelBase):
    """
    LLM Strategy Snapshot Table

    Extends strategy snapshots with LLM-specific metrics.
    Links to the main strategy_snapshots table.
    """

    __tablename__ = "llm_strategy_snapshots"
    __allow_unmapped__ = True

    session: ClassVar[SessionType]

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Link to strategy_snapshots table (optional, may not exist)
    snapshot_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Alternative: store strategy and timestamp directly
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    # LLM usage statistics
    total_llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_cache_hit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Decision distribution (JSON strings)
    entry_decisions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exit_decisions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Cost statistics
    cumulative_llm_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Effect evaluation (optional, requires correlation analysis)
    llm_entry_win_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    llm_exit_timing_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    def __repr__(self):
        return (
            f"LLMStrategySnapshot(strategy={self.strategy}, timestamp={self.timestamp}, "
            f"total_calls={self.total_llm_calls}, cost=${self.cumulative_llm_cost_usd:.4f})"
        )


def init_llm_tables(engine):
    """
    Initialize LLM-related database tables

    Args:
        engine: SQLAlchemy engine

    This function should be called during database initialization
    to create the LLM tables if they don't exist.
    """
    try:
        ModelBase.metadata.create_all(
            engine,
            tables=[
                LLMDecision.__table__,
                LLMPerformanceMetric.__table__,
                LLMStrategySnapshot.__table__,
            ]
        )
        logger.info("LLM database tables initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize LLM tables: {e}")
        raise
