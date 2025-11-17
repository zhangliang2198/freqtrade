from __future__ import annotations

from typing import Iterable

from .base import MetricSample


def _ms_to_seconds(value) -> float | None:
    if value is None:
        return None
    try:
        result = float(value) / 1000.0
    except (TypeError, ValueError):
        return None
    return result


def collect(api, _: float) -> Iterable[MetricSample]:
    data = api.get("/locks", default={"lock_count": 0, "locks": []}) or {}
    if not isinstance(data, dict):
        return []

    samples: list[MetricSample] = []
    samples.append(
        MetricSample(
            "freqtrade_locks_total",
            data.get("lock_count"),
            "当前生效的交易对锁定数量。",
        )
    )

    locks = data.get("locks") or []
    if not isinstance(locks, list):
        return samples

    for entry in locks:
        if not isinstance(entry, dict):
            continue
        labels = {
            "pair": str(entry.get("pair", "")),
            "reason": str(entry.get("reason", "")),
            "side": str(entry.get("side", "")),
        }
        samples.append(
            MetricSample(
                "freqtrade_lock_active",
                entry.get("active"),
                "该锁定是否处于激活状态。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_lock_start_timestamp",
                _ms_to_seconds(entry.get("lock_timestamp")),
                "锁定创建时的 Unix 时间戳（秒）。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_lock_end_timestamp",
                _ms_to_seconds(entry.get("lock_end_timestamp")),
                "锁定失效的 Unix 时间戳（秒）。",
                labels=labels,
            )
        )
    return samples
