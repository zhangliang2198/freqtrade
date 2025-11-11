"""
LLM 辅助策略基类

为使用 LLM 进行交易决策的策略提供基类。
"""

import logging
from typing import Optional, Any
from datetime import datetime

import pandas as pd

from freqtrade.strategy import BaseStrategyWithSnapshot
from freqtrade.llm.engine import LLMDecisionEngine, LLMRequest

logger = logging.getLogger(__name__)


class LLMStrategy(BaseStrategyWithSnapshot):
    """
    LLM 辅助策略基类

    此基类将 LLM 决策集成到 Freqtrade 策略框架中。
    它提供由 LLM 驱动的关键决策点实现：
    - 入场信号 (populate_entry_trend)
    - 出场信号 (custom_exit)
    - 仓位大小 (custom_stake_amount)
    - 仓位调整 (adjust_trade_position)
    - 杠杆控制 (leverage)

    子类必须实现 populate_indicators() 并可以覆盖
    任何决策方法来自定义行为。

    示例:
        class MyLLMStrategy(LLMStrategy):
            timeframe = "5m"
            stoploss = -0.10

            def populate_indicators(self, dataframe, metadata):
                # 添加您的指标
                dataframe['rsi'] = ta.RSI(dataframe)
                return dataframe
    """

    # Strategy interface version
    INTERFACE_VERSION = 3

    # LLM engine instance (initialized in bot_start)
    llm_engine: Optional[LLMDecisionEngine] = None

    def __init__(self, config) -> None:
        """
        初始化 LLM 策略

        调用父类初始化以启用资产快照和账户分离功能
        """
        super().__init__(config)

    def bot_start(self, **kwargs) -> None:
        """
        机器人启动时初始化 LLM 决策引擎

        这在机器人启动时调用一次。如果配置中启用了 LLM，
        则初始化决策引擎。
        """
        llm_config = self.config.get("llm_config", {})

        if llm_config.get("enabled", False):
            try:
                self.llm_engine = LLMDecisionEngine(
                    config=self.config,
                    strategy_name=self.__class__.__name__
                )
                logger.info(
                    f"LLM 决策引擎已为 {self.__class__.__name__} 初始化，"
                    f"使用 {llm_config['provider_type']}/{llm_config['model']}"
                )

            except Exception as e:
                logger.error(f"初始化 LLM 引擎失败: {e}", exc_info=True)
                logger.error("LLM 引擎初始化失败，程序将终止。请检查 LLM 配置。")
                raise RuntimeError(f"LLM 引擎初始化失败: {e}")
        else:
            logger.info("配置中 LLM 已禁用")

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        使用 LLM 确定入场信号

        Args:
            dataframe: 包含指标的数据框
            metadata: 附加信息如交易对

        Returns:
            添加了入场信号的数据框
        """
        if not self.llm_engine:
            # LLM 未启用或初始化失败，直接返回不做任何操作
            return dataframe

        # 只在最后一根K线上做决策
        if len(dataframe) < 1:
            return dataframe

        try:
            # 构建上下文
            portfolio_state = self._get_portfolio_state() if hasattr(self, 'wallets') else None
            context = self.llm_engine.context_builder.build_entry_context(
                dataframe=dataframe,
                metadata=metadata,
                portfolio_state=portfolio_state,
                strategy=self
            )

            # 创建请求
            request = LLMRequest(
                decision_point="entry",
                pair=metadata["pair"],
                context=context
            )

            # 获取 LLM 决策
            response = self.llm_engine.decide(request)

            # 应用决策
            if response.decision == "buy":
                dataframe.loc[dataframe.index[-1], "enter_long"] = 1
                confidence_tag = f"llm_entry_c{int(response.confidence * 100)}"
                dataframe.loc[dataframe.index[-1], "enter_tag"] = confidence_tag

            elif response.decision == "sell" and self.can_short:
                dataframe.loc[dataframe.index[-1], "enter_short"] = 1
                confidence_tag = f"llm_short_c{int(response.confidence * 100)}"
                dataframe.loc[dataframe.index[-1], "enter_tag"] = confidence_tag

            # 'hold' 决策表示不入场

        except Exception as e:
            logger.error(f"LLM 入场决策失败: {e}", exc_info=True)
            # 发生错误时直接略过，不执行任何操作

        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        """
        使用 LLM 确定是否应该退出仓位

        Args:
            pair: 交易对
            trade: 交易对象
            current_time: 当前时间戳
            current_rate: 当前市场价格
            current_profit: 当前利润率

        Returns:
            如果应该退出则返回退出原因字符串，否则返回 None
        """
        if not self.llm_engine:
            # LLM 未启用或初始化失败，直接返回不做任何操作
            return None

        try:
            # 获取当前数据框
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

            if len(dataframe) == 0:
                return None

            # 构建上下文
            context = self.llm_engine.context_builder.build_exit_context(
                trade=trade,
                current_rate=current_rate,
                dataframe=dataframe,
                strategy=self
            )

            # 创建请求
            request = LLMRequest(
                decision_point="exit",
                pair=pair,
                context=context,
                trade_id=trade.id
            )

            # 获取 LLM 决策
            response = self.llm_engine.decide(request)

            # 应用决策
            if response.decision in ["exit", "sell"]:
                # 截断推理以适应退出原因
                reason = response.reasoning[:30] if response.reasoning else "llm_exit"
                return f"llm_{reason.replace(' ', '_')}"

        except Exception as e:
            logger.error(f"LLM 出场决策失败: {e}", exc_info=True)
            # 发生错误时直接略过，不执行任何操作

        return None

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """
        使用 LLM 动态调整仓位大小

        Args:
            pair: 交易对
            current_time: 当前时间戳
            current_rate: 当前市场价格
            proposed_stake: 建议的投入金额
            min_stake: 最小投入金额
            max_stake: 最大投入金额
            leverage: 当前杠杆
            entry_tag: 入场标签
            side: 交易方向 (多头/空头)

        Returns:
            调整后的投入金额
        """
        if not self.llm_engine:
            return proposed_stake

        try:
            # 先获取账户的实际可用余额（考虑账户分离模式）
            if self.strict_account_mode:
                # 严格账户模式：获取指定方向账户的可用余额
                available_balance = self.get_account_available_balance(side)
            else:
                # 非严格模式：使用钱包总余额
                if hasattr(self, 'wallets') and self.wallets:
                    available_balance = self.wallets.get_free(self.config["stake_currency"])
                else:
                    available_balance = proposed_stake

            # 获取当前数据框
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

            if len(dataframe) == 0:
                return proposed_stake

            # 构建上下文（传入实际可用余额，让 LLM 知道资金限制）
            context = self.llm_engine.context_builder.build_stake_context(
                pair=pair,
                current_rate=current_rate,
                dataframe=dataframe,
                available_balance=available_balance,
                strategy=self
            )

            # 创建请求
            request = LLMRequest(
                decision_point="stake",
                pair=pair,
                context=context
            )

            # 获取 LLM 决策
            response = self.llm_engine.decide(request)

            # 应用决策
            if response.decision == "default":
                return proposed_stake

            # 从参数中获取投入倍数
            stake_multiplier = response.parameters.get("stake_multiplier", 1.0)

            # 从配置中获取限制
            point_config = self.llm_engine.config.get("decision_points", {}).get("stake", {})
            min_multiplier = point_config.get("min_stake_multiplier", 0.5)
            max_multiplier = point_config.get("max_stake_multiplier", 2.0)

            # 限制倍数范围
            stake_multiplier = max(min_multiplier, min(stake_multiplier, max_multiplier))

            # 计算调整后的投入
            adjusted_stake = proposed_stake * stake_multiplier

            # 确保在限制范围内
            if min_stake:
                adjusted_stake = max(adjusted_stake, min_stake)
            adjusted_stake = min(adjusted_stake, max_stake)

            # 再次检查账户余额限制（双重保险，防止 LLM 决策超出可用余额）
            allowed, final_stake = self.check_account_balance_limit(
                side=side,
                proposed_stake=adjusted_stake,
                pair=pair
            )

            if not allowed:
                # 账户余额不足，不允许开仓
                logger.warning(
                    f"⚠️ LLM 仓位决策被拒绝 {pair}: "
                    f"调整后仓位 {adjusted_stake:.2f} 超过 {side.upper()} 账户可用余额 "
                    f"(可用: {available_balance:.2f})"
                )
                return 0.0

            # 记录调整信息
            if final_stake != proposed_stake:
                logger.info(
                    f"💰 LLM 调整了 {pair} 的仓位: "
                    f"{proposed_stake:.2f} -> {final_stake:.2f} "
                    f"(multiplier: {stake_multiplier:.2f}, {side.upper()} 可用: {available_balance:.2f})"
                )

            return final_stake
    
        except Exception as e:
            logger.error(f"LLM 仓位调整决策失败: {e}", exc_info=True)
            return proposed_stake

    def adjust_trade_position(
        self,
        trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs
    ) -> Optional[float]:
        """
        使用 LLM 确定是否应该调整仓位 (DCA/金字塔)

        Args:
            trade: 交易对象
            current_time: 当前时间戳
            current_rate: 当前市场价格
            current_profit: 当前利润率
            min_stake: 调整的最小投入金额
            max_stake: 调整的最大投入金额
            (其他参数按照 Freqtrade 接口)

        Returns:
            要添加 (正数) 或移除 (负数) 的投入金额，无变化则返回 None
        """
        if not self.llm_engine:
            return None

        try:
            # 获取当前数据框
            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)

            if len(dataframe) == 0:
                return None

            # 构建上下文
            context = self.llm_engine.context_builder.build_adjust_position_context(
                trade=trade,
                current_time=current_time,
                current_rate=current_rate,
                current_profit=current_profit,
                dataframe=dataframe,
                strategy=self
            )

            # 创建请求
            request = LLMRequest(
                decision_point="adjust_position",
                pair=trade.pair,
                context=context,
                trade_id=trade.id
            )

            # 获取 LLM 决策
            response = self.llm_engine.decide(request)

            # 应用决策
            if response.decision == "no_change":
                return None

            # 从参数中获取调整比例
            adjustment_ratio = response.parameters.get("adjustment_ratio", 0.0)

            # 从配置中获取最大比例
            point_config = self.llm_engine.config.get("decision_points", {}).get("adjust_position", {})
            max_ratio = point_config.get("max_adjustment_ratio", 0.3)

            # 限制比例范围
            adjustment_ratio = max(-max_ratio, min(adjustment_ratio, max_ratio))

            # 计算调整投入
            adjustment_stake = trade.stake_amount * adjustment_ratio

            # 检查调整是否足够显著
            if min_stake and abs(adjustment_stake) < min_stake:
                return None

            # 确保在最大投入限制内
            if adjustment_stake > 0:
                adjustment_stake = min(adjustment_stake, max_stake)

            logger.info(
                f"LLM 调整了 {trade.pair} 的持仓: "
                f"{'add' if adjustment_stake > 0 else 'reduce'} "
                f"{abs(adjustment_stake):.2f} (ratio: {adjustment_ratio:.2%})"
            )

            return adjustment_stake

        except Exception as e:
            logger.error(f"LLM 调仓决策失败: {e}", exc_info=True)
            return None

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """
        使用 LLM 动态调整杠杆

        Args:
            pair: 交易对
            current_time: 当前时间戳
            current_rate: 当前市场价格
            proposed_leverage: 建议的杠杆值
            max_leverage: 允许的最大杠杆
            entry_tag: 入场标签
            side: 交易方向 (多头/空头)

        Returns:
            调整后的杠杆值
        """
        if not self.llm_engine:
            return proposed_leverage

        try:
            # 获取当前数据框
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

            if len(dataframe) == 0:
                return proposed_leverage

            # 构建上下文
            context = self.llm_engine.context_builder.build_leverage_context(
                pair=pair,
                current_rate=current_rate,
                proposed_leverage=proposed_leverage,
                max_leverage=max_leverage,
                dataframe=dataframe,
                strategy=self
            )

            # 创建请求
            request = LLMRequest(
                decision_point="leverage",
                pair=pair,
                context=context
            )

            # 获取 LLM 决策
            response = self.llm_engine.decide(request)

            # 应用决策
            if response.decision == "default":
                return proposed_leverage

            # 从参数中获取杠杆
            llm_leverage = response.parameters.get("leverage", proposed_leverage)

            # 从配置中获取限制
            point_config = self.llm_engine.config.get("decision_points", {}).get("leverage", {})
            min_leverage = point_config.get("min_leverage", 1.0)
            max_leverage_config = point_config.get("max_leverage", 10.0)

            # 限制杠杆范围
            llm_leverage = max(
                min_leverage,
                min(llm_leverage, max_leverage_config, max_leverage)
            )

            logger.info(
                f"LLM 调整了 {pair} 的杠杆: "
                f"{proposed_leverage:.1f}x -> {llm_leverage:.1f}x"
            )

            return llm_leverage

        except Exception as e:
            logger.error(f"LLM 杠杆决策失败: {e}", exc_info=True)
            return proposed_leverage

    def _get_portfolio_state(self) -> Optional[dict]:
        """
        获取当前投资组合状态作为上下文

        Returns:
            包含投资组合信息的字典
        """
        if not hasattr(self, 'wallets') or not self.wallets:
            return None

        try:
            from freqtrade.persistence import Trade

            # 获取开仓交易
            open_trades = Trade.get_open_trades()

            return {
                "total_stake": sum(t.stake_amount for t in open_trades),
                "open_trade_count": len(open_trades),
                "available_balance": self.wallets.get_free(self.config["stake_currency"]),
                "total_balance": self.wallets.get_total(self.config["stake_currency"]),
            }
        except Exception as e:
            logger.warning(f"获取持仓状态失败: {e}")
            return None

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """
        在每个机器人循环开始时调用

        先调用父类方法记录资产快照，再定期记录 LLM 统计信息。
        """
        # 先调用父类方法，记录资产快照
        super().bot_loop_start(current_time=current_time, **kwargs)

        # 定期记录 LLM 统计信息 (每10次调用)
        if self.llm_engine and self.llm_engine.stats["total_calls"] % 100 == 0:
            stats = self.llm_engine.get_stats()
            logger.info(
                f"LLM 统计: {stats['total_calls']} 次调用, "
                f"{stats['cache_hit_rate']:.1%} cache hit rate, "
                f"${stats['total_cost_usd']:.2f} total cost, "
                f"{stats['errors']} errors"
            )

    def log_strategy_specific_info(
        self, current_time: datetime, asset_data: dict[str, Any], **kwargs
    ) -> None:
        """
        记录 LLM 策略特定的信息

        由父类 BaseStrategyWithSnapshot 在每个 loop 调用，
        用于输出 LLM 引擎的状态信息。
        """
        if not self.llm_engine:
            return

        stats = self.llm_engine.get_stats()
        logger.info("🤖 【LLM 引擎状态】")
        logger.info(f"  总调用次数: {stats['total_calls']:>12}")
        logger.info(f"  缓存命中率: {stats['cache_hit_rate']:>11.1%}")
        logger.info(f"  总成本: ${stats['total_cost_usd']:>12.2f}")
        logger.info(f"  错误次数: {stats['errors']:>12}")

    def get_extra_snapshot_data(self, asset_data: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        保存 LLM 统计信息到数据库快照

        由父类 BaseStrategyWithSnapshot 调用，
        返回的数据将保存到 strategy_snapshots 表的 extra_data 字段。
        """
        if not self.llm_engine:
            return None

        stats = self.llm_engine.get_stats()
        return {
            'llm_total_calls': stats['total_calls'],
            'llm_cache_hit_rate': stats['cache_hit_rate'],
            'llm_total_cost_usd': stats['total_cost_usd'],
            'llm_errors': stats['errors'],
        }
