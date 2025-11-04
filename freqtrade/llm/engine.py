"""
LLM 决策引擎

用于管理基于 LLM 的交易决策的核心引擎，
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
    """LLM 请求数据结构"""
    decision_point: DecisionPoint
    pair: str
    context: Dict[str, Any]
    trade_id: Optional[int] = None


@dataclass
class LLMResponse:
    """LLM 响应数据结构"""
    decision: str
    confidence: float
    reasoning: str
    parameters: Dict[str, Any]

    # 元数据
    latency_ms: int
    tokens_used: Optional[int]
    cost_usd: Optional[float]
    cached: bool


class LLMDecisionEngine:
    """
    LLM 决策引擎

    协调用于交易决策的 LLM 调用，管理缓存，
    并将结果记录到数据库。
    """

    def __init__(self, config: Dict[str, Any], strategy_name: str):
        """
        初始化 LLM 决策引擎

        Args:
            config: 完整的 Freqtrade 配置
            strategy_name: 使用此引擎的策略名称
        """
        self.config = config.get("llm_config", {})
        self.strategy_name = strategy_name

        if not self.config.get("enabled", False):
            logger.warning("LLM 配置已禁用")
            return

        # 初始化提供商
        self.provider = self._init_provider()

        # 初始化缓存（目前使用简单字典，可以升级到 TTLCache）
        self.caches: Dict[DecisionPoint, Dict[str, tuple[LLMResponse, float]]] = {}
        for point in ["entry", "exit", "stake", "adjust_position", "leverage"]:
            self.caches[point] = {}

        # 初始化提示词管理器
        user_data_dir = config.get("user_data_dir", "user_data")
        self.prompt_manager = PromptManager(self.config, user_data_dir)

        # 初始化上下文构建器
        self.context_builder = ContextBuilder(self.config.get("context", {}))

        # 统计信息
        self.stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "errors": 0,
            "total_cost_usd": 0.0
        }

        logger.info(f"LLM 决策引擎已为策略 {strategy_name} 初始化")
        logger.info(f"提供商: {self.config['provider']}, 模型: {self.config['model']}")

    def decide(self, request: LLMRequest) -> LLMResponse:
        """
        执行 LLM 决策

        Args:
            request: 包含决策点和上下文的 LLM 请求

        Returns:
            包含决策和元数据的 LLM 响应

        Raises:
            Exception: 如果 LLM 调用失败且没有可用的回退选项
        """
        # 检查此决策点是否已启用
        point_config = self.config.get("decision_points", {}).get(request.decision_point, {})
        if not point_config or not point_config.get("enabled", True):
            return self._default_response(request.decision_point)

        # 检查缓存
        cache_key = self._generate_cache_key(request)
        cache_ttl = point_config.get("cache_ttl", 60)
        cached_response = self._check_cache(request.decision_point, cache_key, cache_ttl)

        if cached_response:
            self.stats["cache_hits"] += 1
            cached_response.cached = True
            logger.debug(f"{request.pair} 的 {request.decision_point} 决策命中缓存")
            return cached_response

        # 构建提示词
        try:
            prompt = self.prompt_manager.build_prompt(
                decision_point=request.decision_point,
                context=request.context
            )
        except Exception as e:
            logger.error(f"构建提示词失败: {e}")
            return self._default_response(request.decision_point)

        # 调用 LLM
        start_time = time.time()
        try:
            temperature = self.config.get("temperature", 0.1)
            raw_response = self.provider.complete(prompt=prompt, temperature=temperature)
            latency_ms = int((time.time() - start_time) * 1000)

            # 解析响应
            response = self._parse_response(
                raw_response=raw_response,
                decision_point=request.decision_point,
                latency_ms=latency_ms
            )

            # 获取使用信息
            usage_info = self.provider.get_usage_info()
            response.tokens_used = usage_info.get("tokens_used")
            response.cost_usd = usage_info.get("cost_usd", 0.0)

            # 更新统计信息
            self.stats["total_calls"] += 1
            self.stats["total_cost_usd"] += response.cost_usd or 0.0

            # 验证响应
            if not self._validate_response(response, point_config):
                logger.warning(
                    f"响应验证失败 {request.decision_point}: "
                    f"confidence {response.confidence} < threshold {point_config.get('confidence_threshold', 0.5)}"
                )
                return self._default_response(request.decision_point)

            # 缓存结果
            self._cache_response(request.decision_point, cache_key, response)

            # 记录到数据库
            if self.config.get("performance", {}).get("log_to_database", True):
                self._log_decision(request, response, prompt, raw_response, success=True)

            logger.info(
                f"LLM 决策 {request.pair} {request.decision_point}: "
                f"{response.decision} (confidence: {response.confidence:.2f}, "
                f"latency: {latency_ms}ms, cost: ${response.cost_usd:.4f})"
            )

            return response

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"{request.decision_point} 的 LLM 决策失败: {e}", exc_info=True)

            # 记录错误
            if self.config.get("performance", {}).get("log_to_database", True):
                self._log_decision(request, None, prompt, None, success=False, error=str(e))

            # 返回默认响应
            return self._default_response(request.decision_point)

    def _init_provider(self):
        """根据配置初始化 LLM 提供商"""
        provider_type = self.config.get("provider_type", "http").lower()

        # 解析配置中的环境变量
        resolved_config = self._resolve_env_vars(self.config)

        if provider_type == "http":
            # 通用 HTTP 提供商（推荐）
            from freqtrade.llm.providers import HttpLLMProvider
            return HttpLLMProvider(resolved_config)

        # 旧版提供商（已弃用）
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
            raise ValueError(f"未知的 LLM 提供商类型: {provider_type}")

    def _resolve_env_vars(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析配置中的环境变量

        支持 ${VAR_NAME} 语法
        """
        resolved = config.copy()

        for key, value in resolved.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                env_var = value[2:-1]
                resolved[key] = os.environ.get(env_var)
                if resolved[key] is None:
                    logger.warning(f"未找到环境变量 {env_var}")

        return resolved

    def _generate_cache_key(self, request: LLMRequest) -> str:
        """基于请求上下文生成缓存键"""
        # 从上下文创建确定性字符串
        context_str = json.dumps(request.context, sort_keys=True, default=str)
        cache_key = hashlib.md5(context_str.encode()).hexdigest()
        return cache_key

    def _check_cache(
        self,
        decision_point: str,
        cache_key: str,
        ttl: int
    ) -> Optional[LLMResponse]:
        """检查缓存响应是否存在且仍然有效"""
        cache = self.caches.get(decision_point, {})

        if cache_key in cache:
            response, timestamp = cache[cache_key]
            age = time.time() - timestamp

            if age < ttl:
                return response
            else:
                # 已过期，从缓存中移除
                del cache[cache_key]

        return None

    def _cache_response(self, decision_point: str, cache_key: str, response: LLMResponse):
        """缓存带有时间戳的响应"""
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
        将 LLM 原始响应解析为结构化格式

        Args:
            raw_response: 来自 LLM 的原始 JSON 字符串
            decision_point: 决策点名称
            latency_ms: 请求延迟（毫秒）

        Returns:
            解析后的 LLMResponse

        Raises:
            ValueError: 如果响应无法解析
        """
        try:
            parsed = json.loads(raw_response)

            return LLMResponse(
                decision=parsed.get("decision", "hold"),
                confidence=float(parsed.get("confidence", 0.0)),
                reasoning=parsed.get("reasoning", ""),
                parameters=parsed.get("parameters", {}),
                latency_ms=latency_ms,
                tokens_used=None,  # 稍后填充
                cost_usd=None,  # 稍后填充
                cached=False
            )

        except json.JSONDecodeError as e:
            logger.error(f"无法将 LLM 响应解析为 JSON: {e}")
            logger.error(f"原始响应: {raw_response[:500]}")
            raise ValueError(f"无效的 JSON 响应: {e}")

    def _validate_response(self, response: LLMResponse, config: Dict) -> bool:
        """
        验证响应是否满足要求

        Args:
            response: LLM 响应
            config: 决策点配置

        Returns:
            如果响应有效则返回 True
        """
        # 检查置信度阈值
        threshold = config.get("confidence_threshold", 0.5)
        if response.confidence < threshold:
            return False

        # 检查决策是否为空
        if not response.decision:
            return False

        return True

    def _default_response(self, decision_point: DecisionPoint) -> LLMResponse:
        """
        当 LLM 不可用时返回默认响应

        Args:
            decision_point: 决策点名称

        Returns:
            默认的 LLMResponse
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
            reasoning="LLM 不可用或已禁用，使用默认值",
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
        将决策记录到数据库

        Args:
            request: LLM 请求
            response: LLM 响应（失败时为 None）
            prompt: 发送到 LLM 的提示词
            raw_response: 来自 LLM 的原始响应
            success: 调用是否成功
            error: 失败时的错误消息
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
            logger.error(f"记录决策到数据库失败: {e}")
        finally:
            try:
                Trade.session.remove()
            except Exception:
                # 忽略remove时的异常，避免掩盖原始错误
                pass

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计信息"""
        return {
            **self.stats,
            "cache_hit_rate": (
                self.stats["cache_hits"] / self.stats["total_calls"]
                if self.stats["total_calls"] > 0 else 0.0
            )
        }
