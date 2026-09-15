"""Long-only leader strategy for crowded-short squeezes on Binance futures."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from pandas import DataFrame
from websockets.sync.client import connect

from freqtrade.constants import BuySell
from freqtrade.exchange import Exchange
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy
from freqtrade.wallets import Wallets


logger = logging.getLogger(__name__)


class LeaderSqueezeStrategy(IStrategy):
    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "5m"
    process_only_new_candles = False
    startup_candle_count = 60

    minimal_roi = {"0": 100.0}
    stoploss = -0.10
    use_exit_signal = True
    exit_profit_only = False
    position_adjustment_enable = False

    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": True,
        "stoploss_on_exchange_interval": 60,
        "stoploss_price_type": "mark",
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    DEFAULTS: dict[str, Any] = {
        "leverage": 5.0,
        "stake_ratio": 0.10,
        "min_positions": 2,
        "max_positions": 5,
        "additional_entry_score": 70.0,
        "min_short_share": 0.30,
        "score_refresh_seconds": 300,
        "score_retry_seconds": 30,
        "data_grace_seconds": 30,
        "remote_metric_max_age_seconds": 660,
        "liquidation_stream_max_age_seconds": 15,
        "external_stop_check_seconds": 60,
        "max_spread_ratio": 0.001,
        "max_slippage_ratio": 0.0025,
        "replacement_score_ratio": 1.30,
        "replacement_confirmations": 2,
        "replacement_min_age_minutes": 15,
        "replacement_cooldown_minutes": 30,
        "daily_loss_limit": 0.05,
        "max_drawdown_limit": 0.10,
        "manage_external_positions": True,
        "weights": {
            "short_crowding": 0.30,
            "momentum": 0.25,
            "volume": 0.15,
            "taker_buy": 0.10,
            "liquidation": 0.10,
            "oi_squeeze": 0.10,
        },
    }

    def bot_start(self, **kwargs) -> None:
        """Initialize runtime state and background market-data workers."""
        supplied = self.config.get("leader_squeeze", {})
        self.settings = {**self.DEFAULTS, **supplied}
        self.settings["weights"] = {**self.DEFAULTS["weights"], **supplied.get("weights", {})}
        if not math.isclose(sum(self.settings["weights"].values()), 1.0, abs_tol=1e-9):
            raise ValueError("leader_squeeze weights must add up to 1.0")

        self._scores: dict[str, float] = {}
        self._metrics: dict[str, dict[str, float]] = {}
        self._entry_pairs: set[str] = set()
        self._external_pairs: set[str] = set()
        self._position_details: dict[str, Any] = {}
        self._external_stop_last_check: dict[str, float] = {}
        self._external_stop_protected: dict[str, bool] = {}
        self._position_first_seen: dict[str, float] = {}
        self._last_score_refresh = 0.0
        self._next_score_refresh = 0.0
        self._score_pending = False
        self._score_result: tuple[float, list[str], dict[str, dict[str, float]]] | None = None
        self._score_result_lock = threading.Lock()
        self._last_position_sync = 0.0
        self._position_data_healthy = False
        self._last_good_data = 0.0
        self._data_healthy = False
        self._account_stopped = False
        self._daily_blocked = False
        self._rotation_pair: str | None = None
        self._rotation_target: str | None = None
        self._rotation_candidate: tuple[str, str] | None = None
        self._rotation_seen = 0
        self._rotation_score_snapshot = 0.0
        self._last_rotation = 0.0
        self._external_exit_requested: dict[str, float] = {}

        self._liquidations: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
        self._liquidation_lock = threading.Lock()
        self._liquidation_connected = threading.Event()
        self._liquidation_started = 0.0
        self._liquidation_last_message = 0.0
        self._stop_event = threading.Event()
        self._adl_ranks: dict[str, float] = {}

        user_data_dir = Path(self.config.get("user_data_dir", "user_data"))
        self._state_path = user_data_dir / "leader_squeeze_state.json"
        self._risk_state = self._load_risk_state()
        self._sync_external_pairs()

        runmode = str(self.config.get("runmode", ""))
        if runmode in {"live", "dry_run"}:
            threading.Thread(
                target=self._liquidation_worker,
                name="leader-squeeze-liquidations",
                daemon=True,
            ).start()

    def ft_bot_cleanup(self) -> None:
        """Request shutdown of background workers."""
        self._stop_event.set()
        super().ft_bot_cleanup()

    def informative_pairs(self):
        """Keep 15m candles for leaders and every managed open position."""
        if not getattr(self, "dp", None):
            return []
        pairs = set(self.dp.current_whitelist())
        db_pairs = {trade.pair for trade in Trade.get_open_trades()}
        external = set(getattr(self, "_external_pairs", set()))
        pairs.update(db_pairs)
        pairs.update(external)
        return [(pair, "15m") for pair in pairs] + [(pair, "5m") for pair in external]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Populate indicators used by the strategy interface."""
        dataframe["ema20"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Emit entries only for candidates selected from the cached ranking."""
        dataframe["enter_long"] = 0
        if metadata["pair"] in self._entry_pairs and not dataframe.empty:
            dataframe.loc[dataframe.index[-1], ["enter_long", "enter_tag"]] = (
                1,
                f"squeeze_{self._scores.get(metadata['pair'], 0):.1f}",
            )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Leave exits to custom_exit and exchange stop-loss orders."""
        dataframe["exit_long"] = 0
        return dataframe

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        """Use the configured leverage without exceeding the market limit."""
        return min(float(self.settings["leverage"]), max_leverage)

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> float:
        """Allocate the configured fraction of currently available stake."""
        return max_stake * float(self.settings["stake_ratio"])

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: str | None,
        side: str,
        **kwargs,
    ) -> bool:
        """Perform the final cached-data safety check before entry."""
        return (
            side == "long"
            and pair in self._entry_pairs
            and self._entries_allowed(time.time())
            and pair not in self._external_pairs
        )

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        """Exit on account risk, planned rotation, or confirmed reversal."""
        if self._account_stopped:
            return "account_drawdown"
        if pair == self._rotation_pair:
            return "leader_rotation"
        if self._trend_reversed(pair):
            return "trend_reversal"
        return None

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        """Refresh position state and schedule non-blocking market-data work."""
        now = time.time()
        if now - self._last_position_sync >= 30:
            try:
                self._wallets.update(require_update=True)
                positions = self._exchange.fetch_positions()
                self._position_details = {
                    position["symbol"]: position
                    for position in positions
                    if float(position.get("contracts") or 0) != 0
                }
                self._refresh_adl_ranks()
                self._last_position_sync = now
                self._position_data_healthy = True
            except Exception as exc:
                logger.warning("Position sync failed: %s", exc)
                self._position_data_healthy = False
        self._sync_external_pairs()
        score_updated = self._consume_score_refresh(now)
        if now >= self._next_score_refresh and not self._score_pending:
            self._start_score_refresh(now)
        self._refresh_risk_state(current_time)
        self._sync_rotation_state()
        if score_updated:
            self._plan_rotation(now, current_time)
        self._manage_external_positions(now)
        self._entry_pairs = self._select_entries()

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))

    @classmethod
    def _minmax(cls, values: dict[str, float]) -> dict[str, float]:
        if not values:
            return {}
        low, high = min(values.values()), max(values.values())
        if math.isclose(low, high):
            return {pair: 0.5 for pair in values}
        return {pair: cls._clamp((value - low) / (high - low)) for pair, value in values.items()}

    def _start_score_refresh(self, now: float) -> None:
        leaders = self.dp.current_whitelist()[:10]
        held = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
        pairs = list(dict.fromkeys([*leaders, *sorted(held)]))
        if not leaders:
            self._data_healthy = False
            self._next_score_refresh = now + float(self.settings["score_retry_seconds"])
            return

        self._score_pending = True
        self._next_score_refresh = math.inf

        def fetch() -> None:
            try:
                metrics = self._fetch_market_metrics(pairs)
            except Exception as exc:
                logger.warning("Market metric refresh failed: %s", exc)
                metrics = {}
            with self._score_result_lock:
                self._score_result = (time.time(), leaders, metrics)
                self._score_pending = False

        threading.Thread(target=fetch, name="leader-squeeze-metrics", daemon=True).start()

    def _consume_score_refresh(self, now: float) -> bool:
        with self._score_result_lock:
            result, self._score_result = self._score_result, None
        if result is None:
            return False

        completed_at, leaders, metrics = result
        combined: dict[str, dict[str, float]] = {}
        for pair, remote in metrics.items():
            candle = self._candle_metrics(pair)
            combined[pair] = {**remote, **(candle or {})}
        valid = {
            pair: combined[pair]
            for pair in leaders
            if pair in combined and "momentum" in combined[pair]
        }

        required = min(int(self.settings["min_positions"]), len(leaders))
        if len(valid) < required:
            logger.warning(
                "Only %s/%s leader pairs have complete data; keeping the last valid snapshot.",
                len(valid),
                len(leaders),
            )
            self._next_score_refresh = now + float(self.settings["score_retry_seconds"])
            return False

        self._apply_scores(completed_at, valid, combined)
        self._next_score_refresh = now + float(self.settings["score_refresh_seconds"])
        return True

    def _apply_scores(
        self,
        now: float,
        valid: dict[str, dict[str, float]],
        all_metrics: dict[str, dict[str, float]],
    ) -> None:
        momentum_scores = self._minmax({pair: item["momentum"] for pair, item in valid.items()})
        weights = self.settings["weights"]
        scores: dict[str, float] = {}
        for pair, item in valid.items():
            short_score = self._clamp(
                (item["short_share"] - float(self.settings["min_short_share"])) / 0.25
            )
            volume_score = self._clamp((item["volume_ratio"] - 1.0) / 2.0)
            taker_score = self._clamp((item["taker_ratio"] - 0.8) / 1.2)
            oi_score = (
                self._clamp(-item["oi_change"] / 0.05)
                if item["momentum"] > 0 and item["oi_change"] < 0
                else 0.0
            )
            components = {
                "short_crowding": short_score,
                "momentum": (momentum_scores[pair] + self._clamp(item["trend_continuity"])) / 2,
                "volume": volume_score,
                "taker_buy": taker_score,
                "liquidation": self._liquidation_score(self._market_id(pair), now),
                "oi_squeeze": oi_score,
            }
            item.update({f"score_{name}": value for name, value in components.items()})
            scores[pair] = 100.0 * sum(weights[name] * value for name, value in components.items())

        self._scores = scores
        self._metrics = all_metrics
        self._last_score_refresh = now
        self._last_good_data = now
        self._data_healthy = True
        logger.info("Leader squeeze ranking: %s", self._ranked_pairs())

    def _fetch_market_metrics(self, pairs: list[str]) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        with ThreadPoolExecutor(max_workers=min(10, len(pairs))) as pool:
            futures = {pool.submit(self._fetch_pair_metrics, pair): pair for pair in pairs}
            for future in as_completed(futures):
                pair = futures[future]
                try:
                    result[pair] = future.result()
                except Exception as exc:
                    logger.warning("Unable to score %s: %s", pair, exc)
        return result

    def _fetch_pair_metrics(self, pair: str) -> dict[str, float]:
        symbol = self._market_id(pair)
        base = "https://fapi.binance.com/futures/data"
        common: dict[str, str] = {"symbol": symbol, "period": "5m"}
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("httpsProxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        api_key = self.config.get("exchange", {}).get("key")
        if not api_key:
            raise ValueError("Binance API key is required for top-trader position metrics")

        session = requests.Session()
        session.headers["X-MBX-APIKEY"] = api_key

        def get(path: str, limit: int) -> list[dict[str, Any]]:
            params: dict[str, str | int] = {**common, "limit": limit}
            response = session.get(
                f"{base}/{path}",
                params=params,
                proxies=proxies,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                raise ValueError(f"empty {path} response")
            timestamp = int(payload[-1].get("timestamp") or 0)
            max_age = float(self.settings["remote_metric_max_age_seconds"])
            period_end = timestamp / 1000
            if path == "takerlongshortRatio":
                period_end += 5 * 60
            if timestamp <= 0 or time.time() - period_end > max_age:
                raise ValueError(f"stale {path} response")
            return payload

        try:
            global_ratio = get("globalLongShortAccountRatio", 1)[-1]
            top_position = get("topLongShortPositionRatio", 1)[-1]
            taker = get("takerlongshortRatio", 1)[-1]
            oi = get("openInterestHist", 4)
        finally:
            session.close()

        short_account_share = float(global_ratio["shortAccount"])
        short_position_share = float(top_position["shortAccount"])
        oi_first, oi_last = float(oi[0]["sumOpenInterest"]), float(oi[-1]["sumOpenInterest"])
        return {
            "short_share": max(short_account_share, short_position_share),
            "short_account_share": short_account_share,
            "short_position_share": short_position_share,
            "taker_ratio": float(taker["buySellRatio"]),
            "oi_change": (oi_last / oi_first - 1.0) if oi_first else 0.0,
        }

    def _candle_metrics(self, pair: str) -> dict[str, float] | None:
        dataframe = self.dp.get_pair_dataframe(pair, self.timeframe)
        if len(dataframe) < 21:
            return None
        close = dataframe["close"]
        recent_trend = close.iloc[-4:].pct_change().dropna()
        volumes = dataframe["volume"].rolling(3).sum()
        baseline = volumes.shift(1).tail(20).mean()
        return {
            "momentum": float(close.iloc[-1] / close.iloc[-13] - 1.0),
            "trend_continuity": float((recent_trend > 0).mean()),
            "volume_ratio": float(volumes.iloc[-1] / baseline) if baseline else 1.0,
        }

    def _ranked_pairs(self) -> list[tuple[str, float]]:
        return sorted(self._scores.items(), key=lambda item: item[1], reverse=True)

    def _select_entries(self) -> set[str]:
        if not self._entries_allowed(time.time()):
            return set()

        db_open = {trade.pair for trade in Trade.get_open_trades()}
        occupied = db_open | self._external_pairs
        capacity = max(0, int(self.settings["max_positions"]) - len(occupied))
        if not capacity:
            return set()

        min_needed = max(0, int(self.settings["min_positions"]) - len(occupied))
        ranked = [item for item in self._ranked_pairs() if item[0] not in occupied]
        rotation_target = getattr(self, "_rotation_target", None)
        if rotation_target:
            ranked.sort(key=lambda item: item[0] != rotation_target)
        selected: list[str] = []
        min_short_share = float(self.settings["min_short_share"])
        for pair, score in ranked:
            if len(selected) >= capacity:
                break
            if min_short_share and self._metrics[pair]["short_share"] < min_short_share:
                continue
            if (
                pair != rotation_target
                and len(selected) >= min_needed
                and score < float(self.settings["additional_entry_score"])
            ):
                continue
            if self._execution_is_safe(pair):
                selected.append(pair)
        return set(selected)

    def _entries_allowed(self, now: float) -> bool:
        max_age = float(self.settings["score_refresh_seconds"]) + float(
            self.settings["data_grace_seconds"]
        )
        position_max_age = 30 + float(self.settings["data_grace_seconds"])
        return (
            self._data_healthy
            and now - self._last_good_data <= max_age
            and self._liquidation_connected.is_set()
            and now - self._liquidation_last_message
            <= float(self.settings["liquidation_stream_max_age_seconds"])
            and self._position_data_healthy
            and now - self._last_position_sync <= position_max_age
            and (
                not self.settings["manage_external_positions"]
                or all(
                    self._external_stop_protected.get(pair, False) for pair in self._external_pairs
                )
            )
            and not self._daily_blocked
            and not self._account_stopped
        )

    def _execution_is_safe(self, pair: str) -> bool:
        try:
            book = self._exchange.fetch_l2_order_book(pair, 20)
            bid, ask = float(book["bids"][0][0]), float(book["asks"][0][0])
            spread = 1.0 - bid / ask
            if spread > float(self.settings["max_spread_ratio"]):
                return False
            stake = self._wallets.get_available_stake_amount() * float(self.settings["stake_ratio"])
            notional = stake * float(self.settings["leverage"])
            remaining = notional / ask
            cost = 0.0
            for price, amount in book["asks"]:
                take = min(remaining, float(amount))
                cost += take * float(price)
                remaining -= take
                if remaining <= 0:
                    break
            if remaining > 0:
                return False
            vwap = cost / (notional / ask)
            return vwap / ask - 1.0 <= float(self.settings["max_slippage_ratio"])
        except Exception as exc:
            logger.warning("Execution safety check failed for %s: %s", pair, exc)
            return False

    def _sync_rotation_state(self) -> None:
        held = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
        if self._rotation_target in held:
            self._rotation_target = None
        if not self._rotation_pair:
            if self._rotation_target and self._rotation_target not in self._scores:
                self._rotation_target = None
            return
        if self._rotation_pair not in held:
            self._rotation_pair = None
            self._next_score_refresh = 0.0

    def _plan_rotation(self, now: float, current_time: datetime) -> None:
        if self._rotation_pair or self._rotation_target:
            return
        if self._rotation_score_snapshot == self._last_score_refresh:
            return
        self._rotation_score_snapshot = self._last_score_refresh
        if now - self._last_rotation < float(self.settings["replacement_cooldown_minutes"]) * 60:
            return
        open_trades = {trade.pair: trade for trade in Trade.get_open_trades() if not trade.is_short}
        held_pairs = set(open_trades) | self._external_pairs
        if not held_pairs or not self._scores:
            return

        min_short_share = float(self.settings["min_short_share"])
        challengers = [
            item
            for item in self._ranked_pairs()
            if item[0] not in held_pairs
            and (
                not min_short_share
                or self._metrics.get(item[0], {}).get("short_share", 0.0) >= min_short_share
            )
        ][:3]
        if not challengers:
            return
        weak_pair = min(held_pairs, key=lambda pair: self._scores.get(pair, 0.0))
        challenger, challenger_score = challengers[0]
        weak_score = self._scores.get(weak_pair, 0.0)
        weak_trade = open_trades.get(weak_pair)
        min_age = float(self.settings["replacement_min_age_minutes"]) * 60
        old_enough = (
            (current_time - weak_trade.open_date_utc).total_seconds() >= min_age
            if weak_trade is not None
            else now - self._position_first_seen.get(weak_pair, now) >= min_age
        )
        qualifies = (
            old_enough
            and weak_score < float(self.settings["additional_entry_score"])
            and challenger_score > weak_score * float(self.settings["replacement_score_ratio"])
            and self._no_new_high(weak_pair)
        )
        candidate = (weak_pair, challenger)
        if qualifies and candidate == self._rotation_candidate:
            self._rotation_seen += 1
        elif qualifies:
            self._rotation_candidate, self._rotation_seen = candidate, 1
        else:
            self._rotation_candidate, self._rotation_seen = None, 0

        if self._rotation_seen >= int(self.settings["replacement_confirmations"]):
            self._rotation_pair = weak_pair
            self._rotation_target = challenger
            self._last_rotation = now
            self._rotation_candidate, self._rotation_seen = None, 0

    def _trend_reversed(self, pair: str) -> bool:
        dataframe_15m = self.dp.get_pair_dataframe(pair, "15m")
        dataframe_5m = self.dp.get_pair_dataframe(pair, "5m")
        if len(dataframe_15m) < 22 or len(dataframe_5m) < 2:
            return False
        close = dataframe_15m["close"]
        ema20 = close.ewm(span=20, adjust=False).mean()
        below_ema = bool((close.iloc[-2:] < ema20.iloc[-2:]).all())
        lower_low = dataframe_5m["low"].iloc[-1] < dataframe_5m["low"].iloc[-2]
        metric = self._metrics.get(pair, {})
        seller_reversal = (
            lower_low
            and metric.get("taker_ratio", 1.0) < 1.0
            and metric.get("oi_change", -1.0) >= 0.0
        )
        return below_ema or seller_reversal

    def _no_new_high(self, pair: str) -> bool:
        dataframe = self.dp.get_pair_dataframe(pair, "15m")
        return len(dataframe) >= 4 and (
            dataframe["high"].iloc[-1] <= dataframe["high"].iloc[-4:-1].max()
        )

    def _refresh_risk_state(self, current_time: datetime) -> None:
        positions = self._wallets.get_all_positions()
        equity = self._wallets.get_total(self.config["stake_currency"]) + sum(
            position.unrealized_pnl for position in positions.values()
        )
        if equity <= 0:
            return
        day = current_time.astimezone(UTC).date().isoformat()
        state = self._risk_state
        if state.get("day") != day:
            state.update({"day": day, "day_start_equity": equity, "daily_blocked": False})
        state["peak_equity"] = max(float(state.get("peak_equity", equity)), equity)
        daily_loss = 1.0 - equity / float(state.get("day_start_equity", equity))
        drawdown = 1.0 - equity / float(state["peak_equity"])
        was_daily_blocked = self._daily_blocked
        was_account_stopped = self._account_stopped
        self._daily_blocked = bool(state.get("daily_blocked")) or daily_loss >= float(
            self.settings["daily_loss_limit"]
        )
        self._account_stopped = bool(state.get("account_stopped")) or drawdown >= float(
            self.settings["max_drawdown_limit"]
        )
        if self._daily_blocked and not was_daily_blocked:
            self.dp.send_msg("Leader squeeze: daily loss limit reached; new entries paused.")
        if self._account_stopped and not was_account_stopped:
            self.dp.send_msg("Leader squeeze: maximum drawdown reached; closing positions.")
        state.update(
            {
                "daily_blocked": self._daily_blocked,
                "account_stopped": self._account_stopped,
                "last_equity": equity,
                "updated_at": current_time.astimezone(UTC).isoformat(),
            }
        )
        self._save_risk_state()

    def _load_risk_state(self) -> dict[str, Any]:
        try:
            return json.loads(self._state_path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            return {}

    def _save_risk_state(self) -> None:
        try:
            temporary = self._state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._risk_state, indent=2))
            temporary.replace(self._state_path)
        except OSError as exc:
            logger.error("Unable to persist leader squeeze risk state: %s", exc)
            self._data_healthy = False

    def _market_id(self, pair: str) -> str:
        return self._exchange._api.market_id(pair)

    @property
    def _exchange(self) -> Exchange:
        exchange = self.dp._exchange
        if exchange is None:
            raise RuntimeError("Exchange is not available")
        return exchange

    @property
    def _wallets(self) -> Wallets:
        if self.wallets is None:
            raise RuntimeError("Wallets are not available")
        return self.wallets

    def _liquidation_worker(self) -> None:
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("wsProxy")
        url = "wss://fstream.binance.com/market/stream?streams=!forceOrder@arr/!markPrice@arr@1s"
        while not self._stop_event.is_set():
            try:
                with connect(url, proxy=proxy or True, open_timeout=10, close_timeout=1) as socket:
                    while not self._stop_event.is_set():
                        try:
                            payload = json.loads(socket.recv(timeout=30))
                        except TimeoutError:
                            self._liquidation_connected.clear()
                            if self._stop_event.is_set():
                                break
                            raise
                        received_at = time.time()
                        if self._process_liquidation_payload(payload, received_at):
                            self._liquidation_last_message = received_at
                            if not self._liquidation_started:
                                self._liquidation_started = received_at
                            self._liquidation_connected.set()
            except Exception as exc:
                self._liquidation_connected.clear()
                if not self._stop_event.wait(5):
                    logger.warning("Liquidation stream reconnecting: %s", exc)
            finally:
                self._liquidation_connected.clear()

    def _process_liquidation_payload(self, payload: Any, received_at: float) -> bool:
        if not isinstance(payload, dict):
            return False
        stream = payload.get("stream")
        data = payload.get("data", payload)
        if stream == "!markPrice@arr@1s":
            return isinstance(data, list)
        if not isinstance(data, dict) or (
            stream != "!forceOrder@arr" and data.get("e") != "forceOrder"
        ):
            return False
        if data.get("st") != 1:
            return True
        order = data.get("o", {})
        if order.get("S") != "BUY":
            return True
        symbol = order.get("s")
        price = float(order.get("ap") or order.get("p") or 0)
        quantity = float(order.get("z") or 0)
        if symbol and price > 0 and quantity > 0:
            with self._liquidation_lock:
                self._liquidations[symbol].append((received_at, price * quantity))
        return True

    def _liquidation_score(self, symbol: str, now: float) -> float:
        with self._liquidation_lock:
            events = self._liquidations[symbol]
            while events and events[0][0] < now - 3600:
                events.popleft()
            if not events or now - self._liquidation_started < 3600:
                return 0.5
            recent = sum(value for timestamp, value in events if timestamp >= now - 60)
            hourly_per_minute = sum(value for _, value in events) / 60
        if hourly_per_minute <= 0:
            return 0.5
        return self._clamp((recent / hourly_per_minute - 1.0) / 4.0)

    def _manage_external_positions(self, now: float) -> None:
        positions = self._wallets.get_all_positions()
        if not self.settings["manage_external_positions"]:
            return
        for pair in self._external_pairs:
            position = positions.get(pair)
            if position is None:
                continue
            should_exit = (
                self._account_stopped
                or position.side == "short"
                or pair == self._rotation_pair
                or self._trend_reversed(pair)
                or self._external_hard_stop_hit(pair, position.side)
            )
            if not should_exit:
                self._external_stop_protected[pair] = self._ensure_external_stop(
                    pair, position, now
                )
            else:
                self._external_stop_protected[pair] = False
            if not should_exit or now - self._external_exit_requested.get(pair, 0) < 60:
                continue
            self._external_exit_requested[pair] = now
            if self.config.get("dry_run", True):
                logger.info("Would close external position %s in dry-run mode.", pair)
                continue
            try:
                side: BuySell = "sell" if position.side == "long" else "buy"
                rate = self._exchange.get_rate(
                    pair, side="exit", is_short=position.side == "short", refresh=True
                )
                order = self._exchange.create_order(
                    pair=pair,
                    ordertype="market",
                    side=side,
                    amount=position.position,
                    rate=rate,
                    leverage=float(position.leverage or self.settings["leverage"]),
                    reduceOnly=True,
                    initial_order=False,
                )
                if order.get("status") == "closed":
                    self._cancel_external_stops(pair, position.side, float(position.position))
                self.dp.send_msg(f"Closed external position {pair}: {side} reduceOnly")
            except Exception as exc:
                logger.error("Unable to close external position %s: %s", pair, exc)

    def _sync_external_pairs(self) -> None:
        db_pairs = {trade.pair for trade in Trade.get_open_trades()}
        positions = self._wallets.get_all_positions()
        now = time.time()
        for pair in positions:
            self._position_first_seen.setdefault(pair, now)
        for pair in set(self._position_first_seen) - set(positions):
            self._position_first_seen.pop(pair, None)
        self._external_pairs = {pair for pair in positions if pair not in db_pairs}
        for state in (self._external_stop_last_check, self._external_stop_protected):
            for pair in set(state) - self._external_pairs:
                state.pop(pair, None)

    def _refresh_adl_ranks(self) -> None:
        try:
            ranks = self._exchange._api.fetch_positions_adl_rank(None, params={"subType": "linear"})
            self._adl_ranks = {
                item["symbol"]: float(item["rank"])
                for item in ranks
                if item.get("symbol") and item.get("rank") is not None
            }
            high_risk = {pair: rank for pair, rank in self._adl_ranks.items() if rank >= 4}
            if high_risk:
                logger.warning("Positions at highest ADL rank: %s", high_risk)
        except Exception as exc:
            logger.warning("ADL rank refresh failed: %s", exc)

    def _external_hard_stop_hit(self, pair: str, side: str) -> bool:
        detail = self._position_details.get(pair, {})
        entry = float(detail.get("entryPrice") or 0)
        if entry <= 0:
            return False
        rate = self._exchange.get_rate(pair, side="exit", is_short=side == "short", refresh=True)
        profit = ((rate / entry) - 1.0) * (-1 if side == "short" else 1)
        profit *= float(detail.get("leverage") or self.settings["leverage"])
        return profit <= self.stoploss

    @staticmethod
    def _is_protective_stop(
        order: dict[str, Any], position_side: str, position_amount: float
    ) -> bool:
        info = order.get("info", {})
        reduce_only = str(info.get("reduceOnly", order.get("reduceOnly", False))).lower() == "true"
        stop_price = info.get("stopPrice") or order.get("stopPrice")
        order_side = str(order.get("side") or info.get("side") or "").lower()
        expected_side = "sell" if position_side == "long" else "buy"
        amount = float(order.get("amount") or info.get("origQty") or 0)
        order_type = str(order.get("type") or info.get("type") or "").lower()
        return bool(
            reduce_only
            and float(stop_price or 0) > 0
            and order_side == expected_side
            and amount >= position_amount * 0.999
            and "take_profit" not in order_type
        )

    def _external_stop_orders(self, pair: str) -> list[dict[str, Any]]:
        return self._exchange._api.fetch_open_orders(pair, params={"stop": True})

    def _ensure_external_stop(self, pair: str, position: Any, now: float) -> bool:
        if self.config.get("dry_run", True):
            return True
        interval = float(self.settings["external_stop_check_seconds"])
        if now - self._external_stop_last_check.get(pair, 0) < interval:
            return self._external_stop_protected.get(pair, False)
        self._external_stop_last_check[pair] = now
        try:
            position_amount = float(position.position)
            existing = self._external_stop_orders(pair)
            protected = any(
                self._is_protective_stop(order, position.side, position_amount)
                for order in existing
            )
            if not protected:
                detail = self._position_details.get(pair, {})
                leverage = float(
                    detail.get("leverage") or position.leverage or self.settings["leverage"]
                )
                entry = float(detail.get("entryPrice") or 0)
                if entry <= 0:
                    raise ValueError("missing entry price")
                distance = abs(self.stoploss) / leverage
                stop_price = entry * (1.0 - distance)
                self._exchange.create_stoploss(
                    pair=pair,
                    amount=position.position,
                    stop_price=stop_price,
                    order_types=self.order_types,
                    side="sell",
                    leverage=leverage,
                )
                self.dp.send_msg(f"Protected external position {pair} with exchange stop.")
            self._external_stop_protected[pair] = True
            return True
        except Exception as exc:
            logger.error("Unable to protect external position %s: %s", pair, exc)
            self._external_stop_protected[pair] = False
            return False

    def _cancel_external_stops(self, pair: str, position_side: str, position_amount: float) -> None:
        for order in self._external_stop_orders(pair):
            if self._is_protective_stop(order, position_side, position_amount):
                self._exchange.cancel_stoploss_order(order["id"], pair)
