from datetime import datetime
from typing import Optional
import pandas as pd
import talib.abstract as ta

from freqtrade.strategy.LLMStrategy import LLMStrategy

class ExampleLLMStrategy(LLMStrategy):
    # 策略接口版本
    INTERFACE_VERSION = 3

    # 基本策略参数
    timeframe = "15m"

    # 启动K线数量 (用于指标计算)
    startup_candle_count = 100

    # 如果您的交易所支持，启用做空
    can_short = True

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
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