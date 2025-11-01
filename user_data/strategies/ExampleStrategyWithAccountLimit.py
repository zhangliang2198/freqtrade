"""
带账户资金限制的策略示例
演示如何使用 BaseStrategyWithSnapshot 的资金分离功能
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from freqtrade.strategy import DecimalParameter

from user_data.strategies.BaseStrategyWithSnapshot import BaseStrategyWithSnapshot


class ExampleStrategyWithAccountLimit(BaseStrategyWithSnapshot):
    """
    示例策略：演示如何使用账户资金限制

    配置示例（在 config.json 中添加）:
    {
        "strategy_account": {
            "enabled": true,
            "long_initial_balance": 2000,
            "short_initial_balance": 2000,
        },
        "strategy_snapshot": {
            "enabled": true,
            "enable_detailed_logs": true,
            "enable_strategy_logs": true
        }
    }
    """

    can_short = True
    timeframe = "1h"

    # 示例参数
    buy_rsi = DecimalParameter(20, 40, default=30, space="buy")
    sell_rsi = DecimalParameter(60, 80, default=70, space="sell")

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # 添加指标
        import talib.abstract as ta

        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # 做多条件
        dataframe.loc[
            (dataframe['rsi'] < self.buy_rsi.value),
            'enter_long'
        ] = 1

        # 做空条件
        dataframe.loc[
            (dataframe['rsi'] > self.sell_rsi.value),
            'enter_short'
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        控制开仓金额，并应用账户资金限制

        这是关键方法：在这里调用基类的 check_account_balance_limit 来限制各账户的资金使用
        """
        # 示例：每次固定开仓 100 USDT
        desired_stake = 100.0

        # 检查账户余额限制（如果启用了严格模式）
        allowed, adjusted_stake = self.check_account_balance_limit(
            side=side,
            proposed_stake=desired_stake,
            pair=pair
        )

        if not allowed:
            # 账户余额不足，不允许开仓
            return 0.0

        # 返回调整后的金额（如果没超限，就是原金额）
        return min(adjusted_stake, max_stake)

    # ========== 可选：添加策略特定的日志 ==========

    def log_strategy_specific_info(
        self, current_time: datetime, asset_data: dict, **kwargs
    ) -> None:
        """记录策略特定的信息"""
        import logging
        logger = logging.getLogger(__name__)

        logger.info("🎯 【示例策略信息】")
        logger.info(f"  RSI 买入阈值: {float(self.buy_rsi.value):.1f}")
        logger.info(f"  RSI 卖出阈值: {float(self.sell_rsi.value):.1f}")

        # 显示各账户可用余额
        if self.strict_account_mode:
            long_available = self.get_account_available_balance("long")
            short_available = self.get_account_available_balance("short")
            logger.info(f"  📊 Long 账户可用余额: {long_available:.2f} USDT")
            logger.info(f"  📊 Short 账户可用余额: {short_available:.2f} USDT")

        logger.info("=" * 80)

    def get_extra_snapshot_data(self, asset_data: dict) -> Optional[dict]:
        """保存策略特定的参数到数据库"""
        data = {
            'buy_rsi': float(self.buy_rsi.value),
            'sell_rsi': float(self.sell_rsi.value),
        }

        # 如果启用了严格模式，也保存各账户可用余额
        if self.strict_account_mode:
            data['long_available'] = self.get_account_available_balance("long")
            data['short_available'] = self.get_account_available_balance("short")

        return data
