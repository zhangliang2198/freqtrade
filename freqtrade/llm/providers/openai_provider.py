"""
OpenAI 大语言模型提供商
"""

from typing import Dict, Any
import logging

from freqtrade.llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """
    OpenAI API 的 GPT 模型提供商

    支持如 gpt-4o、gpt-4o-mini、gpt-4-turbo 等模型。
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 OpenAI 提供商

        Args:
            config: 配置字典，包含：
                - model: 模型名称（例如："gpt-4o"）
                - api_key: OpenAI API 密钥
                - base_url: 可选的自定义 API 端点
                - timeout: 请求超时时间（秒）
                - max_retries: 最大重试次数
        """
        super().__init__(config)

        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")

        if not self.api_key:
            raise ValueError("需要 OpenAI API 密钥")

        # 延迟导入，避免未使用时的依赖
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "OpenAIProvider 需要 OpenAI 包。"
                "请使用以下命令安装：pip install openai>=1.0.0"
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries
        )

        logger.info(f"OpenAI 提供商已初始化，使用模型：{self.model}")

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        调用 OpenAI API 完成提示

        Args:
            prompt: 输入提示
            temperature: 温度参数（0.0-1.0）

        Returns:
            模型的 JSON 格式响应文本
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一名专业的加密货币交易分析师。"
                                   "请始终以有效的 JSON 格式响应。"
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                response_format={"type": "json_object"}
            )

            # 存储使用信息
            usage = response.usage
            self.last_usage = {
                "tokens_used": usage.total_tokens,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cost_usd": self._calculate_cost(usage)
            }

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"OpenAI API 调用失败：{e}")
            raise

    def get_usage_info(self) -> Dict[str, Any]:
        """获取最后一次 API 调用的使用信息"""
        return self.last_usage

    def _calculate_cost(self, usage) -> float:
        """
        根据令牌使用量计算成本

        2024 年价格（需要时更新）：
        - gpt-4o：输入 $5/100万，输出 $15/100万
        - gpt-4o-mini：输入 $0.15/100万，输出 $0.6/100万
        - gpt-4-turbo：输入 $10/100万，输出 $30/100万
        """
        pricing = {
            "gpt-4o": {"input": 5.0, "output": 15.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.6},
            "gpt-4-turbo": {"input": 10.0, "output": 30.0},
            "gpt-4-turbo-preview": {"input": 10.0, "output": 30.0},
            "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        }

        # 如果找不到模型，使用默认定价
        model_pricing = pricing.get(self.model, {"input": 5.0, "output": 15.0})

        input_cost = (usage.prompt_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (usage.completion_tokens / 1_000_000) * model_pricing["output"]

        return input_cost + output_cost
