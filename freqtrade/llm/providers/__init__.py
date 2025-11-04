"""LLM 提供商包"""

from freqtrade.llm.providers.base import LLMProvider
from freqtrade.llm.providers.http_provider import HttpLLMProvider

# 传统提供商（已弃用，请改用 http_provider）
# from freqtrade.llm.providers.ollama_provider import OllamaProvider

__all__ = [
    "LLMProvider",
    "HttpLLMProvider",
]
