from __future__ import annotations

import math
from typing import Iterable, List

from .base import MetricSample, to_lower_bool


def _safe_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _aggregate(trades: List[dict]) -> List[MetricSample]:
    samples: list[MetricSample] = [
        MetricSample(
            "freqtrade_open_trades_total",
            len(trades),
            "当前未平仓交易的数量。",
        )
    ]

    profit_abs_values = [_safe_float(trade.get("profit_abs")) for trade in trades]
    total_profit_abs_values = [_safe_float(trade.get("total_profit_abs")) for trade in trades]
    profit_ratio_values = [_safe_float(trade.get("profit_ratio")) for trade in trades]
    total_profit_ratio_values = [_safe_float(trade.get("total_profit_ratio")) for trade in trades]
    stake_values = [_safe_float(trade.get("stake_amount")) for trade in trades]
    open_trade_values = [_safe_float(trade.get("open_trade_value")) for trade in trades]

    def _sum(values):
        return sum(v for v in values if v is not None)

    def _avg(values):
        filtered = [v for v in values if v is not None]
        if not filtered:
            return None
        return sum(filtered) / len(filtered)

    samples.append(
        MetricSample(
            "freqtrade_open_trades_profit_abs_sum",
            _sum(profit_abs_values),
            "所有未平仓交易的收益和（仓位货币）。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_open_trades_profit_ratio_sum",
            _sum(profit_ratio_values),
            "所有未平仓交易的收益率总和。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_open_trades_profit_ratio_avg",
            _avg(profit_ratio_values),
            "未平仓交易的平均收益率。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_open_trades_total_profit_abs_sum",
            _sum(total_profit_abs_values),
            "未平仓交易包含部分平仓后的总收益。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_open_trades_total_profit_ratio_sum",
            _sum(total_profit_ratio_values),
            "未平仓交易包含部分平仓后的总收益率。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_open_trades_stake_amount_sum",
            _sum(stake_values),
            "未平仓交易占用的总仓位。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_open_trades_value_sum",
            _sum(open_trade_values),
            "未平仓交易当前估值总和（仓位货币）。",
        )
    )
    return samples


def _per_trade(trade: dict, now: float) -> List[MetricSample]:
    labels = {
        "pair": str(trade.get("pair", "")),
        "trade_id": str(trade.get("trade_id", "")),
        "strategy": str(trade.get("strategy", "")),
        "is_short": to_lower_bool(trade.get("is_short")),
    }

    samples: list[MetricSample] = [
        MetricSample(
            "freqtrade_trade_stake_amount",
            trade.get("stake_amount"),
            "该笔交易初始投入的仓位数量。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_open_value",
            trade.get("open_trade_value"),
            "建仓时的名义价值。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_current_rate",
            trade.get("current_rate"),
            "用于收益计算的最新市场价格。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_open_rate",
            trade.get("open_rate"),
            "交易的平均开仓价格。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_profit_ratio",
            trade.get("profit_ratio"),
            "当前收益率。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_profit_abs",
            trade.get("profit_abs"),
            "当前收益（仓位货币）。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_total_profit_ratio",
            trade.get("total_profit_ratio"),
            "累计收益率（含分批平仓）。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_total_profit_abs",
            trade.get("total_profit_abs"),
            "累计收益（含分批平仓）。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_stoploss_distance_ratio",
            trade.get("stoploss_current_dist_ratio"),
            "价格距离止损的比率。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_stoploss_distance_pct",
            trade.get("stoploss_current_dist_pct"),
            "价格距离止损的百分比。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_stoploss_entry_distance_ratio",
            trade.get("stoploss_entry_dist_ratio"),
            "入场价与止损价之间的比率差距。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_stoploss_entry_distance",
            trade.get("stoploss_entry_dist"),
            "入场价与止损价之间的价差（仓位货币）。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_successful_entries",
            trade.get("nr_of_successful_entries"),
            "已成交的加仓次数。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_leverage",
            trade.get("leverage"),
            "当前使用的杠杆倍数（现货为 1）。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_liquidation_price",
            trade.get("liquidation_price"),
            "交易所给出的强平价格（如适用）。",
            labels=labels,
        ),
        MetricSample(
            "freqtrade_trade_has_open_orders",
            trade.get("has_open_orders"),
            "该交易是否仍有挂单未成交。",
            labels=labels,
        ),
    ]

    open_timestamp = _safe_float(trade.get("open_timestamp"))
    if open_timestamp is not None:
        samples.append(
            MetricSample(
                "freqtrade_trade_duration_seconds",
                max(now - open_timestamp, 0.0),
                "该笔交易已运行的秒数。",
                labels=labels,
            )
        )

    return samples


def collect(api, now: float) -> Iterable[MetricSample]:
    trades = api.get("/status", default=[]) or []
    if not isinstance(trades, list):
        trades = []

    samples: list[MetricSample] = []
    samples.extend(_aggregate(trades))
    for trade in trades:
        if isinstance(trade, dict):
            samples.extend(_per_trade(trade, now))

    count_data = api.get("/count", default={}) or {}
    if isinstance(count_data, dict):
        samples.append(
            MetricSample(
                "freqtrade_trade_slots_used",
                count_data.get("current"),
                "当前已占用的交易槽位数量。",
            )
        )
        max_slots = count_data.get("max")
        samples.append(
            MetricSample(
                "freqtrade_trade_slots_max",
                max_slots,
                "允许的最大持仓数（-1 代表无限制）。",
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_trade_open_stake",
                count_data.get("total_stake"),
                "当前未平仓交易占用的总仓位。",
            )
        )

    return samples
