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

    # 在1小时K线上执行，同时使用8小时信息数据作为上下文
    timeframe = "1h"
    informative_timeframe = "8h"

    process_only_new_candles = True
    startup_candle_count = 400  # 需要足够的历史数据用于百分位计算

    # 禁用静态止损；依赖custom_exit进行退出
    # 原始设置参考-8%在10倍杠杆下（约0.8%变动）
    stoploss = -1000
    use_custom_stoploss = False  # 本策略用 custom_exit 管理回撤式止盈，硬止损保底

    # 启用仓位调整/DCA
    position_adjustment_enable = True

    # --- 资金分配参数（可超参优化）---
    # single_trade_cap 定义每笔交易资金上限，越大风险越大（2000/15）看比较好
    single_trade_cap = 18

    # 首次入场规模占single_trade_cap的比例
    first_entry_ratio = 0.19

    # add_seq_X值定义连续DCA入场的相对规模
    # 可根据市场条件调整
    add_seq_1 = DecimalParameter(0.05, 0.2, default=0.10, decimals=2, space="buy", optimize=False)
    add_seq_2 = DecimalParameter(0.05, 0.2, default=0.10, decimals=2, space="buy", optimize=False)
    add_seq_3 = DecimalParameter(0.10, 0.30, default=0.20, decimals=2, space="buy", optimize=False)
    add_seq_4 = DecimalParameter(0.20, 0.50, default=0.40, decimals=2, space="buy", optimize=False)

    # 全局仓位上限限制总仓位使用
    global_exposure_cap = DecimalParameter(
        0.3, 0.8, default=0.50, decimals=2, space="buy", optimize=False
    )

    # 连续DCA入场之间的冷却时间（天）
    add_cooldown_days = IntParameter(1, 10, default=3, space="buy", optimize=False)

    # 当ATR%表示高波动时缩放规模的软上限
    atrp_soft_cap = DecimalParameter(
        0.05, 0.30, default=0.18, decimals=2, space="buy", optimize=True
    )

    # DCA前必须达到的利润阈值（负值）
    dca_trigger_loss = DecimalParameter(
        -15.0, -0.5, default=-5.0, decimals=2, space="buy", optimize=False
    )

    # 激活跟踪逻辑的利润水平
    trail_start = DecimalParameter(0.15, 2.00, default=0.5, decimals=2, space="sell", optimize=True)
    # trail_step为每增加5%利润扩大回撤空间
    trail_step = DecimalParameter(0.02, 0.10, default=0.05, decimals=2, space="sell", optimize=True)

    # 8小时高位百分位过滤器配置（3-30天高位）
    highpct_len = IntParameter(15, 90, default=30, space="buy", optimize=True)
    highpct_th = DecimalParameter(0.80, 0.98, default=0.90, decimals=2, space="buy", optimize=True)

    # 基于滚动成交量的流动性过滤器
    vol_sma_len = IntParameter(10, 40, default=20, space="buy", optimize=False)
    min_dollar_vol = IntParameter(200000, 2000000, default=500000, space="buy", optimize=False)

    max_dca_loss = DecimalParameter(-1.0, -400.0, default=-80.0, decimals=1, space="buy")
    max_single_loss = DecimalParameter(-1.0, -500.0, default=-400.0, decimals=1, space="sell")

    # 绘图覆盖配置
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
        "0": 15,  # 瞬间暴跌75%+的情况
    }
    trailing_stop = False  # 不用内建 trailing，改用 custom_exit 做“回撤式”止盈

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
                    f"交易对: {metadata['pair']} | "
                    f"价格: {last_row['close']:.4f} | "
                    f"高点百分比: {last_row.get('high_pct_8h', 0):.2%}"
                )

        return df

    def populate_exit_trend(self, df: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        # Exits handled via custom_exit logic
        df["exit_short"] = 0
        return df

    # ===== 自定义资金管理 =====
    def _current_exposure_ratio(self, wallets) -> float:
        """
        粗略估计当前资金占用（名义），用于不超过 global_exposure_cap。
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
        按 8h ATR% 软限额缩放单币可用 cap（波动越大，可用 cap 越小）。
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
        管控“是否允许新开仓”与“初始开仓金额”：
          - 若全局占用 > cap → 不开仓（返回 0）
          - 初始开仓 = min(pair_cap_after_atr * first_entry_ratio, 余额允许)
        """
        if side != "short":
            return 0.0

        wallets = kwargs.get("wallets")
        if wallets:
            exposure = self._current_exposure_ratio(wallets)
            if exposure >= float(self.global_exposure_cap.value):
                return 0.0

        # 如果ATR数据缺失则中止DCA
        df, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
        pair_cap = self._pair_cap_after_atr(df)
        first_stake = pair_cap * float(self.first_entry_ratio)

        # 遵守平台最大仓位约束
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
        返回 ("sell", amount) 代表继续加仓做空（增加空头头寸）。
        注意：Freqtrade 中对空头的"buy/sell"语义请以版本文档为准，这里沿用 adjust_trade_position 接口约定：
          - 正向增加仓位用 "sell"。

        优化逻辑：
          1. 只在整点小时检查（避免价格噪音）
          2. 只在自上次加仓以来的最高价格点加仓（做空策略中，最高价=最大亏损点）
        """

        # 【整点检查】只在新K线开始时检查加仓条件
        current_candle_start = current_time.replace(minute=0, second=0, microsecond=0)
        last_check_candle = trade.get_custom_data("last_dca_check_candle", None)

        # 如果在同一根K线内已经检查过，跳过
        if last_check_candle == current_candle_start.isoformat():
            return None

        # 记录本次检查的K线时间
        trade.set_custom_data("last_dca_check_candle", current_candle_start.isoformat())

        # 【跟踪最高价格】自上次加仓以来的最高价格（做空策略中代表最大亏损）
        last_high = float(trade.get_custom_data("high_since_last_dca", 0.0))

        # 更新最高价格记录
        if current_rate > last_high:
            trade.set_custom_data("high_since_last_dca", current_rate)
            last_high = current_rate
            logger.debug(
                f"【更新加仓参考高点】{trade.pair} | "
                f"新高点: {current_rate:.4f} | "
                f"当前亏损: {current_profit:.2%}"
            )

        # Skip if global exposure already at cap
        wallets = kwargs.get("wallets")
        if wallets:
            exposure = self._current_exposure_ratio(wallets)
            if exposure >= float(self.global_exposure_cap.value):
                logger.debug(
                    f"【跳过加仓】{trade.pair} | 原因: 全局仓位占用过高 ({exposure:.2%})"
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

        # 【最高点检查】只在价格等于或非常接近最高点时加仓
        # 允许0.05%的误差范围（避免因为微小价格波动错过加仓机会）
        if last_high > 0:
            price_diff_pct = abs(last_high - current_rate) / last_high
            if price_diff_pct > 0.0005:  # 0.05%误差
                logger.debug(
                    f"【跳过加仓】{trade.pair} | "
                    f"原因: 未达最高点 | "
                    f"当前价格: {current_rate:.4f} | "
                    f"最高点: {last_high:.4f} | "
                    f"差异: {price_diff_pct:.4%}"
                )
                return None

        # Determine pair-specific cap after ATR scaling
        df, _ = self.dp.get_analyzed_dataframe(pair=trade.pair, timeframe=self.timeframe)
        pair_cap = self._pair_cap_after_atr(df)

        # Remaining capital available for this pair
        used = float(trade.stake_amount)  # 已使用资金（非名义+保证金之分，这里按 stake）
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
                f"【跳过加仓】{trade.pair} | 原因: 已达最大加仓次数 ({after_first}/{len(add_seq)})"
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
            f"【加仓 #{after_first + 1}】{trade.pair} | "
            f"加仓金额: {will_add:.2f} USDT | "
            f"总入场次数: {trade.nr_of_successful_entries + 1} | "
            f"当前收益: {current_profit:.2%} | "
            f"价格: {current_rate:.4f} | "
            f"已用/上限: {used:.2f}/{pair_cap:.2f} | "
            f"ATR%: {atrp:.2%} | "
            f"距上次: {delta_days}天 | "
            f"加仓时高点: {last_high:.4f}"
        )

        # 加仓后重置最高价格记录，开始跟踪新一轮的价格变化
        trade.set_custom_data("high_since_last_dca", current_rate)

        return will_add, f"dca_{after_first + 1}"

    # ===== 跟踪回撤退出 =====
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
        逻辑：
          - 当利润 >= trail_start 时，记录 max_profit
          - 若 (max_profit - current_profit) >= 动态阈值 → 触发退出
          - 动态阈值：基础 0.03 + floor( (max_profit - trail_start)/0.05 ) * trail_step
            （即每多 5% 盈利，回撤容忍 + trail_step）
        """
        # 【实盘行为一致性】只在新K线开始时检查退出条件
        # 计算当前K线的开始时间（对齐到整点小时）
        current_candle_start = current_time.replace(minute=0, second=0, microsecond=0)
        last_check_candle = trade.get_custom_data("last_exit_check_candle", None)


        # 如果在同一根K线内已经检查过，跳过（避免价格噪音）
        if last_check_candle == current_candle_start.isoformat():
            return None

        # 记录本次检查的K线时间
        trade.set_custom_data("last_exit_check_candle", current_candle_start.isoformat())

        # 1. 硬止损保护
        if current_profit <= float(self.max_single_loss.value):
            logger.critical(f"🛑【硬止损】{pair} | {current_profit:.2%}")
            return "hard_stoploss"

        # 2. 多次DCA后的累积亏损保护
        if trade.nr_of_successful_entries >= 3:
            max_allow = float(self.max_dca_loss.value)
            if current_profit <= max_allow:
                logger.critical(
                    f"🛑【DCA累积止损】{pair} | {current_profit:.2%} | 入场{trade.nr_of_successful_entries}次"
                )
                return "dca_max_loss"

        start = float(self.trail_start.value)
        step = float(self.trail_step.value)

        maxp = float(trade.get_custom_data("max_profit", -1.0))

        if current_profit >= start:
            if current_profit > maxp:
                trade.set_custom_data("max_profit", current_profit)
                logger.debug(
                    f"【更新最高收益】{pair} | "
                    f"新最高: {current_profit:.2%} | "
                    f"价格: {current_rate:.4f}"
                )
                return None

            # 推导允许回撤
            # 示例: start=0.5, step=0.05
            # 示例: max_profit=0.7 => over=0.2 => floor(...)=2 => allow=0.1
            over = max(0.0, maxp - start)
            buckets = int(np.floor(over / 0.10))
            allow_draw = step * (1 + buckets)
            drawdown = maxp - current_profit

            if drawdown >= allow_draw:
                logger.info(
                    f"【回撤止盈】{pair} | "
                    f"最高收益: {maxp:.2%} | "
                    f"当前收益: {current_profit:.2%} | "
                    f"回撤: {drawdown:.2%} | "
                    f"允许回撤: {allow_draw:.2%} | "
                    f"价格: {current_rate:.4f} | "
                    f"持仓: {(current_time - trade.open_date_utc).days}天"
                )
                return "trail_drawdown_exit"

        else:
            # 当利润低于激活阈值时重置跟踪
            if maxp > 0:
                trade.set_custom_data("max_profit", -1.0)

        return None
