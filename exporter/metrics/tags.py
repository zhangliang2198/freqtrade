from __future__ import annotations

from typing import Iterable

from .base import MetricSample


def _collect_entries(api) -> list[MetricSample]:
    data = api.get("/entries", default=[]) or []
    if not isinstance(data, list):
        return []
    samples: list[MetricSample] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        tag = str(entry.get("enter_tag", ""))
        labels = {"enter_tag": tag}
        samples.append(
            MetricSample(
                "freqtrade_enter_tag_profit_ratio",
                entry.get("profit_ratio"),
                "买入标签对应的平均收益率。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_enter_tag_profit_abs",
                entry.get("profit_abs"),
                "买入标签对应的收益总额（仓位货币）。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_enter_tag_trades_total",
                entry.get("count"),
                "买入标签对应的成交次数。",
                labels=labels,
            )
        )
    return samples


def _collect_exits(api) -> list[MetricSample]:
    data = api.get("/exits", default=[]) or []
    if not isinstance(data, list):
        return []

    samples: list[MetricSample] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        reason = str(entry.get("exit_reason", ""))
        labels = {"exit_reason": reason}
        samples.append(
            MetricSample(
                "freqtrade_exit_reason_profit_ratio",
                entry.get("profit_ratio"),
                "卖出原因对应的平均收益率。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_exit_reason_profit_abs",
                entry.get("profit_abs"),
                "卖出原因对应的收益总额（仓位货币）。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_exit_reason_trades_total",
                entry.get("count"),
                "卖出原因对应的成交次数。",
                labels=labels,
            )
        )
    return samples


def _collect_mix_tags(api) -> list[MetricSample]:
    data = api.get("/mix_tags", default=[]) or []
    if not isinstance(data, list):
        return []

    samples: list[MetricSample] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        labels = {
            "enter_tag": str(entry.get("enter_tag", "")),
            "exit_reason": str(entry.get("exit_reason", "")),
        }
        samples.append(
            MetricSample(
                "freqtrade_mix_tag_profit_ratio",
                entry.get("profit_ratio"),
                "买入标签与卖出原因组合的平均收益率。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_mix_tag_profit_abs",
                entry.get("profit_abs"),
                "买入标签与卖出原因组合的收益总额（仓位货币）。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_mix_tag_trades_total",
                entry.get("count"),
                "买入标签与卖出原因组合的成交次数。",
                labels=labels,
            )
        )
    return samples


def collect(api, _: float) -> Iterable[MetricSample]:
    samples: list[MetricSample] = []
    samples.extend(_collect_entries(api))
    samples.extend(_collect_exits(api))
    samples.extend(_collect_mix_tags(api))
    return samples
