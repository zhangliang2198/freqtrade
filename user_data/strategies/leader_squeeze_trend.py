"""Closed-candle multi-timeframe trend decisions, separate from 15m entry scoring."""

from __future__ import annotations

import math

import pandas as pd
from leader_squeeze_support import LeaderMixinContext, report_cached
from pandas import DataFrame

from freqtrade.exchange import timeframe_to_seconds


class LeaderTrendMixin(LeaderMixinContext):
    def _trend_candles(
        self, pair: str, timeframe: str, count: int, *, columns=("high", "low", "close")
    ) -> DataFrame | None:
        """Aggregate complete UTC buckets only; neither partial ends nor missing bars qualify."""
        base_seconds = timeframe_to_seconds(self.timeframe)
        seconds = timeframe_to_seconds(timeframe)
        if timeframe == self.timeframe:
            return self._closed_candles(pair, timeframe, count, columns=columns)
        ratio = seconds // base_seconds
        base = self._closed_candles(pair, self.timeframe, count * ratio, columns=columns)
        if base is None:
            return None
        dates = pd.to_datetime(base["date"], utc=True)
        if (dates.dt.floor(f"{base_seconds}s") != dates).any():
            self._warn_data_unavailable(f"{pair} {timeframe}", "源K线未对齐UTC周期")
            return None
        rules = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        source = base.set_index(dates)
        grouped = source.resample(f"{seconds}s", origin="epoch", label="left", closed="left")
        frame = grouped.agg({key: value for key, value in rules.items() if key in base})
        frame = frame.loc[grouped.size().eq(ratio)].rename_axis("date").reset_index()
        # _closed_candles has already rejected stale, gapped and unclosed source candles.
        if len(frame) < count:
            self._warn_data_unavailable(f"{pair} {timeframe}", "完整聚合K线数量不足")
            return None
        if {"high", "low", "close"}.issubset(frame) and (
            (base["high"] < base["close"]) | (base["low"] > base["close"])
        ).any():
            self._warn_data_unavailable(f"{pair} {timeframe}", "源K线高低收关系无效")
            return None
        return frame

    @report_cached
    def _trend_context(self, pair: str, timeframe: str) -> dict:
        slope = self.settings["trend_slope_candles"]
        frame = self._trend_candles(
            pair,
            timeframe,
            max(self.settings["trend_ema_candles"] + slope, self.settings["atr_period"] + 2),
        )
        if frame is None:
            return {"timeframe": timeframe, "available": False, "state": "unknown"}
        close = frame["close"]
        ema = close.ewm(span=self.settings["trend_ema_candles"], adjust=False).mean()
        atr = self._wilder_atr(frame.iloc[:-1])
        if not math.isfinite(atr) or atr <= 0:
            return {"timeframe": timeframe, "available": False, "state": "unknown"}
        lower_structure = bool(
            frame["high"].iloc[-1] < frame["high"].iloc[-2]
            and frame["low"].iloc[-1] < frame["low"].iloc[-2]
            and close.iloc[-1] < close.iloc[-2]
        )
        below = bool(close.iloc[-1] < ema.iloc[-1])
        falling = bool(ema.iloc[-1] < ema.iloc[-slope - 1])
        weakening = below and (falling or lower_structure)
        state = (
            "weakening"
            if weakening
            else ("up" if close.iloc[-1] > ema.iloc[-1] and not falling else "consolidating")
        )
        return {
            "timeframe": timeframe,
            "available": True,
            "state": state,
            "last_closed_candle": frame.iloc[-1].to_dict(),
            "ema": float(ema.iloc[-1]),
            "reference_ema": float(ema.iloc[-slope - 1]),
            "atr": atr,
            "below_ema": below,
            "ema_falling": falling,
            "lower_high_low": lower_structure,
            "pullback_atr": float((close.iloc[-slope - 1 : -1].max() - close.iloc[-1]) / atr),
        }

    def _multi_timeframe_snapshot(self, pair: str) -> dict:
        return {
            "holding": self._trend_context(pair, self.settings["holding_timeframe"]),
            "background": self._trend_context(pair, self.settings["background_timeframe"]),
            "entry": getattr(self, "_higher_entry_details", {}).get(pair),
            "rotation": getattr(self, "_holding_rotation_details", {}).get(pair),
            "emergency": getattr(self, "_emergency_exit_details", {}).get(pair),
            "exit_reason": getattr(self, "_trend_exit_details", {}).get(pair),
        }

    def _higher_entry_reason(self, pair: str) -> str:
        """A strong 15m launch can bypass early hourly weakness, never a confirmed exit."""
        context = self._trend_context(pair, self.settings["holding_timeframe"])
        exception = False
        if not context["available"]:
            reason = "小时趋势数据不足或无效, 禁止开仓"
        elif context["state"] == "weakening":
            exception = bool(
                self.settings["replacement_fast_enabled"]
                and self._entry_score(pair) >= self._rotation_floor("fast")
                and self._fast_rotation_quality(pair)
            )
            reason = "" if exception else "小时趋势走弱且未满足快速启动条件"
        else:
            reason = ""
        details = getattr(self, "_higher_entry_details", {})
        details[pair] = {
            **context,
            "fast_exception": exception,
            "passed": not reason,
            "reason": reason,
        }
        self._higher_entry_details = details
        return reason

    def _rotation_holding_weak(self, pair: str) -> bool:
        context = self._trend_context(pair, self.settings["holding_timeframe"])
        stalled = self._no_new_high(pair) if context["available"] else False
        passed = bool(
            context["available"]
            and stalled
            and context["state"] == "weakening"
            and context["pullback_atr"] >= self.settings["replacement_weak_atr_drop"]
        )
        details = getattr(self, "_holding_rotation_details", {})
        details[pair] = {
            **context,
            "no_new_high": stalled,
            "passed": passed,
            "required_pullback_atr": self.settings["replacement_weak_atr_drop"],
        }
        self._holding_rotation_details = details
        self._audit_rotation_check(weak=pair, stage="holding_trend", **details[pair])
        return passed

    def _trend_exit_rule(self, pair: str) -> str:
        """Compact rule name for selection tables and exit log deduplication."""
        details = getattr(self, "_trend_exit_details", {}).get(pair, "趋势反转")
        return details.split(" | ", 1)[0]

    def _trend_reversed(self, pair: str) -> bool | None:
        """Hourly normal exits plus independent 15m breaks of pre-existing hourly support."""
        normal = self._timeframe_reversed(pair, self.settings["holding_timeframe"])
        emergency = self._intrabar_reversed(pair)
        if emergency is True or normal is True:
            return True
        return None if normal is None or emergency is None else False

    def _intrabar_reversed(self, pair: str) -> bool | None:
        timeframe = self.settings["holding_timeframe"]
        count = max(self.settings["reversal_lookback_candles"], self.settings["atr_period"] + 1)
        hours = self._trend_candles(pair, timeframe, count + 1)
        candles = self._closed_candles(pair, self.timeframe, 1, columns=("high", "low", "close"))
        details = getattr(self, "_emergency_exit_details", {})
        details[pair] = {"available": False, "passed": False}
        self._emergency_exit_details = details
        if hours is None or candles is None:
            return None
        if ((candles["high"] < candles["close"]) | (candles["low"] > candles["close"])).any():
            return None
        close = float(candles["close"].iloc[-1])
        hour_end = hours["date"] + pd.Timedelta(seconds=timeframe_to_seconds(timeframe))
        recent = candles.tail(self.settings["reversal_emergency_memory_candles"])
        available = False
        for index in range(len(recent) - 1, -1, -1):
            signal = recent.iloc[index]
            # Never use the hour containing this 15m signal to set its own support or ATR.
            reference = hours.loc[hour_end <= signal["date"]]
            if len(reference) < count:
                continue
            support, atr, _ = self._reversal_levels(
                reference, self.settings["reversal_lookback_candles"]
            )
            if not math.isfinite(atr) or atr <= 0:
                continue
            available = True
            threshold = support - self.settings["reversal_intrabar_atr_buffer"] * atr
            broken = float(signal["close"]) < threshold
            carried = close < support - self.settings["reversal_atr_buffer"] * atr and bool(
                (recent["close"].iloc[index:] < support).all()
            )
            if index == len(recent) - 1:
                details[pair] = {
                    "available": True,
                    "passed": False,
                    "support": support,
                    "atr": atr,
                    "threshold": threshold,
                    "close": close,
                    "signal_time": signal["date"],
                    "reference_time": reference["date"].iloc[-1],
                }
            if broken and (index == len(recent) - 1 or carried):
                details[pair] = {
                    "available": True,
                    "passed": True,
                    "support": support,
                    "atr": atr,
                    "threshold": threshold,
                    "close": close,
                    "signal_time": signal["date"],
                    "reference_time": reference["date"].iloc[-1],
                    "carried": index != len(recent) - 1,
                }
                exit_details = getattr(self, "_trend_exit_details", {})
                exit_details[pair] = (
                    f"{self.timeframe}急跌破位/{timeframe}支撑 | 支撑={support:.8g} "
                    f"ATR={atr:.8g} 急跌阈值={threshold:.8g} 收盘={close:.8g}"
                )
                self._trend_exit_details = exit_details
                return True
        return False if available else None

    def _timeframe_reversed(self, pair: str, timeframe: str) -> bool | None:
        """Return None when a complete trend assessment is unavailable."""
        details = getattr(self, "_trend_exit_details", {})
        details.pop(pair, None)
        self._trend_exit_details = details
        lookback = int(self.settings["reversal_lookback_candles"])
        confirmations = int(self.settings["reversal_confirm_candles"])
        dataframe = self._trend_candles(
            pair,
            timeframe,
            max(lookback, self.settings["atr_period"] + 1) + confirmations,
            columns=("high", "low", "close"),
        )
        if dataframe is None:
            return None
        if (
            (dataframe["low"] > dataframe["close"])
            | (dataframe["high"] < dataframe["close"])
            | (dataframe["low"] > dataframe["high"])
        ).any():
            self._warn_data_unavailable(f"{pair} 反转指标", "K线高低收关系无效")
            return None
        # Exclude signal candles from both support and volatility estimates.
        reference = dataframe.iloc[:-confirmations]
        support, atr, pivot = self._reversal_levels(reference, lookback)
        if not math.isfinite(atr) or atr <= 0:
            self._warn_data_unavailable(
                f"{pair} 反转指标", f"ATR{self.settings['atr_period']}缺少有效波动"
            )
            return None
        threshold = support - float(self.settings["reversal_atr_buffer"]) * atr
        fast_threshold = support - float(self.settings["reversal_fast_atr_buffer"]) * atr
        closes = dataframe["close"].iloc[-confirmations:]
        fast_break = bool(closes.iloc[-1] < fast_threshold)
        structure_break = bool((closes < threshold).all())
        slow_count = int(self.settings["reversal_slow_candles"])
        close = dataframe["close"]
        ema20 = close.ewm(span=self.settings["trend_ema_candles"], adjust=False).mean()
        below_ema = close < ema20
        run_start = len(close)
        while run_start > 0 and below_ema.iloc[run_start - 1]:
            run_start -= 1
        slow_drop = float(close.iloc[max(0, run_start - 1)] - close.iloc[-1])
        slow_ready = len(close) >= self.settings["trend_ema_candles"] + slow_count
        slow_reversal = bool(
            slow_ready
            and below_ema.iloc[-slow_count:].all()
            and ema20.iloc[-1] < ema20.iloc[-slow_count - 1]
            and close.iloc[-1] <= close.iloc[-slow_count - 1]
            and slow_drop >= float(self.settings["reversal_slow_atr_drop"]) * atr
        )
        # Reconstruct unrecovered breaks from all available candle history. Do not
        # assume slow confirmation takes over: selloff volatility can raise its ATR.
        carried_break = False
        for offset in range(
            1, len(dataframe) - max(lookback, self.settings["atr_period"] + 1) - confirmations + 1
        ):
            if fast_break or structure_break or slow_reversal:
                break
            old_reference = dataframe.iloc[: -confirmations - offset]
            if close.iloc[-1] >= old_reference["low"].tail(lookback).max():
                continue
            old_support, old_atr, old_pivot = self._reversal_levels(old_reference, lookback)
            if not math.isfinite(old_atr) or old_atr <= 0:
                continue
            old_threshold = old_support - float(self.settings["reversal_atr_buffer"]) * old_atr
            old_fast = old_support - float(self.settings["reversal_fast_atr_buffer"]) * old_atr
            old_closes = close.iloc[-confirmations - offset : -offset]
            broken = old_closes.iloc[-1] < old_fast or (old_closes < old_threshold).all()
            if (
                broken
                and (close.iloc[-offset:] < old_support).all()
                and close.iloc[-1] < old_threshold
            ):
                carried_break = True
                pivot = old_pivot
                support, atr, threshold, fast_threshold = (
                    old_support,
                    old_atr,
                    old_threshold,
                    old_fast,
                )
                break
        reversed_trend = fast_break or structure_break or slow_reversal or carried_break
        if reversed_trend:
            branch = (
                "急跌破位"
                if fast_break
                else "结构破位"
                if structure_break
                else "持续走弱"
                if slow_reversal
                else "破位未收复"
            )
            details[pair] = (
                f"{timeframe}{branch} | "
                f"{'波段支撑' if pivot else '区间支撑'}={support:.8g} "
                f"ATR{self.settings['atr_period']}={atr:.8g} 普通阈值={threshold:.8g} "
                f"急跌阈值={fast_threshold:.8g} | "
                f"最近{confirmations}根收盘="
                + ", ".join(f"{value:.8g}" for value in closes)
                + f" | 慢跌确认={slow_count}根 连续弱势累计下跌={slow_drop:.8g} "
                f"EMA{self.settings['trend_ema_candles']}={ema20.iloc[-1]:.8g}"
            )
            return True
        if not slow_ready:
            self._warn_data_unavailable(f"{pair} 反转指标", "慢跌确认历史不足")
            return None
        return False

    def _reversal_levels(self, reference: DataFrame, lookback: int) -> tuple[float, float, bool]:
        """Calculate causal support and Wilder ATR before a signal window."""
        lows = reference["low"].tail(lookback).reset_index(drop=True)
        side = self.settings["reversal_pivot_side_candles"]
        pivots = [
            index
            for index in range(side, len(lows) - side)
            if lows.iloc[index] < lows.iloc[index - side : index].min()
            and lows.iloc[index] < lows.iloc[index + 1 : index + side + 1].min()
        ]
        support = float(lows.iloc[pivots[-1]] if pivots else lows.min())
        return support, self._wilder_atr(reference), bool(pivots)

    def _wilder_atr(self, reference: DataFrame) -> float:
        """Compute ATR14 from closed history, excluding the candidate signal candle."""
        previous_close = reference["close"].shift(1)
        true_range = DataFrame(
            {
                "range": reference["high"] - reference["low"],
                "high_gap": (reference["high"] - previous_close).abs(),
                "low_gap": (reference["low"] - previous_close).abs(),
            }
        ).max(axis=1)
        # Seed Wilder ATR14 with the first 14 TRs having a previous close.
        period = self.settings["atr_period"]
        atr = float(true_range.iloc[1 : period + 1].mean())
        for value in true_range.iloc[period + 1 :]:
            atr = ((period - 1) * atr + float(value)) / period
        return atr

    def _no_new_high(self, pair: str) -> bool:
        count = self.settings["replacement_no_new_high_candles"]
        dataframe = self._trend_candles(
            pair, self.settings["holding_timeframe"], count, columns=("high",)
        )
        details = getattr(self, "_no_new_high_details", {})
        if dataframe is None or "high" not in dataframe:
            details[pair] = {"available": False}
            self._no_new_high_details = details
            return False
        high = float(dataframe["high"].iloc[-1])
        previous_high = float(dataframe["high"].iloc[-count:-1].max())
        details[pair] = {
            "available": True,
            "timeframe": self.settings["holding_timeframe"],
            "high": high,
            "reference_high": previous_high,
            "passed": high <= previous_high,
        }
        self._no_new_high_details = details
        return high <= previous_high
