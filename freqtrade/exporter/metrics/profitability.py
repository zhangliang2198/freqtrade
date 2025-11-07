from __future__ import annotations

from typing import Iterable

from .base import MetricSample


def collect(api, _: float) -> Iterable[MetricSample]:
    data = api.get("/profit", default={}) or {}
    if not isinstance(data, dict):
        return []

    mappings = [
        (
            "freqtrade_profit_closed_coin",
            "profit_closed_coin",
            "已平仓交易累计收益（仓位货币）。",
        ),
        (
            "freqtrade_profit_closed_percent",
            "profit_closed_percent",
            "已平仓交易收益率（基于初始资金）。",
        ),
        (
            "freqtrade_profit_closed_percent_mean",
            "profit_closed_percent_mean",
            "已平仓交易平均收益率百分比。",
        ),
        (
            "freqtrade_profit_closed_percent_sum",
            "profit_closed_percent_sum",
            "已平仓交易收益率百分比总和。",
        ),
        (
            "freqtrade_profit_closed_fiat",
            "profit_closed_fiat",
            "已平仓交易折算法币的收益。",
        ),
        (
            "freqtrade_profit_all_coin",
            "profit_all_coin",
            "总体收益（含未平仓交易，仓位货币）。",
        ),
        (
            "freqtrade_profit_all_percent",
            "profit_all_percent",
            "总体收益率（基于初始资金）。",
        ),
        (
            "freqtrade_profit_all_percent_mean",
            "profit_all_percent_mean",
            "总体平均收益率百分比。",
        ),
        (
            "freqtrade_profit_all_percent_sum",
            "profit_all_percent_sum",
            "总体收益率百分比总和。",
        ),
        (
            "freqtrade_profit_all_fiat",
            "profit_all_fiat",
            "总体收益折算法币。",
        ),
        (
            "freqtrade_profit_factor",
            "profit_factor",
            "收益因子（盈利额 / 亏损额）。",
        ),
        (
            "freqtrade_profit_winrate",
            "winrate",
            "已平仓交易胜率（比例）。",
        ),
        (
            "freqtrade_profit_expectancy",
            "expectancy",
            "单笔交易的期望收益（仓位货币）。",
        ),
        (
            "freqtrade_profit_expectancy_ratio",
            "expectancy_ratio",
            "交易期望收益率。",
        ),
        (
            "freqtrade_profit_max_drawdown",
            "max_drawdown",
            "历史最大回撤（相对值）。",
        ),
        (
            "freqtrade_profit_max_drawdown_abs",
            "max_drawdown_abs",
            "历史最大回撤（仓位货币）。",
        ),
        (
            "freqtrade_profit_current_drawdown",
            "current_drawdown",
            "当前回撤（相对值）。",
        ),
        (
            "freqtrade_profit_current_drawdown_abs",
            "current_drawdown_abs",
            "当前回撤（仓位货币）。",
        ),
        (
            "freqtrade_profit_trading_volume",
            "trading_volume",
            "统计区间内的成交量。",
        ),
        (
            "freqtrade_profit_trade_count",
            "trade_count",
            "参与统计的交易总数。",
        ),
        (
            "freqtrade_profit_closed_trade_count",
            "closed_trade_count",
            "统计区间内已平仓交易数。",
        ),
        (
            "freqtrade_profit_winning_trades",
            "winning_trades",
            "盈利交易数量。",
        ),
        (
            "freqtrade_profit_losing_trades",
            "losing_trades",
            "亏损交易数量。",
        ),
        (
            "freqtrade_profit_bot_start_timestamp",
            "bot_start_timestamp",
            "计算统计时机器人启动的 Unix 时间戳。",
        ),
        (
            "freqtrade_profit_first_trade_timestamp",
            "first_trade_timestamp",
            "统计区间内第一笔交易的 Unix 时间戳。",
        ),
        (
            "freqtrade_profit_latest_trade_timestamp",
            "latest_trade_timestamp",
            "统计区间内最近一笔交易的 Unix 时间戳。",
        ),
        (
            "freqtrade_profit_max_drawdown_start_timestamp",
            "max_drawdown_start_timestamp",
            "最大回撤开始的时间戳。",
        ),
        (
            "freqtrade_profit_max_drawdown_end_timestamp",
            "max_drawdown_end_timestamp",
            "最大回撤结束的时间戳。",
        ),
        (
            "freqtrade_profit_current_drawdown_start_timestamp",
            "current_drawdown_start_timestamp",
            "当前回撤开始的时间戳。",
        ),
    ]

    samples = [
        MetricSample(
            metric_name,
            data.get(source_key),
            description,
        )
        for metric_name, source_key, description in mappings
    ]

    return samples
