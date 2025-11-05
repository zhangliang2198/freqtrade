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
            config: 配置字典，必须包含:
                - api_url: API 端点 URL（必需）
                - headers: HTTP 请求头模板（必需）
                - request_body: 请求体模板（必需）
                - response_path: 响应路径配置（必需）
                - api_key: API 密钥（可选）
                - cost_config: 成本计算配置（可选）
                - timeout: 请求超时时间（可选）
                - max_retries: 最大重试次数（可选）
        """
        super().__init__(config)

        # 必需配置
        if "api_url" not in config:
            raise ValueError("HTTP LLM 提供商必须配置 api_url")
        if "headers" not in config:
            raise ValueError("HTTP LLM 提供商必须配置 headers")
        if "request_body" not in config:
            raise ValueError("HTTP LLM 提供商必须配置 request_body")
        if "response_path" not in config:
            raise ValueError("HTTP LLM 提供商必须配置 response_path")

        self.api_url = config["api_url"]
        self.headers = config["headers"]
        self.request_body_template = config["request_body"]
        self.response_path = config["response_path"]

        # 可选配置
        self.api_key = config.get("api_key")
        self.cost_config = config.get("cost_config", {})

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
            # 记录详细的请求信息用于调试
            logger.debug(f"LLM 请求 URL: {self.api_url}")
            logger.debug(f"LLM 请求 Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
            logger.debug(f"LLM 请求 Body: {json.dumps(body, indent=2, ensure_ascii=False)}")
            logger.info(f"发送 LLM 请求到 {self.api_url}，超时设置: {self.timeout}秒")
            
            # 发送 HTTP 请求
            response = requests.post(
                self.api_url,
                headers=headers,
                json=body,
                timeout=self.timeout
            )

            # 记录响应状态码和内容
            logger.debug(f"LLM 响应状态码: {response.status_code}")
            logger.debug(f"LLM 响应 Headers: {json.dumps(dict(response.headers), indent=2, ensure_ascii=False)}")
            
            # 在调用 raise_for_status() 之前记录响应内容
            try:
                response_data = response.json()
                logger.debug(f"LLM 响应 Body: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
            except json.JSONDecodeError:
                logger.debug(f"LLM 响应 Body (非JSON): {response.text[:500]}")
            
            response.raise_for_status()
            response_data = response.json()

            # 从响应中提取内容
            content = self._extract_response_content(response_data)

            # 提取使用信息
            self._extract_usage_info(response_data)

            return content

        except requests.exceptions.RequestException as e:
            # 记录更详细的错误信息
            logger.error(f"HTTP LLM 请求失败: {e}")
            logger.error(f"请求URL: {self.api_url}")
            logger.error(f"超时设置: {self.timeout}秒")
            
            # 特殊处理超时错误
            if isinstance(e, requests.exceptions.Timeout):
                logger.error(f"请求超时 - 可能原因: 1)网络延迟 2)服务器响应慢 3)请求体过大")
                logger.error(f"建议: 增加timeout配置或检查网络连接")
            elif isinstance(e, requests.exceptions.ConnectionError):
                logger.error(f"连接错误 - 可能原因: 网络连接问题或DNS解析失败")
            elif isinstance(e, requests.exceptions.ReadTimeout):
                logger.error(f"读取超时 - 服务器已连接但响应时间过长")
            
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"错误状态码: {e.response.status_code}")
                logger.error(f"错误响应头: {json.dumps(dict(e.response.headers), indent=2, ensure_ascii=False)}")
                try:
                    error_data = e.response.json()
                    logger.error(f"错误响应体: {json.dumps(error_data, indent=2, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    logger.error(f"错误响应体 (非JSON): {e.response.text[:500]}")
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
            headers_str = json.dumps(headers, ensure_ascii=False)
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
            "{temperature}": float(temperature),  # 确保temperature是浮点数
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
                # 特殊处理temperature参数，保持数值类型
                if placeholder == "{temperature}":
                    # 如果整个字符串就是占位符，直接返回数值
                    if result == placeholder:
                        return float(value)
                    # 否则进行字符串替换
                    result = result.replace(placeholder, str(value))
                else:
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
        if "content_path" not in self.response_path:
            raise ValueError("response_path 必须配置 content_path")

        content_path = self.response_path["content_path"]
        
        # 添加详细的响应提取日志
        logger.info(f"[DEBUG] 提取响应内容，路径: {content_path}")
        logger.info(f"[DEBUG] 完整响应数据: {json.dumps(response_data, indent=2, ensure_ascii=False)}")

        try:
            # 使用点号表示法导航到内容
            content = self._navigate_path(response_data, content_path)
            logger.info(f"[DEBUG] 提取的原始内容: {content}")
        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(
                f"无法从响应中提取内容，路径 '{content_path}' 无效: {e}\n"
                f"响应数据: {json.dumps(response_data, indent=2, ensure_ascii=False)}"
            )

        # 如果需要，确保是 JSON 格式
        if self.response_path.get("ensure_json", False):
            logger.info(f"[DEBUG] 确保JSON格式，原始内容: {content}")
            content = self._ensure_json_format(content)
            logger.info(f"[DEBUG] 处理后的JSON内容: {content}")

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
        """
        从响应中提取使用信息

        配置示例:
        {
            "response_path": {
                "usage_path": "usage",
                "usage_fields": {
                    "total_tokens": "total_tokens",                # 可选
                    "input_tokens": "prompt_tokens",               # 必需
                    "output_tokens": "completion_tokens",          # 必需
                    "cache_read_tokens": "cache_read_input_tokens",    # 可选：prompt cache 命中的 tokens
                    "cache_creation_tokens": "cache_creation_input_tokens"  # 可选：prompt cache 创建的 tokens
                }
            }
        }
        """
        if "usage_path" not in self.response_path:
            # 如果没有配置 usage_path，设置为零（可选配置）
            logger.debug("未配置 usage_path，使用信息将为0")
            self.last_usage = {
                "tokens_used": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 0,
                "cost_usd": 0.0
            }
            return

        usage_path = self.response_path["usage_path"]

        # 检查必需的字段映射配置
        if "usage_fields" not in self.response_path:
            raise ValueError(
                "配置了 usage_path 就必须配置 usage_fields，指定字段映射\n"
                "示例: {\"usage_fields\": {\"input_tokens\": \"prompt_tokens\", \"output_tokens\": \"completion_tokens\"}}"
            )

        usage_fields = self.response_path["usage_fields"]

        # 检查必需的字段
        if "input_tokens" not in usage_fields:
            raise ValueError("usage_fields 必须包含 input_tokens 字段映射")
        if "output_tokens" not in usage_fields:
            raise ValueError("usage_fields 必须包含 output_tokens 字段映射")

        try:
            usage_data = self._navigate_path(response_data, usage_path)

            # 从配置的字段名中提取数据
            input_field = usage_fields["input_tokens"]
            output_field = usage_fields["output_tokens"]
            total_field = usage_fields.get("total_tokens")
            cache_read_field = usage_fields.get("cache_read_tokens")
            cache_creation_field = usage_fields.get("cache_creation_tokens")

            # 提取基础 token 数量
            prompt_tokens = usage_data.get(input_field, 0)
            completion_tokens = usage_data.get(output_field, 0)

            # 提取 prompt cache tokens（可选）
            cache_read_tokens = usage_data.get(cache_read_field, 0) if cache_read_field else 0
            cache_creation_tokens = usage_data.get(cache_creation_field, 0) if cache_creation_field else 0

            # 总 tokens：优先使用配置的字段，否则计算
            if total_field:
                tokens_used = usage_data.get(total_field, 0)
            else:
                tokens_used = prompt_tokens + completion_tokens + cache_read_tokens + cache_creation_tokens

            # 计算成本（包含 cache tokens）
            cost_usd = self._calculate_cost(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens
            )

            self.last_usage = {
                "tokens_used": tokens_used,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "prompt_cache_hit_tokens": cache_read_tokens,
                "prompt_cache_miss_tokens": cache_creation_tokens,
                "cost_usd": cost_usd
            }

        except (KeyError, IndexError, TypeError) as e:
            raise ValueError(
                f"无法从响应中提取使用信息，路径 '{usage_path}' 无效: {e}\n"
                f"响应数据: {json.dumps(response_data, indent=2, ensure_ascii=False)}"
            )

    def _calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0
    ) -> float:
        """
        基于 token 使用量计算成本

        成本配置格式:
        {
            "input_cost_per_million": 5.0,               # 普通输入 token 成本
            "output_cost_per_million": 15.0,             # 输出 token 成本
            "cache_read_cost_per_million": 0.5,          # cache 命中的输入 token 成本（通常更低）
            "cache_creation_cost_per_million": 6.25      # cache 创建的输入 token 成本（通常略高）
        }

        Args:
            prompt_tokens: 普通输入 tokens
            completion_tokens: 输出 tokens
            cache_read_tokens: prompt cache 命中的 tokens
            cache_creation_tokens: prompt cache 创建的 tokens

        Returns:
            总成本（美元）
        """
        if not self.cost_config:
            return 0.0

        input_cost_per_million = self.cost_config.get("input_cost_per_million", 0.0)
        output_cost_per_million = self.cost_config.get("output_cost_per_million", 0.0)
        cache_read_cost_per_million = self.cost_config.get("cache_read_cost_per_million", 0.0)
        cache_creation_cost_per_million = self.cost_config.get("cache_creation_cost_per_million", 0.0)

        # 计算各部分成本
        input_cost = (prompt_tokens / 1_000_000) * input_cost_per_million
        output_cost = (completion_tokens / 1_000_000) * output_cost_per_million
        cache_read_cost = (cache_read_tokens / 1_000_000) * cache_read_cost_per_million
        cache_creation_cost = (cache_creation_tokens / 1_000_000) * cache_creation_cost_per_million

        return input_cost + output_cost + cache_read_cost + cache_creation_cost
