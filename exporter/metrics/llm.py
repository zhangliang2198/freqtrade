"""
LLM Metrics Collector

Collects metrics about LLM usage for Prometheus export.
"""

from typing import Generator
from datetime import datetime, timedelta

from .base import MetricSample


def collect(api, now: float) -> Generator[MetricSample, None, None]:
    """
    Collect LLM-related metrics for Prometheus

    Args:
        api: Freqtrade API wrapper
        now: Current timestamp (for consistency with other collectors)

    Yields:
        MetricSample objects for Prometheus export
    """
    # Import here to avoid circular dependencies
    try:
        from freqtrade.persistence import Trade
        from freqtrade.persistence.llm_models import LLMDecision
        from sqlalchemy import func
    except ImportError:
        # If LLM models not available, skip collection silently
        return
    except Exception:
        # Any other import error, skip silently
        return

    # Get database session
    try:
        session = Trade.session
    except Exception:
        # No database available, skip silently
        return

    # Check if LLM tables exist
    try:
        # Try a simple query to verify table exists
        session.query(LLMDecision).limit(1).first()
    except Exception:
        # Table doesn't exist or other DB error, skip silently
        return

    # 1. Total LLM calls
    try:
        total_calls = session.query(func.count(LLMDecision.id)).scalar() or 0
        yield MetricSample(
            name="freqtrade_llm_total_calls",
            value=total_calls,
            description="Total number of LLM API calls made",
            metric_type="counter"
        )
    except Exception:
        pass

    # 2. Success rate
    try:
        success_calls = session.query(func.count(LLMDecision.id)).filter(
            LLMDecision.success == True
        ).scalar() or 0

        if total_calls > 0:
            success_rate = (success_calls / total_calls) * 100
        else:
            success_rate = 0.0

        yield MetricSample(
            name="freqtrade_llm_success_rate",
            value=success_rate,
            description="LLM API call success rate (percentage)",
            metric_type="gauge"
        )
    except Exception:
        pass

    # 3. Statistics by decision point
    try:
        decision_stats = session.query(
            LLMDecision.decision_point,
            func.count(LLMDecision.id).label("count"),
            func.avg(LLMDecision.latency_ms).label("avg_latency"),
            func.avg(LLMDecision.confidence).label("avg_confidence")
        ).filter(
            LLMDecision.success == True
        ).group_by(LLMDecision.decision_point).all()

        for stat in decision_stats:
            # Call count per decision point
            yield MetricSample(
                name="freqtrade_llm_decision_point_calls",
                value=stat.count,
                description="Number of LLM calls per decision point",
                metric_type="counter",
                labels={"decision_point": stat.decision_point}
            )

            # Average latency per decision point
            if stat.avg_latency is not None:
                yield MetricSample(
                    name="freqtrade_llm_decision_point_latency_ms",
                    value=stat.avg_latency,
                    description="Average LLM response latency in milliseconds per decision point",
                    metric_type="gauge",
                    labels={"decision_point": stat.decision_point}
                )

            # Average confidence per decision point
            if stat.avg_confidence is not None:
                yield MetricSample(
                    name="freqtrade_llm_decision_point_confidence",
                    value=stat.avg_confidence,
                    description="Average LLM decision confidence (0.0-1.0) per decision point",
                    metric_type="gauge",
                    labels={"decision_point": stat.decision_point}
                )
    except Exception:
        pass

    # 4. Recent cost (last hour)
    try:
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_cost = session.query(func.sum(LLMDecision.cost_usd)).filter(
            LLMDecision.created_at >= one_hour_ago,
            LLMDecision.success == True,
            LLMDecision.cost_usd.isnot(None)
        ).scalar() or 0.0

        yield MetricSample(
            name="freqtrade_llm_cost_usd_1h",
            value=recent_cost,
            description="LLM cost in USD over the last hour",
            metric_type="gauge"
        )
    except Exception:
        pass

    # 5. Cumulative cost
    try:
        total_cost = session.query(func.sum(LLMDecision.cost_usd)).filter(
            LLMDecision.success == True,
            LLMDecision.cost_usd.isnot(None)
        ).scalar() or 0.0

        yield MetricSample(
            name="freqtrade_llm_total_cost_usd",
            value=total_cost,
            description="Total cumulative LLM cost in USD",
            metric_type="counter"
        )
    except Exception:
        pass

    # 6. Total tokens used
    try:
        total_tokens = session.query(func.sum(LLMDecision.tokens_used)).filter(
            LLMDecision.success == True,
            LLMDecision.tokens_used.isnot(None)
        ).scalar() or 0

        yield MetricSample(
            name="freqtrade_llm_total_tokens",
            value=total_tokens,
            description="Total number of tokens consumed by LLM",
            metric_type="counter"
        )
    except Exception:
        pass

    # 7. Statistics by provider
    try:
        provider_stats = session.query(
            LLMDecision.provider,
            func.count(LLMDecision.id).label("count")
        ).filter(
            LLMDecision.success == True
        ).group_by(LLMDecision.provider).all()

        for stat in provider_stats:
            yield MetricSample(
                name="freqtrade_llm_provider_calls",
                value=stat.count,
                description="Number of LLM calls per provider",
                metric_type="counter",
                labels={"provider": stat.provider}
            )
    except Exception:
        pass

    # 8. LLM entry decisions win rate (requires completed trades)
    try:
        # Get trades that were entered by LLM
        llm_entry_trades = session.query(Trade).join(
            LLMDecision,
            (Trade.id == LLMDecision.trade_id) & (LLMDecision.decision_point == "entry")
        ).filter(Trade.is_open == False).all()

        if llm_entry_trades:
            winning_trades = sum(1 for t in llm_entry_trades if (t.close_profit or 0) > 0)
            win_rate = (winning_trades / len(llm_entry_trades)) * 100

            yield MetricSample(
                name="freqtrade_llm_entry_win_rate",
                value=win_rate,
                description="Win rate of trades entered based on LLM decisions (percentage)",
                metric_type="gauge"
            )
    except Exception:
        pass

    # 9. Average response time by provider and model
    try:
        model_stats = session.query(
            LLMDecision.provider,
            LLMDecision.model,
            func.avg(LLMDecision.latency_ms).label("avg_latency")
        ).filter(
            LLMDecision.success == True
        ).group_by(LLMDecision.provider, LLMDecision.model).all()

        for stat in model_stats:
            if stat.avg_latency is not None:
                yield MetricSample(
                    name="freqtrade_llm_model_latency_ms",
                    value=stat.avg_latency,
                    description="Average LLM response latency in milliseconds per provider/model",
                    metric_type="gauge",
                    labels={
                        "provider": stat.provider,
                        "model": stat.model
                    }
                )
    except Exception:
        pass

    # 10. Recent error count (last hour)
    try:
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_errors = session.query(func.count(LLMDecision.id)).filter(
            LLMDecision.created_at >= one_hour_ago,
            LLMDecision.success == False
        ).scalar() or 0

        yield MetricSample(
            name="freqtrade_llm_errors_1h",
            value=recent_errors,
            description="Number of LLM errors in the last hour",
            metric_type="gauge"
        )
    except Exception:
        pass

    # 11. Decision distribution by decision point
    try:
        for decision_point in ["entry", "exit", "stake", "adjust_position", "leverage"]:
            decision_dist = session.query(
                LLMDecision.decision,
                func.count(LLMDecision.id).label("count")
            ).filter(
                LLMDecision.decision_point == decision_point,
                LLMDecision.success == True
            ).group_by(LLMDecision.decision).all()

            for dist in decision_dist:
                yield MetricSample(
                    name="freqtrade_llm_decision_distribution",
                    value=dist.count,
                    description="Distribution of LLM decisions by type",
                    metric_type="counter",
                    labels={
                        "decision_point": decision_point,
                        "decision": dist.decision
                    }
                )
    except Exception:
        pass
