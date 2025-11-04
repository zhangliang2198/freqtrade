"""
基础 LLM 提供商接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """
    LLM 提供商的抽象基类

    所有 LLM 提供商都必须实现此接口，以确保
    不同模型和 API 之间的一致行为。
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 LLM 提供商

        Args:
            config: 提供商配置字典
        """
        self.config = config
        self.model = config.get("model")
        self.timeout = config.get("timeout", 30)
        self.max_retries = config.get("max_retries", 3)
        self.last_usage = {}

    @abstractmethod
    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        调用 LLM 完成提示

        Args:
            prompt: 输入提示
            temperature: 温度参数 (0.0-1.0)，值越低越确定性

        Returns:
            LLM 响应文本

        Raises:
            Exception: 如果 API 调用失败
        """
        pass

    @abstractmethod
    def get_usage_info(self) -> Dict[str, Any]:
        """
        获取上次 API 调用的使用信息

        Returns:
            包含以下内容的字典：
                - tokens_used: 消耗的总令牌数
                - cost_usd: 估算的美元成本
        """
        pass

    def validate_config(self) -> bool:
        """
        验证提供商配置

        Returns:
            如果配置有效则返回 True

        Raises:
            ValueError: 如果配置无效
        """
        required_fields = ["model"]
        for field in required_fields:
            if field not in self.config:
                error_msg = f"缺少必需的配置字段: {field}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        return True
