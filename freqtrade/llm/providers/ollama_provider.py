"""
Ollama 本地大语言模型提供商
"""

from typing import Dict, Any
import logging
import json

from freqtrade.llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """
    Ollama 本地大语言模型提供商

    支持本地托管的模型，如 Llama 3、Mistral 等。
    需要安装并运行 Ollama。
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Ollama 提供商

        Args:
            config: 配置字典，包含：
                - model: 模型名称（例如："llama3", "mistral"）
                - base_url: Ollama API 端点（默认："http://localhost:11434"）
                - timeout: 请求超时时间（秒）
        """
        super().__init__(config)

        self.base_url = config.get("base_url", "http://localhost:11434")

        logger.info(f"Ollama 提供商已初始化，模型：{self.model}")
        logger.info(f"Ollama 端点：{self.base_url}")

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        调用 Ollama API 来完成提示

        Args:
            prompt: 输入提示
            temperature: 温度参数 (0.0-1.0)

        Returns:
            模型的响应文本，JSON 格式
        """
        try:
            import requests
        except ImportError:
            raise ImportError(
                "OllamaProvider 需要 requests 包。"
                "请使用以下命令安装：pip install requests"
            )

        try:
            # 向提示添加 JSON 指令
            enhanced_prompt = (
                f"{prompt}\n\n"
                "重要：仅以指定格式响应有效的 JSON。"
                "不要包含其他文本、解释或 markdown 格式。"
            )

            # 调用 Ollama API
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": enhanced_prompt,
                    "temperature": temperature,
                    "stream": False,
                    "format": "json"
                },
                timeout=self.timeout
            )

            response.raise_for_status()
            result = response.json()

            # 提取响应文本
            response_text = result.get("response", "")

            # 存储使用信息（Ollama 不收费，但我们跟踪令牌）
            self.last_usage = {
                "tokens_used": result.get("eval_count", 0) + result.get("prompt_eval_count", 0),
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0),
                "cost_usd": 0.0  # 本地模型是免费的
            }

            # 验证 JSON
            try:
                json.loads(response_text)
            except json.JSONDecodeError:
                logger.warning("响应不是有效的 JSON，尝试提取 JSON")
                # 尝试从响应中提取 JSON
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(0)
                else:
                    raise ValueError("无法从响应中提取有效的 JSON")

            return response_text

        except requests.exceptions.ConnectionError:
            logger.error(
                f"无法连接到 Ollama，地址：{self.base_url}。"
                "请确保 Ollama 正在运行（ollama serve）"
            )
            raise
        except Exception as e:
            logger.error(f"Ollama API 调用失败：{e}")
            raise

    def get_usage_info(self) -> Dict[str, Any]:
        """获取上次 API 调用的使用信息"""
        return self.last_usage

    def list_models(self) -> list:
        """
        列出 Ollama 中可用的模型

        Returns:
            模型名称列表
        """
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            return [model["name"] for model in models]
        except Exception as e:
            logger.error(f"列出 Ollama 模型失败：{e}")
            return []

