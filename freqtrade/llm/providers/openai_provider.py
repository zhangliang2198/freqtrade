"""
OpenAI LLM Provider
"""

from typing import Dict, Any
import logging

from freqtrade.llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(LLMProvider):
    """
    OpenAI API provider for GPT models

    Supports models like gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize OpenAI provider

        Args:
            config: Configuration dictionary containing:
                - model: Model name (e.g., "gpt-4o")
                - api_key: OpenAI API key
                - base_url: Optional custom API endpoint
                - timeout: Request timeout in seconds
                - max_retries: Maximum retry attempts
        """
        super().__init__(config)

        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")

        if not self.api_key:
            raise ValueError("OpenAI API key is required")

        # Lazy import to avoid dependency if not used
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "OpenAI package is required for OpenAIProvider. "
                "Install with: pip install openai>=1.0.0"
            )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=self.max_retries
        )

        logger.info(f"OpenAI provider initialized with model: {self.model}")

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        Call OpenAI API to complete a prompt

        Args:
            prompt: The input prompt
            temperature: Temperature parameter (0.0-1.0)

        Returns:
            The model's response text in JSON format
        """
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional cryptocurrency trading analyst. "
                                   "Always respond in valid JSON format."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=temperature,
                response_format={"type": "json_object"}
            )

            # Store usage information
            usage = response.usage
            self.last_usage = {
                "tokens_used": usage.total_tokens,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cost_usd": self._calculate_cost(usage)
            }

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise

    def get_usage_info(self) -> Dict[str, Any]:
        """Get usage information from the last API call"""
        return self.last_usage

    def _calculate_cost(self, usage) -> float:
        """
        Calculate the cost based on token usage

        Pricing as of 2024 (update as needed):
        - gpt-4o: $5/1M input, $15/1M output
        - gpt-4o-mini: $0.15/1M input, $0.6/1M output
        - gpt-4-turbo: $10/1M input, $30/1M output
        """
        pricing = {
            "gpt-4o": {"input": 5.0, "output": 15.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.6},
            "gpt-4-turbo": {"input": 10.0, "output": 30.0},
            "gpt-4-turbo-preview": {"input": 10.0, "output": 30.0},
            "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        }

        # Default pricing if model not found
        model_pricing = pricing.get(self.model, {"input": 5.0, "output": 15.0})

        input_cost = (usage.prompt_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (usage.completion_tokens / 1_000_000) * model_pricing["output"]

        return input_cost + output_cost
