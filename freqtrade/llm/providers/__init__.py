"""LLM Providers Package"""

from freqtrade.llm.providers.base import LLMProvider
from freqtrade.llm.providers.http_provider import HttpLLMProvider

# Legacy providers (deprecated, use http_provider instead)
from freqtrade.llm.providers.openai_provider import OpenAIProvider
from freqtrade.llm.providers.anthropic_provider import AnthropicProvider
from freqtrade.llm.providers.ollama_provider import OllamaProvider

__all__ = [
    "LLMProvider",
    "HttpLLMProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OllamaProvider",
]
