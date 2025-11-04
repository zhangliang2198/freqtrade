"""
Anthropic Claude LLM Provider
"""

from typing import Dict, Any
import logging
import json

from freqtrade.llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    """
    Anthropic Claude API provider

    Supports Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku, etc.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Anthropic provider

        Args:
            config: Configuration dictionary containing:
                - model: Model name (e.g., "claude-3-5-sonnet-20241022")
                - api_key: Anthropic API key
                - timeout: Request timeout in seconds
                - max_retries: Maximum retry attempts
        """
        super().__init__(config)

        self.api_key = config.get("api_key")

        if not self.api_key:
            raise ValueError("Anthropic API key is required")

        # Lazy import to avoid dependency if not used
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "Anthropic package is required for AnthropicProvider. "
                "Install with: pip install anthropic>=0.25.0"
            )

        self.client = Anthropic(
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=self.max_retries
        )

        logger.info(f"Anthropic provider initialized with model: {self.model}")

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        Call Anthropic API to complete a prompt

        Args:
            prompt: The input prompt
            temperature: Temperature parameter (0.0-1.0)

        Returns:
            The model's response text in JSON format
        """
        try:
            # Add JSON instruction to prompt
            enhanced_prompt = (
                f"{prompt}\n\n"
                "IMPORTANT: Respond ONLY with valid JSON. No other text."
            )

            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                temperature=temperature,
                messages=[
                    {"role": "user", "content": enhanced_prompt}
                ]
            )

            # Store usage information
            usage = response.usage
            self.last_usage = {
                "tokens_used": usage.input_tokens + usage.output_tokens,
                "prompt_tokens": usage.input_tokens,
                "completion_tokens": usage.output_tokens,
                "cost_usd": self._calculate_cost(usage)
            }

            # Extract text from response
            response_text = response.content[0].text

            # Validate JSON
            try:
                json.loads(response_text)
            except json.JSONDecodeError:
                logger.warning("Response is not valid JSON, attempting to extract JSON")
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    response_text = json_match.group(0)
                else:
                    raise ValueError("Could not extract valid JSON from response")

            return response_text

        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            raise

    def get_usage_info(self) -> Dict[str, Any]:
        """Get usage information from the last API call"""
        return self.last_usage

    def _calculate_cost(self, usage) -> float:
        """
        Calculate the cost based on token usage

        Pricing as of 2024 (update as needed):
        - Claude 3.5 Sonnet: $3/1M input, $15/1M output
        - Claude 3 Opus: $15/1M input, $75/1M output
        - Claude 3 Sonnet: $3/1M input, $15/1M output
        - Claude 3 Haiku: $0.25/1M input, $1.25/1M output
        """
        pricing = {
            "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
            "claude-3-5-sonnet-20240620": {"input": 3.0, "output": 15.0},
            "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
            "claude-3-sonnet-20240229": {"input": 3.0, "output": 15.0},
            "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
        }

        # Default pricing if model not found
        model_pricing = pricing.get(self.model, {"input": 3.0, "output": 15.0})

        input_cost = (usage.input_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (usage.output_tokens / 1_000_000) * model_pricing["output"]

        return input_cost + output_cost
