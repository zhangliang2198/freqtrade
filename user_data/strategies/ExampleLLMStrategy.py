"""
示例 LLM 辅助交易策略。

这是一个使用 LLM 进行所有交易决策的示例策略。
它作为创建您自己的 LLM 驱动策略的模板。
"""

from datetime import datetime
from typing import Optional
import pandas as pd
import talib.abstract as ta

from freqtrade.strategy.LLMStrategy import LLMStrategy


class ExampleLLMStrategy(LLMStrategy):
    """
    示例 LLM 辅助策略

    此策略演示如何使用 LLM 集成进行交易。
    它计算常见的技术指标，并让 LLM 基于这些指标做出所有
    交易决策。

    使用此策略：
    1. 在您的 config.json 中配置 LLM 设置 (参见 config_examples/config_llm.example.json)
    2. 将您的 API 密钥设置为环境变量
    3. 运行: freqtrade trade -c config.json --strategy ExampleLLMStrategy
    """

    # 策略接口版本
    INTERFACE_VERSION = 3

    # 基本策略参数
    timeframe = "5m"

    # 风险管理
    stoploss = -0.10
    trailing_stop = False
    use_custom_stoploss = False

    # ROI 表 (如果 LLM 不出场则使用)
    minimal_roi = {
        "0": 0.10,      # 10% 利润
        "30": 0.05,     # 30分钟后 5% 利润
        "60": 0.03,     # 1小时后 3% 利润
        "120": 0.01     # 2小时后 1% 利润
    }

    # 启用仓位调整 (DCA/金字塔)
    position_adjustment_enable = True
    max_entry_position_adjustment = 3

    # 启动K线数量 (用于指标计算)
    startup_candle_count = 100

    # 如果您的交易所支持，启用做空
    can_short = False

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        计算技术指标

        LLM 将使用这些指标做出交易决策。
        根据您的交易风格添加或移除指标。

        Args:
            dataframe: OHLCV 数据
            metadata: 策略元数据 (交易对、时间框架等)

        Returns:
            添加了指标的数据框
        """
        # RSI (相对强弱指数)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD (移动平均收敛发散)
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # 布林带
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_lower"] = bollinger["lowerband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]

        # EMAs (指数移动平均线)
        dataframe["ema_9"] = ta.EMA(dataframe, timeperiod=9)
        dataframe["ema_21"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)

        # 成交量指标
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_mean"]

        # ATR (平均真实波幅) 用于波动性
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # 趋势指标
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # 随机指标
        stoch = ta.STOCH(dataframe)
        dataframe["slowk"] = stoch["slowk"]
        dataframe["slowd"] = stoch["slowd"]

        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        我们使用 custom_exit 进行基于 LLM 的出场，所以这里不需要。
        """
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
        desired_stake = super().custom_stake_amount(
            pair, current_time, current_rate, proposed_stake, max_stake, leverage, entry_tag, side, **kwargs
        )

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