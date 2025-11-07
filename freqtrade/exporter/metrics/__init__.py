from __future__ import annotations

from typing import Iterable, Protocol

from .base import MetricSample
from . import (
    balances,
    llm,
    locks,
    pairlists,
    performance,
    profitability,
    stats,
    system,
    tags,
    timeprofits,
    trades,
)


class Collector(Protocol):
    def __call__(self, api, now: float) -> Iterable[MetricSample]:
        ...


COLLECTORS: tuple[Collector, ...] = (
    system.collect,
    balances.collect,
    trades.collect,
    profitability.collect,
    performance.collect,
    locks.collect,
    stats.collect,
    tags.collect,
    timeprofits.collect,
    pairlists.collect,
    llm.collect,
)


def collect_all(api, now: float) -> Iterable[MetricSample]:
    """依次执行所有采集器并合并返回结果。"""
    for collector in COLLECTORS:
        yield from collector(api, now)
