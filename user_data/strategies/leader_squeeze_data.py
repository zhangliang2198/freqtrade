"""Market data requests, freshness checks and liquidation stream management."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import requests
from leader_squeeze_support import (
    LOG_INFO,
    LOG_WARN,
    LeaderMixinContext,
    logger,
    report_cached,
)
from pandas import DataFrame
from websockets.sync.client import connect

from freqtrade.exchange import Exchange, timeframe_to_seconds
from freqtrade.persistence import Trade
from freqtrade.wallets import Wallets


class LeaderDataMixin(LeaderMixinContext):
    def _start_score_refresh(self, now: float, *, exit_only: bool = False) -> None:
        self._last_score_request = now
        leaders = [] if exit_only else self.dp.current_whitelist()
        self._score_selection = [] if exit_only else self.dp.current_selection_whitelist()
        held = {trade.pair for trade in Trade.get_open_trades()} | self._external_pairs
        pairs = list(dict.fromkeys([*leaders, *sorted(held)]))
        if not pairs or (not exit_only and not leaders):
            self._data_healthy = False
            self._next_score_refresh = now + float(self.settings["score_retry_seconds"])
            return

        self._score_pending = True
        self._next_score_refresh = math.inf
        if exit_only:
            logger.info("🛡️ ETH拦截期间仅刷新持仓行情指标: %s", pairs, extra=LOG_INFO)

        def fetch() -> None:
            try:
                metrics = (
                    self._fetch_market_metrics(pairs, exit_only=True)
                    if exit_only
                    else self._fetch_market_metrics(pairs)
                )
            except Exception as exc:
                logger.warning("⚠️ 行情指标刷新失败: %s", exc, extra=LOG_WARN)
                metrics = {}
            with self._score_result_lock:
                self._score_result = (time.time(), leaders, metrics)
                self._score_pending = False

        threading.Thread(target=fetch, name="leader-squeeze-metrics", daemon=True).start()

    def _consume_score_refresh(self, now: float, *, allow_scoring: bool = True) -> bool:
        with self._score_result_lock:
            result, self._score_result = self._score_result, None
        if result is None:
            return False

        completed_at, leaders, metrics = result
        exit_metrics = getattr(self, "_exit_metrics", {})
        fresh_exits = {
            pair: item
            for pair, item in metrics.items()
            if self._metrics_current(item, now, exit_only=True)
        }
        exit_metrics.update(fresh_exits)
        self._exit_metrics = exit_metrics
        if not leaders or not allow_scoring:
            retry = float(self.settings["score_retry_seconds"])
            deadline = min(
                (item["_exit_valid_until"] for item in fresh_exits.values()), default=now
            )
            self._next_score_refresh = min(
                now + float(self.settings["score_refresh_seconds"]),
                max(now + retry, deadline - retry),
            )
            return False
        pairs = list(dict.fromkeys([*leaders, *metrics]))
        candles = {
            pair: candle for pair in pairs if (candle := self._candle_metrics(pair)) is not None
        }
        self._update_market_state(leaders, candles)
        combined = {
            pair: {
                **remote,
                **candles[pair],
                "_score_valid_until": min(
                    remote["_score_valid_until"], candles[pair]["_candle_valid_until"]
                ),
            }
            for pair, remote in metrics.items()
            if pair in candles and self._metrics_current(remote, now)
        }
        valid_leaders = {
            pair: combined[pair]
            for pair in leaders
            if pair in combined and "momentum" in combined[pair]
        }

        required = self._required_leader_count(len(leaders))
        if len(valid_leaders) < required:
            self._data_healthy = False
            self._record_rotation_event(
                "blocked",
                "评分数据覆盖不足, 清除确认计数",
                {"fresh": len(valid_leaders), "required": required},
                once=True,
            )
            self._rotation_candidate, self._rotation_seen = None, 0
            logger.warning(
                "⛔ 行情覆盖不足 | 完整数据=%s/%s | 新开仓保持暂停",
                len(valid_leaders),
                len(leaders),
                extra=LOG_WARN,
            )
            self._next_score_refresh = now + float(self.settings["score_retry_seconds"])
            return False

        scoreable = {pair: item for pair, item in combined.items() if "momentum" in item}
        self._score_leaders = leaders
        self._apply_scores(completed_at, scoreable, combined)
        deadline = min(
            min(item["_score_valid_until"], item["_exit_valid_until"])
            for item in valid_leaders.values()
        )
        retry = float(self.settings["score_retry_seconds"])
        self._next_score_refresh = min(
            now + float(self.settings["score_refresh_seconds"]),
            max(now + retry, deadline - retry),
        )
        return True

    def _score_coverage(self, now: float) -> tuple[int, int, int]:
        leaders = getattr(self, "_entry_leaders", None)
        if leaders is None:
            leaders = getattr(self, "_score_leaders", [])
        metrics = getattr(self, "_metrics", {})
        fresh = sum(self._metrics_current(metrics.get(pair, {}), now) for pair in leaders)
        return fresh, len(leaders), self._required_leader_count(len(leaders))

    def _advance_score_refresh(self, now: float, *, allow_scoring: bool) -> None:
        """名单变化/有效覆盖丢失后及时补刷新, 最快30秒一批, 不并发重复请求。"""
        if not allow_scoring or self._score_pending:
            return
        if now - getattr(self, "_last_score_request", 0) < float(
            self.settings["score_retry_seconds"]
        ):
            return
        fresh, _, required = self._score_coverage(now)
        leaders = getattr(self, "_entry_leaders", None)
        changed = leaders is not None and set(leaders) != set(getattr(self, "_score_leaders", []))
        if changed or not required or fresh < required or not self._data_healthy:
            self._next_score_refresh = min(self._next_score_refresh, now)

    def _fetch_market_metrics(
        self, pairs: list[str], *, exit_only: bool = False
    ) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {}
        with ThreadPoolExecutor(
            max_workers=min(self.settings["metric_workers"], len(pairs))
        ) as pool:
            funding_future = (
                pool.submit(self._fetch_funding_metrics, pairs)
                if not exit_only and self.settings["weights"].get("funding", 0) > 0
                else None
            )
            futures = {
                pool.submit(self._fetch_pair_metrics, pair, exit_only=exit_only): pair
                for pair in pairs
            }
            for future in as_completed(futures):
                pair = futures[future]
                try:
                    result[pair] = future.result()
                except Exception as exc:
                    logger.warning("⚠️ 行情指标刷新失败 %s: %s", pair, exc, extra=LOG_WARN)
            if funding_future is not None:
                try:
                    for pair, funding in funding_future.result().items():
                        if pair in result:
                            result[pair].update(funding)
                except Exception as exc:
                    logger.warning(
                        "⚠️ 资金费率批次失败, 不加分但不单独拦截: %s", exc, extra=LOG_WARN
                    )
        return result

    def _fetch_funding_metrics(self, pairs: list[str]) -> dict[str, dict[str, float]]:
        """每个评分批次仅两次公开请求; 费率/上下限缺失不会使核心指标失效。"""
        result: dict[str, dict[str, float]] = {}
        requested_at = time.time()
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("httpsProxy")
        session = requests.Session()
        try:
            payloads = []
            for endpoint in ("fundingInfo", "premiumIndex"):
                response = session.get(
                    f"{self.settings['rest_base_url']}/fapi/v1/{endpoint}",
                    proxies={"http": proxy, "https": proxy} if proxy else None,
                    timeout=self.settings["funding_request_timeout_seconds"],
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError(f"invalid {endpoint} response")
                payloads.append(
                    {
                        item["symbol"]: item
                        for item in payload
                        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
                    }
                )
            infos, rates = payloads
            now = time.time()
            for pair in pairs:
                try:
                    symbol = self._market_id(pair)
                    result[pair] = self._parse_funding_metric(
                        infos[symbol], rates[symbol], now, requested_at
                    )
                except (KeyError, TypeError, ValueError, OverflowError) as exc:
                    logger.warning(
                        "⚠️ 资金费率/实际限额不可用 %s (%s), 加分=0, 不单独拦截",
                        pair,
                        type(exc).__name__,
                        extra=LOG_WARN,
                    )
        except Exception as exc:
            logger.warning("⚠️ 资金费率获取失败, 加分=0, 不单独拦截: %s", exc, extra=LOG_WARN)
        finally:
            session.close()
        return result

    def _parse_funding_metric(
        self, info: dict, rate: dict, now: float, requested_at: float
    ) -> dict[str, float]:
        hours = float(info["fundingIntervalHours"])
        value = float(rate["lastFundingRate"])
        floor = float(info["adjustedFundingRateFloor"])
        cap = float(info["adjustedFundingRateCap"])
        sampled_at = float(rate["time"]) / 1000
        next_time = float(rate["nextFundingTime"]) / 1000
        max_age = float(self.settings["funding_max_age_seconds"])
        if not (
            all(math.isfinite(v) for v in (hours, value, floor, cap, sampled_at, next_time))
            and 1 <= hours <= 24
            and hours.is_integer()
            and -1 <= floor < 0 < cap <= 1
            and abs(value) <= 1
            and sampled_at > 0
            and 0 <= now - sampled_at <= max_age
            and 0 <= now - requested_at <= max_age
            and next_time > now
            and next_time - sampled_at <= hours * 3600 + float(self.settings["data_grace_seconds"])
        ):
            raise ValueError("invalid or stale funding rate/interval/limits")
        return {
            "funding_rate": value,
            "funding_interval_hours": hours,
            "funding_rate_hourly": value / hours,
            "funding_floor": floor,
            "funding_cap": cap,
            "funding_floor_hourly": floor / hours,
            "funding_next_time": next_time,
            "_funding_valid_until": min(sampled_at + max_age, requested_at + max_age, next_time),
        }

    @staticmethod
    def _taker_ratio(buy_volume: float, sell_volume: float, full_ratio: float) -> float:
        if not math.isfinite(buy_volume) or not math.isfinite(sell_volume):
            raise ValueError("invalid aggregate taker volumes")
        if sell_volume == 0:
            return 1.0 if buy_volume == 0 else full_ratio
        value = buy_volume / sell_volume
        if not math.isfinite(value):
            raise ValueError("invalid taker ratio")
        return value

    @classmethod
    def _parse_taker_rows(
        cls,
        rows: list[dict[str, Any]],
        *,
        window: int,
        timeframe: str,
        now: float,
        full_ratio: float,
    ) -> tuple[float, float]:
        if len(rows) < window:
            raise ValueError("insufficient taker candles")
        if not math.isfinite(full_ratio) or full_ratio <= 1:
            raise ValueError("invalid taker full ratio")
        period_ms = timeframe_to_seconds(timeframe) * 1000
        timestamps: list[int] = []
        volumes: list[tuple[float, float]] = []
        for row in rows[-window:]:
            timestamp = int(row.get("timestamp") or 0)
            if timestamp <= 0 or timestamp + period_ms > now * 1000:
                raise ValueError("invalid or unclosed taker timestamp")
            buy_volume = float(row["buyVol"])
            sell_volume = float(row["sellVol"])
            if not all(math.isfinite(value) and value >= 0 for value in (buy_volume, sell_volume)):
                raise ValueError("invalid taker volumes")
            timestamps.append(timestamp)
            volumes.append((buy_volume, sell_volume))
        if any(current - previous != period_ms for previous, current in pairwise(timestamps)):
            raise ValueError("taker candles are not continuous")

        buy_volume = sum(buy for buy, _ in volumes)
        sell_volume = sum(sell for _, sell in volumes)
        return (
            cls._taker_ratio(buy_volume, sell_volume, full_ratio),
            cls._taker_ratio(*volumes[-1], full_ratio),
        )

    def _fetch_pair_metrics(self, pair: str, *, exit_only: bool = False) -> dict[str, float]:
        symbol = self._market_id(pair)
        base = f"{self.settings['rest_base_url']}/futures/data"
        common: dict[str, str] = {"symbol": symbol, "period": self.timeframe}
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("httpsProxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        api_key = self.config.get("exchange", {}).get("key")
        session = requests.Session()
        if api_key:
            session.headers["X-MBX-APIKEY"] = api_key
        valid_until: dict[str, float] = {}

        def get(path: str, limit: int) -> list[dict[str, Any]]:
            params: dict[str, str | int] = {**common, "limit": limit}
            response = session.get(
                f"{base}/{path}",
                params=params,
                proxies=proxies,
                timeout=self.settings["metric_request_timeout_seconds"],
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                raise ValueError(f"empty {path} response")
            timestamp = int(payload[-1].get("timestamp") or 0)
            max_age = float(self.settings["remote_metric_max_age_seconds"])
            period_end = timestamp / 1000
            if path == "takerlongshortRatio":
                period_end += timeframe_to_seconds(self.timeframe)
            if timestamp <= 0 or not 0 <= time.time() - period_end <= max_age:
                raise ValueError(f"stale {path} response")
            valid_until[path] = period_end + max_age
            return payload

        exit_metric: dict[str, float] = {}
        try:
            taker_window = self.settings["taker_window_candles"]
            if type(taker_window) is not int or taker_window < 1:
                raise ValueError("invalid taker window")
            taker_rows = get("takerlongshortRatio", taker_window)
            taker_ratio, taker_ratio_latest = self._parse_taker_rows(
                taker_rows,
                window=taker_window,
                timeframe=self.timeframe,
                now=time.time(),
                full_ratio=float(self.settings["taker_score_full_ratio"]),
            )
            oi = get("openInterestHist", self.settings["oi_sample_count"])
            oi_first, oi_last = float(oi[0]["sumOpenInterest"]), float(oi[-1]["sumOpenInterest"])
            if not all(math.isfinite(value) for value in (oi_first, oi_last, taker_ratio)) or (
                oi_first <= 0 or oi_last < 0 or taker_ratio < 0
            ):
                raise ValueError("invalid taker/OI values")
            exit_metric = {
                "taker_ratio": taker_ratio,
                "taker_ratio_latest": taker_ratio_latest,
                "taker_latest_candle_time": int(taker_rows[-1]["timestamp"]) / 1000,
                "oi_change": oi_last / oi_first - 1.0,
                "_exit_valid_until": min(valid_until.values()),
            }
            if exit_only:
                return exit_metric
            global_ratio = get("globalLongShortAccountRatio", 1)[-1]
            top_position = get("topLongShortPositionRatio", 1)[-1]
            short_account_share = float(global_ratio["shortAccount"])
            short_position_share = float(top_position["shortAccount"])
            if not all(0 <= value <= 1 for value in (short_account_share, short_position_share)):
                raise ValueError("invalid short crowding values")
            return {
                **exit_metric,
                "_score_valid_until": min(valid_until.values()),
                "short_share": max(short_account_share, short_position_share),
                "short_account_share": short_account_share,
                "short_position_share": short_position_share,
            }
        except Exception as exc:
            if not self._metrics_current(exit_metric, time.time(), exit_only=True):
                raise
            logger.warning(
                "⚠️ 评分指标不完整 %s: %s | 仅保留有效 OI/主动买卖缓存, 不用于评分开仓",
                pair,
                exc,
                extra=LOG_WARN,
            )
            return exit_metric
        finally:
            session.close()

    @staticmethod
    def _metrics_current(metric: dict[str, float], now: float, *, exit_only: bool = False) -> bool:
        deadlines = (
            ("_exit_valid_until",) if exit_only else ("_exit_valid_until", "_score_valid_until")
        )
        return all(
            type(metric.get(key)) in (int, float)
            and math.isfinite(metric[key])
            and 0 < metric[key] >= now
            for key in deadlines
        )

    def _pair_score_current(self, pair: str, now: float | None = None) -> bool:
        if self._metrics_current(
            getattr(self, "_metrics", {}).get(pair, {}), time.time() if now is None else now
        ):
            return True
        self._warn_data_unavailable(f"{pair} 评分指标", "缓存缺失或已过期, 等待新指标")
        return False

    def _warn_data_unavailable(self, key: str, reason: str) -> None:
        now = time.time()
        warnings = getattr(self, "_data_warning_times", {})
        if now - warnings.get(key, -math.inf) >= float(self.settings["status_log_seconds"]):
            logger.warning(
                "⚠️ 数据不可用 %s | %s | 跳过依赖此数据的信号", key, reason, extra=LOG_WARN
            )
            warnings[key] = now
        self._data_warning_times = warnings

    @report_cached
    def _closed_candles(
        self,
        pair: str,
        timeframe: str,
        count: int,
        *,
        columns: tuple[str, ...] = ("close",),
        now: float | None = None,
    ) -> DataFrame | None:
        """仅接受新鲜、连续且已收盘的 K 线, 不以接口响应时间替代行情时间。"""
        try:
            dataframe = self.dp.get_pair_dataframe(pair, timeframe)
            if not {"date", *columns}.issubset(dataframe.columns):
                raise ValueError("缺少必要K线字段")
            seconds = timeframe_to_seconds(timeframe)
            current_time = datetime.fromtimestamp(time.time() if now is None else now, UTC)
            dataframe = dataframe.loc[
                dataframe["date"] <= current_time - timedelta(seconds=seconds)
            ]
            if len(dataframe) < count:
                raise ValueError("已收盘K线数量不足")
            dates = dataframe["date"]
            age = (current_time - dates.iloc[-1]).total_seconds()
            if age > 2 * seconds + float(self.settings["data_grace_seconds"]):
                raise ValueError(f"K线过期: {age:.0f}秒")
            if not dates.diff().dropna().dt.total_seconds().eq(seconds).all():
                raise ValueError("K线时间不连续")
            for column in ("close", "high", "low", "volume"):
                if column in dataframe:
                    values = dataframe[column]
                    if not values.map(math.isfinite).all() or (
                        (values < 0).any() if column == "volume" else (values <= 0).any()
                    ):
                        raise ValueError(f"K线{column}数值无效")
            return dataframe
        except Exception as exc:
            self._warn_data_unavailable(f"{pair} {timeframe}", str(exc))
            return None

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

    def _liquidation_stream_stale(
        self, now: float, connected_at: float, stream_max_age: float
    ) -> bool:
        with self._liquidation_lock:
            last_message = self._liquidation_last_message
        reference = last_message or connected_at
        return now >= reference and now - reference > stream_max_age

    def _receive_liquidation_payload(
        self, socket: Any, timeout: float, connected_at: float, stream_max_age: float
    ) -> tuple[Any, bool]:
        try:
            raw_payload = socket.recv(timeout=timeout)
        except TimeoutError:
            if self._stop_event.is_set():
                return None, True
            if self._liquidation_stream_stale(time.time(), connected_at, stream_max_age):
                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
            # A single websocket receive timeout is not proof of a断流. Keep the
            # existing window and let the age gate decide when reconnecting is necessary.
            return None, False
        try:
            return json.loads(raw_payload), False
        except (TypeError, ValueError, UnicodeDecodeError):
            # Malformed input is isolated to this message. It does not refresh the
            # stream heartbeat or force a reconnect.
            if self._liquidation_stream_stale(time.time(), connected_at, stream_max_age):
                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
            return None, False

    def _liquidation_worker(self) -> None:
        proxy = self.config.get("exchange", {}).get("ccxt_config", {}).get("wsProxy")
        url = self.settings["liquidation_stream_url"]
        while not self._stop_event.is_set():
            try:
                with connect(
                    url,
                    proxy=proxy or True,
                    open_timeout=self.settings["liquidation_open_timeout_seconds"],
                    close_timeout=self.settings["liquidation_close_timeout_seconds"],
                ) as socket:
                    self._reset_liquidation_window()
                    connected_at = time.time()
                    stream_max_age = float(self.settings["liquidation_stream_max_age_seconds"])
                    receive_timeout = min(
                        float(self.settings["liquidation_receive_timeout_seconds"]),
                        stream_max_age,
                    )
                    while not self._stop_event.is_set():
                        payload, stop = self._receive_liquidation_payload(
                            socket, receive_timeout, connected_at, stream_max_age
                        )
                        if stop:
                            break
                        if payload is None:
                            if self._liquidation_stream_stale(
                                time.time(), connected_at, stream_max_age
                            ):
                                self._liquidation_connected.clear()
                                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
                            continue
                        received_at = time.time()
                        if self._liquidation_last_message and (
                            received_at - self._liquidation_last_message > stream_max_age
                            or received_at < self._liquidation_last_message
                        ):
                            self._reset_liquidation_window()
                        if not self._process_liquidation_payload(payload, received_at):
                            if self._liquidation_stream_stale(
                                received_at, connected_at, stream_max_age
                            ):
                                self._liquidation_connected.clear()
                                raise ConnectionError("强平数据流超过配置时限未收到有效消息")
                            continue
                        with self._liquidation_lock:
                            self._liquidation_last_message = received_at
                            if not self._liquidation_started:
                                self._liquidation_started = received_at
                        self._prune_liquidations(received_at)
                        self._liquidation_connected.set()
            except Exception as exc:
                self._liquidation_connected.clear()
                if not self._stop_event.wait(self.settings["liquidation_reconnect_seconds"]):
                    logger.warning("🔌 强平数据流断开, 正在重连: %s", exc, extra=LOG_WARN)
            finally:
                self._liquidation_connected.clear()

    def _reset_liquidation_window(self) -> None:
        initial = not (
            getattr(self, "_liquidation_window_initialized", False)
            or getattr(self, "_liquidation_started", 0)
            or getattr(self, "_liquidation_last_message", 0)
        )
        self._liquidation_connected.clear()
        with self._liquidation_lock:
            self._liquidations.clear()
            self._liquidation_started = 0.0
            self._liquidation_last_message = 0.0
        self._liquidation_window_initialized = True
        logger.log(
            logging.INFO if initial else logging.WARNING,
            "🔌 强平流%s | %s%.0f分钟; 期间强平评分使用配置值, 收到有效心跳后不单独阻止开仓",
            "初始化统计窗口" if initial else "连接重建或心跳断档, 清空统计窗口",
            "预热" if initial else "重新预热",
            self.settings["liquidation_window_seconds"] / 60,
            extra=LOG_INFO if initial else LOG_WARN,
        )

    def _prune_liquidations(self, now: float) -> None:
        """由全市场心跳清理所有币种, 不依赖币种是否参与排名。"""
        with self._liquidation_lock:
            for symbol, events in list(self._liquidations.items()):
                while events and events[0][0] < now - self.settings["liquidation_window_seconds"]:
                    events.popleft()
                if not events:
                    del self._liquidations[symbol]

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
        if not isinstance(order, dict):
            return False
        if order.get("S") != "BUY":
            return True
        symbol = order.get("s")
        if not isinstance(symbol, str) or not symbol:
            return False
        try:
            price = float(order.get("ap") or order.get("p") or 0)
            quantity = float(order.get("z") or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        notional = price * quantity
        if not (
            math.isfinite(price)
            and math.isfinite(quantity)
            and math.isfinite(notional)
            and price > 0
            and quantity > 0
            and notional > 0
            and math.isfinite(received_at)
        ):
            return False
        with self._liquidation_lock:
            self._liquidations[symbol].append((received_at, notional))
        return True
