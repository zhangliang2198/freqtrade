import pandas as pd
import talib.abstract as ta

from freqtrade.strategy import merge_informative_pair
from freqtrade.strategy.LLMStrategy import LLMStrategy

class ExampleLLMStrategy(LLMStrategy):
    # 策略接口版本
    INTERFACE_VERSION = 3

    # 基本策略参数
    timeframe = "15m"

    # 启动K线数量 (用于指标计算)
    startup_candle_count = 100

    # 如果您的交易所支持,启用做空
    can_short = True

    def informative_pairs(self):
        """
        定义额外的信息对和时间框架
        添加 8 小时级别的数据作为参考
        """
        pairs = self.dp.current_whitelist()
        informative_pairs = [(pair, "8h") for pair in pairs]
        return informative_pairs

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # 获取 8 小时级别的数据
        if self.dp:
            informative_8h = self.dp.get_pair_dataframe(pair=metadata['pair'], timeframe='8h')

            # 计算 8 小时级别的指标（merge_informative_pair 会自动添加 _8h 后缀）
            informative_8h['rsi'] = ta.RSI(informative_8h, timeperiod=14)
            informative_8h['ema_21'] = ta.EMA(informative_8h, timeperiod=21)
            informative_8h['ema_50'] = ta.EMA(informative_8h, timeperiod=50)

            # MACD 8小时
            macd_8h = ta.MACD(informative_8h)
            informative_8h['macd'] = macd_8h['macd']
            informative_8h['macdsignal'] = macd_8h['macdsignal']

            # ATR 8小时
            informative_8h['atr'] = ta.ATR(informative_8h, timeperiod=14)

            # ADX 8小时 (趋势强度)
            informative_8h['adx'] = ta.ADX(informative_8h, timeperiod=14)

            # 合并到主时间框架（会自动添加 _8h 后缀，如 rsi_8h, ema_21_8h 等）
            dataframe = merge_informative_pair(
                dataframe,
                informative_8h,
                self.timeframe,
                '8h',
                ffill=True,
            )

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
