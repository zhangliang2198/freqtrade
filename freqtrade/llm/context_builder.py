"""
Context Builder

Converts market data into LLM-friendly context.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Builds context data for LLM decision making

    Transforms raw market data (dataframes, trade objects, etc.)
    into structured context dictionaries that can be used in prompts.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the context builder

        Args:
            config: Context configuration from llm_config.context
        """
        self.config = config
        self.lookback_candles = config.get("lookback_candles", 100)
        self.include_indicators = config.get("include_indicators", [])
        self.include_orderbook = config.get("include_orderbook", False)
        self.include_recent_trades = config.get("include_recent_trades", False)
        self.include_funding_rate = config.get("include_funding_rate", False)
        self.include_portfolio_state = config.get("include_portfolio_state", False)

    def build_entry_context(
        self,
        dataframe: pd.DataFrame,
        metadata: Dict,
        portfolio_state: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Build context for entry decision

        Args:
            dataframe: Analyzed dataframe with indicators
            metadata: Strategy metadata (pair, etc.)
            portfolio_state: Optional current portfolio state

        Returns:
            Context dictionary for entry decision
        """
        if len(dataframe) == 0:
            raise ValueError("Empty dataframe provided")

        recent_data = dataframe.tail(self.lookback_candles)
        current_candle = dataframe.iloc[-1]

        context = {
            "pair": metadata.get("pair", "UNKNOWN"),
            "current_time": str(current_candle.get("date", datetime.utcnow())),
            "current_candle": self._format_candle(current_candle),
            "market_summary": self._summarize_market(recent_data),
        }

        # Add indicators
        if self.include_indicators:
            context["indicators"] = self._extract_indicators(current_candle)

        # Add recent candles
        if self.include_recent_trades:
            context["recent_candles"] = self._format_recent_candles(recent_data, num=10)

        # Add portfolio state
        if self.include_portfolio_state and portfolio_state:
            context["portfolio"] = portfolio_state

        return context

    def build_exit_context(
        self,
        trade: Any,
        current_rate: float,
        dataframe: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Build context for exit decision

        Args:
            trade: Trade object
            current_rate: Current market rate
            dataframe: Current analyzed dataframe

        Returns:
            Context dictionary for exit decision
        """
        # Calculate current profit
        current_profit_pct = trade.calc_profit_ratio(current_rate) * 100
        current_profit_abs = trade.calc_profit(current_rate)

        # Calculate holding duration
        holding_duration_minutes = (
            (datetime.utcnow() - trade.open_date).total_seconds() / 60
        )

        context = {
            "pair": trade.pair,
            "entry_price": float(trade.open_rate),
            "current_price": float(current_rate),
            "current_profit_pct": float(current_profit_pct),
            "current_profit_abs": float(current_profit_abs),
            "holding_duration_minutes": float(holding_duration_minutes),
            "stop_loss": float(trade.stop_loss),
            "entry_tag": trade.enter_tag,
        }

        # Add optional fields
        if trade.max_rate:
            context["max_rate"] = float(trade.max_rate)
        if trade.min_rate:
            context["min_rate"] = float(trade.min_rate)

        # Add current indicators
        if self.include_indicators and len(dataframe) > 0:
            context["current_indicators"] = self._extract_indicators(dataframe.iloc[-1])

        return context

    def build_stake_context(
        self,
        pair: str,
        current_rate: float,
        dataframe: pd.DataFrame,
        available_balance: float
    ) -> Dict[str, Any]:
        """
        Build context for stake amount decision

        Args:
            pair: Trading pair
            current_rate: Current market rate
            dataframe: Analyzed dataframe
            available_balance: Available balance for trading

        Returns:
            Context dictionary for stake decision
        """
        recent_data = dataframe.tail(self.lookback_candles)

        context = {
            "pair": pair,
            "current_price": float(current_rate),
            "available_balance": float(available_balance),
            "market_summary": self._summarize_market(recent_data),
            "volatility": self._calculate_volatility(dataframe),
        }

        # Add current indicators
        if self.include_indicators and len(dataframe) > 0:
            context["indicators"] = self._extract_indicators(dataframe.iloc[-1])

        return context

    def build_adjust_position_context(
        self,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        dataframe: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Build context for position adjustment decision

        Args:
            trade: Trade object
            current_time: Current timestamp
            current_rate: Current market rate
            current_profit: Current profit ratio
            dataframe: Analyzed dataframe

        Returns:
            Context dictionary for adjustment decision
        """
        holding_duration_minutes = (
            (current_time - trade.open_date).total_seconds() / 60
        )

        recent_data = dataframe.tail(self.lookback_candles)

        context = {
            "pair": trade.pair,
            "current_profit_pct": float(current_profit * 100),
            "current_rate": float(current_rate),
            "entry_rate": float(trade.open_rate),
            "stake_amount": float(trade.stake_amount),
            "holding_duration_minutes": float(holding_duration_minutes),
            "market_summary": self._summarize_market(recent_data),
        }

        # Add indicators
        if self.include_indicators and len(dataframe) > 0:
            context["indicators"] = self._extract_indicators(dataframe.iloc[-1])

        return context

    def build_leverage_context(
        self,
        pair: str,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        dataframe: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Build context for leverage decision

        Args:
            pair: Trading pair
            current_rate: Current market rate
            proposed_leverage: Proposed leverage value
            max_leverage: Maximum allowed leverage
            dataframe: Analyzed dataframe

        Returns:
            Context dictionary for leverage decision
        """
        recent_data = dataframe.tail(self.lookback_candles)

        context = {
            "pair": pair,
            "current_rate": float(current_rate),
            "proposed_leverage": float(proposed_leverage),
            "max_leverage": float(max_leverage),
            "volatility": self._calculate_volatility(dataframe),
            "market_summary": self._summarize_market(recent_data),
        }

        # Add indicators
        if self.include_indicators and len(dataframe) > 0:
            context["indicators"] = self._extract_indicators(dataframe.iloc[-1])

        return context

    def _format_candle(self, row: pd.Series) -> Dict[str, float]:
        """
        Format a single candle into a dictionary

        Args:
            row: DataFrame row representing a candle

        Returns:
            Dictionary with OHLCV data
        """
        return {
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": float(row.get("volume", 0))
        }

    def _summarize_market(self, df: pd.DataFrame) -> str:
        """
        Create a text summary of market conditions

        Args:
            df: DataFrame with candle data

        Returns:
            Human-readable market summary
        """
        if len(df) == 0:
            return "No market data available"

        try:
            first_close = float(df.iloc[0]["close"])
            last_close = float(df.iloc[-1]["close"])
            recent_returns = (last_close / first_close - 1) * 100

            # Determine trend
            if recent_returns > 2:
                trend = "bullish"
            elif recent_returns < -2:
                trend = "bearish"
            else:
                trend = "neutral"

            # Calculate volatility
            volatility = self._calculate_volatility(df)

            return (
                f"Recent {len(df)} candles: {trend} trend, "
                f"{recent_returns:+.2f}% change, "
                f"{volatility:.2f}% volatility"
            )

        except Exception as e:
            logger.warning(f"Failed to summarize market: {e}")
            return "Market data available but summary unavailable"

    def _extract_indicators(self, row: pd.Series) -> Dict[str, Any]:
        """
        Extract technical indicators from a dataframe row

        Args:
            row: DataFrame row with indicator columns

        Returns:
            Dictionary of indicator name -> value
        """
        indicators = {}

        for indicator_name in self.include_indicators:
            if indicator_name in row.index:
                value = row[indicator_name]

                # Handle NaN values
                if pd.isna(value):
                    indicators[indicator_name] = None
                else:
                    indicators[indicator_name] = float(value)

        return indicators

    def _format_recent_candles(self, df: pd.DataFrame, num: int = 10) -> list:
        """
        Format recent candles into a list

        Args:
            df: DataFrame with candle data
            num: Number of recent candles to include

        Returns:
            List of formatted candles
        """
        candles = []
        start_idx = max(0, len(df) - num)

        for i in range(start_idx, len(df)):
            candles.append(self._format_candle(df.iloc[i]))

        return candles

    def _calculate_volatility(self, df: pd.DataFrame, window: int = 20) -> float:
        """
        Calculate price volatility (standard deviation of returns)

        Args:
            df: DataFrame with close prices
            window: Window size for calculation

        Returns:
            Volatility as a percentage
        """
        try:
            if len(df) < 2:
                return 0.0

            # Calculate returns
            returns = df["close"].pct_change().dropna()

            if len(returns) == 0:
                return 0.0

            # Use rolling window if enough data
            if len(returns) > window:
                volatility = returns.tail(window).std()
            else:
                volatility = returns.std()

            return float(volatility * 100)

        except Exception as e:
            logger.warning(f"Failed to calculate volatility: {e}")
            return 0.0
