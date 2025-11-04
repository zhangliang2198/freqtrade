from __future__ import annotations

from typing import Iterable

from .base import MetricSample


def _collect_health(api, now: float) -> Iterable[MetricSample]:
    data = api.get("/health", default={}) or {}
    if not isinstance(data, dict):
        return []

    samples: list[MetricSample] = []
    last_process_ts = data.get("last_process_ts")
    if last_process_ts is not None:
        samples.append(
            MetricSample(
                "freqtrade_last_process_timestamp",
                last_process_ts,
                "机器人最近一次循环处理完成的 Unix 时间戳。",
            )
        )
        samples.append(
            MetricSample(
                "freqtrade_last_process_seconds_ago",
                max(now - float(last_process_ts), 0.0),
                "距离上次循环结束经过的秒数。",
            )
        )

    bot_start_ts = data.get("bot_start_ts")
    if bot_start_ts is not None:
        samples.append(
            MetricSample(
                "freqtrade_bot_start_timestamp",
                bot_start_ts,
                "机器人进入 RUNNING 状态的 Unix 时间戳。",
            )
        )

    bot_startup_ts = data.get("bot_startup_ts")
    if bot_startup_ts is not None:
        samples.append(
            MetricSample(
                "freqtrade_bot_startup_timestamp",
                bot_startup_ts,
                "机器人进程启动的 Unix 时间戳。",
            )
        )

    return samples


def _collect_sysinfo(api) -> Iterable[MetricSample]:
    data = api.get("/sysinfo", default={}) or {}
    if not isinstance(data, dict):
        return []

    samples: list[MetricSample] = []
    cpu_pct = data.get("cpu_pct") or []
    if isinstance(cpu_pct, list):
        for idx, value in enumerate(cpu_pct):
            samples.append(
                MetricSample(
                    "freqtrade_system_cpu_pct",
                    value,
                    "Per-core CPU utilisation reported by the bot host.",
                    labels={"core": str(idx)},
                )
            )

    ram_pct = data.get("ram_pct")
    if ram_pct is not None:
        samples.append(
            MetricSample(
                "freqtrade_system_ram_pct",
                ram_pct,
                "System RAM utilisation reported by the bot host.",
            )
        )

    return samples


def collect(api, now: float) -> Iterable[MetricSample]:
    """采集系统层面的运行状态指标。"""
    samples: list[MetricSample] = [
        MetricSample(
            "freqtrade_exporter_up",
            1,
            "导出器自身可用性指示（抓取成功即为 1）。",
        )
    ]
    samples.extend(_collect_health(api, now))
    samples.extend(_collect_sysinfo(api))
    return samples
