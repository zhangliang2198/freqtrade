"""Operational state files and complete rotation event snapshots."""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from leader_squeeze_audit import RotationJournal, json_safe
from leader_squeeze_config import FRAMEWORK_SETTINGS
from leader_squeeze_support import (
    LOG_ERROR,
    LeaderMixinContext,
    logger,
)

from freqtrade.persistence import Trade


class LeaderStorageMixin(LeaderMixinContext):
    def _load_risk_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self._state_path.read_text())
            if not isinstance(state, dict):
                raise ValueError("风控状态必须是JSON对象")
            if type(state.get("account_stopped")) is not bool:
                raise ValueError("account_stopped缺失或不是布尔值")
            for key in ("peak_equity", "day_start_equity", "last_equity"):
                if key != "peak_equity" and key not in state:
                    continue
                value = state.get(key)
                if (
                    value is None
                    or type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value <= 0
                ):
                    raise ValueError(f"{key}缺失或不是正有限数值")
            self._validate_rotation_state(state)
            return state
        except FileNotFoundError:
            # 首次运行没有状态文件是正常情况; 不将损坏/权限错误视为首次运行。
            return {}
        except (ValueError, OSError, OverflowError) as exc:
            self._risk_state_load_failed = True
            logger.error(
                "🚨 风控状态读取失败 | 文件=%s | %s: %s | 暂停新开仓和轮换, "
                "保留原文件; 已有仓位继续止损和退出。请修复状态文件或权限后重启, "
                "不要删除文件重置历史风控",
                self._state_path,
                type(exc).__name__,
                exc,
                extra=LOG_ERROR,
            )
            return {}

    @staticmethod
    def _validate_rotation_state(state: dict[str, Any]) -> None:
        last_rotation = state.get("last_rotation", 0.0)
        if (
            type(last_rotation) not in (int, float)
            or not math.isfinite(last_rotation)
            or last_rotation < 0
        ):
            raise ValueError("last_rotation无效")
        rotation = state.get("rotation")
        if rotation is None:
            return
        if not isinstance(rotation, dict):
            raise ValueError("rotation必须是对象")
        if not all(
            isinstance(rotation.get(key), str) and rotation[key]
            for key in ("weak", "target", "token")
        ):
            raise ValueError("rotation交易对或标识无效")
        if rotation["weak"] == rotation["target"] or rotation.get("phase") not in {
            "buy",
            "buy_pending",
            "sell",
            "review",
        }:
            raise ValueError("rotation阶段无效")
        amount = rotation.get("amount")
        if (
            amount is None
            or type(amount) not in (int, float)
            or not math.isfinite(amount)
            or amount < 0
            or (rotation["phase"] != "buy" and amount <= 0)
        ):
            raise ValueError("rotation数量无效")
        trade_id = rotation.get("weak_trade_id")
        if "weak_trade_id" not in rotation or (
            trade_id is not None and (type(trade_id) is not int or trade_id <= 0)
        ):
            raise ValueError("rotation旧仓记录无效")

    def _save_risk_state(self) -> bool:
        if getattr(self, "_risk_state_load_failed", False):
            return False
        try:
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._risk_state, indent=2))
            temporary.replace(self._state_path)
            self._risk_state_save_failed = False
            return True
        except OSError as exc:
            logger.error("🚨 风控状态保存失败, 暂停新开仓: %s", exc, extra=LOG_ERROR)
            self._data_healthy = False
            self._risk_state_save_failed = True
            return False

    def _initialize_rotation_audit(self) -> None:
        self._rotation_journal = None
        self._audit_run_id = str(uuid4())
        self._audit_fingerprints = {}
        if not self.settings["rotation_audit_enabled"]:
            return
        mode = "dry_run" if self.config.get("dry_run", True) else "live"
        spool = Path(self.config["user_data_dir"]) / self.settings[f"rotation_audit_spool_{mode}"]
        self._rotation_journal = RotationJournal(
            Trade.session.get_bind(),
            spool,
            self.settings["rotation_audit_statement_timeout_ms"],
            self.settings["rotation_audit_retry_seconds"],
        )
        self._record_rotation_event("startup", "策略启动, 恢复轮换状态和未写入的历史事件")

    def _rotation_snapshot(self) -> dict:
        """Only cached/local market data and explicitly allowed config, never credentials."""
        pairs = {}
        for pair, stored_score in getattr(self, "_scores", {}).items():
            raw = self._current_score(pair)
            heat = (
                self._entry_heat_metrics(pair) if self.settings["entry_heat_max_penalty"] else None
            )
            entry = (
                raw
                if not self.settings["entry_heat_max_penalty"]
                else (raw * (1 - heat["penalty"]) if heat is not None else None)
            )
            frame = self._closed_candles(pair, self.timeframe, 1)
            pairs[pair] = {
                "stored_score": stored_score,
                "raw_score": raw,
                "entry_score": entry,
                "heat": heat,
                "metrics": getattr(self, "_metrics", {}).get(pair),
                "score_current": self._pair_score_current(pair),
                "last_closed_candle": frame.iloc[-1].to_dict() if frame is not None else None,
                "fast_breakout": getattr(self, "_fast_rotation_details", {}).get(pair),
                "no_new_high": getattr(self, "_no_new_high_details", {}).get(pair),
                "multi_timeframe": self._multi_timeframe_snapshot(pair),
                "score_components": {
                    name: 100
                    * weight
                    * (
                        self._funding_score(
                            getattr(self, "_metrics", {}).get(pair, {}), time.time()
                        )
                        if name == "funding"
                        else getattr(self, "_metrics", {})
                        .get(pair, {})
                        .get(f"score_{name}", math.nan)
                    )
                    for name, weight in self.settings["weights"].items()
                },
            }
        holdings = []
        for trade in Trade.get_open_trades():
            holdings.append(
                {
                    "trade_id": trade.id,
                    "pair": trade.pair,
                    "is_short": trade.is_short,
                    "open_date": trade.open_date_utc,
                    "open_rate": trade.open_rate,
                    "amount": trade.amount,
                    "leverage": trade.leverage,
                    "opening_score": self._opening_score_label(trade),
                }
            )
        return json_safe(
            {
                "configuration": {
                    "leader_squeeze": self.settings,
                    **{key: self.config[key] for key in FRAMEWORK_SETTINGS},
                },
                "score_refreshed_at": getattr(self, "_last_score_refresh", None),
                "rotation": getattr(self, "_rotation_state", None),
                "candidate": getattr(self, "_rotation_candidate", None),
                "confirmations": getattr(self, "_rotation_seen", 0),
                "signal_bar": getattr(self, "_rotation_candidate_bar", None),
                "pairs": pairs,
                "holdings": holdings,
                "positions": getattr(self, "_position_details", {}),
                "external_pairs": sorted(getattr(self, "_external_pairs", set())),
                "account": getattr(self, "_risk_state", {}),
                "gates": {
                    name: getattr(self, name, None)
                    for name in (
                        "_entry_block_reason",
                        "_eth_block_reason",
                        "_eth_trend",
                        "_market_down",
                        "_market_emergency",
                        "_market_data_healthy",
                        "_position_data_healthy",
                        "_data_healthy",
                        "_risk_state_load_failed",
                        "_risk_state_save_failed",
                        "_execution_block_reason",
                    )
                },
            }
        )

    def _record_rotation_event(
        self, event_type: str, reason: str, details: dict | None = None, *, once: bool = False
    ) -> None:
        journal = getattr(self, "_rotation_journal", None)
        if journal is None:
            return
        state = getattr(self, "_rotation_state", None) or {}
        candidate = getattr(self, "_rotation_candidate", None) or (None, None)
        weak, target = state.get("weak", candidate[0]), state.get("target", candidate[1])
        fingerprint = json.dumps(json_safe([state, candidate, reason, details]), sort_keys=True)
        fingerprints = getattr(self, "_audit_fingerprints", {})
        if once and fingerprints.get(event_type) == fingerprint:
            return
        now = time.time()
        try:
            snapshot = self._rotation_snapshot()
        except Exception as exc:
            # Event identity and lifecycle must survive a broken/missing market snapshot.
            snapshot = {
                "snapshot_error": type(exc).__name__,
                "rotation": json_safe(state),
                "configuration": {"leader_squeeze": json_safe(self.settings)},
            }
            logger.error("轮换现场快照不完整 (%s), 仍记录事件", type(exc).__name__)
        snapshot["decision"] = json_safe(details or {})
        pairs = snapshot.get("pairs", {})
        old = pairs.get(weak, {}).get("raw_score")
        new = pairs.get(target, {}).get("entry_score")
        event = {
            "event_id": str(uuid4()),
            "occurred_at": datetime.fromtimestamp(now, UTC).isoformat(),
            "run_id": self._audit_run_id,
            "bot_name": self.config.get("bot_name", type(self).__name__),
            "dry_run": bool(self.config.get("dry_run", True)),
            "event_type": event_type,
            "rotation_token": state.get("token"),
            "channel": state.get("channel", getattr(self, "_rotation_candidate_channel", None)),
            "weak_pair": weak,
            "target_pair": target,
            "weak_score": old,
            "target_raw_score": pairs.get(target, {}).get("raw_score"),
            "target_entry_score": new,
            "score_gap": new - old if new is not None and old is not None else None,
            "reason": reason,
            "snapshot": snapshot,
        }
        try:
            journal.record(event, now)
        except Exception as exc:
            logger.error("轮换审计记录异常 (%s), 不阻断交易风控", type(exc).__name__)
            return
        fingerprints[event_type] = fingerprint
        self._audit_fingerprints = fingerprints

    def _rotation_execution_details(self, target) -> dict:
        return {
            "target_trade_id": target.id if target else None,
            "orders": [
                {
                    key: getattr(order, key, None)
                    for key in (
                        "order_id",
                        "ft_order_side",
                        "status",
                        "ft_is_open",
                        "amount",
                        "filled",
                        "average",
                        "price",
                    )
                }
                for order in target.orders
            ]
            if target
            else [],
        }

    def _audit_entry_confirmation(
        self, pair: str, allowed: bool, reason: str, amount: float, rate: float
    ) -> None:
        if pair == getattr(self, "_rotation_target", None) and not allowed:
            self._record_rotation_event(
                "entry_rejected", reason, {"amount": amount, "rate": rate}, once=True
            )
