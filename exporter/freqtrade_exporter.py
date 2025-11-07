from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict
import threading

import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from exporter.metrics import COLLECTORS
from exporter.metrics.base import MetricSample, render_samples

logger = logging.getLogger(__name__)

# 全局配置变量（从 config 初始化）
API_USER: str = ""
API_PASS: str = ""
FREQTRADE_API: str = ""
EXPORTER_PORT: int = 8000
EXPORTER_HOST: str = "127.0.0.1"


class FreqtradeAPI:
    """用于在单次采集过程中缓存 Freqtrade REST API 响应的轻量封装。"""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self.timeout = timeout
        self._cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()
        self._session_local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()

    def _get_session(self) -> requests.Session:
        """为每个线程创建独立的 Session，避免多线程竞争。"""
        session = getattr(self._session_local, "session", None)
        if session is None:
            session = requests.Session()
            self._session_local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def get(self, path: str, *, default: Any | None = None, use_cache: bool = True) -> Any:
        """调用 REST 接口并缓存结果，失败时返回 default。"""
        normalized = path if path.startswith("/") else f"/{path}"
        if use_cache:
            with self._cache_lock:
                if normalized in self._cache:
                    return self._cache[normalized]

        url = f"{self.base_url}{normalized}"
        session = self._get_session()
        try:
            response = session.get(url, auth=self.auth, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Freqtrade API 调用失败 %s: %s", normalized, exc)
            return default

        try:
            payload = response.json()
        except ValueError as exc:
            logger.warning("Freqtrade API 返回的 JSON 无法解析 %s: %s", normalized, exc)
            return default

        if use_cache:
            with self._cache_lock:
                self._cache[normalized] = payload
        return payload

    def close(self) -> None:
        """关闭底层会话连接。"""
        with self._sessions_lock:
            for session in self._sessions:
                session.close()
            self._sessions.clear()


app = FastAPI(title="Freqtrade Prometheus Exporter")


def _execute_collector(collector, api: FreqtradeAPI, now: float, collector_name: str) -> tuple[list[MetricSample], int]:
    """在线程池中执行单个采集器，返回采集结果和错误标记。"""
    try:
        collected = collector(api, now)
        if isinstance(collected, Iterable):
            return list(collected), 0
        logger.warning("采集器 %s 返回了无法遍历的数据对象。", collector_name)
        return [], 0
    except Exception as exc:  # noqa: BLE001 捕获所有异常用于写入 exporter 状态
        logger.exception("采集器 %s 执行异常: %s", collector_name, exc)
        return [], 1

def build_metrics() -> str:
    """整合所有采集器返回的指标并渲染成 Prometheus 文本格式。"""
    api = FreqtradeAPI(FREQTRADE_API, API_USER, API_PASS)
    scrape_start = time.time()
    now = scrape_start
    samples: list[MetricSample] = []

    try:
        max_workers = max(1, len(COLLECTORS))
        collector_results: list[tuple[str, list[MetricSample], int]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_name = {}
            for collector in COLLECTORS:
                collector_name = getattr(collector, "__name__", repr(collector))
                future = executor.submit(_execute_collector, collector, api, now, collector_name)
                future_to_name[future] = collector_name

            for future, collector_name in future_to_name.items():
                collected, error_flag = future.result()
                collector_results.append((collector_name, collected, error_flag))

        for collector_name, collected, error_flag in collector_results:
            samples.extend(collected)
            samples.append(
                MetricSample(
                    "freqtrade_exporter_collector_errors",
                    error_flag,
                    "单个采集器的错误指示器（出现异常时为 1）。",
                    labels={"collector": collector_name},
                )
            )

        scrape_duration = time.time() - scrape_start
        samples.append(
            MetricSample(
                "freqtrade_exporter_scrape_duration_seconds",
                scrape_duration,
                "本次抓取生成指标所用时间（秒）。",
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_exporter_scrape_timestamp",
                now,
                "导出器完成抓取时的 Unix 时间戳。",
            )
        )

        lines = render_samples(samples)
        return "\n".join(lines) + "\n"
    finally:
        api.close()


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    """Prometheus 指标输出端点"""
    payload = build_metrics()
    logger.info("输出 Prometheus 指标（%d 字节）。", len(payload))
    return PlainTextResponse(content=payload, media_type="text/plain; version=0.0.4")


def configure_exporter(config: Dict[str, Any]) -> None:
    """从 freqtrade 配置中提取 exporter 配置并设置全局变量。"""
    global API_USER, API_PASS, FREQTRADE_API, EXPORTER_PORT, EXPORTER_HOST

    api_server_config = config.get("api_server", {})
    exporter_config = config.get("prometheus_exporter", {})

    # 从 api_server 配置中获取认证信息和 API 地址
    API_USER = api_server_config.get("username")
    API_PASS = api_server_config.get("password")
    api_host = api_server_config.get("listen_ip_address", "127.0.0.1")
    api_port = api_server_config.get("listen_port", 8080)
    FREQTRADE_API = f"http://{api_host}:{api_port}/api/v1"

    # 从 prometheus_exporter 配置中获取 exporter 监听地址和端口
    EXPORTER_HOST = exporter_config.get("listen_ip_address", "127.0.0.1")
    EXPORTER_PORT = exporter_config.get("listen_port", 8000)

    logger.info(
        "Prometheus Exporter 配置: host=%s, port=%d, freqtrade_api=%s, user=%s",
        EXPORTER_HOST,
        EXPORTER_PORT,
        FREQTRADE_API,
        API_USER,
    )


def run_exporter(config: Dict[str, Any], threaded: bool = True) -> threading.Thread:
    """
    启动 Prometheus Exporter FastAPI 服务。

    Args:
        config: freqtrade 配置字典（必需）
        threaded: 是否在后台线程中运行（默认 True）

    Returns:
        运行服务的线程对象
    """
    configure_exporter(config)

    def _run():
        logger.info("启动 Prometheus Exporter FastAPI 服务于 http://%s:%d/metrics", EXPORTER_HOST, EXPORTER_PORT)
        uvicorn.run(
            app,
            host=EXPORTER_HOST,
            port=EXPORTER_PORT,
            log_level="info",
            access_log=False,
        )

    thread = threading.Thread(target=_run, daemon=True, name="PrometheusExporter")
    thread.start()
    return thread
