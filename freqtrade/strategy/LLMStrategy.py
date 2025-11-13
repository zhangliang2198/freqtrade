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
    
    # 风险管理
    # stoploss = -0.10
    trailing_stop = False
    use_custom_stoploss = False

    # Strategy interface version
    INTERFACE_VERSION = 3
    stoploss = -99999
    
    # 启用仓位调整 (DCA/金字塔)
    position_adjustment_enable = True
    max_entry_position_adjustment = 999
    
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

        # 检查该交易对是否已有持仓，如果有则跳过入场分析（节省 LLM 成本）
        pair = metadata.get("pair", "")
        if pair and self._has_open_position(pair):
            return dataframe

        # 检查是否有可用资金，如果没有资金则跳过分析（节省 LLM 成本）
        if not self._has_available_funds_for_entry():
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

            pair = metadata.get("pair", "UNKNOWN")

            # 创建请求
            request = LLMRequest(
                decision_point="entry",
                pair=pair,
                context=context
            )

            # 获取 LLM 决策
            response = self.llm_engine.decide(request)

            # 应用决策
            if response.decision == "buy":
                dataframe.loc[dataframe.index[-1], "enter_long"] = 1
                confidence_tag = f"llm_entry_c{int(response.confidence * 100)}"
                dataframe.loc[dataframe.index[-1], "enter_tag"] = confidence_tag
                logger.info(
                    f"🎯 LLM 入场 {pair}: 开多 "
                    f"(confidence={response.confidence:.2f}, reason={self._shorten_reason(response.reasoning)})"
                )

            elif response.decision == "sell" and self.can_short:
                dataframe.loc[dataframe.index[-1], "enter_short"] = 1
                confidence_tag = f"llm_short_c{int(response.confidence * 100)}"
                dataframe.loc[dataframe.index[-1], "enter_tag"] = confidence_tag
                logger.info(
                    f"🎯 LLM 入场 {pair}: 开空 "
                    f"(confidence={response.confidence:.2f}, reason={self._shorten_reason(response.reasoning)})"
                )

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
                logger.info(
                    f"🛑 LLM 触发 {pair} 出场 "
                    f"(confidence={response.confidence:.2f}, reason={self._shorten_reason(response.reasoning)})"
                )
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

        # 检查对应方向是否有可用资金，如果没有则跳过 LLM 分析（节省成本）
        if not self._has_available_funds_for_side(side):
            logger.info(f"⏭️  跳过 {pair} {side.upper()} 的 stake 分析：{side.upper()} 账户资金不足")
            # 返回 proposed_stake 让 Freqtrade 框架自己处理资金不足的情况
            # 如果确实没钱，Freqtrade 会拒绝开仓；如果有钱但低于阈值，仍然可以开仓
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

            # 构建上下文（传入实际可用余额和交易方向，让 LLM 知道资金限制）
            context = self.llm_engine.context_builder.build_stake_context(
                pair=pair,
                current_rate=current_rate,
                dataframe=dataframe,
                available_balance=available_balance,
                strategy=self,
                side=side
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

            # 应用每次开单的最小/最大额度限制（如果配置了）
            max_stake_config = point_config.get("max_stake_per_trade")
            min_stake_config = point_config.get("min_stake_per_trade")

            # 获取账户总资金（用于百分比计算）
            if self.strict_account_mode:
                total_balance = self.long_initial_balance if side == "long" else self.short_initial_balance
            else:
                total_balance = self.wallets.get_total(self.config["stake_currency"]) if hasattr(self, 'wallets') and self.wallets else available_balance

            # 应用最大额度限制
            if max_stake_config:
                mode = max_stake_config.get("mode", "percent")
                value = max_stake_config.get("value", 0)

                if mode == "fixed":
                    max_per_trade = float(value)
                    if adjusted_stake > max_per_trade:
                        logger.info(
                            f"📊 {pair} 开单额度受限于配置的固定最大值: "
                            f"{adjusted_stake:.2f} -> {max_per_trade:.2f} USDT"
                        )
                        adjusted_stake = max_per_trade

                elif mode == "percent":
                    # 百分比模式：基于总资金
                    max_per_trade = total_balance * (value / 100.0)
                    if adjusted_stake > max_per_trade:
                        logger.info(
                            f"📊 {pair} 开单额度受限于总资金的 {value}%: "
                            f"{adjusted_stake:.2f} -> {max_per_trade:.2f} USDT "
                            f"(总资金: {total_balance:.2f})"
                        )
                        adjusted_stake = max_per_trade

            # 应用最小额度限制
            if min_stake_config:
                mode = min_stake_config.get("mode", "percent")
                value = min_stake_config.get("value", 0)

                if mode == "fixed":
                    min_per_trade = float(value)
                    if adjusted_stake < min_per_trade:
                        logger.info(
                            f"📊 {pair} 开单额度低于配置的固定最小值: "
                            f"{adjusted_stake:.2f} -> {min_per_trade:.2f} USDT"
                        )
                        adjusted_stake = min_per_trade

                elif mode == "percent":
                    # 百分比模式：基于总资金
                    min_per_trade = total_balance * (value / 100.0)
                    if adjusted_stake < min_per_trade:
                        logger.info(
                            f"📊 {pair} 开单额度低于总资金的 {value}%: "
                            f"{adjusted_stake:.2f} -> {min_per_trade:.2f} USDT "
                            f"(总资金: {total_balance:.2f})"
                        )
                        adjusted_stake = min_per_trade

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

            # 检查调整是否足够显著（使用 Freqtrade 的最小值）
            if min_stake and abs(adjustment_stake) < min_stake:
                return None

            # 确保在最大投入限制内
            if adjustment_stake > 0:
                adjustment_stake = min(adjustment_stake, max_stake)

            # 应用 llm_config 中配置的最小/最大额度限制（加仓时）
            if adjustment_stake > 0:
                # 从 stake 决策点配置中获取限制
                stake_point_config = self.llm_engine.config.get("decision_points", {}).get("stake", {})

                # 应用最小额度限制
                min_stake_config = stake_point_config.get("min_stake_per_trade")
                if min_stake_config:
                    mode = min_stake_config.get("mode", "percent")
                    value = min_stake_config.get("value", 0)

                    if mode == "fixed":
                        min_per_trade = float(value)
                        if adjustment_stake < min_per_trade:
                            logger.info(
                                f"📊 {trade.pair} 加仓额度低于配置的固定最小值: "
                                f"{adjustment_stake:.2f} < {min_per_trade:.2f} USDT，取消加仓"
                            )
                            return None
                    elif mode == "percent":
                        # 百分比模式：基于账户总资金
                        side = "short" if trade.is_short else "long"
                        if self.strict_account_mode:
                            total_balance = self.long_initial_balance if side == "long" else self.short_initial_balance
                        else:
                            total_balance = self.wallets.get_total(self.config["stake_currency"]) if hasattr(self, 'wallets') and self.wallets else 0

                        min_per_trade = total_balance * (value / 100.0)
                        if adjustment_stake < min_per_trade:
                            logger.info(
                                f"📊 {trade.pair} 加仓额度低于总资金的 {value}%: "
                                f"{adjustment_stake:.2f} < {min_per_trade:.2f} USDT，取消加仓"
                            )
                            return None

                # 应用最大额度限制
                max_stake_config = stake_point_config.get("max_stake_per_trade")
                if max_stake_config:
                    mode = max_stake_config.get("mode", "percent")
                    value = max_stake_config.get("value", 0)

                    if mode == "fixed":
                        max_per_trade = float(value)
                        if adjustment_stake > max_per_trade:
                            logger.info(
                                f"📊 {trade.pair} 加仓额度受限于配置的固定最大值: "
                                f"{adjustment_stake:.2f} -> {max_per_trade:.2f} USDT"
                            )
                            adjustment_stake = max_per_trade
                    elif mode == "percent":
                        # 百分比模式：基于账户总资金
                        side = "short" if trade.is_short else "long"
                        if self.strict_account_mode:
                            total_balance = self.long_initial_balance if side == "long" else self.short_initial_balance
                        else:
                            total_balance = self.wallets.get_total(self.config["stake_currency"]) if hasattr(self, 'wallets') and self.wallets else 0

                        max_per_trade = total_balance * (value / 100.0)
                        if adjustment_stake > max_per_trade:
                            logger.info(
                                f"📊 {trade.pair} 加仓额度受限于总资金的 {value}%: "
                                f"{adjustment_stake:.2f} -> {max_per_trade:.2f} USDT"
                            )
                            adjustment_stake = max_per_trade

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

        # 检查对应方向是否有可用资金，如果没有则跳过 LLM 分析（节省成本）
        if not self._has_available_funds_for_side(side):
            logger.info(f"⏭️  跳过 {pair} {side.upper()} 的 leverage 分析：{side.upper()} 账户资金不足")
            # 返回默认杠杆，让 Freqtrade 框架处理
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

    def _shorten_reason(self, reasoning: Optional[str], limit: int = 80) -> str:
        """
        将 LLM 返回的推理压缩为简短文本用于日志
        """
        if not reasoning:
            return "无推理"
        reason = " ".join(str(reasoning).split())
        return reason if len(reason) <= limit else f"{reason[:limit]}..."

    def _has_available_funds_for_entry(self) -> bool:
        """
        检查是否有可用资金进行入场分析

        考虑账户分离和做空功能，如果所有账户都没有可用资金则返回 False

        Returns:
            如果至少有一个方向有可用资金则返回 True
        """
        if not hasattr(self, 'wallets') or not self.wallets:
            # 没有钱包信息，默认允许分析
            return True

        try:
            # 从 llm_config 中获取最小可用余额百分比阈值
            llm_config = self.config.get("llm_config", {})
            fund_check_config = llm_config.get("fund_check", {})
            min_balance_pct = fund_check_config.get("min_available_balance_pct", 1.0) * 100

            # 如果启用了账户分离
            if hasattr(self, 'account_enabled') and self.account_enabled:
                long_available = self.get_account_available_balance("long") if hasattr(self, 'get_account_available_balance') else 0
                short_available = self.get_account_available_balance("short") if hasattr(self, 'get_account_available_balance') else 0

                # 计算最小阈值（基于初始余额的百分比）
                long_initial = float(self.long_initial_balance) if hasattr(self, 'long_initial_balance') else 0
                short_initial = float(self.short_initial_balance) if hasattr(self, 'short_initial_balance') else 0

                long_threshold = long_initial * (min_balance_pct / 100.0)
                short_threshold = short_initial * (min_balance_pct / 100.0)

                # 检查做多账户
                has_long_funds = long_available >= long_threshold

                # 检查做空账户（如果支持做空）
                has_short_funds = short_available >= short_threshold if self.can_short else False

                # 至少一个方向有资金
                if has_long_funds or has_short_funds:
                    return True
                else:
                    logger.debug(
                        f"⏭️  跳过入场分析：所有账户资金不足 "
                        f"(多头可用: {long_available:.2f}/{long_threshold:.2f}, "
                        f"空头可用: {short_available:.2f}/{short_threshold:.2f}, "
                        f"阈值: {min_balance_pct}%)"
                    )
                    return False
            else:
                # 非账户分离模式：检查总可用余额
                stake_currency = self.config.get("stake_currency", "USDT")
                available = self.wallets.get_free(stake_currency)

                # 获取初始余额
                try:
                    initial_balance = self.wallets.get_starting_balance()
                except Exception:
                    initial_balance = self.wallets.get_total(stake_currency)

                min_threshold = initial_balance * (min_balance_pct / 100.0)

                if available >= min_threshold:
                    return True
                else:
                    logger.debug(
                        f"⏭️  跳过入场分析：资金不足 "
                        f"(可用: {available:.2f}/{min_threshold:.2f}, 阈值: {min_balance_pct}%)"
                    )
                    return False

        except Exception as e:
            logger.warning(f"检查资金可用性失败: {e}")
            # 出错时默认允许分析
            return True

    def _has_available_funds_for_side(self, side: str) -> bool:
        """
        检查指定方向是否有可用资金

        Args:
            side: 交易方向 ("long" 或 "short")

        Returns:
            如果指定方向有可用资金则返回 True
        """
        if not hasattr(self, 'wallets') or not self.wallets:
            # 没有钱包信息，默认允许分析
            return True

        try:
            # 从 llm_config 中获取最小可用余额百分比阈值
            llm_config = self.config.get("llm_config", {})
            fund_check_config = llm_config.get("fund_check", {})
            min_balance_pct = fund_check_config.get("min_available_balance_pct", 1.0) * 100

            # 如果启用了账户分离
            if hasattr(self, 'account_enabled') and self.account_enabled:
                if hasattr(self, 'get_account_available_balance'):
                    available = self.get_account_available_balance(side)
                else:
                    available = 0

                # 获取对应账户的初始余额
                if side == "long":
                    initial = float(self.long_initial_balance) if hasattr(self, 'long_initial_balance') else 0
                else:
                    initial = float(self.short_initial_balance) if hasattr(self, 'short_initial_balance') else 0

                min_threshold = initial * (min_balance_pct / 100.0)
            else:
                # 非账户分离模式：使用总可用余额
                stake_currency = self.config.get("stake_currency", "USDT")
                available = self.wallets.get_free(stake_currency)

                # 获取初始余额
                try:
                    initial = self.wallets.get_starting_balance()
                except Exception:
                    initial = self.wallets.get_total(stake_currency)

                min_threshold = initial * (min_balance_pct / 100.0)

            return available >= min_threshold

        except Exception as e:
            logger.warning(f"检查 {side} 方向资金可用性失败: {e}")
            # 出错时默认允许分析
            return True

    def _has_open_position(self, pair: str) -> bool:
        """
        检查指定交易对是否已有持仓

        Args:
            pair: 交易对

        Returns:
            如果有持仓则返回 True
        """
        try:
            from freqtrade.persistence import Trade

            # 检查是否有该交易对的开仓交易
            open_trades = Trade.get_open_trades()
            has_position = any(t.pair == pair for t in open_trades)

            if has_position:
                logger.debug(f"⏭️  跳过 {pair} 入场分析：已有持仓")

            return has_position

        except Exception as e:
            logger.warning(f"检查 {pair} 持仓状态失败: {e}")
            # 出错时默认不跳过（保守策略）
            return False

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
