"""
Command helpers for the Prometheus exporter.
"""

from __future__ import annotations

import logging
from typing import Any

from freqtrade.enums import RunMode
from freqtrade.configuration import setup_utils_configuration
from freqtrade.exporter.freqtrade_exporter import run_exporter

logger = logging.getLogger(__name__)


def start_exporter_service(args: dict[str, Any]) -> None:
    """
    Launch the Prometheus exporter as a standalone service.
    """
    config = setup_utils_configuration(args, RunMode.UTIL_NO_EXCHANGE)

    if not config.get("prometheus_exporter"):
        logger.warning(
            "配置中未找到 'prometheus_exporter' 段，Exporter 将回退到默认监听地址/端口。"
        )

    logger.info("启动 Prometheus Exporter ... 按 Ctrl+C 停止。")
    run_exporter(config, threaded=False)
