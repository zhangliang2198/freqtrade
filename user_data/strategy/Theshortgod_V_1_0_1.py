from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
import logging

import numpy as np
import pandas as pd
import talib.abstract as ta

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    CategoricalParameter,
    DecimalParameter,
    IntParameter,
    IStrategy,
    merge_informative_pair,
)

logger = logging.getLogger(__name__)

INTERFACE_VERSION = 3


"""
Strategy summary:
1) Short-only futures strategy (can_short=True).
2) Uses 8h informative candles merged into the 1h execution timeframe to gate entries (EMA trend + high-percentile filter).
3) Fixed stake cap with configurable DCA trigger and scaling sequences.
4) Trailing profit capture handled via custom_exit drawdown logic.
5) ATR-based exposure cap and cooldown slow down position stacking.
"""  # noqa: RUF001

class Theshortgod_V_1_0_1(IStrategy):
    can_short = True

    # Execute on 1h candles, using 8h informative data as context
    timeframe = "1h"
    informative_timeframe = "8h"

    process_only_new_candles = True
    startup_candle_count = 400  # Need sufficient historical data for percentile calculations

    # Disable static stoploss; rely on custom_exit for exits
    # Original setting reference: -8% at 10x leverage (~0.8% price move)
    stoploss = -1000
    use_custom_stoploss = False  # This strategy uses custom_exit for drawdown-based profit taking, hard stop as backup

    # Enable position adjustment/DCA
    position_adjustment_enable = True

    # --- Capital allocation parameters (hyperopt-optimizable) ---
    # single_trade_cap defines capital limit per trade, higher = more risk (2000/15 looks good)
    single_trade_cap = 18

    # Initial entry size as ratio of single_trade_cap
    first_entry_ratio = 0.19

    # add_seq_X values define relative size for sequential DCA entries
    # Can be adjusted based on market conditions
    add_seq_1 = DecimalParameter(0.05, 0.2, default=0.10, decimals=2, space="buy", optimize=False)
    add_seq_2 = DecimalParameter(0.05, 0.2, default=0.10, decimals=2, space="buy", optimize=False)
    add_seq_3 = DecimalParameter(0.10, 0.30, default=0.20, decimals=2, space="buy", optimize=False)
    add_seq_4 = DecimalParameter(0.20, 0.50, default=0.40, decimals=2, space="buy", optimize=False)

    # Global exposure cap limits total position usage
    global_exposure_cap = DecimalParameter(
        0.3, 0.8, default=0.50, decimals=2, space="buy", optimize=False
    )

    # Cooldown time between consecutive DCA entries (days)
    add_cooldown_days = IntParameter(1, 10, default=3, space="buy", optimize=False)

    # Soft cap for scaling size when ATR% indicates high volatility
    atrp_soft_cap = DecimalParameter(
        0.05, 0.30, default=0.18, decimals=2, space="buy", optimize=True
    )

    # Profit threshold (negative value) required before DCA
    dca_trigger_loss = DecimalParameter(
        -15.0, -0.5, default=-5.0, decimals=2, space="buy", optimize=False
    )

    # Profit level to activate trailing logic
    trail_start = DecimalParameter(0.15, 2.00, default=0.5, decimals=2, space="sell", optimize=True)
    # trail_step expands drawdown tolerance for each 5% profit increase
    trail_step = DecimalParameter(0.02, 0.10, default=0.05, decimals=2, space="sell", optimize=True)

    # 8h high percentile filter configuration (3-30 day highs)
    highpct_len = IntParameter(15, 90, default=30, space="buy", optimize=True)
    highpct_th = DecimalParameter(0.80, 0.98, default=0.90, decimals=2, space="buy", optimize=True)

    # Liquidity filter based on rolling volume
    vol_sma_len = IntParameter(10, 40, default=20, space="buy", optimize=False)
    min_dollar_vol = IntParameter(200000, 2000000, default=500000, space="buy", optimize=False)

    max_dca_loss = DecimalParameter(-1.0, -400.0, default=-80.0, decimals=1, space="buy")
    max_single_loss = DecimalParameter(-1.0, -500.0, default=-400.0, decimals=1, space="sell")

    # Plot overlay configuration
    plot_config = {
        "main_plot": {
            "ema50_8h": {"color": "orange"},
            "ema200_8h": {"color": "red"},
            "bb_upper_1h": {"color": "blue"},
            "bb_mid_1h": {"color": "gray"},
        },
        "subplots": {
            "ATR%": {"atrp_8h": {"color": "purple"}},
        },
    }

    minimal_roi = {
        "0": 15,  # Case of instant 75%+ crash
    }
    trailing_stop = False  # Don't use built-in trailing, use custom_exit for "drawdown-based" profit taking

    # ------- Leverage settings -------
    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        side: str,
        **kwargs,
    ) -> float:
        # Cap leverage by the exchange maximum
        return min(20.0, max_leverage)

    # ===== Indicator preparation =====
    def informative_pairs(self):
        # Merge 8h informative dataframe entries
        return [(pair, self.informative_timeframe) for pair in self.dp.current_whitelist()]

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Core 1h indicators
        bb = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0, matype=0)
        dataframe["bb_upper_1h"] = bb["upperband"]
        dataframe["bb_mid_1h"] = bb["middleband"]

        # Build 8h informative indicators
        inf_8h = self.dp.get_pair_dataframe(
            pair=metadata["pair"], timeframe=self.informative_timeframe
        )
        inf_8h["ema50"] = ta.EMA(inf_8h, timeperiod=50)
        inf_8h["ema200"] = ta.EMA(inf_8h, timeperiod=200)
        inf_8h["hh"] = inf_8h["close"].rolling(int(self.highpct_len.value)).max()
        inf_8h["high_pct"] = (inf_8h["close"] / inf_8h["hh"]).clip(upper=1.0)
        atr_8h = ta.ATR(inf_8h, timeperiod=14)
        inf_8h["atrp"] = (atr_8h / inf_8h["close"]).abs()

        # Liquidity metrics on 1h candles
        dataframe["vol_sma"] = dataframe["volume"].rolling(int(self.vol_sma_len.value)).mean()
        dataframe["dollar_vol"] = dataframe["vol_sma"] * dataframe["close"]

        # Merge informative columns back onto the 1h frame
        dataframe = merge_informative_pair(
            dataframe, inf_8h, self.timeframe, self.informative_timeframe, ffill=True
        )

        return dataframe

    # ===== Entry logic (short only) =====
    def populate_entry_trend(self, df: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df["enter_short"] = 0

        conds = []
        # Market regime filters
        conds += [
            (df["ema50_8h"] > df["ema200_8h"]),  # Informative downtrend
            (df["high_pct_8h"] >= float(self.highpct_th.value)),
            (df["close"] >= df["bb_mid_1h"]),
            (df["dollar_vol"] >= int(self.min_dollar_vol.value)),
        ]

        if conds:
            entry_mask = np.logical_and.reduce(conds)
            entry_mask = pd.Series(entry_mask, index=df.index)
            df.loc[entry_mask, "enter_short"] = 1

            # Log entries for the latest candle when triggered
            if entry_mask.any() and entry_mask.iloc[-1]:
                last_row = df.iloc[-1]
                logger.info(
                    f"Pair: {metadata['pair']} | "
                    f"Price: {last_row['close']:.4f} | "
                    f"High Percentile: {last_row.get('high_pct_8h', 0):.2%}"
                )

        return df

    def populate_exit_trend(self, df: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Exits handled via custom_exit logic
        df["exit_short"] = 0
        return df

    # ===== Custom capital management =====
    def _current_exposure_ratio(self, wallets) -> float:
        """
        Roughly estimate current capital usage (notional) to stay under global_exposure_cap.
        """
        try:
            total = float(wallets.get_total_balance())
            avail = float(wallets.get_total(stake=True))
            used = max(total - avail, 0.0)
            return used / total if total > 0 else 1.0
        except Exception:
            return 0.0

    def _pair_cap_after_atr(self, df: pd.DataFrame) -> float:
        """
        Scale per-pair available cap by 8h ATR% soft limit (higher volatility = smaller cap).
        """
        if df.empty or "atrp_8h" not in df.columns:
            return float(self.single_trade_cap)

        atrp = float(df["atrp_8h"].iloc[-1])
        soft_cap = float(self.atrp_soft_cap.value)
        base = float(self.single_trade_cap)

        if np.isnan(atrp) or atrp <= 0:
            return base

        # Scale position down once ATR% exceeds the soft cap
        if atrp <= soft_cap:
            return base
        scale = max(0.5, soft_cap / atrp)
        return base * scale

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        """
        Control whether new position is allowed and initial position size:
          - If global usage > cap → no new position (return 0)
          - Initial stake = min(pair_cap_after_atr * first_entry_ratio, available balance)
        """
        if side != "short":
            return 0.0

        wallets = kwargs.get("wallets")
        if wallets:
            exposure = self._current_exposure_ratio(wallets)
            if exposure >= float(self.global_exposure_cap.value):
                return 0.0

        # Abort DCA if ATR data missing
        df, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
        pair_cap = self._pair_cap_after_atr(df)
        first_stake = pair_cap * float(self.first_entry_ratio)

        # Respect platform max position constraints
        return max(0.0, min(first_stake, max_stake))

    # ===== DCA logic (enforces cooldown / loss thresholds) =====
    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[Tuple[str, float]]:
        """
        Return ("sell", amount) represents continuing to add to short position.
        Note: For Freqtrade short "buy/sell" semantics refer to version docs, following adjust_trade_position interface:
          - Use "sell" to increase position.

        Optimization logic:
          1. Only check at hourly candles (avoid price noise)
          2. Only add at highest price since last DCA (in short strategy, highest price = max loss point)
        """

        # [Hourly Check] Only check DCA conditions at new candle start
        current_candle_start = current_time.replace(minute=0, second=0, microsecond=0)
        last_check_candle = trade.get_custom_data("last_dca_check_candle", None)

        # Skip if already checked within same candle
        if last_check_candle == current_candle_start.isoformat():
            return None

        # Record current candle check time
        trade.set_custom_data("last_dca_check_candle", current_candle_start.isoformat())

        # [Track Highest Price] Highest price since last DCA (represents max loss in short strategy)
        last_high = float(trade.get_custom_data("high_since_last_dca", 0.0))

        # Update highest price record
        if current_rate > last_high:
            trade.set_custom_data("high_since_last_dca", current_rate)
            last_high = current_rate
            logger.debug(
                f"[Update DCA Reference High]{trade.pair} | "
                f"New high: {current_rate:.4f} | "
                f"Current loss: {current_profit:.2%}"
            )

        # Skip if global exposure already at cap
        wallets = kwargs.get("wallets")
        if wallets:
            exposure = self._current_exposure_ratio(wallets)
            if exposure >= float(self.global_exposure_cap.value):
                logger.debug(
                    f"[Skip DCA]{trade.pair} | Reason: Global exposure too high ({exposure:.2%})"
                )
                return None

        # Honour the cooldown between filled entries
        last_entry = trade.open_date_utc
        if trade.is_short and trade.nr_of_successful_entries > 1:
            filled_entries = trade.select_filled_orders(trade.entry_side)
            filled_dates = [o.order_filled_date for o in filled_entries if o.order_filled_date]
            if filled_dates:
                last_entry = max(filled_dates)

        if last_entry:
            delta_days = (current_time.replace(tzinfo=timezone.utc) - last_entry).days
            if delta_days < int(self.add_cooldown_days.value):
                return None

        # Require configured drawdown before adding again
        trigger_loss = float(self.dca_trigger_loss.value)
        if not np.isfinite(current_profit) or current_profit > trigger_loss:
            return None

        # [High Point Check] Only add when price equals or very close to highest point
        # Allow 0.05% tolerance (avoid missing DCA due to minor price fluctuations)
        if last_high > 0:
            price_diff_pct = abs(last_high - current_rate) / last_high
            if price_diff_pct > 0.0005:  # 0.05% tolerance
                logger.debug(
                    f"[Skip DCA]{trade.pair} | "
                    f"Reason: Not at highest point | "
                    f"Current price: {current_rate:.4f} | "
                    f"Highest point: {last_high:.4f} | "
                    f"Difference: {price_diff_pct:.4%}"
                )
                return None

        # Determine pair-specific cap after ATR scaling
        df, _ = self.dp.get_analyzed_dataframe(pair=trade.pair, timeframe=self.timeframe)
        pair_cap = self._pair_cap_after_atr(df)

        # Remaining capital available for this pair
        used = float(trade.stake_amount)  # Used capital (based on stake, not notional+margin distinction)
        remain = max(pair_cap - used, 0.0)
        if remain <= 0:
            return None

        # Select DCA size from sequence based on prior fills
        # Sequence index uses number of successful entries minus one
        after_first = max(trade.nr_of_successful_entries - 1, 0)
        add_seq = [
            float(self.add_seq_1.value),
            float(self.add_seq_2.value),
            float(self.add_seq_3.value),
            float(self.add_seq_4.value),
        ]

        if after_first >= len(add_seq):
            logger.debug(
                f"[Skip DCA]{trade.pair} | Reason: Max DCA count reached ({after_first}/{len(add_seq)})"
            )
            return None

        # Compute target add size
        will_add = pair_cap * add_seq[after_first]
        will_add = min(will_add, remain)

        # Ensure wallet balance can fund the addition
        if wallets:
            avail = float(wallets.get_total(stake=True))
            if will_add > avail:
                will_add = max(0.0, avail * 0.95)

        if will_add <= 0:
            return None

        # Log DCA activity for debugging
        atrp = df["atrp_8h"].iloc[-1] if "atrp_8h" in df.columns else 0
        logger.info(
            f"[DCA #{after_first + 1}】{trade.pair} | "
            f"DCA amount: {will_add:.2f} USDT | "
            f"Total entries: {trade.nr_of_successful_entries + 1} | "
            f"Current profit: {current_profit:.2%} | "
            f"Price: {current_rate:.4f} | "
            f"Used/Cap: {used:.2f}/{pair_cap:.2f} | "
            f"ATR%: {atrp:.2%} | "
            f"Since last: {delta_days}days | "
            f"High at DCA: {last_high:.4f}"
        )

        # Reset highest price record after DCA, start tracking new price changes
        trade.set_custom_data("high_since_last_dca", current_rate)

        return will_add, f"dca_{after_first + 1}"

    # ===== Trailing drawdown exit =====
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        """
        Logic:
          - When profit >= trail_start, record max_profit
          - If (max_profit - current_profit) >= dynamic threshold → trigger exit
          - Dynamic threshold: base 0.03 + floor( (max_profit - trail_start)/0.05 ) * trail_step
            (i.e., for every 5% more profit, drawdown tolerance + trail_step)
        """
        # [Live Trading Consistency] Only check exit conditions at new candle start
        # Calculate current candle start time (aligned to hour)
        current_candle_start = current_time.replace(minute=0, second=0, microsecond=0)
        last_check_candle = trade.get_custom_data("last_exit_check_candle", None)


        # Skip if already checked within same candle（avoid price noise）
        if last_check_candle == current_candle_start.isoformat():
            return None

        # Record current candle check time
        trade.set_custom_data("last_exit_check_candle", current_candle_start.isoformat())

        # 1. Hard stoploss protection
        if current_profit <= float(self.max_single_loss.value):
            logger.critical(f"[Hard Stoploss]{pair} | {current_profit:.2%}")
            return "hard_stoploss"

        # 2. Cumulative loss protection after multiple DCA
        if trade.nr_of_successful_entries >= 3:
            max_allow = float(self.max_dca_loss.value)
            if current_profit <= max_allow:
                logger.critical(
                    f"[DCA Cumulative Stoploss]{pair} | {current_profit:.2%} | entries{trade.nr_of_successful_entries} times"
                )
                return "dca_max_loss"

        start = float(self.trail_start.value)
        step = float(self.trail_step.value)

        maxp = float(trade.get_custom_data("max_profit", -1.0))

        if current_profit >= start:
            if current_profit > maxp:
                trade.set_custom_data("max_profit", current_profit)
                logger.debug(
                    f"[Update Max Profit]{pair} | "
                    f"New max: {current_profit:.2%} | "
                    f"Price: {current_rate:.4f}"
                )
                return None

            # Derive allowed drawdown
            # Example: start=0.5, step=0.05
            # Example: max_profit=0.7 => over=0.2 => floor(...)=2 => allow=0.1
            over = max(0.0, maxp - start)
            buckets = int(np.floor(over / 0.10))
            allow_draw = step * (1 + buckets)
            drawdown = maxp - current_profit

            if drawdown >= allow_draw:
                logger.info(
                    f"[Drawdown Exit]{pair} | "
                    f"Max profit: {maxp:.2%} | "
                    f"Current profit: {current_profit:.2%} | "
                    f"Drawdown: {drawdown:.2%} | "
                    f"Allowed Drawdown: {allow_draw:.2%} | "
                    f"Price: {current_rate:.4f} | "
                    f"Position held: {(current_time - trade.open_date_utc).days}days"
                )
                return "trail_drawdown_exit"

        else:
            # Reset tracking when profit below activation threshold
            if maxp > 0:
                trade.set_custom_data("max_profit", -1.0)

        return None




















