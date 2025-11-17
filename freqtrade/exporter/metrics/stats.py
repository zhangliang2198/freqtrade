from __future__ import annotations

from typing import Iterable

from .base import MetricSample


def collect(api, _: float) -> Iterable[MetricSample]:
    data = api.get("/stats", default={}) or {}
    if not isinstance(data, dict):
        return []

    samples: list[MetricSample] = []
    durations = data.get("durations") or {}
    if isinstance(durations, dict):
        for outcome in ("wins", "draws", "losses"):
            value = durations.get(outcome)
            if value is not None:
                samples.append(
                    MetricSample(
                        "freqtrade_trade_duration_seconds_avg",
                        value,
                        "不同结果类型的平均持仓时长（秒）。",
                        labels={"outcome": outcome},
                    )
                )

    exit_reasons = data.get("exit_reasons") or {}
    if isinstance(exit_reasons, dict):
        for reason, counts in exit_reasons.items():
            if not isinstance(counts, dict):
                continue
            for outcome, value in counts.items():
                samples.append(
                    MetricSample(
                        "freqtrade_exit_reason_trades_total",
                        value,
                        "各退出原因在不同结果类型下的成交次数。",
                        labels={"reason": str(reason), "outcome": str(outcome)},
                    )
                )

    return samples
