"""Readable score, position and strategy status tables."""

from __future__ import annotations

import math
from datetime import datetime

from leader_squeeze_support import (
    DISPLAY_TZ,
    LOG_ERROR,
    LOG_INFO,
    LOG_WARN,
    LeaderMixinContext,
    _log_table,
    logger,
    report_snapshot,
)

from freqtrade.persistence import Trade


class LeaderReportingMixin(LeaderMixinContext):
    def _trend_labels(self, pair: str) -> list[str]:
        names = {"unknown": "数据不足", "weakening": "走弱", "up": "上行", "consolidating": "整理"}
        return [
            names[self._trend_context(pair, self.settings[key])["state"]]
            for key in ("holding_timeframe", "background_timeframe")
        ]

    @staticmethod
    def _opening_score_label(trade: Trade | None) -> str:
        """Use recorded entry data only; old signal tags remain explicitly labelled."""
        if trade is None:
            return "未记录"
        getter = getattr(trade, "get_custom_data", None)
        if callable(getter):
            record = getter("leader_entry_score")
            if isinstance(record, dict):
                score = record.get("score")
                if (
                    score is not None
                    and type(score) in (int, float)
                    and math.isfinite(score)
                    and score >= 0
                ):
                    return f"{score:.1f}"
        tag = getattr(trade, "enter_tag", None)
        if isinstance(tag, str) and tag.startswith("squeeze_"):
            try:
                score = float(tag.removeprefix("squeeze_"))
                if math.isfinite(score) and score >= 0:
                    return f"{score:.1f}(标签)"
            except ValueError:
                pass
        return "未记录"

    @report_snapshot
    def _log_strategy_status(self, now: float) -> None:
        """使用本轮已有结果打印状态, 不为日志额外请求行情或执行交易。"""
        rotation = getattr(self, "_rotation_state", None) or {}
        phase = {
            "buy": "准备先买",
            "buy_pending": "等待买入确认",
            "sell": "等待旧仓退出",
            "review": "需要核对订单",
        }.get(rotation.get("phase", ""), "无轮换")
        signature = (
            self._entry_block_reason,
            tuple(sorted(self._entry_pairs)),
            self._rotation_pair,
            self._rotation_target,
            phase,
        )
        if signature == self._last_status_signature and now - self._last_status_log < float(
            self.settings["status_log_seconds"]
        ):
            return
        self._last_status_signature, self._last_status_log = signature, now

        def age(timestamp: float) -> str:
            return f"{max(0, now - timestamp):.0f}s" if timestamp else "从未成功"

        heat_labels: dict[str, list[str]] = {}

        def heat_cells(pair: str) -> list[str]:
            if pair not in heat_labels:
                if not self.settings["entry_heat_max_penalty"]:
                    heat_labels[pair] = ["—", "关闭"]
                elif (heat := self._entry_heat_metrics(pair)) is not None:
                    heat_labels[pair] = [
                        f"{100 * heat['return_15d']:+.1f}%",
                        f"{100 * heat['penalty']:.1f}%",
                    ]
                else:
                    heat_labels[pair] = ["未知", "未知"]
            return heat_labels[pair]

        fresh_count, total, required = self._score_coverage(now)
        logger.info(
            "🧭 策略状态 | 全局开仓=%s | 上批评分=%s 当前有效=%s/%s (至少%s) 评分年龄=%s | "
            "评分任务=%s 下次刷新=%s | 仓位同步=%s 年龄=%s | 强平流=%s 心跳年龄=%s | "
            "市场状态=%s",
            self._entry_block_reason or "允许 (仍须通过逐币筛选)",
            "成功" if self._data_healthy else "等待/不足",
            fresh_count,
            total,
            required,
            age(self._last_good_data),
            "进行中" if self._score_pending else "空闲",
            "等待后台结果"
            if math.isinf(self._next_score_refresh)
            else f"{max(0, self._next_score_refresh - now):.0f}s 后",
            "正常" if self._position_data_healthy else "异常",
            age(self._last_position_sync),
            "已连接" if self._liquidation_connected.is_set() else "断开",
            age(self._liquidation_last_message),
            "未知"
            if not self._market_data_healthy
            else "严重普跌"
            if getattr(self, "_market_emergency", False)
            else "转弱/暂停买入"
            if self._market_down
            else "非普跌",
            extra=LOG_WARN if self._entry_block_reason else LOG_INFO,
        )
        ranked = self._ranked_pairs()
        ranks = {pair: str(rank) for rank, (pair, _) in enumerate(ranked, 1)}
        ranked_scores = dict(ranked)
        decision_pairs = list(
            dict.fromkeys(
                [
                    *ranked_scores,
                    *self._entry_decisions,
                    *sorted(self._entry_pairs),
                ]
            )
        )
        _log_table(
            "🎯 选币结果",
            ["排名", "交易对", "买入评分", "15日涨幅", "热度折扣", "本轮入选", "筛选结果"],
            [
                [
                    ranks.get(pair, "—"),
                    pair,
                    f"{ranked_scores[pair]:.1f}"
                    if math.isfinite(ranked_scores.get(pair, math.nan))
                    else "—",
                    *heat_cells(pair),
                    "是" if pair in self._entry_pairs else "否",
                    self._entry_decisions.get(pair, self._entry_block_reason or "尚未评估"),
                ]
                for pair in decision_pairs
            ],
            caption=(self._entry_block_reason + " | " if self._entry_block_reason else "")
            + "热度折扣为评分扣减比例; 买入评分已扣除折扣",
        )
        positions = self._wallets.get_all_positions()
        db_trades = {trade.pair: trade for trade in Trade.get_open_trades()}
        db_pairs = set(db_trades)
        logger.info(
            "📦 仓位状态 | 已占用=%s 常规上限=%s 轮换临时上限=%s | 数据库持仓数=%s | "
            "外部接管=%s | 钱包缓存仓位数=%s",
            len(db_pairs | self._external_pairs),
            self.settings["max_positions"],
            int(self.settings["max_positions"]) + 1,
            len(db_pairs),
            "开启" if self.settings["manage_external_positions"] else "关闭",
            len(positions),
            extra=LOG_INFO,
        )
        holding_rows, holding_styles = [], []
        for pair in sorted(set(positions) | db_pairs | self._external_pairs):
            trade = db_trades.get(pair)
            position = positions.get(pair)
            detail = self._position_details.get(pair, {})
            mark = detail.get("markPrice")
            try:
                mark = float(mark)
                current_price = f"{mark:.8g}" if math.isfinite(mark) and mark > 0 else "未知"
            except (TypeError, ValueError):
                current_price = "未知"
            if current_price != "未知" and (
                not self._position_data_healthy
                or not 0
                <= now - self._last_position_sync
                <= self.settings["position_stale_seconds"]
            ):
                current_price += "(旧)"
            entry_score = self._opening_score_label(trade)
            protection = (
                "—"
                if trade
                else (
                    (
                        "交易所止损已确认"
                        if self.order_types.get("stoploss_on_exchange")
                        else "本地监控正常 (不新建交易所止损)"
                    )
                    if self._external_stop_protected.get(pair, False)
                    else "未确认/异常"
                )
            )
            if position is None:
                holding_rows.append(
                    [
                        pair,
                        "策略仓位" if trade else "外部仓位",
                        "钱包缓存缺失",
                        "—",
                        "—",
                        "—",
                        current_price,
                        entry_score,
                        *heat_cells(pair),
                        "—",
                        "—",
                        "—",
                        protection,
                        *self._trend_labels(pair),
                    ]
                )
                holding_styles.append("yellow")
                continue
            holding_rows.append(
                [
                    pair,
                    "策略仓位" if trade else "外部仓位",
                    "多单" if position.side == "long" else "空单",
                    f"{position.position:.8f}",
                    str(
                        position.leverage
                        or detail.get("leverage")
                        or getattr(trade, "leverage", "未知")
                    ),
                    str(getattr(trade, "open_rate", None) or detail.get("entryPrice") or "未知"),
                    current_price,
                    entry_score,
                    *heat_cells(pair),
                    f"{position.unrealized_pnl:+.2f}",
                    str(trade.stoploss_or_liquidation) if trade else "见外部止损检查",
                    ("有" if trade.has_open_sl_orders else "无")
                    if trade
                    else (
                        "未核验 (不新建)"
                        if not self.order_types.get("stoploss_on_exchange")
                        else "已确认"
                        if self._external_stop_protected.get(pair, False)
                        else "未确认"
                    ),
                    protection,
                    *self._trend_labels(pair),
                ]
            )
            holding_styles.append("green" if position.unrealized_pnl >= 0 else "red")
        _log_table(
            "📦 持仓明细",
            [
                "交易对",
                "来源",
                "方向",
                "数量",
                "杠杆",
                "开仓价",
                "当前价(标记)",
                "开仓分数",
                "15日涨幅",
                "热度折扣",
                f"未实现盈亏({self.config['stake_currency']})",
                "策略止损价",
                "交易所止损记录",
                "外部风控",
                f"{self.settings['holding_timeframe']}趋势",
                f"{self.settings['background_timeframe']}背景",
            ],
            holding_rows,
            style="cyan",
            row_styles=holding_styles,
            caption="当前价使用最近同步标记价, (旧)表示同步失效; 热度折扣仅供新买入参考; "
            "开仓分数取下单复核记录, (标签)为历史信号分, 旧版可能未扣热度",
        )
        state = self._risk_state
        equity = float(state.get("last_equity", 0))
        day_start = float(state.get("day_start_equity", 0))
        peak = float(state.get("peak_equity", 0))
        logger.info(
            "🛡️ 账户风控 | 权益=%.2f %s | UTC日收益=%s (仅统计, 不限制开仓) | "
            "峰值回撤=%s (仅统计, 不清仓、不限制开仓) | 状态文件=%s 权益更新时间(UTC)=%s | "
            "轮换候选=%s 确认=%s/%s 旧仓=%s 目标=%s 阶段=%s 通道=%s",
            equity,
            self.config["stake_currency"],
            f"{(equity / day_start - 1) * 100:+.2f}%" if day_start > 0 else "未知",
            f"{(1 - equity / peak) * 100:.2f}%" if peak > 0 else "未知",
            "读取失败, 暂停开仓并保留原文件"
            if getattr(self, "_risk_state_load_failed", False)
            else "读取正常/首次初始化",
            state.get("updated_at", "尚未更新"),
            self._rotation_candidate,
            self._rotation_seen,
            self.settings[
                "replacement_fast_confirmations"
                if getattr(self, "_rotation_candidate_channel", None) == "fast"
                else "replacement_confirmations"
            ],
            self._rotation_pair,
            self._rotation_target,
            phase,
            (getattr(self, "_rotation_state", None) or {}).get("channel")
            or getattr(self, "_rotation_candidate_channel", None)
            or "—",
            extra=LOG_ERROR if getattr(self, "_risk_state_load_failed", False) else LOG_INFO,
        )

    @report_snapshot
    def _log_score_tables(self, now: float, valid: dict[str, dict[str, float]]) -> None:
        score_rows, metric_rows, funding_rows, heat_rows = [], [], [], []
        ranks = {pair: str(rank) for rank, (pair, _) in enumerate(self._ranked_pairs(), 1)}
        # 使用本批评分的选币快照, 避免后台取数期间白名单刷新造成来源误标。
        selected = set(getattr(self, "_score_selection", getattr(self, "_score_leaders", ranks)))
        selected_count = len(selected.intersection(valid))
        for pair in sorted(
            valid, key=lambda pair: (int(ranks.get(pair, len(ranks) + 1)), -self._scores[pair])
        ):
            item = valid[pair]
            contributions = [
                f"{100 * self.settings['weights'][name] * item[f'score_{name}']:.1f}"
                for name in (
                    "short_crowding",
                    "momentum",
                    "volume",
                    "taker_buy",
                    "liquidation",
                    "oi_squeeze",
                    "funding",
                )
            ]
            score_rows.append(
                [
                    ranks.get(pair, "—"),
                    pair,
                    f"{self._scores[pair]:.1f}",
                    "本轮选币" if pair in selected else "持仓监控",
                    *contributions,
                    *self._trend_labels(pair),
                ]
            )
            if self.settings["entry_heat_max_penalty"]:
                heat = self._entry_heat_metrics(pair)
                heat_rows.append(
                    [
                        pair,
                        f"{100 * heat['return_15d']:+.1f}%",
                        f"{heat['extension_atr']:.2f}",
                        "是" if heat["cooled_breakout"] else "否",
                        f"{100 * heat['penalty']:.1f}%",
                        f"{self._current_score(pair) * (1 - heat['penalty']):.1f}",
                    ]
                    if heat is not None
                    else [pair, "行情不足/无效", "—", "—", "—", "禁止买入"]
                )
            metric_rows.append(
                [
                    pair,
                    f"{100 * item.get('short_account_share', item['short_share']):.1f}%",
                    f"{100 * item.get('short_position_share', item['short_share']):.1f}%",
                    f"{100 * item['short_share']:.1f}%",
                    f"{100 * item['momentum']:+.2f}%",
                    f"{round(3 * item['trend_continuity'])}/3",
                    f"{item['volume_ratio']:.2f}",
                    f"{item['volume_activity_ratio']:.2f}",
                    f"{item['taker_ratio']:.2f}",
                    f"{item['taker_ratio_latest']:.2f}",
                    f"{100 * item['oi_change']:+.2f}%",
                ]
            )
            if item.get("_funding_valid_until", 0) > now:
                funding_rows.append(
                    [
                        pair,
                        f"{100 * item['funding_rate']:+.5f}%",
                        f"{item['funding_interval_hours']:.0f}h",
                        f"{100 * item['funding_rate_hourly']:+.5f}%",
                        f"{800 * item['funding_rate_hourly']:+.5f}%",
                        f"{100 * item['funding_floor']:+.5f}%",
                        f"{100 * item['funding_cap']:+.5f}%",
                        f"{100 * item['score_funding']:.1f}%",
                        f"{100 * self.settings['weights']['funding'] * item['score_funding']:.2f}",
                        datetime.fromtimestamp(item["funding_next_time"], DISPLAY_TZ).strftime(
                            "%m-%d %H:%M:%S"
                        ),
                    ]
                )
            else:
                funding_rows.append(
                    [pair, "不可用/已过期", "—", "—", "—", "—", "—", "—", "0.00", "—"]
                )
        _log_table(
            "📊 评分明细 (原评分, 轮换还需小时趋势走弱)",
            [
                "买入排名",
                "交易对",
                "原评分",
                "来源",
                "空头",
                "动量",
                "放量",
                "主动买",
                "强平",
                "OI",
                "资金费",
                f"{self.settings['holding_timeframe']}趋势",
                f"{self.settings['background_timeframe']}背景",
            ],
            score_rows,
            caption=(
                f"本批评分 {len(valid)} 个 = 本轮选币 {selected_count} 个"
                f" + 榜外持仓监控 {len(valid) - selected_count} 个; "
                f"选币池共 {len(selected)} 个; 已在选币池的持仓不重复计数; 本轮选币不代表买入"
            ),
        )
        if heat_rows:
            _log_table(
                "🌡️ 入场过热评估",
                [
                    "交易对",
                    "15日涨幅",
                    f"偏离EMA{self.settings['entry_heat_ema_candles']}/ATR",
                    "整理突破",
                    "评分折扣",
                    "买入评分",
                ],
                heat_rows,
                caption="只影响买入; 旧仓轮换仍按原评分衡量强弱",
            )
        _log_table(
            "📈 原始指标",
            [
                "交易对",
                "空头人数",
                "空头持仓量",
                "最终取高",
                "1h涨幅",
                "15m上涨",
                "短期量比",
                "持续量比",
                f"主动买卖比({self.settings['taker_window_candles']}根)",
                "主动买卖比(最新)",
                "OI变化",
            ],
            metric_rows,
            caption=(
                f"近期均量={self.settings['volume_window_candles']}根; "
                f"短期/持续基准={self.settings['volume_baseline_windows']}/"
                f"{self.settings['volume_activity_baseline_candles']}根, 均排除近期窗口"
            ),
        )
        _log_table(
            "💰 资金费率",
            [
                "交易对",
                "本期费率",
                "间隔",
                "每小时",
                "等效8h",
                "本期下限",
                "本期上限",
                "收取上限利用率",
                "加分",
                "下次结算(北京)",
            ],
            funding_rows,
            caption="负费率: 空头付给多头; 正/零费率不加分; "
            "数据不可用/已过期不单独拦截; 非到账承诺",
        )
