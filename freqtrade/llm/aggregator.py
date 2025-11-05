"""
LLM 性能指标聚合器

定期从 llm_decisions 表聚合数据到 llm_performance_metrics 表，
用于长期性能分析和趋势监控。
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class LLMMetricsAggregator:
    """
    LLM 性能指标聚合器

    负责定期聚合 LLM 决策数据，生成性能指标摘要。
    """

    def __init__(self, aggregation_interval_minutes: int = 60):
        """
        初始化聚合器

        Args:
            aggregation_interval_minutes: 聚合时间间隔（分钟），默认 60 分钟
        """
        self.aggregation_interval = aggregation_interval_minutes
        self.last_aggregation_time: Optional[datetime] = None

    def should_aggregate(self, current_time: datetime) -> bool:
        """
        判断是否应该执行聚合

        Args:
            current_time: 当前时间

        Returns:
            是否应该执行聚合
        """
        if self.last_aggregation_time is None:
            return True

        time_since_last = (current_time - self.last_aggregation_time).total_seconds() / 60
        return time_since_last >= self.aggregation_interval

    def aggregate(self, strategy_name: Optional[str] = None) -> None:
        """
        执行聚合任务

        Args:
            strategy_name: 可选的策略名称过滤器，如果为 None 则聚合所有策略
        """
        try:
            from freqtrade.persistence import Trade
            from freqtrade.persistence.llm_models import LLMDecision, LLMPerformanceMetric
            from sqlalchemy import func
            import json

            session = Trade.session
            current_time = datetime.utcnow()

            # 计算时间桶（向下取整到小时）
            time_bucket = current_time.replace(minute=0, second=0, microsecond=0)

            # 获取要聚合的决策点列表
            decision_points = ["entry", "exit", "stake", "adjust_position", "leverage"]

            # 构建查询的基础条件
            base_query = session.query(LLMDecision).filter(
                LLMDecision.created_at >= time_bucket,
                LLMDecision.created_at < time_bucket + timedelta(hours=1)
            )

            if strategy_name:
                base_query = base_query.filter(LLMDecision.strategy == strategy_name)

            # 获取所有策略列表
            strategies_query = base_query.with_entities(LLMDecision.strategy).distinct()
            strategies = [s[0] for s in strategies_query.all()]

            if not strategies:
                logger.debug("没有需要聚合的 LLM 数据")
                self.last_aggregation_time = current_time
                return

            # 为每个策略和决策点创建聚合指标
            for strategy in strategies:
                for decision_point in decision_points:
                    self._aggregate_for_point(
                        session,
                        strategy,
                        decision_point,
                        time_bucket
                    )

            # 提交所有更改
            Trade.commit()
            self.last_aggregation_time = current_time

            logger.info(
                f"LLM 性能指标聚合完成: {len(strategies)} 个策略, "
                f"时间桶 {time_bucket.strftime('%Y-%m-%d %H:%M')}"
            )

        except Exception as e:
            logger.error(f"LLM 性能指标聚合失败: {e}", exc_info=True)
        finally:
            try:
                Trade.session.remove()
            except Exception:
                pass

    def _aggregate_for_point(
        self,
        session,
        strategy: str,
        decision_point: str,
        time_bucket: datetime
    ) -> None:
        """
        为特定策略和决策点聚合指标

        Args:
            session: 数据库会话
            strategy: 策略名称
            decision_point: 决策点
            time_bucket: 时间桶
        """
        try:
            from freqtrade.persistence.llm_models import LLMDecision, LLMPerformanceMetric
            from sqlalchemy import func
            import json

            # 查询该时间段的所有决策
            decisions = session.query(LLMDecision).filter(
                LLMDecision.strategy == strategy,
                LLMDecision.decision_point == decision_point,
                LLMDecision.created_at >= time_bucket,
                LLMDecision.created_at < time_bucket + timedelta(hours=1)
            ).all()

            if not decisions:
                # 没有数据，跳过
                return

            # 计算统计数据
            total_calls = len(decisions)
            success_calls = sum(1 for d in decisions if d.success)
            failed_calls = total_calls - success_calls
            cache_hits = 0  # TODO: 需要从引擎缓存统计获取

            # 延迟统计
            latencies = [d.latency_ms for d in decisions if d.success]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

            # P95 和 P99 延迟
            p95_latency = None
            p99_latency = None
            if latencies:
                sorted_latencies = sorted(latencies)
                p95_idx = int(len(sorted_latencies) * 0.95)
                p99_idx = int(len(sorted_latencies) * 0.99)
                p95_latency = sorted_latencies[p95_idx] if p95_idx < len(sorted_latencies) else sorted_latencies[-1]
                p99_latency = sorted_latencies[p99_idx] if p99_idx < len(sorted_latencies) else sorted_latencies[-1]

            # Token 和成本统计
            total_tokens = sum(d.tokens_used or 0 for d in decisions if d.success)
            total_cost = sum(d.cost_usd or 0.0 for d in decisions if d.success)

            # 置信度统计
            confidences = [d.confidence for d in decisions if d.success and d.confidence is not None]
            avg_confidence = sum(confidences) / len(confidences) if confidences else None

            # 决策分布
            decision_dist = {}
            for d in decisions:
                if d.success and d.decision:
                    decision_dist[d.decision] = decision_dist.get(d.decision, 0) + 1

            # 检查是否已存在该记录（使用 UPSERT 逻辑）
            existing_metric = session.query(LLMPerformanceMetric).filter(
                LLMPerformanceMetric.strategy == strategy,
                LLMPerformanceMetric.decision_point == decision_point,
                LLMPerformanceMetric.time_bucket == time_bucket
            ).first()

            if existing_metric:
                # 更新现有记录
                existing_metric.total_calls = total_calls
                existing_metric.success_calls = success_calls
                existing_metric.failed_calls = failed_calls
                existing_metric.cache_hits = cache_hits
                existing_metric.avg_latency_ms = avg_latency
                existing_metric.p95_latency_ms = p95_latency
                existing_metric.p99_latency_ms = p99_latency
                existing_metric.total_tokens = total_tokens
                existing_metric.total_cost_usd = total_cost
                existing_metric.avg_confidence = avg_confidence
                existing_metric.decision_distribution = json.dumps(decision_dist) if decision_dist else None
            else:
                # 创建新记录
                metric = LLMPerformanceMetric(
                    strategy=strategy,
                    decision_point=decision_point,
                    time_bucket=time_bucket,
                    total_calls=total_calls,
                    success_calls=success_calls,
                    failed_calls=failed_calls,
                    cache_hits=cache_hits,
                    avg_latency_ms=avg_latency,
                    p95_latency_ms=p95_latency,
                    p99_latency_ms=p99_latency,
                    total_tokens=total_tokens,
                    total_cost_usd=total_cost,
                    avg_confidence=avg_confidence,
                    decision_distribution=json.dumps(decision_dist) if decision_dist else None,
                    created_at=datetime.utcnow()
                )
                session.add(metric)

            logger.debug(
                f"聚合完成: {strategy}/{decision_point} - "
                f"{total_calls} 次调用, {success_calls} 成功"
            )

        except Exception as e:
            logger.error(
                f"聚合 {strategy}/{decision_point} 失败: {e}",
                exc_info=True
            )

    def cleanup_old_metrics(self, days_to_keep: int = 90) -> None:
        """
        清理旧的性能指标数据

        Args:
            days_to_keep: 保留最近多少天的数据，默认 90 天
        """
        try:
            from freqtrade.persistence import Trade
            from freqtrade.persistence.llm_models import LLMPerformanceMetric

            session = Trade.session
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

            deleted_count = session.query(LLMPerformanceMetric).filter(
                LLMPerformanceMetric.time_bucket < cutoff_date
            ).delete()

            Trade.commit()

            if deleted_count > 0:
                logger.info(f"清理了 {deleted_count} 条旧的性能指标记录（{days_to_keep} 天前）")

        except Exception as e:
            logger.error(f"清理旧性能指标失败: {e}", exc_info=True)
        finally:
            try:
                Trade.session.remove()
            except Exception:
                pass
