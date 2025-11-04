"""
示例 LLM 辅助交易策略。

这是一个使用 LLM 进行所有交易决策的示例策略。
它作为创建您自己的 LLM 驱动策略的模板。
"""

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

    # 可选: 覆盖回退方法以实现非 LLM 行为

    def _populate_entry_trend_fallback(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        LLM 不可用时的回退入场逻辑

        这是一个使用 RSI 和 MACD 的简单示例。
        随意自定义或移除此部分。
        """
        dataframe.loc[
            (
                (dataframe["rsi"] < 30) &
                (dataframe["macd"] > dataframe["macdsignal"]) &
                (dataframe["volume"] > 0)
            ),
            "enter_long"
        ] = 1

        return dataframe

    def _custom_exit_fallback(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float
    ):
        """
        LLM 不可用时的回退出场逻辑

        简单的利润目标示例。
        """
        # 在 5% 时止盈
        if current_profit > 0.05:
            return "profit_target_5pct"

        # 在 -8% 时止损
        if current_profit < -0.08:
            return "stop_loss_8pct"

        return None
