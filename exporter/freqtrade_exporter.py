from __future__ import annotations

import logging
import pathlib
import sys
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict
import threading

# Ensure the project root is importable when executed as a script (e.g. `python exporter/freqtrade_exporter.py`).
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests
from flask import Flask, Response

from exporter.metrics import COLLECTORS
from exporter.metrics.base import MetricSample, render_samples

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

# 修改为你的 API 账号密码
API_USER = "mikoozhang"
API_PASS = "Meili163!!"
FREQTRADE_API = "http://127.0.0.1:8080/api/v1"


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


app = Flask(__name__)


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


@app.route("/metrics")
def metrics() -> Response:
    payload = build_metrics()
    logger.info("输出 Prometheus 指标（%d 字节）。", len(payload))
    return Response(payload, mimetype="text/plain; version=0.0.4")


if __name__ == "__main__":
    # Windows 上直接跑 Flask，端口 8000
    app.run(host="127.0.0.1", port=8000)
