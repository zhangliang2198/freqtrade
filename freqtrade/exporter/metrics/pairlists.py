from __future__ import annotations

from typing import Iterable

from .base import MetricSample


def _collect_pairs(data: dict, metric_prefix: str, list_key: str, label_desc: str) -> list[MetricSample]:
    pairs = data.get(list_key) or []
    if not isinstance(pairs, list):
        return []

    samples: list[MetricSample] = [
        MetricSample(
            f"{metric_prefix}_total",
            len(pairs),
            f"{label_desc} 列表中的交易对数量。",
        )
    ]
    for pair in pairs:
        samples.append(
            MetricSample(
                f"{metric_prefix}_present",
                1,
                f"{label_desc} 列表中存在的交易对标记。",
                labels={"pair": str(pair)},
            )
        )
    return samples


def collect(api, _: float) -> Iterable[MetricSample]:
    samples: list[MetricSample] = []

    whitelist_data = api.get("/whitelist", default={}) or {}
    if isinstance(whitelist_data, dict):
        samples.extend(_collect_pairs(whitelist_data, "freqtrade_whitelist", "whitelist", "白名单"))

    blacklist_data = api.get("/blacklist", default={}) or {}
    if isinstance(blacklist_data, dict):
        samples.extend(_collect_pairs(blacklist_data, "freqtrade_blacklist", "blacklist", "黑名单"))
        expanded = blacklist_data.get("blacklist_expanded")
        if isinstance(expanded, list):
            samples.append(
                MetricSample(
                    "freqtrade_blacklist_expanded_total",
                    len(expanded),
                    "黑名单在交易所映射后的实际交易对数量。",
                )
            )

    return samples
