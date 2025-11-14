"""
上下文构建器

将市场数据转换为适合LLM使用的上下文。
"""

from typing import Dict, Any, Optional
from datetime import datetime
import pandas as pd
import logging
import re
import inspect

from sqlalchemy import select

from freqtrade.util import dt_now

logger = logging.getLogger(__name__)

# 预编译时间周期正则表达式
TIMEFRAME_PATTERN = re.compile(r'^(.+)_(\d+[mhdw])$')


class ContextBuilder:
    """
    为LLM决策构建上下文数据

    将原始市场数据（数据框、交易对象等）
    转换为可在提示中使用的结构化上下文字典。
    """

    def __init__(
        self,
        config: Dict[str, Any]
    ):
        """
        初始化上下文构建器

        Args:
            config: 完整的配置字典，包含 context 和 decision_points 部分
        """
        # 从完整配置中提取 context 和 decision_points 部分
        context_config = config.get("context", {})
        decision_config = config.get("decision_points", {})
        
        self.config = config
        self.decision_config = decision_config
        self.lookback_candles = context_config.get("lookback_candles", 32)
        self.include_indicators = context_config.get("include_indicators", [])
        self.include_orderbook = context_config.get("include_orderbook", False)
        self.include_raw_candles_in_summary = context_config.get("include_raw_candles_in_summary", False)
        self.include_funding_rate = context_config.get("include_funding_rate", False)
        self.include_portfolio_state = context_config.get("include_portfolio_state", False)

        # 控制是否包含详细的账户和持仓信息
        self.include_account_info = context_config.get("include_account_info", True)
        self.include_wallet_info = context_config.get("include_wallet_info", True)
        self.include_positions_info = context_config.get("include_positions_info", True)
        self.include_closed_trades_info = context_config.get("include_closed_trades_info", True)

        # 控制是否包含风险指标（止损、清算价格等）
        self.include_risk_metrics = context_config.get("include_risk_metrics", True)

        # 调仓历史记录条数限制
        self.adjustment_history_limit = context_config.get("adjustment_history_limit", 5)

    def _get_leverage_info(self, strategy: Optional[Any]) -> tuple[float, float]:
        """
        从策略中获取杠杆信息
        
        Args:
            strategy: 策略实例
            
        Returns:
            (current_leverage, max_leverage) 元组
        """
        current_leverage = 1.0
        max_leverage = 1.0
        
        # 尝试从策略中获取杠杆信息
        if strategy:
            # 获取当前杠杆值
            if hasattr(strategy, 'leverage') and strategy.leverage:
                try:
                    # 检查 leverage 是方法还是属性
                    if callable(strategy.leverage):
                        # 对于 LLMStrategy，leverage() 方法需要7个参数，我们无法提供
                        # 所以这里应该尝试获取默认值或使用默认值 1.0
                        # 我们可以检查是否是 LLMStrategy 的 leverage 方法
                        sig = inspect.signature(strategy.leverage)
                        if len(sig.parameters) > 0:
                            # 这是一个需要参数的方法，我们无法调用，使用默认值
                            current_leverage = 1.0
                        else:
                            # 这是一个无参数的方法，可以调用
                            current_leverage = float(strategy.leverage())
                    else:
                        # leverage 是一个属性
                        current_leverage = float(strategy.leverage)
                except (TypeError, ValueError) as e:
                    logger.warning(f"获取策略杠杆值失败: {e}，使用默认值 1.0")
                    current_leverage = 1.0
            
            # 获取最大杠杆值
            # 首先尝试从配置中获取
            max_leverage_config = None
            if hasattr(strategy, 'config') and isinstance(strategy.config, dict):
                leverage_config = strategy.config.get('leverage', {})
                if isinstance(leverage_config, dict):
                    max_leverage_config = leverage_config.get('max_leverage')
            
            # 如果配置中没有，尝试从策略属性获取
            if max_leverage_config is None and hasattr(strategy, 'max_leverage'):
                max_leverage_config = strategy.max_leverage
            
            # 如果获取到了最大杠杆值，使用它；否则使用默认值1.0
            if max_leverage_config is not None:
                max_leverage = float(max_leverage_config)
        
        return current_leverage, max_leverage

    def build_entry_context(
        self,
        dataframe: pd.DataFrame,
        metadata: Dict,
        portfolio_state: Optional[Dict] = None,
        strategy: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        构建入场决策的上下文

        Args:
            dataframe: 包含指标的分析数据框
            metadata: 策略元数据（交易对等）
            portfolio_state: 可选的当前投资组合状态
            strategy: 策略实例（用于提取账户、钱包、持仓信息）

        Returns:
            入场决策的上下文字典
        """
        if len(dataframe) == 0:
            raise ValueError("提供了空的数据框")

        recent_data = dataframe.tail(self.lookback_candles)
        current_candle = dataframe.iloc[-1]
        pair = metadata.get("pair", "UNKNOWN")

        # 获取时间周期信息
        timeframe = strategy.timeframe if strategy and hasattr(strategy, 'timeframe') else "未知"
        informative_timeframe = (
            strategy.informative_timeframe
            if strategy and hasattr(strategy, 'informative_timeframe')
            else None
        )

        # 获取杠杆信息
        current_leverage, max_leverage = self._get_leverage_info(strategy)

        context = {
            "pair": pair,
            "timeframe": timeframe,
            "current_time": str(current_candle.get("date", dt_now())),
            "current_candle": self._format_candle(current_candle),
            # 添加杠杆信息
            "current_leverage": current_leverage,
            "max_leverage": max_leverage,
        }
        
        # 使用新的辅助方法添加市场摘要
        self._add_market_summary_to_context(context, recent_data, strategy, pair)

        # 添加指标（分离主周期和信息周期）
        if self.include_indicators:
            indicators_data = self._extract_indicators_with_timeframes(
                current_candle,
                dataframe,
                timeframe,
                informative_timeframe
            )
            context.update(indicators_data)

        # 注释掉：由于已经有了市场汇总，这里不再需要添加最近的K线数据
        # if self.include_recent_trades:
        #     context["recent_candles"] = self._format_recent_candles(recent_data, num=10)

        # 添加投资组合状态（旧格式，保持向后兼容）
        if self.include_portfolio_state and portfolio_state:
            context["portfolio"] = portfolio_state

        # 添加新的细粒度信息
        if strategy:
            if self.include_account_info:
                context.update(self._extract_account_info(strategy))

            if self.include_wallet_info:
                context.update(self._extract_wallet_info(strategy))

            if self.include_positions_info:
                positions_info = self._extract_positions_info(strategy, pair=pair)
                context.update(positions_info)

            if self.include_closed_trades_info:
                context.update(self._extract_closed_trades_info(strategy))

        # 清除缓存，下次调用重新获取
        self._clear_trades_cache()
        return context

    def build_exit_context(
        self,
        trade: Any,
        current_rate: float,
        dataframe: pd.DataFrame,
        strategy: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        构建出场决策的上下文

        Args:
            trade: 交易对象
            current_rate: 当前市场价格
            dataframe: 当前分析的数据框
            strategy: 策略实例（用于提取账户、钱包、持仓信息）

        Returns:
            出场决策的上下文字典
        """
        # 计算当前利润
        current_profit_pct = trade.calc_profit_ratio(current_rate) * 100
        current_profit_abs = trade.calc_profit(current_rate)

        # 计算持有时间
        holding_duration_minutes = (
            (dt_now() - trade.open_date_utc).total_seconds() / 60
        )

        # 获取时间周期信息
        timeframe = strategy.timeframe if strategy and hasattr(strategy, 'timeframe') else "未知"
        informative_timeframe = (
            strategy.informative_timeframe
            if strategy and hasattr(strategy, 'informative_timeframe')
            else None
        )

        # 获取当前K线数据
        current_candle = dataframe.iloc[-1] if len(dataframe) > 0 else None

        # 获取杠杆信息
        # 优先使用 trade 对象的实际杠杆，如果没有则从策略获取
        current_leverage = float(trade.leverage) if hasattr(trade, 'leverage') and trade.leverage else 1.0
        _, max_leverage = self._get_leverage_info(strategy)

        context = {
            "pair": trade.pair,
            "timeframe": timeframe,
            "current_time": str(current_candle.get("date", dt_now())) if current_candle is not None else str(dt_now()),
            "current_candle": self._format_candle(current_candle) if current_candle is not None else None,
            "side": "short" if trade.is_short else "long",
            "entry_price": float(trade.open_rate),
            "current_price": float(current_rate),
            "current_profit_pct": float(current_profit_pct),
            "current_profit_abs": float(current_profit_abs),
            "holding_duration_minutes": float(holding_duration_minutes),
            "stop_loss": float(trade.stop_loss),
            "entry_tag": trade.enter_tag or "无",
            "current_leverage": current_leverage,
            "max_leverage": max_leverage,
        }

        # 添加风险指标（如果配置启用）
        if self.include_risk_metrics:
            risk_metrics = self._extract_risk_metrics(trade, current_rate)
            context.update(risk_metrics)

        # 添加可选字段和回撤计算
        if trade.max_rate:
            context["max_rate"] = float(trade.max_rate)
            # 计算从最高点的回撤百分比
            drawdown_pct = ((trade.max_rate - current_rate) / trade.max_rate) * 100
            context["drawdown_from_high_pct"] = float(drawdown_pct)

            # 计算最高点利润（用于了解盈利回撤）
            max_profit_ratio = trade.calc_profit_ratio(trade.max_rate)
            context["max_profit_pct"] = float(max_profit_ratio * 100)

        if trade.min_rate:
            context["min_rate"] = float(trade.min_rate)

        # 获取最近数据用于市场摘要
        recent_data = dataframe.tail(self.lookback_candles)
        
        # 使用新的辅助方法添加市场摘要
        self._add_market_summary_to_context(context, recent_data, strategy, trade.pair)

        # 添加当前指标（分离主周期和信息周期）
        if self.include_indicators and len(dataframe) > 0:
            indicators_data = self._extract_indicators_with_timeframes(
                dataframe.iloc[-1],
                dataframe,
                timeframe,
                informative_timeframe
            )
            context.update(indicators_data)

        # 添加新的细粒度信息
        if strategy:
            if self.include_account_info:
                context.update(self._extract_account_info(strategy))

            if self.include_wallet_info:
                context.update(self._extract_wallet_info(strategy))

            if self.include_positions_info:
                positions_info = self._extract_positions_info(strategy, pair=trade.pair)
                context.update(positions_info)

            if self.include_closed_trades_info:
                context.update(self._extract_closed_trades_info(strategy))

        adjustment_ratio_limit = self._get_adjustment_ratio_limit()
        if adjustment_ratio_limit is not None:
            context["adjustment_ratio_limit"] = adjustment_ratio_limit

        # 添加调仓历史
        adjustment_history = self._extract_adjustment_history(
            trade,
            limit=self.adjustment_history_limit
        )
        if adjustment_history:
            context["adjustment_history"] = adjustment_history

        return context

    def build_stake_context(
        self,
        pair: str,
        current_rate: float,
        dataframe: pd.DataFrame,
        available_balance: float,
        strategy: Optional[Any] = None,
        side: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        构建投资金额决策的上下文

        Args:
            pair: 交易对
            current_rate: 当前市场价格
            dataframe: 分析的数据框
            available_balance: 可用于交易的余额
            strategy: 策略实例（用于提取账户、钱包、持仓信息）
            side: 交易方向 (long/short)，用于账户分离模式

        Returns:
            投资决策的上下文字典
        """
        recent_data = dataframe.tail(self.lookback_candles)

        # 获取时间周期信息
        timeframe = strategy.timeframe if strategy and hasattr(strategy, 'timeframe') else "未知"
        informative_timeframe = (
            strategy.informative_timeframe
            if strategy and hasattr(strategy, 'informative_timeframe')
            else None
        )

        # 获取当前K线数据
        current_candle = dataframe.iloc[-1] if len(dataframe) > 0 else None
        
        # 获取杠杆信息
        current_leverage, max_leverage = self._get_leverage_info(strategy)

        # 获取当前K线数据
        current_candle = dataframe.iloc[-1] if len(dataframe) > 0 else None
        
        context = {
            "pair": pair,
            "timeframe": timeframe,
            "current_time": str(current_candle.get("date", dt_now())) if current_candle is not None else str(dt_now()),
            "current_candle": self._format_candle(current_candle) if current_candle is not None else None,
            "current_price": float(current_rate),
            "available_balance": float(available_balance),
            "volatility": self._calculate_volatility(dataframe),
            # 添加杠杆信息
            "current_leverage": current_leverage,
            "max_leverage": max_leverage,
        }
        
        # 使用新的辅助方法添加市场摘要
        self._add_market_summary_to_context(context, recent_data, strategy, pair)

        stake_limits = self._get_stake_limits()
        if stake_limits:
            context["stake_multiplier_limits"] = stake_limits

        # 添加每次开单的最大额度限制
        max_stake_info = self._calculate_max_stake_per_trade(
            available_balance=available_balance,
            side=side,
            strategy=strategy
        )
        if max_stake_info:
            context["max_stake_per_trade"] = max_stake_info

        # 添加每次开单的最小额度限制
        min_stake_info = self._calculate_min_stake_per_trade(
            available_balance=available_balance,
            side=side,
            strategy=strategy
        )
        if min_stake_info:
            context["min_stake_per_trade"] = min_stake_info

        # 添加当前指标（分离主周期和信息周期）
        if self.include_indicators and len(dataframe) > 0:
            indicators_data = self._extract_indicators_with_timeframes(
                dataframe.iloc[-1],
                dataframe,
                timeframe,
                informative_timeframe
            )
            context.update(indicators_data)

        # 添加新的细粒度信息
        if strategy:
            if self.include_account_info:
                context.update(self._extract_account_info(strategy))

            if self.include_wallet_info:
                context.update(self._extract_wallet_info(strategy))

            if self.include_positions_info:
                positions_info = self._extract_positions_info(strategy, pair=pair)
                context.update(positions_info)

            if self.include_closed_trades_info:
                context.update(self._extract_closed_trades_info(strategy))

        # 清除缓存，下次调用重新获取
        self._clear_trades_cache()
        return context

    def build_adjust_position_context(
        self,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        dataframe: pd.DataFrame,
        strategy: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        构建仓位调整决策的上下文

        Args:
            trade: 交易对象
            current_time: 当前时间戳
            current_rate: 当前市场价格
            current_profit: 当前利润率
            dataframe: 分析的数据框
            strategy: 策略实例（用于提取账户、钱包、持仓信息）

        Returns:
            调整决策的上下文字典
        """
        holding_duration_minutes = (
            (current_time - trade.open_date_utc).total_seconds() / 60
        )

        recent_data = dataframe.tail(self.lookback_candles)

        # 获取时间周期信息
        timeframe = strategy.timeframe if strategy and hasattr(strategy, 'timeframe') else "未知"
        informative_timeframe = (
            strategy.informative_timeframe
            if strategy and hasattr(strategy, 'informative_timeframe')
            else None
        )

        # 计算调整次数和平均入场价
        nr_of_entries = trade.nr_of_successful_entries if hasattr(trade, 'nr_of_successful_entries') else 1
        average_entry_rate = float(trade.open_rate_requested) if hasattr(trade, 'open_rate_requested') else float(trade.open_rate)

        # 计算相对平均成本的盈亏
        profit_from_average = ((current_rate - average_entry_rate) / average_entry_rate) * 100 if average_entry_rate > 0 else 0.0

        # 获取最大调整次数限制
        max_adjustments = -1  # 默认无限制
        if strategy and hasattr(strategy, 'max_entry_position_adjustment'):
            max_adjustments = strategy.max_entry_position_adjustment

        # 计算已调整次数（不包含首次入场）
        nr_of_adjustments = nr_of_entries - 1

        # 计算剩余调整次数
        if max_adjustments > 0:
            remaining_adjustments = max(0, max_adjustments - nr_of_adjustments)
        else:
            remaining_adjustments = -1  # -1 表示无限制

        # 获取当前K线数据
        current_candle = dataframe.iloc[-1] if len(dataframe) > 0 else None

        # 获取杠杆信息
        # 优先使用 trade 对象的实际杠杆，如果没有则从策略获取
        current_leverage = float(trade.leverage) if hasattr(trade, 'leverage') and trade.leverage else 1.0
        _, max_leverage = self._get_leverage_info(strategy)

        # 计算仓位大小相关信息
        position_size_info = self._calculate_position_size_info(trade, strategy)

        context = {
            "pair": trade.pair,
            "timeframe": timeframe,
            "current_time": str(current_candle.get("date", current_time)) if current_candle is not None else str(current_time),
            "current_candle": self._format_candle(current_candle) if current_candle is not None else None,
            "side": "short" if trade.is_short else "long",
            "current_profit_pct": float(current_profit * 100),
            "current_rate": float(current_rate),
            "entry_rate": float(trade.open_rate),
            "average_entry_rate": float(average_entry_rate),
            "profit_from_average_pct": float(profit_from_average),
            "stake_amount": float(trade.stake_amount),
            "holding_duration_minutes": float(holding_duration_minutes),
            "nr_of_entries": int(nr_of_entries),
            "max_adjustments": int(max_adjustments),
            "remaining_adjustments": int(remaining_adjustments),
            "entry_tag": trade.enter_tag or "无",
            # 添加杠杆信息
            "current_leverage": current_leverage,
            "max_leverage": max_leverage,
            # 添加仓位大小信息
            **position_size_info,
        }

        # 添加风险指标（如果配置启用）
        if self.include_risk_metrics:
            risk_metrics = self._extract_risk_metrics(trade, current_rate)
            context.update(risk_metrics)
        
        # 使用新的辅助方法添加市场摘要
        self._add_market_summary_to_context(context, recent_data, strategy, trade.pair)

        # 添加指标（分离主周期和信息周期）
        if self.include_indicators and len(dataframe) > 0:
            indicators_data = self._extract_indicators_with_timeframes(
                dataframe.iloc[-1],
                dataframe,
                timeframe,
                informative_timeframe
            )
            context.update(indicators_data)

        # 添加新的细粒度信息
        if strategy:
            if self.include_account_info:
                context.update(self._extract_account_info(strategy))

            if self.include_wallet_info:
                context.update(self._extract_wallet_info(strategy))

            if self.include_positions_info:
                positions_info = self._extract_positions_info(strategy, pair=trade.pair)
                context.update(positions_info)

            if self.include_closed_trades_info:
                context.update(self._extract_closed_trades_info(strategy))

        adjustment_ratio_limit = self._get_adjustment_ratio_limit()
        if adjustment_ratio_limit is not None:
            context["adjustment_ratio_limit"] = adjustment_ratio_limit

        # 添加调仓历史
        adjustment_history = self._extract_adjustment_history(
            trade,
            limit=self.adjustment_history_limit
        )
        if adjustment_history:
            context["adjustment_history"] = adjustment_history

        self._clear_trades_cache()
        return context

    def build_leverage_context(
        self,
        pair: str,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        dataframe: pd.DataFrame,
        strategy: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        构建杠杆决策的上下文

        Args:
            pair: 交易对
            current_rate: 当前市场价格
            proposed_leverage: 建议的杠杆值
            max_leverage: 最大允许杠杆
            dataframe: 分析的数据框
            strategy: 策略实例（用于提取账户、钱包、持仓信息）

        Returns:
            杠杆决策的上下文字典
        """
        recent_data = dataframe.tail(self.lookback_candles)

        # 获取时间周期信息
        timeframe = strategy.timeframe if strategy and hasattr(strategy, 'timeframe') else "未知"
        informative_timeframe = (
            strategy.informative_timeframe
            if strategy and hasattr(strategy, 'informative_timeframe')
            else None
        )

        # 获取当前K线数据
        current_candle = dataframe.iloc[-1] if len(dataframe) > 0 else None
        
        # 获取当前杠杆信息（max_leverage 已作为参数传入）
        current_leverage, _ = self._get_leverage_info(strategy)

        # 获取当前K线数据
        current_candle = dataframe.iloc[-1] if len(dataframe) > 0 else None
        
        context = {
            "pair": pair,
            "timeframe": timeframe,
            "current_time": str(current_candle.get("date", dt_now())) if current_candle is not None else str(dt_now()),
            "current_candle": self._format_candle(current_candle) if current_candle is not None else None,
            "current_rate": float(current_rate),
            "proposed_leverage": float(proposed_leverage),
            "max_leverage": float(max_leverage),
            "volatility": self._calculate_volatility(dataframe),
            # 添加当前杠杆信息
            "current_leverage": current_leverage,
        }
        
        # 使用新的辅助方法添加市场摘要
        self._add_market_summary_to_context(context, recent_data, strategy, pair)

        leverage_limits = self._get_leverage_limits(max_leverage)
        if leverage_limits:
            context["leverage_limits"] = leverage_limits

        # 添加指标（分离主周期和信息周期）
        if self.include_indicators and len(dataframe) > 0:
            indicators_data = self._extract_indicators_with_timeframes(
                dataframe.iloc[-1],
                dataframe,
                timeframe,
                informative_timeframe
            )
            context.update(indicators_data)

        # 添加新的细粒度信息
        if strategy:
            if self.include_account_info:
                context.update(self._extract_account_info(strategy))

            if self.include_wallet_info:
                context.update(self._extract_wallet_info(strategy))

            if self.include_positions_info:
                positions_info = self._extract_positions_info(strategy, pair=pair)
                context.update(positions_info)

            if self.include_closed_trades_info:
                context.update(self._extract_closed_trades_info(strategy))

        # 清除缓存，下次调用重新获取
        self._clear_trades_cache()
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

    def _summarize_market(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        创建市场状况的摘要

        Args:
            df: 包含K线数据的DataFrame

        Returns:
            包含市场摘要信息的字典，包括：
            - summary: 原有的市场摘要文本（保持向后兼容）
            - trend: 趋势判断（bullish/bearish/neutral）
            - change_pct: 价格变化百分比
            - candle_count: K线数量
            - raw_candles: 可选的原始K线数据（如果启用配置）
        """
        result = {
            "summary": "无可用市场数据",
            "trend": "neutral",
            "change_pct": 0.0,
            "candle_count": 0,
            "raw_candles": None
        }

        if len(df) == 0:
            return result

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

            # 构建摘要文本（保持向后兼容）
            summary_text = (
                f"最近 {len(df)} 根K线: {trend} 趋势, "
                f"{recent_returns:+.2f}% 变化, "
                f"{volatility:.2f}% 波动率"
            )

            # 更新结果字典
            result.update({
                "summary": summary_text,
                "trend": trend,
                "change_pct": recent_returns,
                "candle_count": len(df)
            })

            # 如果启用了包含原始K线数据，则添加格式化的原始K线数据
            if self.include_raw_candles_in_summary:
                result["raw_candles"] = self._format_raw_candles(df, self.lookback_candles)

            return result

        except Exception as e:
            logger.warning(f"市场摘要生成失败: {e}")
            result["summary"] = "市场数据可用但摘要不可用"
            return result

    def _add_market_summary_to_context(
        self,
        context: Dict[str, Any],
        recent_data: pd.DataFrame,
        strategy: Optional[Any] = None,
        pair: Optional[str] = None
    ) -> None:
        """
        添加市场摘要到上下文字典

        该方法调用 _summarize_market 获取市场数据，并将结果添加到上下文中：
        - 将市场摘要字符串添加到 "market_summary" 键（保持向后兼容）
        - 将完整的市场数据字典添加到 "market_data" 键（提供新功能）
        - 添加信息对的 K 线数据到 "informative_candles" 键（新功能）

        Args:
            context: 要更新的上下文字典
            recent_data: 包含市场数据的DataFrame
            strategy: 策略实例，用于获取信息对数据
            pair: 交易对，用于获取信息对数据
        """
        try:
            # 获取市场数据
            market_data = self._summarize_market(recent_data)
            
            # 添加市场摘要字符串（保持向后兼容）
            if "summary" in market_data:
                context["market_summary"] = market_data["summary"]
            
            # 添加完整的市场数据字典（提供新功能）
            context["market_data"] = market_data
            
            # 添加信息对的 K 线数据（新功能）
            if strategy and pair and hasattr(strategy, 'informative_pairs'):
                informative_candles = {}
                
                # 获取策略定义的信息对
                informative_pairs = strategy.informative_pairs()
                
                for inf_pair, inf_timeframe in informative_pairs:
                    # 只处理当前交易对的信息对
                    if inf_pair == pair:
                        candles = self._get_informative_candles(
                            strategy, inf_pair, inf_timeframe, self.lookback_candles
                        )
                        if candles:
                            informative_candles[inf_timeframe] = candles
                
                # 添加信息对 K 线数据到上下文
                if informative_candles:
                    context["informative_candles"] = informative_candles
            
        except Exception as e:
            logger.warning(f"添加市场摘要到上下文失败: {e}")
            # 提供合理的默认值
            context["market_summary"] = "市场数据不可用"
            context["market_data"] = {
                "summary": "市场数据不可用",
                "trend": "neutral",
                "change_pct": 0.0,
                "candle_count": 0,
                "raw_candles": None
            }

    def _format_raw_candles(self, df: pd.DataFrame, limit: int) -> list:
        """
        格式化原始K线数据为OHLCV字典列表

        Args:
            df: 包含K线数据的DataFrame
            limit: 要包含的K线数量限制

        Returns:
            格式化后的OHLCV字典列表
        """
        candles = []
        
        if len(df) == 0:
            return candles
            
        # 获取最近的limit根K线
        start_idx = max(0, len(df) - limit)
        
        try:
            for i in range(start_idx, len(df)):
                row = df.iloc[i]
                candle_data = {
                    "date": str(row.get("date", "")),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0))
                }
                candles.append(candle_data)
        except Exception as e:
            logger.warning(f"格式化原始K线数据失败: {e}")
            # 返回空列表而不是部分数据，以保持一致性
            return []
            
        return candles

    def _get_informative_candles(self, strategy: Any, pair: str, timeframe: str, limit: int) -> list:
        """
        获取信息对的原始K线数据

        Args:
            strategy: 策略实例，用于访问DataProvider
            pair: 交易对
            timeframe: 信息对的时间周期
            limit: 要包含的K线数量限制

        Returns:
            格式化后的OHLCV字典列表，如果获取失败返回空列表
        """
        if not strategy or not hasattr(strategy, 'dp'):
            logger.warning("策略实例无效或没有DataProvider，无法获取信息对K线数据")
            return []
            
        try:
            # 获取信息对的DataFrame
            informative_df = strategy.dp.get_pair_dataframe(pair=pair, timeframe=timeframe)
            
            if len(informative_df) == 0:
                logger.warning(f"信息对 {pair} {timeframe} 没有数据")
                return []
                
            # 使用现有的_format_raw_candles方法格式化数据
            return self._format_raw_candles(informative_df, limit)
            
        except Exception as e:
            logger.warning(f"获取信息对 {pair} {timeframe} K线数据失败: {e}")
            return []

    def _detect_all_indicators(self, dataframe: pd.DataFrame) -> list:
        """
        自动检测DataFrame中的所有指标列（包含OHLCV基本数据）

        Args:
            dataframe: 包含指标数据的DataFrame

        Returns:
            检测到的指标列名列表
        """
        # 只排除信号列和日期列，OHLCV也是重要的指标数据
        excluded_columns = {
            'enter_long', 'exit_long', 'enter_short', 'exit_short',
            'enter_tag', 'exit_tag', 'date'
        }

        # 获取所有列名
        all_columns = set(dataframe.columns)

        # 排除信号列，保留所有指标列（包括 open/high/low/close/volume）
        indicator_columns = list(all_columns - excluded_columns)

        return sorted(indicator_columns)

    def _match_indicator_with_suffix(self, indicator_name: str, available_columns: set) -> Optional[str]:
        """
        匹配指标名称，自动处理带 timeframe 后缀的情况

        例如：用户配置 "rsi" 可以匹配 "rsi"、"rsi_5m"、"rsi_1h" 等

        Args:
            indicator_name: 配置中的指标名称（不带后缀）
            available_columns: DataFrame中所有可用的列名

        Returns:
            匹配到的完整列名，如果没有匹配则返回 None
        """
        # 1. 精确匹配（优先）
        if indicator_name in available_columns:
            return indicator_name

        # 2. 尝试匹配带 timeframe 后缀的列
        # 常见的 timeframe 后缀：_1m, _5m, _15m, _30m, _1h, _4h, _1d 等
        # 使用模糊匹配：indicator_name + "_" + 任意后缀
        matching_columns = [
            col for col in available_columns
            if col.startswith(indicator_name + "_")
        ]

        if matching_columns:
            # 如果找到多个匹配，优先返回第一个（通常是最短的）
            # 例如：如果有 rsi_5m 和 rsi_5m_sma，优先返回 rsi_5m
            return sorted(matching_columns, key=len)[0]

        # 3. 没有找到任何匹配
        return None

    def _extract_indicators_with_timeframes(
        self,
        row: pd.Series,
        dataframe: pd.DataFrame,
        main_timeframe: str,
        informative_timeframe: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        从数据框行中提取技术指标，自动分离主周期和多个信息周期

        Args:
            row: 包含指标列的DataFrame行
            dataframe: 完整DataFrame，用于自动检测指标
            main_timeframe: 主时间周期（如 "15m"）
            informative_timeframe: 已废弃，现在自动检测所有信息周期

        Returns:
            包含分组指标的字典，格式：
            {
                "main_timeframe": "15m",
                "main_indicators": {...},  # 主周期指标
                "informative_timeframes": [  # 多个信息周期
                    {"timeframe": "8h", "indicators": {...}},
                    {"timeframe": "1d", "indicators": {...}}
                ]
            }
        """
        result = {
            "main_timeframe": main_timeframe
        }
        available_columns = set(row.index)

        # 获取所有指标列名
        if isinstance(self.include_indicators, bool):
            if self.include_indicators:
                all_indicator_names = self._detect_all_indicators(dataframe)
            else:
                return {}
        elif isinstance(self.include_indicators, list):
            all_indicator_names = []
            for config_name in self.include_indicators:
                matched_name = self._match_indicator_with_suffix(config_name, available_columns)
                if matched_name:
                    all_indicator_names.append(matched_name)
        else:
            return {}

        # 自动检测所有可能的时间周期后缀（使用预编译正则，O(n)复杂度）
        # 常见的 timeframe 后缀：_1m, _5m, _15m, _30m, _1h, _4h, _8h, _1d 等
        timeframe_suffixes = set()
        for indicator_name in all_indicator_names:
            # 使用预编译正则表达式快速匹配
            match = TIMEFRAME_PATTERN.match(indicator_name)
            if match:
                timeframe = match.group(2)  # 提取时间周期部分 (如 "5m", "1h")
                timeframe_suffixes.add(f"_{timeframe}")

        # 分离主周期和多个信息周期的指标
        main_indicators = {}
        informative_by_timeframe = {}  # {timeframe: {indicators}}

        for indicator_name in all_indicator_names:
            if indicator_name not in row.index:
                continue

            value = row[indicator_name]

            # 处理NaN值和类型转换
            if pd.isna(value):
                continue
            if isinstance(value, (pd.Timestamp, datetime)):
                continue
            try:
                float_value = float(value)
            except (ValueError, TypeError):
                logger.warning(f"无法将指标 {indicator_name} 的值 {value} 转换为float，已跳过")
                continue

            # 判断是否为信息周期指标
            is_informative = False
            for suffix in timeframe_suffixes:
                if indicator_name.endswith(suffix):
                    is_informative = True
                    # 提取时间周期（去掉前缀的下划线）
                    timeframe = suffix[1:]  # 去掉 '_'
                    # 去除后缀，使指标名称更简洁
                    clean_name = indicator_name[:-len(suffix)]

                    if timeframe not in informative_by_timeframe:
                        informative_by_timeframe[timeframe] = {}

                    informative_by_timeframe[timeframe][clean_name] = float_value
                    break

            if not is_informative:
                main_indicators[indicator_name] = float_value

        # 构建返回结果
        if main_indicators:
            result["main_indicators"] = main_indicators

        if informative_by_timeframe:
            # 转换为列表格式，并按时间周期排序
            informative_list = []
            for tf in sorted(informative_by_timeframe.keys()):
                informative_list.append({
                    "timeframe": tf,
                    "indicators": informative_by_timeframe[tf]
                })
            result["informative_timeframes"] = informative_list

        return result

    def _extract_indicators(self, row: pd.Series, dataframe: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        从数据框行中提取技术指标

        支持自动匹配带 timeframe 后缀的指标名称。
        例如：配置中的 "rsi" 可以自动匹配 "rsi_5m"、"rsi_1h" 等

        Args:
            row: 包含指标列的DataFrame行
            dataframe: 可选的完整DataFrame，用于自动检测指标

        Returns:
            指标名称到值的字典
        """
        indicators = {}
        available_columns = set(row.index)

        # 处理include_indicators的不同类型
        if isinstance(self.include_indicators, bool):
            # 如果是布尔值True，自动检测所有指标
            if self.include_indicators and dataframe is not None:
                indicator_names = self._detect_all_indicators(dataframe)
            else:
                # 如果是False，不包含任何指标
                return indicators
        elif isinstance(self.include_indicators, list):
            # 如果是列表，使用指定的指标（需要匹配后缀）
            indicator_names = []
            for config_name in self.include_indicators:
                matched_name = self._match_indicator_with_suffix(config_name, available_columns)
                if matched_name:
                    indicator_names.append(matched_name)
                else:
                    logger.debug(
                        f"配置的指标 '{config_name}' 在 DataFrame 中未找到匹配列，已跳过"
                    )
        else:
            # 其他类型，视为空列表
            return indicators

        for indicator_name in indicator_names:
            if indicator_name in row.index:
                value = row[indicator_name]

                # 处理NaN值
                if pd.isna(value):
                    indicators[indicator_name] = None
                else:
                    # 检查值类型，跳过Timestamp和datetime类型
                    if isinstance(value, (pd.Timestamp, datetime)):
                        # 跳过日期时间类型，不将其作为指标
                        continue
                    try:
                        indicators[indicator_name] = float(value)
                    except (ValueError, TypeError):
                        # 如果无法转换为float，跳过该指标
                        logger.warning(f"无法将指标 {indicator_name} 的值 {value} 转换为float，已跳过")
                        continue

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

    def _get_stake_limits(self) -> Optional[Dict[str, float]]:
        """
        获取仓位倍数范围，用于提示词中引用
        """
        config = self.decision_config.get("stake", {})
        min_multiplier = config.get("min_stake_multiplier")
        max_multiplier = config.get("max_stake_multiplier")

        if min_multiplier is None and max_multiplier is None:
            return None

        limits: Dict[str, float] = {}
        if min_multiplier is not None:
            limits["min"] = float(min_multiplier)
        if max_multiplier is not None:
            limits["max"] = float(max_multiplier)

        return limits

    def _get_leverage_limits(self, max_leverage: float) -> Optional[Dict[str, float]]:
        """
        获取杠杆范围，优先使用配置中的 min/max，其次 fallback 到参数
        """
        config = self.decision_config.get("leverage", {})
        min_leverage = config.get("min_leverage")
        max_leverage_config = config.get("max_leverage")

        if min_leverage is None and max_leverage_config is None:
            # 仍然返回函数参数的最大值，以便提示词可提示上限
            return {"max": float(max_leverage)}

        limits: Dict[str, float] = {}
        if min_leverage is not None:
            limits["min"] = float(min_leverage)
        if max_leverage_config is not None:
            limits["max"] = float(max_leverage_config)
        elif max_leverage is not None:
            limits["max"] = float(max_leverage)

        return limits

    def _get_adjustment_ratio_limit(self) -> Optional[float]:
        """
        获取最大加减仓比例限制
        """
        config = self.decision_config.get("adjust_position", {})
        max_ratio = config.get("max_adjustment_ratio")
        return float(max_ratio) if max_ratio is not None else None

    def _calculate_max_stake_per_trade(
        self,
        available_balance: float,
        side: Optional[str] = None,
        strategy: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        计算每次开单的最大额度限制

        Args:
            available_balance: 可用余额
            side: 交易方向 (long/short)，用于账户分离模式
            strategy: 策略实例

        Returns:
            包含最大额度信息的字典，如果未配置则返回 None
        """
        stake_config = self.decision_config.get("stake", {})
        max_stake_config = stake_config.get("max_stake_per_trade")

        if not max_stake_config:
            return None

        mode = max_stake_config.get("mode", "percent")
        value = max_stake_config.get("value", 0)

        if mode == "fixed":
            # 固定金额模式
            max_stake = float(value)
            return {
                "mode": "fixed",
                "max_stake_amount": max_stake,
                "description": f"每次最大开单额度: {max_stake:.2f} USDT (固定值)"
            }

        elif mode == "percent":
            # 百分比模式：根据总资金计算（初始余额，而非剩余可用余额）
            # 获取账户总资金
            if strategy and hasattr(strategy, 'account_enabled') and strategy.account_enabled:
                # 账户分离模式：使用对应账户的初始余额
                if side == "long":
                    total_balance = float(strategy.long_initial_balance)
                else:
                    total_balance = float(strategy.short_initial_balance)
            else:
                # 非账户分离模式：使用钱包总余额
                if strategy and hasattr(strategy, 'wallets') and strategy.wallets:
                    total_balance = strategy.wallets.get_total(strategy.config.get("stake_currency", "USDT"))
                else:
                    # 无法获取总余额，回退到可用余额
                    total_balance = available_balance

            max_stake = total_balance * (value / 100.0)
            return {
                "mode": "percent",
                "percent_value": float(value),
                "total_balance": total_balance,
                "available_balance": available_balance,
                "max_stake_amount": max_stake,
                "description": (
                    f"每次最大开单额度: {value}% 的总资金 "
                    f"(总资金: {total_balance:.2f}, 最大: {max_stake:.2f}, 可用: {available_balance:.2f})"
                )
            }

        return None

    def _calculate_min_stake_per_trade(
        self,
        available_balance: float,
        side: Optional[str] = None,
        strategy: Optional[Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        计算每次开单的最小额度限制

        Args:
            available_balance: 可用余额
            side: 交易方向 (long/short)，用于账户分离模式
            strategy: 策略实例

        Returns:
            包含最小额度信息的字典，如果未配置则返回 None
        """
        stake_config = self.decision_config.get("stake", {})
        min_stake_config = stake_config.get("min_stake_per_trade")

        if not min_stake_config:
            return None

        mode = min_stake_config.get("mode", "percent")
        value = min_stake_config.get("value", 0)

        if mode == "fixed":
            # 固定金额模式
            min_stake = float(value)
            return {
                "mode": "fixed",
                "min_stake_amount": min_stake,
                "description": f"每次最小开单额度: {min_stake:.2f} USDT (固定值)"
            }

        elif mode == "percent":
            # 百分比模式：根据总资金计算
            # 获取账户总资金
            if strategy and hasattr(strategy, 'account_enabled') and strategy.account_enabled:
                # 账户分离模式：使用对应账户的初始余额
                if side == "long":
                    total_balance = float(strategy.long_initial_balance)
                else:
                    total_balance = float(strategy.short_initial_balance)
            else:
                # 非账户分离模式：使用钱包总余额
                if strategy and hasattr(strategy, 'wallets') and strategy.wallets:
                    total_balance = strategy.wallets.get_total(strategy.config.get("stake_currency", "USDT"))
                else:
                    # 无法获取总余额，回退到可用余额
                    total_balance = available_balance

            min_stake = total_balance * (value / 100.0)
            return {
                "mode": "percent",
                "percent_value": float(value),
                "total_balance": total_balance,
                "min_stake_amount": min_stake,
                "description": (
                    f"每次最小开单额度: {value}% 的总资金 "
                    f"(总资金: {total_balance:.2f}, 最小: {min_stake:.2f})"
                )
            }

        return None

    # ========== 新增：细粒度信息提取方法 ==========

    def _get_cached_trades(self, strategy: Any) -> tuple:
        """
        获取并缓存交易数据，避免重复查询数据库

        Args:
            strategy: 策略实例

        Returns:
            (open_trades, closed_trades) 元组
        """
        from freqtrade.persistence import Trade

        # 使用策略对象作为缓存键（每次 context build 调用都是新的）
        cache_key = '_trades_cache'
        if not hasattr(self, cache_key):
            open_trades = Trade.get_trades_proxy(is_open=True)
            closed_trades = Trade.get_trades_proxy(is_open=False)
            setattr(self, cache_key, (open_trades, closed_trades))
            logger.debug(f"缓存交易数据: {len(open_trades)} 个持仓, {len(closed_trades)} 个已平仓")
        return getattr(self, cache_key)

    def _clear_trades_cache(self):
        """清除交易缓存"""
        if hasattr(self, '_trades_cache'):
            delattr(self, '_trades_cache')

    def _extract_account_info(self, strategy: Any) -> Dict[str, Any]:
        """
        提取账户分离信息

        Args:
            strategy: 策略实例（需要有账户分离功能）

        Returns:
            账户信息字典
        """
        account_info = {
            "account_mode_enabled": False,
            "account_long_initial": 0.0,
            "account_short_initial": 0.0,
            "account_long_available": 0.0,
            "account_short_available": 0.0,
            "account_long_used": 0.0,
            "account_short_used": 0.0,
        }

        try:
            # 检查是否有账户分离功能
            if not hasattr(strategy, 'account_enabled'):
                return account_info

            account_info["account_mode_enabled"] = strategy.account_enabled

            if strategy.account_enabled:
                # 获取初始余额
                account_info["account_long_initial"] = float(strategy.long_initial_balance)
                account_info["account_short_initial"] = float(strategy.short_initial_balance)

                long_stats = {}
                short_stats = {}

                # 获取可用余额（同时刷新账户统计数据）
                if hasattr(strategy, 'get_account_available_balance'):
                    account_info["account_long_available"] = float(
                        strategy.get_account_available_balance("long")
                    )
                    account_info["account_short_available"] = float(
                        strategy.get_account_available_balance("short")
                    )

                if hasattr(strategy, 'get_account_usage_stats'):
                    long_stats = strategy.get_account_usage_stats("long")
                    short_stats = strategy.get_account_usage_stats("short")

                # 使用账户统计数据（若可用），否则退回到旧的简单计算
                account_info["account_long_used"] = float(long_stats.get("used_balance", 0.0)) if long_stats else max(
                    0.0,
                    account_info["account_long_initial"] - account_info["account_long_available"]
                )
                account_info["account_short_used"] = float(short_stats.get("used_balance", 0.0)) if short_stats else max(
                    0.0,
                    account_info["account_short_initial"] - account_info["account_short_available"]
                )

        except Exception as e:
            logger.warning(f"提取账户信息失败: {e}")

        return account_info

    def _extract_wallet_info(self, strategy: Any) -> Dict[str, Any]:
        """
        提取钱包信息

        Args:
            strategy: 策略实例

        Returns:
            钱包信息字典
        """
        wallet_info = {
            "wallet_total_balance": 0.0,
            "wallet_free_balance": 0.0,
            "wallet_used_balance": 0.0,
            "wallet_starting_balance": 0.0,
        }

        try:
            if not hasattr(strategy, 'wallets') or not strategy.wallets:
                return wallet_info

            stake_currency = strategy.config.get("stake_currency", "USDT")

            # 获取钱包余额
            wallet_info["wallet_total_balance"] = float(
                strategy.wallets.get_total(stake_currency)
            )
            wallet_info["wallet_free_balance"] = float(
                strategy.wallets.get_free(stake_currency)
            )

            # 计算已使用资金
            wallet_info["wallet_used_balance"] = (
                wallet_info["wallet_total_balance"] - wallet_info["wallet_free_balance"]
            )

            # 获取初始余额
            try:
                wallet_info["wallet_starting_balance"] = float(
                    strategy.wallets.get_starting_balance()
                )
            except Exception:
                wallet_info["wallet_starting_balance"] = wallet_info["wallet_total_balance"]

        except Exception as e:
            logger.warning(f"提取钱包信息失败: {e}")

        return wallet_info

    def _extract_positions_info(self, strategy: Any, pair: Optional[str] = None) -> Dict[str, Any]:
        """
        提取持仓信息

        Args:
            strategy: 策略实例
            pair: 可选的交易对过滤

        Returns:
            持仓信息字典
        """
        positions_info = {
            "positions_total_count": 0,
            "positions_long_count": 0,
            "positions_short_count": 0,
            "positions_long_stake_total": 0.0,
            "positions_short_stake_total": 0.0,
            "positions_long_profit_total": 0.0,
            "positions_short_profit_total": 0.0,
            "positions_long_profit_pct": 0.0,
            "positions_short_profit_pct": 0.0,
            "current_pair_positions": [],
            # 新增：风险评估指标
            "positions_at_risk_count": 0,  # 亏损持仓数量
            "positions_in_profit_count": 0,  # 盈利持仓数量
            "max_single_position_stake": 0.0,  # 最大单笔持仓金额
            "avg_position_stake": 0.0,  # 平均持仓金额
        }

        try:
            # 获取所有持仓（使用缓存）
            open_trades, _ = self._get_cached_trades(strategy)

            long_stake = 0.0
            short_stake = 0.0
            long_profit = 0.0
            short_profit = 0.0
            at_risk_count = 0
            in_profit_count = 0
            max_stake = 0.0
            total_stake = 0.0

            for trade in open_trades:
                is_long = not trade.is_short

                # 计算浮动盈亏
                try:
                    current_rate = self._get_current_rate(strategy, trade.pair)
                    if current_rate:
                        profit_ratio = trade.calc_profit_ratio(current_rate)
                        profit_abs = trade.calc_profit(current_rate)
                    else:
                        logger.debug(f"无法获取 {trade.pair} 的当前价格，使用 0 作为盈亏")
                        profit_ratio = 0.0
                        profit_abs = 0.0
                except Exception as e:
                    logger.warning(f"计算 {trade.pair} 盈亏失败: {e}")
                    profit_ratio = 0.0
                    profit_abs = 0.0

                # 使用实时仓位价值而非历史 max_stake
                stake = self._estimate_trade_stake_value(
                    trade,
                    current_rate=current_rate,
                    strategy=strategy,
                )

                # 累计统计
                if is_long:
                    positions_info["positions_long_count"] += 1
                    long_stake += stake
                    long_profit += profit_abs
                else:
                    positions_info["positions_short_count"] += 1
                    short_stake += stake
                    short_profit += profit_abs

                # 风险评估统计
                total_stake += stake
                max_stake = max(max_stake, stake)
                if profit_abs < 0:
                    at_risk_count += 1
                else:
                    in_profit_count += 1

                # 如果是当前交易对，记录详细信息
                if pair and trade.pair == pair:
                    holding_minutes = (
                        (dt_now() - trade.open_date_utc).total_seconds() / 60
                    )

                    positions_info["current_pair_positions"].append({
                        "trade_id": trade.id,
                        "pair": trade.pair,
                        "side": "long" if is_long else "short",
                        "open_rate": float(trade.open_rate),
                        "current_rate": float(current_rate) if current_rate else 0.0,
                        "stake_amount": float(stake),
                        "open_date": str(trade.open_date_utc),
                        "holding_minutes": float(holding_minutes),
                        "profit_abs": float(profit_abs),
                        "profit_pct": float(profit_ratio * 100),
                        "leverage": float(trade.leverage or 1.0),
                    })

            # 总计
            positions_info["positions_total_count"] = len(open_trades)
            positions_info["positions_long_stake_total"] = long_stake
            positions_info["positions_short_stake_total"] = short_stake
            positions_info["positions_long_profit_total"] = long_profit
            positions_info["positions_short_profit_total"] = short_profit

            # 计算盈亏百分比
            if long_stake > 0:
                positions_info["positions_long_profit_pct"] = (long_profit / long_stake) * 100
            if short_stake > 0:
                positions_info["positions_short_profit_pct"] = (short_profit / short_stake) * 100

            # 风险评估指标
            positions_info["positions_at_risk_count"] = at_risk_count
            positions_info["positions_in_profit_count"] = in_profit_count
            positions_info["max_single_position_stake"] = max_stake
            if len(open_trades) > 0:
                positions_info["avg_position_stake"] = total_stake / len(open_trades)

        except Exception as e:
            logger.warning(f"提取持仓信息失败: {e}")

        return positions_info

    def _extract_closed_trades_info(self, strategy: Any) -> Dict[str, Any]:
        """
        提取已平仓交易统计

        Args:
            strategy: 策略实例

        Returns:
            已平仓交易信息字典
        """
        closed_info = {
            "closed_trades_total": 0,
            "closed_long_count": 0,
            "closed_short_count": 0,
            "closed_long_profit": 0.0,
            "closed_short_profit": 0.0,
            "closed_total_profit": 0.0,
        }

        try:
            from freqtrade.persistence import Trade

            if getattr(Trade, "use_db", False):
                stmt = select(Trade.is_short, Trade.realized_profit).where(Trade.is_open.is_(False))
                try:
                    results = Trade.session.execute(stmt).all()
                    for is_short, profit in results:
                        profit = float(profit or 0.0)
                        if is_short:
                            closed_info["closed_short_count"] += 1
                            closed_info["closed_short_profit"] += profit
                        else:
                            closed_info["closed_long_count"] += 1
                            closed_info["closed_long_profit"] += profit

                    closed_info["closed_trades_total"] = len(results)
                    closed_info["closed_total_profit"] = (
                        closed_info["closed_long_profit"] + closed_info["closed_short_profit"]
                    )
                finally:
                    # 释放会话，防止对象在后续访问时触发 lazy load
                    Trade.session.remove()

                return closed_info

            # 非数据库模式（如 Dry-run/回测）仍旧使用缓存中的 LocalTrade 对象
            _, closed_trades = self._get_cached_trades(strategy)
            closed_info["closed_trades_total"] = len(closed_trades)

            long_profit = 0.0
            short_profit = 0.0

            for trade in closed_trades:
                profit = float(trade.realized_profit or 0.0)

                if trade.is_short:
                    closed_info["closed_short_count"] += 1
                    short_profit += profit
                else:
                    closed_info["closed_long_count"] += 1
                    long_profit += profit

            closed_info["closed_long_profit"] = long_profit
            closed_info["closed_short_profit"] = short_profit
            closed_info["closed_total_profit"] = long_profit + short_profit

        except Exception as e:
            logger.warning(f"提取已平仓信息失败: {e}")

        return closed_info

    def _get_current_rate(self, strategy: Any, pair: str) -> Optional[float]:
        """
        获取交易对当前价格

        Args:
            strategy: 策略实例
            pair: 交易对

        Returns:
            当前价格，如果获取失败返回 None
        """
        try:
            if not hasattr(strategy, 'dp'):
                return None

            df, _ = strategy.dp.get_analyzed_dataframe(pair, strategy.timeframe)
            if len(df) > 0:
                return float(df["close"].iloc[-1])
        except Exception as e:
            logger.debug(f"获取 {pair} 当前价格失败: {e}")

        return None

    def _extract_risk_metrics(self, trade: Any, current_rate: float) -> Dict[str, Any]:
        """
        提取风险相关指标（止损、清算价格等）

        Args:
            trade: 交易对象
            current_rate: 当前市场价格

        Returns:
            风险指标字典
        """
        risk_metrics = {}

        # 止损信息
        # 注意：在全仓模式下，止损价格可能是负数（允许极大亏损）
        if hasattr(trade, 'stop_loss') and trade.stop_loss is not None:
            stop_loss = float(trade.stop_loss)

            # 计算距离止损的距离百分比
            # 对于多头：(当前价 - 止损价) / 当前价 * 100
            # 对于空头：(止损价 - 当前价) / 当前价 * 100
            if trade.is_short:
                # 空头：止损价在上方
                stop_loss_distance_pct = ((stop_loss - current_rate) / current_rate) * 100
            else:
                # 多头：止损价在下方
                stop_loss_distance_pct = ((current_rate - stop_loss) / current_rate) * 100

            risk_metrics.update({
                "stop_loss": stop_loss,
                "stop_loss_distance_pct": float(stop_loss_distance_pct),
            })

            # 初始止损信息
            if hasattr(trade, 'initial_stop_loss') and trade.initial_stop_loss is not None:
                risk_metrics["initial_stop_loss"] = float(trade.initial_stop_loss)

            if hasattr(trade, 'initial_stop_loss_pct') and trade.initial_stop_loss_pct is not None:
                risk_metrics["initial_stop_loss_pct"] = float(trade.initial_stop_loss_pct * 100)

            # 跟踪止损标志
            if hasattr(trade, 'is_stop_loss_trailing'):
                risk_metrics["is_stop_loss_trailing"] = trade.is_stop_loss_trailing

        # 清算价格信息（杠杆交易）
        if hasattr(trade, 'liquidation_price') and trade.liquidation_price:
            liquidation_price = float(trade.liquidation_price)

            # 计算距离清算价的距离百分比
            # 对于多头：(当前价 - 清算价) / 当前价 * 100
            # 对于空头：(清算价 - 当前价) / 当前价 * 100
            if trade.is_short:
                # 空头：清算价在上方
                liquidation_distance_pct = ((liquidation_price - current_rate) / current_rate) * 100
            else:
                # 多头：清算价在下方
                liquidation_distance_pct = ((current_rate - liquidation_price) / current_rate) * 100

            risk_metrics.update({
                "liquidation_price": liquidation_price,
                "liquidation_distance_pct": float(liquidation_distance_pct),
            })

            # 有效止损价格（考虑清算价）
            if hasattr(trade, 'stoploss_or_liquidation'):
                risk_metrics["stoploss_or_liquidation"] = float(trade.stoploss_or_liquidation)

        return risk_metrics

    def _calculate_position_size_info(self, trade: Any, strategy: Optional[Any]) -> Dict[str, Any]:
        """
        计算仓位大小相关信息，用于调仓决策

        只提供客观数据，不做主观判断（如大/小），让AI自己分析

        Args:
            trade: 交易对象
            strategy: 策略实例

        Returns:
            仓位大小信息字典（纯客观数据）
        """
        position_info = {
            "total_stake_amount": 0.0,
            "position_percent_of_account": 0.0,
            "account_total_balance": 0.0,
            "min_stake_per_trade": 0.0,
        }

        try:
            current_rate = self._get_current_rate(strategy, trade.pair) if strategy else None
            total_stake = self._estimate_trade_stake_value(
                trade,
                current_rate=current_rate,
                strategy=strategy,
            )
            position_info["total_stake_amount"] = total_stake

            # 获取账户总资金
            if strategy:
                is_long = not trade.is_short
                side = "long" if is_long else "short"

                # 获取总资金
                if hasattr(strategy, 'account_enabled') and strategy.account_enabled:
                    # 账户分离模式
                    if is_long:
                        total_balance = float(strategy.long_initial_balance)
                    else:
                        total_balance = float(strategy.short_initial_balance)
                else:
                    # 非账户分离模式
                    if hasattr(strategy, 'wallets') and strategy.wallets:
                        total_balance = strategy.wallets.get_total(strategy.config.get("stake_currency", "USDT"))
                    else:
                        total_balance = 0.0

                position_info["account_total_balance"] = total_balance

                # 计算仓位占比（客观数据，不做判断）
                if total_balance > 0:
                    position_percent = (total_stake / total_balance) * 100
                    position_info["position_percent_of_account"] = position_percent

                # 获取最小下单量配置
                stake_config = self.decision_config.get("stake", {})
                min_stake_config = stake_config.get("min_stake_per_trade")

                if min_stake_config:
                    mode = min_stake_config.get("mode", "percent")
                    value = min_stake_config.get("value", 0)

                    if mode == "fixed":
                        min_per_trade = float(value)
                    elif mode == "percent" and total_balance > 0:
                        min_per_trade = total_balance * (value / 100.0)
                    else:
                        min_per_trade = 0.0

                    position_info["min_stake_per_trade"] = min_per_trade

        except Exception as e:
            logger.warning(f"计算仓位大小信息失败: {e}")

        return position_info

    def _extract_adjustment_history(self, trade: Any, limit: int = 5) -> list[Dict[str, Any]]:
        """
        提取持仓的调仓历史记录

        Args:
            trade: 交易对象
            limit: 返回最近的N条记录（默认5条）

        Returns:
            调仓历史列表，每条记录包含：时间、方向、金额、价格等
        """
        history = []

        try:
            if not hasattr(trade, 'orders') or not trade.orders:
                return history

            # 过滤出已成交的订单，并按时间排序
            filled_orders = [
                order for order in trade.orders
                if order.status in ['closed', 'filled'] and order.filled and order.filled > 0
            ]

            # 按订单时间排序（最新的在前）
            filled_orders.sort(
                key=lambda x: x.order_filled_utc or x.order_date_utc,
                reverse=True
            )

            # 获取最近的N条订单
            recent_orders = filled_orders[:limit]

            for order in recent_orders:
                # 更精确地判断订单类型
                order_side = order.ft_order_side if hasattr(order, 'ft_order_side') and order.ft_order_side else order.side
                if not order_side:
                    order_side = "unknown"

                # 区分入场、加仓、减仓、平仓、止损
                # ft_order_side 可能的值: buy, sell, stoploss
                # 对于多头: buy=入场/加仓, sell=平仓/减仓
                # 对于空头: sell=入场/加仓, buy=平仓/减仓
                is_long_trade = not trade.is_short

                if order_side == "stoploss":
                    action_type = "stoploss"
                    is_entry = False
                elif is_long_trade:
                    # 多头持仓
                    if order_side == "buy":
                        action_type = "buy_long"  # 入场或加仓
                        is_entry = True
                    else:  # sell
                        action_type = "sell_long"  # 平仓或减仓
                        is_entry = False
                else:
                    # 空头持仓
                    if order_side == "sell":
                        action_type = "sell_short"  # 入场或加仓
                        is_entry = True
                    else:  # buy
                        action_type = "buy_short"  # 平仓或减仓
                        is_entry = False

                # 计算订单的投入金额（stake amount）
                stake_amount = order.stake_amount_filled if hasattr(order, 'stake_amount_filled') else 0.0

                # 构建调仓记录 - 使用带时区的时间戳
                adjustment_time = order.order_filled_utc or order.order_date_utc
                if adjustment_time:
                    minutes_ago = (dt_now() - adjustment_time).total_seconds() / 60
                else:
                    minutes_ago = 0

                record = {
                    "time": str(adjustment_time) if adjustment_time else "未知",
                    "minutes_ago": float(minutes_ago),
                    "action": action_type,  # buy_long/sell_long/sell_short/buy_short/stoploss
                    "is_entry": is_entry,  # True=入场/加仓, False=平仓/减仓/止损
                    "price": float(order.safe_price),
                    "amount": float(order.safe_filled),
                    "stake_amount": float(stake_amount),
                    "order_type": order.order_type or "unknown",
                    "order_id": order.order_id,
                    "status": order.status,
                }

                history.append(record)

        except Exception as e:
            logger.warning(f"提取调仓历史失败: {e}")

        return history

    def _estimate_trade_stake_value(
        self,
        trade: Any,
        current_rate: Optional[float] = None,
        strategy: Optional[Any] = None,
    ) -> float:
        """
        根据当前价格估算持仓在 stake 货币中的价值
        """
        rate = current_rate
        if rate is None and strategy is not None:
            try:
                rate = self._get_current_rate(strategy, trade.pair)
            except Exception:
                rate = None

        leverage = float(getattr(trade, "leverage", 1.0) or 1.0)
        if leverage <= 0:
            leverage = 1.0

        if rate:
            try:
                value = trade.calc_close_trade_value(rate)
                value = abs(float(value))
                if leverage > 1.0:
                    value = value / leverage
                return value
            except Exception as e:
                logger.debug(f"估算 {trade.pair} 仓位价值失败，回退到历史投入: {e}")

        if hasattr(trade, 'max_stake_amount') and trade.max_stake_amount:
            return float(trade.max_stake_amount)

        stake_amount = getattr(trade, 'stake_amount', 0.0) or 0.0
        return float(stake_amount)
