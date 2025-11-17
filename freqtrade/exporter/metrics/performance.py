from __future__ import annotations

from typing import Iterable

from .base import MetricSample


def collect(api, _: float) -> Iterable[MetricSample]:
    data = api.get("/performance", default=[]) or []
    if not isinstance(data, list):
        return []

    samples: list[MetricSample] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        pair = str(entry.get("pair", ""))
        labels = {"pair": pair}
        samples.append(
            MetricSample(
                "freqtrade_pair_profit_ratio",
                entry.get("profit_ratio"),
                "该交易对每笔已平仓交易的平均收益率。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_pair_profit_percent",
                entry.get("profit_pct"),
                "该交易对每笔已平仓交易的平均收益率百分比。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_pair_profit_abs",
                entry.get("profit_abs"),
                "该交易对累积收益（仓位货币）。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_pair_trade_count",
                entry.get("count"),
                "该交易对参与统计的已平仓交易数量。",
                labels=labels,
            )
        )

    return samples
