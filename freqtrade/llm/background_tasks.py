"""
LLM 后台任务

在独立线程中运行，不阻塞主交易循环。
"""

import logging
import threading
import time
from freqtrade.llm.aggregator import LLMMetricsAggregator
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class LLMBackgroundTasks:
    """
    LLM 后台任务管理器

    在独立线程中定期执行性能指标聚合和数据清理任务，
    避免阻塞主交易循环。
    """

    def __init__(self, config: dict):
        """
        初始化后台任务管理器

        Args:
            config: Freqtrade 配置字典
        """
        self.config = config
        self.llm_config = config.get("llm_config", {})

        # 后台线程控制
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 聚合器实例（延迟初始化）
        self._aggregator: Optional[any] = None

        # 配置参数
        self.aggregation_interval = self.llm_config.get("aggregation_interval_minutes", 60)
        self.enabled = self.llm_config.get("enable_background_aggregation", True)

    def start(self) -> None:
        """
        启动后台任务线程
        """
        if not self.enabled:
            logger.info("LLM 后台聚合任务已禁用")
            return

        if self._thread is not None and self._thread.is_alive():
            logger.warning("LLM 后台任务已在运行")
            return

        try:
            # 初始化聚合器
            self._aggregator = LLMMetricsAggregator(
                aggregation_interval_minutes=self.aggregation_interval
            )

            # 启动后台线程
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="LLM_Background_Tasks",
                daemon=True
            )
            self._thread.start()

            logger.info(
                f"🚀 LLM 后台任务已启动 (聚合间隔: {self.aggregation_interval} 分钟)"
            )

        except Exception as e:
            logger.error(f"启动 LLM 后台任务失败: {e}", exc_info=True)

    def stop(self) -> None:
        """
        停止后台任务线程
        """
        if self._thread is None or not self._thread.is_alive():
            return

        logger.info("正在停止 LLM 后台任务...")
        self._stop_event.set()

        # 等待线程结束（最多 10 秒）
        self._thread.join(timeout=10)

        if self._thread.is_alive():
            logger.warning("LLM 后台任务未能在 10 秒内停止")
        else:
            logger.info("✅ LLM 后台任务已停止")

    def _run(self) -> None:
        """
        后台任务主循环
        """
        logger.info("LLM 后台任务线程已启动")

        # 初始延迟，避免与 bot 启动冲突
        time.sleep(60)

        while not self._stop_event.is_set():
            try:
                current_time = datetime.utcnow()

                # 执行聚合任务
                if self._aggregator and self._aggregator.should_aggregate(current_time):
                    logger.info("🔄 开始执行 LLM 性能指标聚合...")
                    start_time = time.time()

                    self._aggregator.aggregate()

                    elapsed = time.time() - start_time
                    logger.info(f"✅ LLM 性能指标聚合完成，耗时 {elapsed:.2f} 秒")

            except Exception as e:
                logger.error(f"LLM 后台任务执行出错: {e}", exc_info=True)

            # 每分钟检查一次
            self._stop_event.wait(60)

        logger.info("LLM 后台任务线程已退出")

    def is_running(self) -> bool:
        """
        检查后台任务是否正在运行

        Returns:
            是否正在运行
        """
        return self._thread is not None and self._thread.is_alive()


# 全局单例实例
_background_tasks_instance: Optional[LLMBackgroundTasks] = None


def get_background_tasks(config: dict) -> LLMBackgroundTasks:
    """
    获取或创建后台任务单例实例

    Args:
        config: Freqtrade 配置字典

    Returns:
        LLMBackgroundTasks 实例
    """
    global _background_tasks_instance

    if _background_tasks_instance is None:
        _background_tasks_instance = LLMBackgroundTasks(config)

    return _background_tasks_instance


def start_background_tasks(config: dict) -> None:
    """
    启动 LLM 后台任务

    Args:
        config: Freqtrade 配置字典
    """
    tasks = get_background_tasks(config)
    tasks.start()


def stop_background_tasks() -> None:
    """
    停止 LLM 后台任务
    """
    global _background_tasks_instance

    if _background_tasks_instance is not None:
        _background_tasks_instance.stop()
        _background_tasks_instance = None
