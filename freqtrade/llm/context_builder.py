"""
上下文构建器

将市场数据转换为适合LLM使用的上下文。
"""

from typing import Dict, Any, Optional
from datetime import datetime
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    为LLM决策构建上下文数据

    将原始市场数据（数据框、交易对象等）
    转换为可在提示中使用的结构化上下文字典。
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化上下文构建器

        Args:
            config: 来自llm_config.context的上下文配置
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
        构建入场决策的上下文

        Args:
            dataframe: 包含指标的分析数据框
            metadata: 策略元数据（交易对等）
            portfolio_state: 可选的当前投资组合状态

        Returns:
            入场决策的上下文字典
        """
        if len(dataframe) == 0:
            raise ValueError("提供了空的数据框")

        recent_data = dataframe.tail(self.lookback_candles)
        current_candle = dataframe.iloc[-1]

        context = {
            "pair": metadata.get("pair", "UNKNOWN"),
            "current_time": str(current_candle.get("date", datetime.utcnow())),
            "current_candle": self._format_candle(current_candle),
            "market_summary": self._summarize_market(recent_data),
        }

        # 添加指标
        if self.include_indicators:
            context["indicators"] = self._extract_indicators(current_candle)

        # 添加最近的K线
        if self.include_recent_trades:
            context["recent_candles"] = self._format_recent_candles(recent_data, num=10)

        # 添加投资组合状态
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
        构建出场决策的上下文

        Args:
            trade: 交易对象
            current_rate: 当前市场价格
            dataframe: 当前分析的数据框

        Returns:
            出场决策的上下文字典
        """
        # 计算当前利润
        current_profit_pct = trade.calc_profit_ratio(current_rate) * 100
        current_profit_abs = trade.calc_profit(current_rate)

        # 计算持有时间
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

        # 添加可选字段
        if trade.max_rate:
            context["max_rate"] = float(trade.max_rate)
        if trade.min_rate:
            context["min_rate"] = float(trade.min_rate)

        # 添加当前指标
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
        构建投资金额决策的上下文

        Args:
            pair: 交易对
            current_rate: 当前市场价格
            dataframe: 分析的数据框
            available_balance: 可用于交易的余额

        Returns:
            投资决策的上下文字典
        """
        recent_data = dataframe.tail(self.lookback_candles)

        context = {
            "pair": pair,
            "current_price": float(current_rate),
            "available_balance": float(available_balance),
            "market_summary": self._summarize_market(recent_data),
            "volatility": self._calculate_volatility(dataframe),
        }

        # 添加当前指标
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
        构建仓位调整决策的上下文

        Args:
            trade: 交易对象
            current_time: 当前时间戳
            current_rate: 当前市场价格
            current_profit: 当前利润率
            dataframe: 分析的数据框

        Returns:
            调整决策的上下文字典
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

        # 添加指标
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
        构建杠杆决策的上下文

        Args:
            pair: 交易对
            current_rate: 当前市场价格
            proposed_leverage: 建议的杠杆值
            max_leverage: 最大允许杠杆
            dataframe: 分析的数据框

        Returns:
            杠杆决策的上下文字典
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

        # 添加指标
        if self.include_indicators and len(dataframe) > 0:
            context["indicators"] = self._extract_indicators(dataframe.iloc[-1])

        return context

    def _format_candle(self, row: pd.Series) -> Dict[str, float]:
        """
        将单个K线格式化为字典

        Args:
            row: 表示K线的DataFrame行

        Returns:
            包含OHLCV数据的字典
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
        创建市场状况的文本摘要

        Args:
            df: 包含K线数据的DataFrame

        Returns:
            人类可读的市场摘要
        """
        if len(df) == 0:
            return "无可用市场数据"

        try:
            first_close = float(df.iloc[0]["close"])
            last_close = float(df.iloc[-1]["close"])
            recent_returns = (last_close / first_close - 1) * 100

            # 确定趋势
            if recent_returns > 2:
                trend = "bullish"
            elif recent_returns < -2:
                trend = "bearish"
            else:
                trend = "neutral"

            # 计算波动率
            volatility = self._calculate_volatility(df)

            return (
                f"最近 {len(df)} 根K线: {trend} 趋势, "
                f"{recent_returns:+.2f}% 变化, "
                f"{volatility:.2f}% 波动率"
            )

        except Exception as e:
            logger.warning(f"市场摘要生成失败: {e}")
            return "市场数据可用但摘要不可用"

    def _extract_indicators(self, row: pd.Series) -> Dict[str, Any]:
        """
        从数据框行中提取技术指标

        Args:
            row: 包含指标列的DataFrame行

        Returns:
            指标名称到值的字典
        """
        indicators = {}

        for indicator_name in self.include_indicators:
            if indicator_name in row.index:
                value = row[indicator_name]

                # 处理NaN值
                if pd.isna(value):
                    indicators[indicator_name] = None
                else:
                    indicators[indicator_name] = float(value)

        return indicators

    def _format_recent_candles(self, df: pd.DataFrame, num: int = 10) -> list:
        """
        将最近的K线格式化为列表

        Args:
            df: 包含K线数据的DataFrame
            num: 要包含的最近K线数量

        Returns:
            格式化后的K线列表
        """
        candles = []
        start_idx = max(0, len(df) - num)

        for i in range(start_idx, len(df)):
            candles.append(self._format_candle(df.iloc[i]))

        return candles

    def _calculate_volatility(self, df: pd.DataFrame, window: int = 20) -> float:
        """
        计算价格波动率（收益率的标准差）

        Args:
            df: 包含收盘价的DataFrame
            window: 计算窗口大小

        Returns:
            波动率百分比
        """
        try:
            if len(df) < 2:
                return 0.0

            # 计算收益率
            returns = df["close"].pct_change().dropna()

            if len(returns) == 0:
                return 0.0

            # 如果数据足够，使用滚动窗口
            if len(returns) > window:
                volatility = returns.tail(window).std()
            else:
                volatility = returns.std()

            return float(volatility * 100)

        except Exception as e:
            logger.warning(f"波动率计算失败: {e}")
            return 0.0
