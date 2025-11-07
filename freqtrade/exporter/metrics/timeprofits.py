from __future__ import annotations

from typing import Iterable, List

from .base import MetricSample


def _collect(api, endpoint: str, timeunit: str) -> List[MetricSample]:
    data = api.get(endpoint, default={}) or {}
    records = data.get("data") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return []

    samples: list[MetricSample] = []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        date_str = str(entry.get("date", ""))
        labels = {"timeunit": timeunit, "date": date_str}
        samples.append(
            MetricSample(
                "freqtrade_timeunit_profit_abs",
                entry.get("abs_profit"),
                "按时间粒度统计的收益（仓位货币）。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_timeunit_profit_rel",
                entry.get("rel_profit"),
                "按时间粒度统计的收益率。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_timeunit_starting_balance",
                entry.get("starting_balance"),
                "统计时段起始资金（仓位货币）。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_timeunit_trade_count",
                entry.get("trade_count"),
                "统计时段内的成交笔数。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_timeunit_profit_fiat",
                entry.get("fiat_value"),
                "按时间粒度统计的收益（折算法币）。",
                labels=labels,
            )
        )
    return samples


def collect(api, _: float) -> Iterable[MetricSample]:
    samples: list[MetricSample] = []
    samples.extend(_collect(api, "/daily?timescale=7", "daily"))
    samples.extend(_collect(api, "/weekly?timescale=4", "weekly"))
    samples.extend(_collect(api, "/monthly?timescale=3", "monthly"))
    return samples
