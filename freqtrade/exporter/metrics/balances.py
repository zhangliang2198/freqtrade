from __future__ import annotations

from typing import Iterable

from .base import MetricSample, to_lower_bool


def _summary_metrics(data: dict) -> list[MetricSample]:
    samples: list[MetricSample] = []
    samples.append(
        MetricSample(
            "freqtrade_balance_total_stake",
            data.get("total"),
            "折算为仓位货币的账户总估值。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_total_bot",
            data.get("total_bot"),
            "机器人实际占用的仓位货币总额。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_fiat_value",
            data.get("value"),
            "折算为法币的账户总估值。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_fiat_value_bot",
            data.get("value_bot"),
            "机器人管理资产折算为法币的估值。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_starting_capital",
            data.get("starting_capital"),
            "机器人配置的初始资金（仓位货币）。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_starting_capital_ratio",
            data.get("starting_capital_ratio"),
            "机器人当前资产与初始资金的比值。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_starting_capital_fiat",
            data.get("starting_capital_fiat"),
            "初始资金折算为法币。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_starting_capital_fiat_ratio",
            data.get("starting_capital_fiat_ratio"),
            "当前法币估值与初始法币资金的比值。",
        )
    )
    samples.append(
        MetricSample(
            "freqtrade_balance_trade_history_count",
            data.get("trade_count"),
            "数据库中记录的交易总数。",
        )
    )
    return samples


def _per_currency_metrics(data: dict) -> list[MetricSample]:
    currencies = data.get("currencies") or []
    if not isinstance(currencies, list):
        return []

    samples: list[MetricSample] = []
    for entry in currencies:
        if not isinstance(entry, dict):
            continue
        labels = {
            "currency": str(entry.get("currency", "")),
            "stake": str(entry.get("stake", "")),
            "side": str(entry.get("side", "")),
            "is_bot_managed": to_lower_bool(entry.get("is_bot_managed")),
            "is_position": to_lower_bool(entry.get("is_position")),
        }
        samples.append(
            MetricSample(
                "freqtrade_currency_free",
                entry.get("free"),
                "交易所当前可用的币种余额。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_currency_balance",
                entry.get("balance"),
                "交易所账户该币种总余额。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_currency_used",
                entry.get("used"),
                "挂单中占用的币种数量。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_currency_bot_owned",
                entry.get("bot_owned"),
                "机器人仓位占用的币种数量。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_currency_est_stake",
                entry.get("est_stake"),
                "该资产折算为仓位货币的估值。",
                labels=labels,
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_currency_est_stake_bot",
                entry.get("est_stake_bot"),
                "机器人管理的资产折算为仓位货币的估值。",
                labels=labels,
            )
        )
        position = entry.get("position")
        if position is not None:
            samples.append(
                MetricSample(
                    "freqtrade_currency_position",
                    position,
                    "合约模式下的持仓数量（若适用）。",
                    labels=labels,
                )
            )
    return samples


def collect(api, _: float) -> Iterable[MetricSample]:
    """采集账户余额及资产分布指标。"""
    data = api.get("/balance", default={}) or {}
    if not isinstance(data, dict):
        return []
    samples: list[MetricSample] = []
    samples.extend(_summary_metrics(data))
    samples.extend(_per_currency_metrics(data))
    return samples
