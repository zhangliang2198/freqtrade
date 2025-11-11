"""
LLM Metrics Collector

Collects metrics about LLM usage for Prometheus export。
"""

from datetime import datetime, timedelta

from .base import MetricSample


def collect(api, now: float) -> list[MetricSample]:
    """
    Collect LLM-related metrics for Prometheus.

    Args:
        api: Freqtrade API wrapper (unused, kept for signature compatibility)
        now: Current timestamp (unused)

    Returns:
        List of MetricSample objects for Prometheus export.
    """

    try:
        from freqtrade.persistence import Trade
        from freqtrade.persistence.llm_models import LLMDecision
        from sqlalchemy import func
    except ImportError:
        return []
    except Exception:
        return []

    try:
        session = Trade.session
    except Exception:
        return []

    samples: list[MetricSample] = []

    try:
        # Ensure LLM tables exist before running expensive queries.
        session.query(LLMDecision).limit(1).first()

        try:
            total_calls = session.query(func.count(LLMDecision.id)).scalar() or 0
            samples.append(
                MetricSample(
                    name="freqtrade_llm_total_calls",
                    value=total_calls,
                    description="Total number of LLM API calls made",
                    metric_type="counter",
                )
            )
        except Exception:
            total_calls = 0

        try:
            success_calls = session.query(func.count(LLMDecision.id)).filter(
                LLMDecision.success.is_(True)
            ).scalar() or 0
            success_rate = (success_calls / total_calls) * 100 if total_calls > 0 else 0.0
            samples.append(
                MetricSample(
                    name="freqtrade_llm_success_rate",
                    value=success_rate,
                    description="LLM API call success rate (percentage)",
                    metric_type="gauge",
                )
            )
        except Exception:
            pass

        try:
            decision_stats = session.query(
                LLMDecision.decision_point,
                func.count(LLMDecision.id).label("count"),
                func.avg(LLMDecision.latency_ms).label("avg_latency"),
                func.avg(LLMDecision.confidence).label("avg_confidence"),
            ).filter(LLMDecision.success.is_(True)).group_by(LLMDecision.decision_point).all()

            for stat in decision_stats:
                samples.append(
                    MetricSample(
                        name="freqtrade_llm_decision_point_calls",
                        value=stat.count,
                        description="Number of LLM calls per decision point",
                        metric_type="counter",
                        labels={"decision_point": stat.decision_point},
                    )
                )
                if stat.avg_latency is not None:
                    samples.append(
                        MetricSample(
                            name="freqtrade_llm_decision_point_latency_ms",
                            value=stat.avg_latency,
                            description="Average response latency per decision point",
                            metric_type="gauge",
                            labels={"decision_point": stat.decision_point},
                        )
                    )
                if stat.avg_confidence is not None:
                    samples.append(
                        MetricSample(
                            name="freqtrade_llm_decision_point_confidence",
                            value=stat.avg_confidence,
                            description="Average decision confidence per decision point",
                            metric_type="gauge",
                            labels={"decision_point": stat.decision_point},
                        )
                    )
        except Exception:
            pass

        one_hour_ago = datetime.utcnow() - timedelta(hours=1)

        try:
            recent_cost = session.query(func.sum(LLMDecision.cost)).filter(
                LLMDecision.created_at >= one_hour_ago,
                LLMDecision.success.is_(True),
            ).scalar() or 0.0
            samples.append(
                MetricSample(
                    name="freqtrade_llm_cost_1h",
                    value=recent_cost,
                    description="Total LLM API cost over the last hour",
                    metric_type="counter",
                )
            )
        except Exception:
            pass

        try:
            avg_latency = session.query(func.avg(LLMDecision.latency_ms)).filter(
                LLMDecision.created_at >= one_hour_ago,
                LLMDecision.latency_ms.isnot(None),
            ).scalar()
            if avg_latency is not None:
                samples.append(
                    MetricSample(
                        name="freqtrade_llm_latency_ms_1h",
                        value=avg_latency,
                        description="Average LLM latency in the last hour",
                        metric_type="gauge",
                    )
                )
        except Exception:
            pass

        try:
            total_tokens = session.query(func.sum(LLMDecision.tokens_used)).filter(
                LLMDecision.success.is_(True),
                LLMDecision.tokens_used.isnot(None),
            ).scalar() or 0
            samples.append(
                MetricSample(
                    name="freqtrade_llm_total_tokens",
                    value=total_tokens,
                    description="Total number of tokens consumed by LLM",
                    metric_type="counter",
                )
            )
        except Exception:
            pass

        try:
            provider_stats = session.query(
                LLMDecision.provider,
                func.count(LLMDecision.id).label("count"),
            ).filter(LLMDecision.success.is_(True)).group_by(LLMDecision.provider).all()

            for stat in provider_stats:
                samples.append(
                    MetricSample(
                        name="freqtrade_llm_provider_calls",
                        value=stat.count,
                        description="Number of LLM calls per provider",
                        metric_type="counter",
                        labels={"provider": stat.provider},
                    )
                )
        except Exception:
            pass

        try:
            llm_entry_trades = session.query(Trade).join(
                LLMDecision,
                (Trade.id == LLMDecision.trade_id) & (LLMDecision.decision_point == "entry"),
            ).filter(Trade.is_open.is_(False)).all()

            if llm_entry_trades:
                winning_trades = sum(1 for t in llm_entry_trades if (t.close_profit or 0) > 0)
                win_rate = (winning_trades / len(llm_entry_trades)) * 100
                samples.append(
                    MetricSample(
                        name="freqtrade_llm_entry_win_rate",
                        value=win_rate,
                        description="Win rate of trades entered based on LLM decisions",
                        metric_type="gauge",
                    )
                )
        except Exception:
            pass

        try:
            model_stats = session.query(
                LLMDecision.provider,
                LLMDecision.model,
                func.avg(LLMDecision.latency_ms).label("avg_latency"),
            ).filter(LLMDecision.success.is_(True)).group_by(
                LLMDecision.provider,
                LLMDecision.model,
            ).all()

            for stat in model_stats:
                if stat.avg_latency is not None:
                    samples.append(
                        MetricSample(
                            name="freqtrade_llm_model_latency_ms",
                            value=stat.avg_latency,
                            description="Average latency per provider/model",
                            metric_type="gauge",
                            labels={"provider": stat.provider, "model": stat.model},
                        )
                    )
        except Exception:
            pass

        try:
            recent_errors = session.query(func.count(LLMDecision.id)).filter(
                LLMDecision.created_at >= one_hour_ago,
                LLMDecision.success.is_(False),
            ).scalar() or 0
            samples.append(
                MetricSample(
                    name="freqtrade_llm_errors_1h",
                    value=recent_errors,
                    description="Number of LLM errors in the last hour",
                    metric_type="gauge",
                )
            )
        except Exception:
            pass

        try:
            for decision_point in ["entry", "exit", "stake", "adjust_position", "leverage"]:
                decision_dist = session.query(
                    LLMDecision.decision,
                    func.count(LLMDecision.id).label("count"),
                ).filter(
                    LLMDecision.decision_point == decision_point,
                    LLMDecision.success.is_(True),
                ).group_by(LLMDecision.decision).all()

                for dist in decision_dist:
                    samples.append(
                        MetricSample(
                            name="freqtrade_llm_decision_distribution",
                            value=dist.count,
                            description="Distribution of LLM decisions by type",
                            metric_type="counter",
                            labels={"decision_point": decision_point, "decision": dist.decision},
                        )
                    )
        except Exception:
            pass
    except Exception:
        return samples
    finally:
        try:
            session.rollback()
        except Exception:
            pass
        try:
            Trade.session.remove()
        except Exception:
            pass

    return samples
