"""
LLM 决策日志模型

用于记录 LLM 交易决策和性能指标的数据库模型。
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
    LLM 决策日志表

    记录交易过程中做出的每个 LLM 决策，包括：
    - 请求上下文
    - 模型响应
    - 性能指标
    - 成本跟踪
    """

    __tablename__ = "llm_decisions"
    __allow_unmapped__ = True

    session: ClassVar[SessionType]

    # 常用查询的索引
    __table_args__ = (
        Index("ix_llm_decisions_pair_created", "pair", "created_at"),
        Index("ix_llm_decisions_strategy_point", "strategy", "decision_point"),
        Index("ix_llm_decisions_success", "success"),
    )

    # 主键
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 与交易表的关联
    trade_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("trades.id"), nullable=True, index=True
    )

    # 交易上下文
    pair: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # 决策点
    decision_point: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 可能的值: 'entry', 'exit', 'stake', 'adjust_position', 'leverage'

    # LLM 配置
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # 请求和响应（可选，由配置控制）
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 解析后的决策结果
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    # 可能的值取决于 decision_point:
    # - entry: 'buy', 'sell', 'hold'
    # - exit: 'exit', 'hold'
    # - stake: 'adjust', 'default'
    # - adjust_position: 'add', 'reduce', 'no_change'
    # - leverage: 'adjust', 'default'

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 决策参数（JSON 字符串）
    parameters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 示例: '{"stake_multiplier": 1.5, "leverage": 3.0}'

    # 性能指标
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_cache_hit_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_cache_miss_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 状态
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 时间戳
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
        获取最近的 LLM 决策

        Args:
            session: 数据库会话
            strategy: 可选的策略名称过滤器
            decision_point: 可选的决策点过滤器
            limit: 最大结果数量

        Returns:
            LLMDecision 对象列表
        """
        try:
            query = session.query(cls)

            if strategy:
                query = query.filter(cls.strategy == strategy)
            if decision_point:
                query = query.filter(cls.decision_point == decision_point)

            return query.order_by(cls.created_at.desc()).limit(limit).all()
        finally:
            session.remove()

    @classmethod
    def get_success_rate(
        cls,
        session: SessionType,
        strategy: Optional[str] = None,
        decision_point: Optional[str] = None
    ) -> float:
        """
        计算 LLM 成功率

        Args:
            session: 数据库会话
            strategy: 可选的策略名称过滤器
            decision_point: 可选的决策点过滤器

        Returns:
            成功率百分比 (0.0-100.0)
        """
        try:
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
        finally:
            session.remove()

    @classmethod
    def get_total_cost(
        cls,
        session: SessionType,
        strategy: Optional[str] = None
    ) -> float:
        """
        计算 LLM 总成本

        Args:
            session: 数据库会话
            strategy: 可选的策略名称过滤器

        Returns:
            总成本（美元）
        """
        from sqlalchemy import func

        try:
            query = session.query(func.sum(cls.cost_usd))

            if strategy:
                query = query.filter(cls.strategy == strategy)

            result = query.filter(cls.success == True).scalar()
            return float(result or 0.0)
        finally:
            session.remove()
class LLMPerformanceMetric(ModelBase):
    """
    LLM 性能指标表

    用于 LLM 性能分析的聚合统计数据。
    通常由定期聚合任务填充。
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

    # 主键
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 维度
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    decision_point: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    time_bucket: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # 聚合时间桶（例如：每小时或每天）

    # 调用统计
    total_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 性能统计
    avg_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    p95_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    p99_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 成本统计
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 决策质量
    avg_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    decision_distribution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON 字符串: {"buy": 10, "hold": 5, "sell": 2}

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    def __repr__(self):
        return (
            f"LLMPerformanceMetric(strategy={self.strategy}, "
            f"decision_point={self.decision_point}, time_bucket={self.time_bucket}, "
            f"total_calls={self.total_calls}, avg_latency={self.avg_latency_ms}ms)"
        )
def init_llm_tables(engine):
    """
    初始化 LLM 相关数据库表

    Args:
        engine: SQLAlchemy 引擎

    此函数应在数据库初始化期间调用，
    以创建不存在的 LLM 表。
    """
    try:
        ModelBase.metadata.create_all(
            engine,
            tables=[
                LLMDecision.__table__,
                LLMPerformanceMetric.__table__,
            ]
        )
        logger.info("LLM 数据库表初始化成功")
    except Exception as e:
        logger.error(f"初始化 LLM 表失败: {e}")
        raise
