"""
通用 HTTP LLM 提供商

通过配置即可支持任意 LLM API 的通用 HTTP 提供商。
"""

from typing import Dict, Any, Optional
import logging
import json
import requests

from freqtrade.llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class HttpLLMProvider(LLMProvider):
    """
    通用 HTTP LLM 提供商

    通过配置以下内容即可支持任意 LLM API：
    - API 端点 URL
    - 请求格式（headers, body 模板）
    - 响应格式（JSON 路径提取内容）
    - 成本计算

    不同提供商的配置示例见 config_examples/llm_providers/
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 HTTP LLM 提供商

        Args:
            config: 配置字典，包含:
                - api_url: API 端点 URL
                - api_key: API 密钥（可选）
                - headers: HTTP 请求头模板
                - request_body: 请求体模板
                - response_path: 响应路径配置
                - cost_config: 成本计算配置
                - timeout: 请求超时时间
                - max_retries: 最大重试次数
        """
        super().__init__(config)

        self.api_url = config.get("api_url")
        self.api_key = config.get("api_key")
        self.headers = config.get("headers", {})
        self.request_body_template = config.get("request_body", {})
        self.response_path = config.get("response_path", {})
        self.cost_config = config.get("cost_config", {})

        if not self.api_url:
            raise ValueError("HTTP LLM 提供商需要配置 api_url")

        logger.info(f"HTTP LLM 提供商已初始化: {self.api_url}")

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        通过 HTTP 调用 LLM API

        Args:
            prompt: 输入提示词
            temperature: 温度参数 (0.0-1.0)

        Returns:
            LLM 响应文本

        Raises:
            Exception: 当 API 调用失败时
        """
        # 构建请求头
        headers = self._build_headers()

        # 构建请求体
        body = self._build_request_body(prompt, temperature)

        try:
            # 发送 HTTP 请求
            response = requests.post(
                self.api_url,
                headers=headers,
                json=body,
                timeout=self.timeout
            )

            response.raise_for_status()
            response_data = response.json()

            # 从响应中提取内容
            content = self._extract_response_content(response_data)

            # 提取使用信息
            self._extract_usage_info(response_data)

            return content

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP LLM 请求失败: {e}")
            raise
        except Exception as e:
            logger.error(f"处理 LLM 响应失败: {e}")
            raise

    def get_usage_info(self) -> Dict[str, Any]:
        """获取最后一次 API 调用的使用信息"""
        return self.last_usage

    def _build_headers(self) -> Dict[str, str]:
        """从模板构建 HTTP 请求头"""
        headers = self.headers.copy()

        # 替换占位符
        if self.api_key and "{api_key}" in str(headers):
            headers_str = json.dumps(headers)
            headers_str = headers_str.replace("{api_key}", self.api_key)
            headers = json.loads(headers_str)

        return headers

    def _build_request_body(self, prompt: str, temperature: float) -> Dict[str, Any]:
        """
        从模板构建请求体

        替换占位符:
        - {prompt}: 用户提示词
        - {temperature}: 温度值
        - {model}: 模型名称
        """
        body = json.loads(json.dumps(self.request_body_template))

        # 递归替换占位符
        body = self._replace_placeholders(body, {
            "{prompt}": prompt,
            "{temperature}": temperature,
            "{model}": self.model
        })

        return body

    def _replace_placeholders(self, obj: Any, replacements: Dict[str, Any]) -> Any:
        """递归替换嵌套结构中的占位符"""
        if isinstance(obj, dict):
            return {k: self._replace_placeholders(v, replacements) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._replace_placeholders(item, replacements) for item in obj]
        elif isinstance(obj, str):
            result = obj
            for placeholder, value in replacements.items():
                result = result.replace(placeholder, str(value))
            return result
        else:
            return obj

    def _extract_response_content(self, response_data: Dict[str, Any]) -> str:
        """
        使用配置的路径从响应中提取内容

        响应路径配置示例:
        {
            "content_path": "choices.0.message.content",
            "ensure_json": true
        }
        """
        content_path = self.response_path.get("content_path", "")

        if not content_path:
            # 如果没有指定路径，尝试常见模式
            content = self._try_common_paths(response_data)
        else:
            # 使用点号表示法导航到内容
            content = self._navigate_path(response_data, content_path)

        # 如果需要，确保是 JSON 格式
        if self.response_path.get("ensure_json", False):
            content = self._ensure_json_format(content)

        return content

    def _navigate_path(self, data: Any, path: str) -> Any:
        """
        使用点号表示法导航嵌套结构

        示例:
        - "choices.0.message.content" -> data["choices"][0]["message"]["content"]
        - "result.text" -> data["result"]["text"]
        """
        parts = path.split(".")
        current = data

        for part in parts:
            if part.isdigit():
                # 数组索引
                current = current[int(part)]
            else:
                # 字典键
                current = current[part]

        return current

    def _try_common_paths(self, data: Dict[str, Any]) -> str:
        """尝试常见的响应模式"""
        common_paths = [
            "choices.0.message.content",  # OpenAI 格式
            "content.0.text",              # Anthropic 格式
            "response",                    # 简单格式
            "text",                        # 简单格式
            "result.text",                 # 通用格式
        ]

        for path in common_paths:
            try:
                return self._navigate_path(data, path)
            except (KeyError, IndexError, TypeError):
                continue

        # 如果都不行，返回整个响应的字符串形式
        logger.warning("无法从响应中提取内容，返回完整响应")
        return json.dumps(data)

    def _ensure_json_format(self, content: str) -> str:
        """确保内容是有效的 JSON，必要时提取"""
        try:
            # 尝试解析为 JSON
            json.loads(content)
            return content
        except json.JSONDecodeError:
            # 尝试从文本中提取 JSON
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json_match.group(0)
            else:
                logger.warning("无法从响应中提取 JSON")
                return content

    def _extract_usage_info(self, response_data: Dict[str, Any]):
        """从响应中提取使用信息"""
        usage_path = self.response_path.get("usage_path", "")

        if not usage_path:
            # 尝试常见模式
            self._try_common_usage_paths(response_data)
            return

        try:
            usage_data = self._navigate_path(response_data, usage_path)

            # 提取 token 数量
            tokens_used = usage_data.get("total_tokens", 0)
            if tokens_used == 0:
                tokens_used = usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0)

            prompt_tokens = usage_data.get("prompt_tokens", usage_data.get("input_tokens", 0))
            completion_tokens = usage_data.get("completion_tokens", usage_data.get("output_tokens", 0))

            # 计算成本
            cost_usd = self._calculate_cost(prompt_tokens, completion_tokens)

            self.last_usage = {
                "tokens_used": tokens_used,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost_usd
            }

        except Exception as e:
            logger.warning(f"提取使用信息失败: {e}")
            self.last_usage = {
                "tokens_used": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_usd": 0.0
            }

    def _try_common_usage_paths(self, data: Dict[str, Any]):
        """尝试从常见路径提取使用信息"""
        common_paths = [
            "usage",           # OpenAI 格式
            "usage.tokens",    # 替代格式
        ]

        for path in common_paths:
            try:
                usage_data = self._navigate_path(data, path)
                tokens_used = usage_data.get("total_tokens", 0)
                if tokens_used == 0:
                    tokens_used = usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0)

                prompt_tokens = usage_data.get("prompt_tokens", usage_data.get("input_tokens", 0))
                completion_tokens = usage_data.get("completion_tokens", usage_data.get("output_tokens", 0))

                cost_usd = self._calculate_cost(prompt_tokens, completion_tokens)

                self.last_usage = {
                    "tokens_used": tokens_used,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "cost_usd": cost_usd
                }
                return
            except (KeyError, IndexError, TypeError):
                continue

        # 默认为零
        self.last_usage = {
            "tokens_used": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0
        }

    def _calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """
        基于 token 使用量计算成本

        成本配置格式:
        {
            "input_cost_per_million": 5.0,
            "output_cost_per_million": 15.0
        }
        """
        if not self.cost_config:
            return 0.0

        input_cost_per_million = self.cost_config.get("input_cost_per_million", 0.0)
        output_cost_per_million = self.cost_config.get("output_cost_per_million", 0.0)

        input_cost = (prompt_tokens / 1_000_000) * input_cost_per_million
        output_cost = (completion_tokens / 1_000_000) * output_cost_per_million

        return input_cost + output_cost
