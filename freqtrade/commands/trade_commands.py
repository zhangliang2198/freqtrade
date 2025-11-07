import logging
import signal
from typing import Any
from freqtrade.configuration import Configuration
from freqtrade.exporter.freqtrade_exporter import run_exporter

logger = logging.getLogger(__name__)


def start_trading(args: dict[str, Any]) -> int:
    """
    Main entry point for trading mode
    """
    # Import here to avoid loading worker module when it's not used
    from freqtrade.worker import Worker

    config_override: dict[str, Any] | None = None
    if args.get("start_exporter"):
        try:
            configuration = Configuration(args)
            config_override = configuration.get_config()
            run_exporter(config_override)
            logger.info("Prometheus Exporter 已通过 --start-exporter 启动。")
        except Exception as exc:  # noqa: BLE001
            logger.error("通过 --start-exporter 启动 Prometheus Exporter 失败: %s", exc)

    def term_handler(signum, frame):
        # Raise KeyboardInterrupt - so we can handle it in the same way as Ctrl-C
        raise KeyboardInterrupt()

    # Create and run worker
    worker = None
    try:
        signal.signal(signal.SIGTERM, term_handler)
        worker = Worker(args, config_override)
        worker.run()
    finally:
        if worker:
            logger.info("worker found ... calling exit")
            worker.exit()
    return 0
