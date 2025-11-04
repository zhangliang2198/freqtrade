"""
Base LLM Provider Interface
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers

    All LLM providers must implement this interface to ensure
    consistent behavior across different models and APIs.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the LLM provider

        Args:
            config: Provider configuration dictionary
        """
        self.config = config
        self.model = config.get("model")
        self.timeout = config.get("timeout", 30)
        self.max_retries = config.get("max_retries", 3)
        self.last_usage = {}

    @abstractmethod
    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        Call the LLM to complete a prompt

        Args:
            prompt: The input prompt
            temperature: Temperature parameter (0.0-1.0), lower = more deterministic

        Returns:
            The LLM response text

        Raises:
            Exception: If the API call fails
        """
        pass

    @abstractmethod
    def get_usage_info(self) -> Dict[str, Any]:
        """
        Get usage information from the last API call

        Returns:
            Dictionary containing:
                - tokens_used: Total tokens consumed
                - cost_usd: Estimated cost in USD
        """
        pass

    def validate_config(self) -> bool:
        """
        Validate the provider configuration

        Returns:
            True if configuration is valid
        """
        required_fields = ["model"]
        for field in required_fields:
            if field not in self.config:
                logger.error(f"Missing required config field: {field}")
                return False
        return True
