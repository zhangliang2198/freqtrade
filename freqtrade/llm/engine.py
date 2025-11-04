"""
LLM Decision Engine

Core engine for managing LLM-based trading decisions.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal
from datetime import datetime
import time
import json
import hashlib
import logging
import os

from freqtrade.llm.context_builder import ContextBuilder
from freqtrade.llm.prompts.manager import PromptManager

logger = logging.getLogger(__name__)

DecisionPoint = Literal["entry", "exit", "stake", "adjust_position", "leverage"]


@dataclass
class LLMRequest:
    """LLM request data structure"""
    decision_point: DecisionPoint
    pair: str
    context: Dict[str, Any]
    trade_id: Optional[int] = None


@dataclass
class LLMResponse:
    """LLM response data structure"""
    decision: str
    confidence: float
    reasoning: str
    parameters: Dict[str, Any]

    # Metadata
    latency_ms: int
    tokens_used: Optional[int]
    cost_usd: Optional[float]
    cached: bool


class LLMDecisionEngine:
    """
    LLM Decision Engine

    Orchestrates LLM calls for trading decisions, manages caching,
    and logs results to database.
    """

    def __init__(self, config: Dict[str, Any], strategy_name: str):
        """
        Initialize the LLM decision engine

        Args:
            config: Full Freqtrade configuration
            strategy_name: Name of the strategy using this engine
        """
        self.config = config.get("llm_config", {})
        self.strategy_name = strategy_name

        if not self.config.get("enabled", False):
            logger.warning("LLM config is disabled")
            return

        # Initialize provider
        self.provider = self._init_provider()

        # Initialize cache (using simple dict for now, can upgrade to TTLCache)
        self.caches: Dict[DecisionPoint, Dict[str, tuple[LLMResponse, float]]] = {}
        for point in ["entry", "exit", "stake", "adjust_position", "leverage"]:
            self.caches[point] = {}

        # Initialize prompt manager
        user_data_dir = config.get("user_data_dir", "user_data")
        self.prompt_manager = PromptManager(self.config, user_data_dir)

        # Initialize context builder
        self.context_builder = ContextBuilder(self.config.get("context", {}))

        # Statistics
        self.stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "errors": 0,
            "total_cost_usd": 0.0
        }

        logger.info(f"LLM Decision Engine initialized for strategy: {strategy_name}")
        logger.info(f"Provider: {self.config['provider']}, Model: {self.config['model']}")

    def decide(self, request: LLMRequest) -> LLMResponse:
        """
        Execute an LLM decision

        Args:
            request: LLM request with decision point and context

        Returns:
            LLM response with decision and metadata

        Raises:
            Exception: If LLM call fails and no fallback available
        """
        # Check if this decision point is enabled
        point_config = self.config.get("decision_points", {}).get(request.decision_point, {})
        if not point_config or not point_config.get("enabled", True):
            return self._default_response(request.decision_point)

        # Check cache
        cache_key = self._generate_cache_key(request)
        cache_ttl = point_config.get("cache_ttl", 60)
        cached_response = self._check_cache(request.decision_point, cache_key, cache_ttl)

        if cached_response:
            self.stats["cache_hits"] += 1
            cached_response.cached = True
            logger.debug(f"Cache hit for {request.decision_point} on {request.pair}")
            return cached_response

        # Build prompt
        try:
            prompt = self.prompt_manager.build_prompt(
                decision_point=request.decision_point,
                context=request.context
            )
        except Exception as e:
            logger.error(f"Failed to build prompt: {e}")
            return self._default_response(request.decision_point)

        # Call LLM
        start_time = time.time()
        try:
            temperature = self.config.get("temperature", 0.1)
            raw_response = self.provider.complete(prompt=prompt, temperature=temperature)
            latency_ms = int((time.time() - start_time) * 1000)

            # Parse response
            response = self._parse_response(
                raw_response=raw_response,
                decision_point=request.decision_point,
                latency_ms=latency_ms
            )

            # Get usage info
            usage_info = self.provider.get_usage_info()
            response.tokens_used = usage_info.get("tokens_used")
            response.cost_usd = usage_info.get("cost_usd", 0.0)

            # Update stats
            self.stats["total_calls"] += 1
            self.stats["total_cost_usd"] += response.cost_usd or 0.0

            # Validate response
            if not self._validate_response(response, point_config):
                logger.warning(
                    f"Response failed validation for {request.decision_point}: "
                    f"confidence {response.confidence} < threshold {point_config.get('confidence_threshold', 0.5)}"
                )
                return self._default_response(request.decision_point)

            # Cache result
            self._cache_response(request.decision_point, cache_key, response)

            # Log to database
            if self.config.get("performance", {}).get("log_to_database", True):
                self._log_decision(request, response, prompt, raw_response, success=True)

            logger.info(
                f"LLM decision for {request.pair} {request.decision_point}: "
                f"{response.decision} (confidence: {response.confidence:.2f}, "
                f"latency: {latency_ms}ms, cost: ${response.cost_usd:.4f})"
            )

            return response

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"LLM decision failed for {request.decision_point}: {e}", exc_info=True)

            # Log error
            if self.config.get("performance", {}).get("log_to_database", True):
                self._log_decision(request, None, prompt, None, success=False, error=str(e))

            # Return default response
            return self._default_response(request.decision_point)

    def _init_provider(self):
        """Initialize the LLM provider based on configuration"""
        provider_type = self.config.get("provider_type", "http").lower()

        # Resolve environment variables in config
        resolved_config = self._resolve_env_vars(self.config)

        if provider_type == "http":
            # Universal HTTP provider (recommended)
            from freqtrade.llm.providers import HttpLLMProvider
            return HttpLLMProvider(resolved_config)

        # Legacy providers (deprecated)
        elif provider_type == "openai_legacy":
            from freqtrade.llm.providers import OpenAIProvider
            return OpenAIProvider(resolved_config)

        elif provider_type == "anthropic_legacy":
            from freqtrade.llm.providers import AnthropicProvider
            return AnthropicProvider(resolved_config)

        elif provider_type == "ollama_legacy":
            from freqtrade.llm.providers import OllamaProvider
            return OllamaProvider(resolved_config)

        else:
            raise ValueError(f"Unknown LLM provider type: {provider_type}")

    def _resolve_env_vars(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve environment variables in config

        Supports ${VAR_NAME} syntax
        """
        resolved = config.copy()

        for key, value in resolved.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                resolved[key] = os.environ.get(env_var)
                if resolved[key] is None:
                    logger.warning(f"Environment variable {env_var} not found")

        return resolved

    def _generate_cache_key(self, request: LLMRequest) -> str:
        """Generate a cache key based on request context"""
        # Create a deterministic string from context
        context_str = json.dumps(request.context, sort_keys=True, default=str)
        cache_key = hashlib.md5(context_str.encode()).hexdigest()
        return cache_key

    def _check_cache(
        self,
        decision_point: str,
        cache_key: str,
        ttl: int
    ) -> Optional[LLMResponse]:
        """Check if a cached response exists and is still valid"""
        cache = self.caches.get(decision_point, {})

        if cache_key in cache:
            response, timestamp = cache[cache_key]
            age = time.time() - timestamp

            if age < ttl:
                return response
            else:
                # Expired, remove from cache
                del cache[cache_key]

        return None

    def _cache_response(self, decision_point: str, cache_key: str, response: LLMResponse):
        """Cache a response with timestamp"""
        cache = self.caches.get(decision_point, {})
        cache[cache_key] = (response, time.time())
        self.caches[decision_point] = cache

    def _parse_response(
        self,
        raw_response: str,
        decision_point: str,
        latency_ms: int
    ) -> LLMResponse:
        """
        Parse LLM raw response into structured format

        Args:
            raw_response: Raw JSON string from LLM
            decision_point: Decision point name
            latency_ms: Request latency in milliseconds

        Returns:
            Parsed LLMResponse

        Raises:
            ValueError: If response cannot be parsed
        """
        try:
            parsed = json.loads(raw_response)

            return LLMResponse(
                decision=parsed.get("decision", "hold"),
                confidence=float(parsed.get("confidence", 0.0)),
                reasoning=parsed.get("reasoning", ""),
                parameters=parsed.get("parameters", {}),
                latency_ms=latency_ms,
                tokens_used=None,  # Will be filled later
                cost_usd=None,  # Will be filled later
                cached=False
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Raw response: {raw_response[:500]}")
            raise ValueError(f"Invalid JSON response: {e}")

    def _validate_response(self, response: LLMResponse, config: Dict) -> bool:
        """
        Validate that response meets requirements

        Args:
            response: LLM response
            config: Decision point configuration

        Returns:
            True if response is valid
        """
        # Check confidence threshold
        threshold = config.get("confidence_threshold", 0.5)
        if response.confidence < threshold:
            return False

        # Check that decision is not empty
        if not response.decision:
            return False

        return True

    def _default_response(self, decision_point: DecisionPoint) -> LLMResponse:
        """
        Return a default response when LLM is unavailable

        Args:
            decision_point: Decision point name

        Returns:
            Default LLMResponse
        """
        defaults = {
            "entry": "hold",
            "exit": "hold",
            "stake": "default",
            "adjust_position": "no_change",
            "leverage": "default"
        }

        return LLMResponse(
            decision=defaults.get(decision_point, "hold"),
            confidence=0.0,
            reasoning="LLM not available or disabled, using default",
            parameters={},
            latency_ms=0,
            tokens_used=None,
            cost_usd=None,
            cached=False
        )

    def _log_decision(
        self,
        request: LLMRequest,
        response: Optional[LLMResponse],
        prompt: str,
        raw_response: Optional[str],
        success: bool,
        error: Optional[str] = None
    ):
        """
        Log decision to database

        Args:
            request: LLM request
            response: LLM response (None if failed)
            prompt: The prompt sent to LLM
            raw_response: Raw response from LLM
            success: Whether the call succeeded
            error: Error message if failed
        """
        try:
            from freqtrade.persistence.llm_models import LLMDecision
            from freqtrade.persistence import Trade

            perf_config = self.config.get("performance", {})

            decision_log = LLMDecision(
                trade_id=request.trade_id,
                pair=request.pair,
                strategy=self.strategy_name,
                decision_point=request.decision_point,
                provider=self.config["provider"],
                model=self.config["model"],
                prompt=prompt if perf_config.get("log_prompts", False) else None,
                response=raw_response if perf_config.get("log_responses", True) else None,
                decision=response.decision if response else "error",
                confidence=response.confidence if response else None,
                reasoning=response.reasoning if response else None,
                parameters=json.dumps(response.parameters) if response else None,
                latency_ms=response.latency_ms if response else 0,
                tokens_used=response.tokens_used if response else None,
                cost_usd=response.cost_usd if response else None,
                success=success,
                error_message=error,
                created_at=datetime.utcnow()
            )

            Trade.session.add(decision_log)
            Trade.commit()

        except Exception as e:
            logger.error(f"Failed to log decision to database: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics"""
        return {
            **self.stats,
            "cache_hit_rate": (
                self.stats["cache_hits"] / self.stats["total_calls"]
                if self.stats["total_calls"] > 0 else 0.0
            )
        }
