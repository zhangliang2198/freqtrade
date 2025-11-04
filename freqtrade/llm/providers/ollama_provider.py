"""
Ollama Local LLM Provider
"""

from typing import Dict, Any
import logging
import json

from freqtrade.llm.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class OllamaProvider(LLMProvider):
    """
    Ollama local LLM provider

    Supports locally hosted models like Llama 3, Mistral, etc.
    Requires Ollama to be installed and running.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Ollama provider

        Args:
            config: Configuration dictionary containing:
                - model: Model name (e.g., "llama3", "mistral")
                - base_url: Ollama API endpoint (default: "http://localhost:11434")
                - timeout: Request timeout in seconds
        """
        super().__init__(config)

        self.base_url = config.get("base_url", "http://localhost:11434")

        logger.info(f"Ollama provider initialized with model: {self.model}")
        logger.info(f"Ollama endpoint: {self.base_url}")

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        Call Ollama API to complete a prompt

        Args:
            prompt: The input prompt
            temperature: Temperature parameter (0.0-1.0)

        Returns:
            The model's response text in JSON format
        """
        try:
            import requests
        except ImportError:
            raise ImportError(
                "requests package is required for OllamaProvider. "
                "Install with: pip install requests"
            )

        try:
            # Add JSON instruction to prompt
            enhanced_prompt = (
                f"{prompt}\n\n"
                "IMPORTANT: Respond ONLY with valid JSON in the specified format. "
                "No other text, explanations, or markdown formatting."
            )

            # Call Ollama API
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

            # Extract response text
            response_text = result.get("response", "")

            # Store usage information (Ollama doesn't charge, but we track tokens)
            self.last_usage = {
                "tokens_used": result.get("eval_count", 0) + result.get("prompt_eval_count", 0),
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0),
                "cost_usd": 0.0  # Local models are free
            }

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

        except requests.exceptions.ConnectionError:
            logger.error(
                f"Could not connect to Ollama at {self.base_url}. "
                "Make sure Ollama is running (ollama serve)"
            )
            raise
        except Exception as e:
            logger.error(f"Ollama API call failed: {e}")
            raise

    def get_usage_info(self) -> Dict[str, Any]:
        """Get usage information from the last API call"""
        return self.last_usage

    def list_models(self) -> list:
        """
        List available models in Ollama

        Returns:
            List of model names
        """
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])
            return [model["name"] for model in models]
        except Exception as e:
            logger.error(f"Failed to list Ollama models: {e}")
            return []
