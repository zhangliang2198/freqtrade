from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal, List
from datetime import datetime
import time
import json
import hashlib
import logging
import re
from collections import OrderedDict
from freqtrade.llm.providers import HttpLLMProvider
from freqtrade.llm.context_builder import ContextBuilder
from freqtrade.llm.prompts.manager import PromptManager
from freqtrade.util import dt_now

logger = logging.getLogger(__name__)

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


class TTLCache:
    """带 TTL 和 LRU 功能的缓存"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def get(self, key: str, ttl: float) -> Optional[Any]:
        if key not in self.cache:
            return None

        value, timestamp = self.cache[key]
        age = time.time() - timestamp

        if age >= ttl:
            del self.cache[key]
            return None

        self.cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any):
        if key in self.cache:
            del self.cache[key]

        self.cache[key] = (value, time.time())

        while len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def clear(self):
        self.cache.clear()


@dataclass
class LLMRequest:
    decision_point: DecisionPoint
    pair: str
    context: Dict[str, Any]
    trade_id: Optional[int] = None


@dataclass
class LLMResponse:
    decision: str
    confidence: float
    reasoning: str
    parameters: Dict[str, Any]

    latency_ms: int
    tokens_used: Optional[int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    prompt_cache_hit_tokens: Optional[int]
    prompt_cache_miss_tokens: Optional[int]
    cost_usd: Optional[float]
    cached: bool


class LLMDecisionEngine:
    def __init__(self, config: Dict[str, Any], strategy_name: str):
        self.config = config.get("llm_config", {})
        self.strategy_name = strategy_name

        if not self.config.get("enabled", False):
            logger.debug("LLM 配置已禁用")
            return

        self.provider = self._init_provider()

        cache_max_size = self.config.get("performance", {}).get("cache_max_size", 1000)
        self.caches: Dict[DecisionPoint, TTLCache] = {}
        for point in ["entry", "exit", "stake", "adjust_position", "leverage"]:
            self.caches[point] = TTLCache(max_size=cache_max_size)

        user_data_dir = config.get("user_data_dir", "user_data")
        self.prompt_manager = PromptManager(self.config, user_data_dir)

        self.context_builder = ContextBuilder(self.config)

        self.stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "errors": 0,
            "total_cost_usd": 0.0
        }

        logger.debug(
            "LLM 决策引擎初始化完成 strategy=%s provider=%s model=%s",
            strategy_name,
            self.config.get("provider"),
            self.config.get("model"),
        )

    def decide(self, request: LLMRequest) -> LLMResponse:
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
            logger.debug(
                "调用 LLM API provider=%s model=%s prompt_len=%s temperature=%.2f",
                self.config.get("provider"),
                self.config.get("model"),
                len(prompt),
                temperature,
            )

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
            validation_passed = self._validate_response(response, point_config, request.decision_point)

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
                logger.debug(
                    "LLM 响应验证失败 decision_point=%s confidence=%.3f threshold=%.3f",
                    request.decision_point,
                    response.confidence,
                    point_config.get("confidence_threshold", 0.5),
                )
                return self._default_response(request.decision_point)

            logger.debug(
                "LLM 决策完成 pair=%s decision_point=%s decision=%s confidence=%.2f latency_ms=%s cost=%.4f",
                request.pair,
                request.decision_point,
                response.decision,
                response.confidence,
                latency_ms,
                response.cost_usd,
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
        """检查缓存响应是否存在且仍然有效（使用 TTLCache）"""
        cache = self.caches.get(decision_point)
        if not cache:
            return None

        return cache.get(cache_key, ttl)

    def _cache_response(self, decision_point: str, cache_key: str, response: LLMResponse):
        """缓存响应（使用 TTLCache）"""
        cache = self.caches.get(decision_point)
        if cache:
            cache.set(cache_key, response)

    def _parse_response(
        self,
        raw_response: str,
        decision_point: str,
        latency_ms: int
    ) -> LLMResponse:
        logger.debug("原始响应 decision_point=%s payload=%s", decision_point, raw_response)

        cleaned_text = self._clean_response_text(raw_response)
        payload = self._load_decision_payload(cleaned_text)

        decision = str(payload.get("decision", "hold")).strip() or "hold"

        # 将置信度归一化到 0-1 区间（LLM 常见返回 0-100 百分比）
        confidence_raw = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            logger.warning(f"置信度字段无法转换: {confidence_raw!r}，使用 0.0")
            confidence = 0.0
        if confidence > 1.0 and confidence <= 100.0:
            logger.debug("将百分比置信度 %s 转换为 0-1 区间", confidence)
            confidence /= 100.0
        confidence = max(0.0, min(confidence, 1.0))

        reasoning = str(payload.get("reasoning", "") or "").strip()

        parameters_raw = payload.get("parameters", {})
        if isinstance(parameters_raw, dict):
            parameters = parameters_raw
        else:
            logger.warning(
                f"parameters 字段类型异常 ({type(parameters_raw).__name__})，使用空字典"
            )
            parameters = {}

        logger.debug(
            "%s 解析结果 decision=%s confidence=%s reasoning=%s parameters=%s",
            decision_point,
            decision,
            confidence,
            reasoning,
            parameters,
        )

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

    def _validate_response(self, response: LLMResponse, config: Dict, decision_point: str = None) -> bool:
        # 检查决策是否为空
        if not response.decision:
            logger.debug("决策为空，验证失败")
            return False

        # stake 和 leverage 决策点不需要置信度检查（这些是参数调整，而非二元决策）
        if decision_point in ("stake", "leverage"):
            logger.debug("响应验证通过 decision=%s (跳过置信度检查)", response.decision)
            return True

        # 其他决策点需要检查置信度阈值
        threshold = config.get("confidence_threshold", 0.5)

        # 添加详细的验证日志
        logger.debug(
            "响应验证 decision=%s confidence=%.3f threshold=%.3f reasoning=%s",
            response.decision,
            response.confidence,
            threshold,
            response.reasoning,
        )

        if response.confidence < threshold:
            logger.debug("置信度验证失败: %.3f < %.3f", response.confidence, threshold)
            return False

        logger.debug("响应验证通过 decision=%s", response.decision)
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
            logger.debug("JSON 解析失败: %s; 片段: %r", exc, candidate[:160])
            return None

    def _ensure_dict_payload(self, payload: Any) -> Dict[str, Any]:
        """兼容数组形式，确保最终返回字典"""
        if isinstance(payload, list):
            if not payload:
                raise ValueError("LLM 响应数组为空，无法提取决策。")
            logger.debug("JSON 为数组形式，取第一个元素作为决策。")
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

        try:
            Trade.session.add(decision_log)
            Trade.commit()
        except Exception as e:
            logger.error(f"记录决策到数据库失败: {e}")
            try:
                Trade.session.rollback()
            except Exception:
                pass  # 忽略回滚异常


    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计信息"""
        return {
            **self.stats,
            "cache_hit_rate": (
                self.stats["cache_hits"] / self.stats["total_calls"]
                if self.stats["total_calls"] > 0 else 0.0
            )
        }
