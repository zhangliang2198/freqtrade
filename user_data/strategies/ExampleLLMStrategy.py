"""
Example LLM-Assisted Trading Strategy

This is an example strategy that uses LLM for all trading decisions.
It serves as a template for creating your own LLM-powered strategies.
"""

import pandas as pd
import talib.abstract as ta

from freqtrade.strategy.LLMStrategy import LLMStrategy


class ExampleLLMStrategy(LLMStrategy):
    """
    Example LLM-Assisted Strategy

    This strategy demonstrates how to use the LLM integration for trading.
    It calculates common technical indicators and lets the LLM make all
    trading decisions based on those indicators.

    To use this strategy:
    1. Configure LLM settings in your config.json (see config_examples/config_llm.example.json)
    2. Set your API key as an environment variable
    3. Run: freqtrade trade -c config.json --strategy ExampleLLMStrategy
    """

    # Strategy interface version
    INTERFACE_VERSION = 3

    # Basic strategy parameters
    timeframe = "5m"

    # Risk management
    stoploss = -0.10
    trailing_stop = False
    use_custom_stoploss = False

    # ROI table (fallback if LLM doesn't exit)
    minimal_roi = {
        "0": 0.10,      # 10% profit
        "30": 0.05,     # 5% profit after 30 minutes
        "60": 0.03,     # 3% profit after 1 hour
        "120": 0.01     # 1% profit after 2 hours
    }

    # Enable position adjustment (DCA/pyramiding)
    position_adjustment_enable = True
    max_entry_position_adjustment = 3

    # Startup candle count (for indicator calculation)
    startup_candle_count = 100

    # Enable shorting if your exchange supports it
    can_short = False

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        Calculate technical indicators

        The LLM will use these indicators to make trading decisions.
        Add or remove indicators based on your trading style.

        Args:
            dataframe: OHLCV data
            metadata: Strategy metadata (pair, timeframe, etc.)

        Returns:
            Dataframe with indicators added
        """
        # RSI (Relative Strength Index)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD (Moving Average Convergence Divergence)
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # Bollinger Bands
        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2, nbdevdn=2)
        dataframe["bb_lower"] = bollinger["lowerband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_upper"] = bollinger["upperband"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_middle"]

        # EMAs (Exponential Moving Averages)
        dataframe["ema_9"] = ta.EMA(dataframe, timeperiod=9)
        dataframe["ema_21"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)

        # Volume indicators
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_mean"]

        # ATR (Average True Range) for volatility
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # Trend indicators
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # Stochastic
        stoch = ta.STOCH(dataframe)
        dataframe["slowk"] = stoch["slowk"]
        dataframe["slowd"] = stoch["slowd"]

        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        We use custom_exit for LLM-based exits, so this is not needed.
        """
        return dataframe

    # Optional: Override fallback methods for non-LLM behavior

    def _populate_entry_trend_fallback(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        Fallback entry logic when LLM is not available

        This is a simple example using RSI and MACD.
        Feel free to customize or remove this.
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
        Fallback exit logic when LLM is not available

        Simple profit target example.
        """
        # Take profit at 5%
        if current_profit > 0.05:
            return "profit_target_5pct"

        # Stop loss at -8%
        if current_profit < -0.08:
            return "stop_loss_8pct"

        return None
