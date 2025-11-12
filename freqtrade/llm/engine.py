"""
LLM 决策引擎

用于管理基于 LLM 的交易决策的核心引擎，
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal, List
from datetime import datetime
import time
import json
import hashlib
import logging
import re
            # 通用 HTTP 提供商（推荐）
from freqtrade.llm.providers import HttpLLMProvider
from freqtrade.llm.context_builder import ContextBuilder
from freqtrade.llm.prompts.manager import PromptManager
from freqtrade.util import dt_now

logger = logging.getLogger(__name__)

# 预编译正则（对齐 JSON 提取逻辑）
JSON_FENCE_RE = re.compile(r"```json\s*(?P<json>(?:.|\s)+?)```", re.IGNORECASE)
JSON_ARRAY_RE = re.compile(r"\[\s*\{.*?\}\s*\]", re.DOTALL | re.IGNORECASE)
INVISIBLE_RUNE_RE = re.compile(r"[\u200B\u200C\u200D\uFEFF]")
ARRAY_OPEN_WITH_SPACE_RE = re.compile(r"\[\s+\{", re.DOTALL)

FULLWIDTH_TRANSLATION = str.maketrans({
    "“": "\"",
    "”": "\"",
    "‘": "'",
    "’": "'",
    "［": "[",
    "］": "]",
    "｛": "{",
    "｝": "}",
    "：": ":",
    "，": ",",
    "【": "[",
    "】": "]",
    "〔": "[",
    "〕": "]",
    "、": ",",
    "　": " ",
})

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
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    prompt_cache_hit_tokens: Optional[int]
    prompt_cache_miss_tokens: Optional[int]
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
        self.context_builder = ContextBuilder(
            self.config.get("context", {}),
            self.config.get("decision_points", {})
        )

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
            logger.info(f"准备调用 LLM API，提供商: {self.config.get('provider')}, 模型: {self.config.get('model')}")
            logger.info(f"提示词长度: {len(prompt)} 字符")
            logger.info(f"温度参数: {temperature}")
            
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
            response.prompt_tokens = usage_info.get("prompt_tokens")
            response.completion_tokens = usage_info.get("completion_tokens")
            response.prompt_cache_hit_tokens = usage_info.get("prompt_cache_hit_tokens")
            response.prompt_cache_miss_tokens = usage_info.get("prompt_cache_miss_tokens")
            response.cost_usd = usage_info.get("cost_usd", 0.0)

            # 更新统计信息
            self.stats["total_calls"] += 1
            self.stats["total_cost_usd"] += response.cost_usd or 0.0

            # 验证响应
            validation_passed = self._validate_response(response, point_config)

            # 无论验证是否通过，都缓存结果（避免重复调用）
            self._cache_response(request.decision_point, cache_key, response)

            # 无论验证是否通过，都记录到数据库（用于分析和调试）
            if self.config.get("performance", {}).get("log_to_database", True):
                self._log_decision(
                    request,
                    response,
                    prompt,
                    raw_response,
                    success=validation_passed,
                    error=None if validation_passed else f"置信度不足: {response.confidence} < {point_config.get('confidence_threshold', 0.5)}"
                )

            if not validation_passed:
                logger.info(
                    f"响应验证失败 {request.decision_point}: "
                    f"confidence {response.confidence} < threshold {point_config.get('confidence_threshold', 0.5)}"
                )
                return self._default_response(request.decision_point)

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
        if provider_type == "http":
            return HttpLLMProvider(self.config)

        # 旧版提供商（已弃用）
        elif provider_type in ["openai_legacy", "anthropic_legacy", "ollama_legacy"]:
            raise ValueError(
                f"LLM 提供商类型 '{provider_type}' 已弃用。"
                f"请使用 'http' 提供商并通过配置指定 API 端点。"
                f"参考文档了解如何配置 http_provider。"
            )

        else:
            raise ValueError(f"未知的 LLM 提供商类型: {provider_type}")

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
        logger.info(f"[DEBUG] {decision_point} 原始响应: {raw_response}")

        cleaned_text = self._clean_response_text(raw_response)
        payload = self._load_decision_payload(cleaned_text)

        decision = str(payload.get("decision", "hold")).strip() or "hold"

        # 将置信度归一化到 0-1 区间（LLM 常见返回 0-100 百分比）
        confidence_raw = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            logger.warning(f"[DEBUG] 置信度字段无法转换: {confidence_raw!r}，使用 0.0")
            confidence = 0.0
        if confidence > 1.0 and confidence <= 100.0:
            logger.info(f"[DEBUG] 将百分比置信度 {confidence} 转换为 0-1 区间")
            confidence /= 100.0
        confidence = max(0.0, min(confidence, 1.0))

        reasoning = str(payload.get("reasoning", "") or "").strip()

        parameters_raw = payload.get("parameters", {})
        if isinstance(parameters_raw, dict):
            parameters = parameters_raw
        else:
            logger.warning(
                f"[DEBUG] parameters 字段类型异常 ({type(parameters_raw).__name__})，使用空字典"
            )
            parameters = {}

        logger.info(f"[DEBUG] {decision_point} 解析结果:")
        logger.info(f"[DEBUG]   - decision: {decision}")
        logger.info(f"[DEBUG]   - confidence: {confidence}")
        logger.info(f"[DEBUG]   - reasoning: {reasoning}")
        logger.info(f"[DEBUG]   - parameters: {parameters}")

        return LLMResponse(
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
            parameters=parameters,
            latency_ms=latency_ms,
            tokens_used=None,
            prompt_tokens=None,
            completion_tokens=None,
            prompt_cache_hit_tokens=None,
            prompt_cache_miss_tokens=None,
            cost_usd=None,
            cached=False
        )

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
        
        # 添加详细的验证日志
        logger.info(f"[DEBUG] 响应验证:")
        logger.info(f"[DEBUG]   - 置信度: {response.confidence}")
        logger.info(f"[DEBUG]   - 阈值: {threshold}")
        logger.info(f"[DEBUG]   - 决策: {response.decision}")
        logger.info(f"[DEBUG]   - 推理: {response.reasoning}")
        
        if response.confidence < threshold:
            logger.info(f"[DEBUG] 置信度验证失败: {response.confidence} < {threshold}")
            return False

        # 检查决策是否为空
        if not response.decision:
            logger.warning(f"[DEBUG] 决策为空，验证失败")
            return False

        logger.info(f"[DEBUG] 响应验证通过")
        return True

    def _clean_response_text(self, text: str) -> str:
        """去除零宽字符、全角符号并规整 JSON 格式"""
        if not isinstance(text, str):
            text = str(text)
        text = INVISIBLE_RUNE_RE.sub("", text)
        text = text.translate(FULLWIDTH_TRANSLATION)
        text = text.replace("\r\n", "\n").strip()
        text = ARRAY_OPEN_WITH_SPACE_RE.sub("[{", text)
        return text

    def _load_decision_payload(self, text: str) -> Dict[str, Any]:
        """
        尝试从原始 LLM 输出中解析出决策字典

        兼容以下格式:
        1. 直接返回 JSON 对象
        2. 带有 ```json ``` 代码块
        3. 先输出思维链，再附带 JSON 对象/数组
        """
        direct = self._safe_json_load(text)
        if direct is not None:
            return self._ensure_dict_payload(direct)

        for segment in self._extract_json_segments(text):
            parsed = self._safe_json_load(segment)
            if parsed is not None:
                return self._ensure_dict_payload(parsed)

        snippet = text[:200]
        logger.error(f"无法在响应中找到有效 JSON 段落，截取片段: {snippet!r}")
        raise ValueError("未能解析 LLM 响应 JSON。")

    def _extract_json_segments(self, text: str) -> List[str]:
        """按优先级提取所有潜在的 JSON 段落"""
        segments = []

        fence_match = JSON_FENCE_RE.search(text)
        if fence_match:
            segments.append(fence_match.group("json").strip())

        segments.extend(match.strip() for match in JSON_ARRAY_RE.findall(text))

        balanced = self._extract_balanced_json(text)
        if balanced:
            segments.append(balanced.strip())

        return segments

    def _extract_balanced_json(self, text: str) -> Optional[str]:
        """使用括号匹配提取首个 {} 或 [] 包裹的 JSON 片段"""
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            while start != -1:
                end = self._find_matching_bracket(text, start, opener, closer)
                if end != -1:
                    return text[start:end + 1]
                start = text.find(opener, start + 1)
        return None

    def _safe_json_load(self, candidate: str) -> Optional[Any]:
        """带保护的 json.loads，失败时返回 None 并记录调试日志"""
        candidate = candidate.strip()
        if not candidate:
            return None
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            logger.debug(f"[DEBUG] JSON 解析失败: {exc}; 片段: {candidate[:160]!r}")
            return None

    def _ensure_dict_payload(self, payload: Any) -> Dict[str, Any]:
        """兼容数组形式，确保最终返回字典"""
        if isinstance(payload, list):
            if not payload:
                raise ValueError("LLM 响应数组为空，无法提取决策。")
            logger.info("[DEBUG] JSON 为数组形式，取第一个元素作为决策。")
            payload = payload[0]
        if not isinstance(payload, dict):
            raise ValueError(f"LLM 响应应为对象，实际类型: {type(payload).__name__}")
        return payload

    def _find_matching_bracket(self, text: str, start: int, opener: str, closer: str) -> int:
        """匹配 JSON 括号，忽略字符串中的括号"""
        depth = 0
        in_string = False
        escape = False

        for idx in range(start, len(text)):
            ch = text[idx]

            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                elif ch == "\"":
                    in_string = False
                continue

            if ch == "\"":
                in_string = True
                continue

            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return idx

        return -1

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
            prompt_tokens=None,
            completion_tokens=None,
            prompt_cache_hit_tokens=None,
            prompt_cache_miss_tokens=None,
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
                prompt_tokens=response.prompt_tokens if response else None,
                completion_tokens=response.completion_tokens if response else None,
                prompt_cache_hit_tokens=response.prompt_cache_hit_tokens if response else None,
                prompt_cache_miss_tokens=response.prompt_cache_miss_tokens if response else None,
                cost_usd=response.cost_usd if response else None,
                success=success,
                error_message=error,
                created_at=dt_now()
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
