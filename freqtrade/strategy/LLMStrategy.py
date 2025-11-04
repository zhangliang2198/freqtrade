"""
LLM-Assisted Strategy Base Class

Provides a base class for strategies that use LLM for trading decisions.
"""

import logging
from typing import Optional
from datetime import datetime

import pandas as pd

from freqtrade.strategy import IStrategy
from freqtrade.llm.engine import LLMDecisionEngine, LLMRequest

logger = logging.getLogger(__name__)


class LLMStrategy(IStrategy):
    """
    LLM-Assisted Strategy Base Class

    This base class integrates LLM decision making into the Freqtrade strategy framework.
    It provides LLM-powered implementations of key decision points:
    - Entry signals (populate_entry_trend)
    - Exit signals (custom_exit)
    - Position sizing (custom_stake_amount)
    - Position adjustment (adjust_trade_position)
    - Leverage control (leverage)

    Subclasses must implement populate_indicators() and can override
    any decision method to customize behavior.

    Example:
        class MyLLMStrategy(LLMStrategy):
            timeframe = "5m"
            stoploss = -0.10

            def populate_indicators(self, dataframe, metadata):
                # Add your indicators
                dataframe['rsi'] = ta.RSI(dataframe)
                return dataframe
    """

    # Strategy interface version
    INTERFACE_VERSION = 3

    # LLM engine instance (initialized in bot_start)
    llm_engine: Optional[LLMDecisionEngine] = None

    def bot_start(self, **kwargs) -> None:
        """
        Initialize the LLM decision engine when the bot starts

        This is called once at bot startup. If LLM is enabled in config,
        it initializes the decision engine.
        """
        llm_config = self.config.get("llm_config", {})

        if llm_config.get("enabled", False):
            try:
                self.llm_engine = LLMDecisionEngine(
                    config=self.config,
                    strategy_name=self.__class__.__name__
                )
                logger.info(
                    f"LLM Decision Engine initialized for {self.__class__.__name__} "
                    f"using {llm_config['provider']}/{llm_config['model']}"
                )

                # Create default templates if requested
                if llm_config.get("create_default_templates", False):
                    self.llm_engine.prompt_manager.create_default_templates()

            except Exception as e:
                logger.error(f"Failed to initialize LLM engine: {e}", exc_info=True)
                self.llm_engine = None
                logger.warning("Strategy will continue without LLM assistance")
        else:
            logger.info("LLM is disabled in config")

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        Use LLM to determine entry signals

        Args:
            dataframe: Dataframe with indicators
            metadata: Additional information like pair

        Returns:
            Dataframe with entry signals added
        """
        if not self.llm_engine:
            return self._populate_entry_trend_fallback(dataframe, metadata)

        # Only decide on the last candle
        if len(dataframe) < 1:
            return dataframe

        try:
            # Build context
            portfolio_state = self._get_portfolio_state() if hasattr(self, 'wallets') else None
            context = self.llm_engine.context_builder.build_entry_context(
                dataframe=dataframe,
                metadata=metadata,
                portfolio_state=portfolio_state
            )

            # Create request
            request = LLMRequest(
                decision_point="entry",
                pair=metadata["pair"],
                context=context
            )

            # Get LLM decision
            response = self.llm_engine.decide(request)

            # Apply decision
            if response.decision == "buy":
                dataframe.loc[dataframe.index[-1], "enter_long"] = 1
                confidence_tag = f"llm_entry_c{int(response.confidence * 100)}"
                dataframe.loc[dataframe.index[-1], "enter_tag"] = confidence_tag

            elif response.decision == "sell" and self.can_short:
                dataframe.loc[dataframe.index[-1], "enter_short"] = 1
                confidence_tag = f"llm_short_c{int(response.confidence * 100)}"
                dataframe.loc[dataframe.index[-1], "enter_tag"] = confidence_tag

            # 'hold' decision means no entry

        except Exception as e:
            logger.error(f"LLM entry decision failed: {e}", exc_info=True)

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
        Use LLM to determine if position should be exited

        Args:
            pair: Trading pair
            trade: Trade object
            current_time: Current timestamp
            current_rate: Current market rate
            current_profit: Current profit ratio

        Returns:
            Exit reason string if should exit, None otherwise
        """
        if not self.llm_engine:
            return self._custom_exit_fallback(pair, trade, current_time, current_rate, current_profit)

        try:
            # Get current dataframe
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

            if len(dataframe) == 0:
                return None

            # Build context
            context = self.llm_engine.context_builder.build_exit_context(
                trade=trade,
                current_rate=current_rate,
                dataframe=dataframe
            )

            # Create request
            request = LLMRequest(
                decision_point="exit",
                pair=pair,
                context=context,
                trade_id=trade.id
            )

            # Get LLM decision
            response = self.llm_engine.decide(request)

            # Apply decision
            if response.decision in ["exit", "sell"]:
                # Truncate reasoning to fit in exit reason
                reason = response.reasoning[:30] if response.reasoning else "llm_exit"
                return f"llm_{reason.replace(' ', '_')}"

        except Exception as e:
            logger.error(f"LLM exit decision failed: {e}", exc_info=True)

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
        Use LLM to dynamically adjust position size

        Args:
            pair: Trading pair
            current_time: Current timestamp
            current_rate: Current market rate
            proposed_stake: Proposed stake amount
            min_stake: Minimum stake amount
            max_stake: Maximum stake amount
            leverage: Current leverage
            entry_tag: Entry tag
            side: Trade side (long/short)

        Returns:
            Adjusted stake amount
        """
        if not self.llm_engine:
            return proposed_stake

        try:
            # Get available balance
            if hasattr(self, 'wallets') and self.wallets:
                available_balance = self.wallets.get_free(self.config["stake_currency"])
            else:
                available_balance = proposed_stake

            # Get current dataframe
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

            if len(dataframe) == 0:
                return proposed_stake

            # Build context
            context = self.llm_engine.context_builder.build_stake_context(
                pair=pair,
                current_rate=current_rate,
                dataframe=dataframe,
                available_balance=available_balance
            )

            # Create request
            request = LLMRequest(
                decision_point="stake",
                pair=pair,
                context=context
            )

            # Get LLM decision
            response = self.llm_engine.decide(request)

            # Apply decision
            if response.decision == "default":
                return proposed_stake

            # Get stake multiplier from parameters
            stake_multiplier = response.parameters.get("stake_multiplier", 1.0)

            # Get limits from config
            point_config = self.llm_engine.config.get("decision_points", {}).get("stake", {})
            min_multiplier = point_config.get("min_stake_multiplier", 0.5)
            max_multiplier = point_config.get("max_stake_multiplier", 2.0)

            # Clamp multiplier
            stake_multiplier = max(min_multiplier, min(stake_multiplier, max_multiplier))

            # Calculate adjusted stake
            adjusted_stake = proposed_stake * stake_multiplier

            # Ensure within bounds
            if min_stake:
                adjusted_stake = max(adjusted_stake, min_stake)
            adjusted_stake = min(adjusted_stake, max_stake)

            logger.info(
                f"LLM adjusted stake for {pair}: "
                f"{proposed_stake:.2f} -> {adjusted_stake:.2f} "
                f"(multiplier: {stake_multiplier:.2f})"
            )

            return adjusted_stake

        except Exception as e:
            logger.error(f"LLM stake decision failed: {e}", exc_info=True)
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
        Use LLM to determine if position should be adjusted (DCA/pyramid)

        Args:
            trade: Trade object
            current_time: Current timestamp
            current_rate: Current market rate
            current_profit: Current profit ratio
            min_stake: Minimum stake for adjustment
            max_stake: Maximum stake for adjustment
            (other parameters as per Freqtrade interface)

        Returns:
            Stake amount to add (positive) or remove (negative), or None for no change
        """
        if not self.llm_engine:
            return None

        try:
            # Get current dataframe
            dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)

            if len(dataframe) == 0:
                return None

            # Build context
            context = self.llm_engine.context_builder.build_adjust_position_context(
                trade=trade,
                current_time=current_time,
                current_rate=current_rate,
                current_profit=current_profit,
                dataframe=dataframe
            )

            # Create request
            request = LLMRequest(
                decision_point="adjust_position",
                pair=trade.pair,
                context=context,
                trade_id=trade.id
            )

            # Get LLM decision
            response = self.llm_engine.decide(request)

            # Apply decision
            if response.decision == "no_change":
                return None

            # Get adjustment ratio from parameters
            adjustment_ratio = response.parameters.get("adjustment_ratio", 0.0)

            # Get max ratio from config
            point_config = self.llm_engine.config.get("decision_points", {}).get("adjust_position", {})
            max_ratio = point_config.get("max_adjustment_ratio", 0.3)

            # Clamp ratio
            adjustment_ratio = max(-max_ratio, min(adjustment_ratio, max_ratio))

            # Calculate adjustment stake
            adjustment_stake = trade.stake_amount * adjustment_ratio

            # Check if adjustment is significant enough
            if min_stake and abs(adjustment_stake) < min_stake:
                return None

            # Ensure within max_stake limits
            if adjustment_stake > 0:
                adjustment_stake = min(adjustment_stake, max_stake)

            logger.info(
                f"LLM position adjustment for {trade.pair}: "
                f"{'add' if adjustment_stake > 0 else 'reduce'} "
                f"{abs(adjustment_stake):.2f} (ratio: {adjustment_ratio:.2%})"
            )

            return adjustment_stake

        except Exception as e:
            logger.error(f"LLM adjust position decision failed: {e}", exc_info=True)
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
        Use LLM to dynamically adjust leverage

        Args:
            pair: Trading pair
            current_time: Current timestamp
            current_rate: Current market rate
            proposed_leverage: Proposed leverage value
            max_leverage: Maximum allowed leverage
            entry_tag: Entry tag
            side: Trade side (long/short)

        Returns:
            Adjusted leverage value
        """
        if not self.llm_engine:
            return proposed_leverage

        try:
            # Get current dataframe
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

            if len(dataframe) == 0:
                return proposed_leverage

            # Build context
            context = self.llm_engine.context_builder.build_leverage_context(
                pair=pair,
                current_rate=current_rate,
                proposed_leverage=proposed_leverage,
                max_leverage=max_leverage,
                dataframe=dataframe
            )

            # Create request
            request = LLMRequest(
                decision_point="leverage",
                pair=pair,
                context=context
            )

            # Get LLM decision
            response = self.llm_engine.decide(request)

            # Apply decision
            if response.decision == "default":
                return proposed_leverage

            # Get leverage from parameters
            llm_leverage = response.parameters.get("leverage", proposed_leverage)

            # Get limits from config
            point_config = self.llm_engine.config.get("decision_points", {}).get("leverage", {})
            min_leverage = point_config.get("min_leverage", 1.0)
            max_leverage_config = point_config.get("max_leverage", 10.0)

            # Clamp leverage
            llm_leverage = max(
                min_leverage,
                min(llm_leverage, max_leverage_config, max_leverage)
            )

            logger.info(
                f"LLM adjusted leverage for {pair}: "
                f"{proposed_leverage:.1f}x -> {llm_leverage:.1f}x"
            )

            return llm_leverage

        except Exception as e:
            logger.error(f"LLM leverage decision failed: {e}", exc_info=True)
            return proposed_leverage

    # Fallback methods (called when LLM is not available)

    def _populate_entry_trend_fallback(
        self,
        dataframe: pd.DataFrame,
        metadata: dict
    ) -> pd.DataFrame:
        """
        Fallback entry logic when LLM is not available

        Default: no entries. Subclasses can override.
        """
        # By default, don't enter any trades
        return dataframe

    def _custom_exit_fallback(
        self,
        pair: str,
        trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float
    ) -> Optional[str]:
        """
        Fallback exit logic when LLM is not available

        Default: no custom exits. Subclasses can override.
        """
        return None

    def _get_portfolio_state(self) -> Optional[dict]:
        """
        Get current portfolio state for context

        Returns:
            Dictionary with portfolio information
        """
        if not hasattr(self, 'wallets') or not self.wallets:
            return None

        try:
            from freqtrade.persistence import Trade

            # Get open trades
            open_trades = Trade.get_open_trades()

            return {
                "total_stake": sum(t.stake_amount for t in open_trades),
                "open_trade_count": len(open_trades),
                "available_balance": self.wallets.get_free(self.config["stake_currency"]),
                "total_balance": self.wallets.get_total(self.config["stake_currency"]),
            }
        except Exception as e:
            logger.warning(f"Failed to get portfolio state: {e}")
            return None

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """
        Called at the start of each bot loop

        Can be overridden to add custom behavior, like logging LLM stats.
        """
        # Log LLM stats periodically (every 100 calls)
        if self.llm_engine and self.llm_engine.stats["total_calls"] % 100 == 0:
            stats = self.llm_engine.get_stats()
            logger.info(
                f"LLM Stats: {stats['total_calls']} calls, "
                f"{stats['cache_hit_rate']:.1%} cache hit rate, "
                f"${stats['total_cost_usd']:.2f} total cost, "
                f"{stats['errors']} errors"
            )
