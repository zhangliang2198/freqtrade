# LLM 辅助交易策略设计方案

> **版本**: 1.0.0
> **更新日期**: 2025-11-04
> **状态**: 设计方案

## 目录

1. [概述](#概述)
2. [架构设计](#架构设计)
3. [配置结构](#配置结构)
4. [数据库模型](#数据库模型)
5. [LLM 决策引擎](#llm-决策引擎)
6. [策略实现](#策略实现)
7. [Exporter 指标](#exporter-指标)
8. [使用示例](#使用示例)
9. [扩展指南](#扩展指南)

---

## 概述

### 目标

设计一个通用、可扩展的 LLM 辅助交易策略框架，通过大语言模型在以下关键决策点进行智能判断：

- **入场信号** (`populate_entry_trend`)：分析市场数据，判断是否开仓
- **出场信号** (`custom_exit`)：判断是否平仓及原因
- **仓位管理** (`custom_stake_amount`)：动态计算开仓金额
- **加仓决策** (`adjust_trade_position`)：判断是否加仓或减仓
- **杠杆控制** (`leverage`)：根据市场状况动态调整杠杆

### 核心特性

- **通用性**：支持多种 LLM 提供商（OpenAI、Anthropic、本地模型等）
- **自定义性**：灵活配置 Prompt 模板和决策规则
- **扩展性**：模块化设计，易于添加新的决策点和指标
- **可观测性**：完整的日志记录和指标监控
- **可追溯性**：所有 LLM 决策存入数据库，方便回溯分析

---

## 架构设计

### 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Freqtrade 策略层                         │
│                 (LLMAssistedStrategy)                       │
└───────────────┬──────────────────────────────┬──────────────┘
                │                              │
                ▼                              ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │  LLM Decision Engine │      │  Context Builder     │
    │  - 决策调度          │◄─────┤  - 市场数据组装      │
    │  - 结果解析          │      │  - 指标计算          │
    │  - 缓存管理          │      │  - Prompt 构建       │
    └──────────┬───────────┘      └──────────────────────┘
               │
               ▼
    ┌──────────────────────┐
    │  LLM Provider Layer  │
    │  - OpenAI            │
    │  - Anthropic         │
    │  - Local (Ollama)    │
    │  - Custom API        │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐      ┌──────────────────────┐
    │  Database Logger     │      │  Prometheus Exporter │
    │  - LLMDecision       │      │  - 决策次数          │
    │  - LLMPerformance    │      │  - 响应时间          │
    │  - LLMMetrics        │      │  - 成功率            │
    └──────────────────────┘      └──────────────────────┘
```

### 模块划分

| 模块名 | 文件路径 | 职责 |
|--------|---------|------|
| **LLM 决策引擎** | `freqtrade/llm/engine.py` | 核心决策调度、缓存、重试 |
| **LLM 提供商** | `freqtrade/llm/providers/` | 各 LLM API 的适配器 |
| **上下文构建器** | `freqtrade/llm/context_builder.py` | 将市场数据转换为 LLM 可理解的格式 |
| **Prompt 管理器** | `freqtrade/llm/prompts/` | 管理各决策点的 Prompt 模板 |
| **数据库模型** | `freqtrade/persistence/llm_models.py` | LLM 决策日志表 |
| **Exporter 采集器** | `exporter/metrics/llm.py` | LLM 相关指标采集 |
| **策略基类** | `freqtrade/strategy/LLMStrategy.py` | LLM 辅助策略的抽象基类 |

---

## 配置结构

### 配置示例 (`config.json`)

```json
{
  "strategy": "MyLLMStrategy",
  "max_open_trades": 5,
  "stake_currency": "USDT",
  "stake_amount": "unlimited",
  "dry_run": true,
  "timeframe": "5m",

  "llm_config": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": "${OPENAI_API_KEY}",
    "base_url": null,
    "timeout": 30,
    "max_retries": 3,
    "temperature": 0.1,

    "decision_points": {
      "entry": {
        "enabled": true,
        "cache_ttl": 60,
        "confidence_threshold": 0.7,
        "prompt_template": "prompts/entry.j2"
      },
      "exit": {
        "enabled": true,
        "cache_ttl": 30,
        "confidence_threshold": 0.6,
        "prompt_template": "prompts/exit.j2"
      },
      "stake": {
        "enabled": true,
        "cache_ttl": 300,
        "min_stake_multiplier": 0.5,
        "max_stake_multiplier": 2.0,
        "prompt_template": "prompts/stake.j2"
      },
      "adjust_position": {
        "enabled": true,
        "cache_ttl": 120,
        "max_adjustment_ratio": 0.3,
        "prompt_template": "prompts/adjust.j2"
      },
      "leverage": {
        "enabled": true,
        "cache_ttl": 600,
        "min_leverage": 1.0,
        "max_leverage": 10.0,
        "prompt_template": "prompts/leverage.j2"
      }
    },

    "context": {
      "lookback_candles": 100,
      "include_indicators": [
        "rsi", "macd", "bb_bands", "ema", "volume"
      ],
      "include_orderbook": false,
      "include_recent_trades": true,
      "include_funding_rate": true,
      "include_portfolio_state": true
    },

    "performance": {
      "log_to_database": true,
      "log_prompts": true,
      "log_responses": true,
      "export_metrics": true
    }
  }
}
```

### 配置字段说明

#### `llm_config`

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | bool | 是否启用 LLM 决策 |
| `provider` | str | LLM 提供商：`openai`/`anthropic`/`ollama`/`custom` |
| `model` | str | 模型名称，如 `gpt-4o`, `claude-3-5-sonnet-20241022` |
| `api_key` | str | API 密钥，支持环境变量 `${VAR_NAME}` |
| `base_url` | str\|null | 自定义 API 地址（用于本地模型或代理） |
| `timeout` | int | API 请求超时（秒） |
| `max_retries` | int | 失败重试次数 |
| `temperature` | float | 温度参数（0.0-1.0），越低越确定 |

#### `decision_points.<point>`

每个决策点可配置：

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | bool | 是否启用该决策点 |
| `cache_ttl` | int | 缓存有效期（秒），相同输入复用结果 |
| `confidence_threshold` | float | 置信度阈值（0.0-1.0） |
| `prompt_template` | str | Prompt 模板文件路径（相对于 `user_data/llm_prompts/`） |

**特殊配置**：
- `stake`: `min_stake_multiplier`, `max_stake_multiplier` - 仓位倍数范围
- `adjust_position`: `max_adjustment_ratio` - 最大调整比例
- `leverage`: `min_leverage`, `max_leverage` - 杠杆范围

#### `context`

| 字段 | 说明 |
|------|------|
| `lookback_candles` | 提供给 LLM 的历史 K 线数量 |
| `include_indicators` | 包含的技术指标列表 |
| `include_orderbook` | 是否包含订单簿数据 |
| `include_recent_trades` | 是否包含最近成交 |
| `include_funding_rate` | 是否包含资金费率 |
| `include_portfolio_state` | 是否包含当前持仓状态 |

#### `performance`

| 字段 | 说明 |
|------|------|
| `log_to_database` | 是否记录决策到数据库 |
| `log_prompts` | 是否记录完整 Prompt |
| `log_responses` | 是否记录完整响应 |
| `export_metrics` | 是否导出 Prometheus 指标 |

---

## 数据库模型

### 表结构设计

#### 1. `llm_decisions` - LLM 决策记录表

记录每次 LLM 决策的完整信息。

```python
class LLMDecision(ModelBase):
    __tablename__ = "llm_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 关联信息
    trade_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("trades.id"), nullable=True, index=True)
    pair: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # 决策点信息
    decision_point: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 可能的值: 'entry', 'exit', 'stake', 'adjust_position', 'leverage'

    # LLM 配置
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # 请求和响应
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 解析结果
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    # 可能的值: 'buy', 'sell', 'hold', 'adjust', 'no_change', etc.

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 决策参数（JSON 格式）
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 例如: {"stake_multiplier": 1.5, "leverage": 3.0}

    # 性能指标
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 状态
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
```

**索引策略**：
- `(strategy, decision_point, created_at)` - 按策略和决策点查询
- `(pair, created_at)` - 按交易对查询
- `(trade_id)` - 关联交易查询

#### 2. `llm_performance_metrics` - LLM 性能指标表

聚合统计 LLM 决策的表现。

```python
class LLMPerformanceMetric(ModelBase):
    __tablename__ = "llm_performance_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 维度
    strategy: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    decision_point: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    time_bucket: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # 时间桶，例如每小时或每天聚合一次

    # 调用统计
    total_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 性能统计
    avg_latency_ms: Mapped[float] = mapped_column(Float, nullable=False)
    p95_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    p99_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 成本统计
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 决策质量
    avg_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_distribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON: {"buy": 10, "hold": 5, "sell": 2}

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

**唯一索引**：`(strategy, decision_point, time_bucket)`

#### 3. `llm_strategy_snapshots` - LLM 策略快照表

扩展 `strategy_snapshots` 表，增加 LLM 特有指标。

```python
class LLMStrategySnapshot(ModelBase):
    __tablename__ = "llm_strategy_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, ForeignKey("strategy_snapshots.id"), nullable=False)

    # LLM 使用统计
    total_llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_cache_hit_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 决策分布（JSON）
    entry_decisions: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_decisions: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 成本统计
    cumulative_llm_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 效果评估
    llm_entry_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_exit_timing_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

### 数据库初始化

```python
# freqtrade/persistence/llm_models.py

from freqtrade.persistence.base import ModelBase
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def init_llm_db(db_url: str):
    """初始化 LLM 相关表"""
    engine = create_engine(db_url)
    ModelBase.metadata.create_all(engine, tables=[
        LLMDecision.__table__,
        LLMPerformanceMetric.__table__,
        LLMStrategySnapshot.__table__
    ])
    return sessionmaker(bind=engine)
```

---

## LLM 决策引擎

### 核心接口设计

```python
# freqtrade/llm/engine.py

from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal
from datetime import datetime, timedelta
from cachetools import TTLCache
import time

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
    """LLM 决策引擎核心类"""

    def __init__(self, config: Dict[str, Any], strategy_name: str):
        self.config = config["llm_config"]
        self.strategy_name = strategy_name

        # 初始化提供商
        self.provider = self._init_provider()

        # 初始化缓存
        self.caches: Dict[DecisionPoint, TTLCache] = {}
        for point, conf in self.config["decision_points"].items():
            ttl = conf.get("cache_ttl", 60)
            self.caches[point] = TTLCache(maxsize=100, ttl=ttl)

        # 初始化 Prompt 管理器
        self.prompt_manager = PromptManager(config["llm_config"])

        # 初始化上下文构建器
        self.context_builder = ContextBuilder(config["llm_config"]["context"])

        # 统计
        self.stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "errors": 0
        }

    def decide(self, request: LLMRequest) -> LLMResponse:
        """
        执行 LLM 决策

        Args:
            request: LLM 请求

        Returns:
            LLM 响应
        """
        # 检查是否启用该决策点
        point_config = self.config["decision_points"].get(request.decision_point)
        if not point_config or not point_config.get("enabled", True):
            return self._default_response(request.decision_point)

        # 生成缓存键
        cache_key = self._generate_cache_key(request)

        # 检查缓存
        cache = self.caches[request.decision_point]
        if cache_key in cache:
            self.stats["cache_hits"] += 1
            cached_response = cache[cache_key]
            cached_response.cached = True
            return cached_response

        # 构建 Prompt
        prompt = self.prompt_manager.build_prompt(
            decision_point=request.decision_point,
            context=request.context
        )

        # 调用 LLM
        start_time = time.time()
        try:
            raw_response = self.provider.complete(
                prompt=prompt,
                temperature=self.config.get("temperature", 0.1)
            )
            latency_ms = int((time.time() - start_time) * 1000)

            # 解析响应
            response = self._parse_response(
                raw_response=raw_response,
                decision_point=request.decision_point,
                latency_ms=latency_ms
            )

            # 验证响应
            if not self._validate_response(response, point_config):
                return self._default_response(request.decision_point)

            # 缓存结果
            cache[cache_key] = response

            # 记录日志
            if self.config["performance"]["log_to_database"]:
                self._log_decision(request, response, prompt, raw_response)

            self.stats["total_calls"] += 1
            return response

        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"LLM decision failed: {e}")

            # 记录错误
            if self.config["performance"]["log_to_database"]:
                self._log_error(request, str(e))

            # 返回默认响应
            return self._default_response(request.decision_point)

    def _generate_cache_key(self, request: LLMRequest) -> str:
        """生成缓存键（基于上下文的哈希）"""
        import hashlib
        import json
        context_str = json.dumps(request.context, sort_keys=True)
        return hashlib.md5(context_str.encode()).hexdigest()

    def _parse_response(self, raw_response: str, decision_point: str, latency_ms: int) -> LLMResponse:
        """解析 LLM 原始响应"""
        # 这里需要根据 Prompt 设计解析 JSON 或结构化输出
        import json
        parsed = json.loads(raw_response)

        return LLMResponse(
            decision=parsed["decision"],
            confidence=parsed.get("confidence", 0.5),
            reasoning=parsed.get("reasoning", ""),
            parameters=parsed.get("parameters", {}),
            latency_ms=latency_ms,
            tokens_used=parsed.get("tokens_used"),
            cost_usd=parsed.get("cost_usd"),
            cached=False
        )

    def _validate_response(self, response: LLMResponse, config: Dict) -> bool:
        """验证响应是否满足配置要求"""
        threshold = config.get("confidence_threshold", 0.5)
        return response.confidence >= threshold

    def _default_response(self, decision_point: DecisionPoint) -> LLMResponse:
        """返回默认响应（当 LLM 不可用时）"""
        defaults = {
            "entry": "hold",
            "exit": "hold",
            "stake": "default",
            "adjust_position": "no_change",
            "leverage": "default"
        }

        return LLMResponse(
            decision=defaults[decision_point],
            confidence=0.0,
            reasoning="LLM not available, using default",
            parameters={},
            latency_ms=0,
            tokens_used=None,
            cost_usd=None,
            cached=False
        )

    def _log_decision(self, request: LLMRequest, response: LLMResponse, prompt: str, raw_response: str):
        """记录决策到数据库"""
        from freqtrade.persistence.llm_models import LLMDecision
        from freqtrade.persistence import Trade

        Trade.session.add(LLMDecision(
            trade_id=request.trade_id,
            pair=request.pair,
            strategy=self.strategy_name,
            decision_point=request.decision_point,
            provider=self.config["provider"],
            model=self.config["model"],
            prompt=prompt if self.config["performance"]["log_prompts"] else None,
            response=raw_response if self.config["performance"]["log_responses"] else None,
            decision=response.decision,
            confidence=response.confidence,
            reasoning=response.reasoning,
            parameters=json.dumps(response.parameters),
            latency_ms=response.latency_ms,
            tokens_used=response.tokens_used,
            cost_usd=response.cost_usd,
            success=True,
            created_at=datetime.utcnow()
        ))
        Trade.commit()

    def _log_error(self, request: LLMRequest, error: str):
        """记录错误到数据库"""
        from freqtrade.persistence.llm_models import LLMDecision
        from freqtrade.persistence import Trade

        Trade.session.add(LLMDecision(
            trade_id=request.trade_id,
            pair=request.pair,
            strategy=self.strategy_name,
            decision_point=request.decision_point,
            provider=self.config["provider"],
            model=self.config["model"],
            success=False,
            error_message=error,
            created_at=datetime.utcnow()
        ))
        Trade.commit()
```

### LLM 提供商接口

```python
# freqtrade/llm/providers/base.py

from abc import ABC, abstractmethod
from typing import Dict, Any

class LLMProvider(ABC):
    """LLM 提供商抽象基类"""

    @abstractmethod
    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        """
        调用 LLM 完成对话

        Args:
            prompt: 输入提示词
            temperature: 温度参数

        Returns:
            LLM 响应文本
        """
        pass

    @abstractmethod
    def get_usage_info(self) -> Dict[str, Any]:
        """获取最后一次调用的使用信息（tokens, cost 等）"""
        pass
```

```python
# freqtrade/llm/providers/openai.py

from openai import OpenAI
from freqtrade.llm.providers.base import LLMProvider

class OpenAIProvider(LLMProvider):
    """OpenAI API 提供商"""

    def __init__(self, config: Dict[str, Any]):
        self.model = config["model"]
        self.api_key = config["api_key"]
        self.base_url = config.get("base_url")
        self.timeout = config.get("timeout", 30)

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout
        )

        self.last_usage = {}

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are a professional trading analyst."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            response_format={"type": "json_object"}
        )

        self.last_usage = {
            "tokens_used": response.usage.total_tokens,
            "cost_usd": self._calculate_cost(response.usage)
        }

        return response.choices[0].message.content

    def get_usage_info(self) -> Dict[str, Any]:
        return self.last_usage

    def _calculate_cost(self, usage) -> float:
        """根据 token 使用量计算成本"""
        # GPT-4o 定价示例（需根据实际调整）
        input_cost = usage.prompt_tokens * 0.000005  # $5/1M tokens
        output_cost = usage.completion_tokens * 0.000015  # $15/1M tokens
        return input_cost + output_cost
```

```python
# freqtrade/llm/providers/anthropic.py

from anthropic import Anthropic
from freqtrade.llm.providers.base import LLMProvider

class AnthropicProvider(LLMProvider):
    """Anthropic Claude API 提供商"""

    def __init__(self, config: Dict[str, Any]):
        self.model = config["model"]
        self.api_key = config["api_key"]
        self.timeout = config.get("timeout", 30)

        self.client = Anthropic(api_key=self.api_key)
        self.last_usage = {}

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            temperature=temperature,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        self.last_usage = {
            "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
            "cost_usd": self._calculate_cost(response.usage)
        }

        return response.content[0].text

    def get_usage_info(self) -> Dict[str, Any]:
        return self.last_usage

    def _calculate_cost(self, usage) -> float:
        # Claude 3.5 Sonnet 定价
        input_cost = usage.input_tokens * 0.000003  # $3/1M tokens
        output_cost = usage.output_tokens * 0.000015  # $15/1M tokens
        return input_cost + output_cost
```

### Prompt 管理器

```python
# freqtrade/llm/prompts/manager.py

from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from typing import Dict, Any

class PromptManager:
    """Prompt 模板管理器"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

        # 初始化 Jinja2 环境
        template_dir = Path("user_data/llm_prompts")
        template_dir.mkdir(parents=True, exist_ok=True)

        self.env = Environment(loader=FileSystemLoader(str(template_dir)))

    def build_prompt(self, decision_point: str, context: Dict[str, Any]) -> str:
        """
        构建 Prompt

        Args:
            decision_point: 决策点名称
            context: 上下文数据

        Returns:
            渲染后的 Prompt
        """
        point_config = self.config["decision_points"][decision_point]
        template_name = point_config.get("prompt_template", f"{decision_point}.j2")

        try:
            template = self.env.get_template(template_name)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Failed to render prompt template {template_name}: {e}")
            return self._get_default_prompt(decision_point, context)

    def _get_default_prompt(self, decision_point: str, context: Dict[str, Any]) -> str:
        """获取默认 Prompt（当模板不存在时）"""
        return f"""
You are a professional cryptocurrency trading analyst. Based on the following market data, please make a {decision_point} decision.

Market Data:
{context}

Please respond in JSON format with the following structure:
{{
    "decision": "your decision (buy/sell/hold/etc.)",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "parameters": {{}}
}}
"""
```

### 上下文构建器

```python
# freqtrade/llm/context_builder.py

from typing import Dict, Any
import pandas as pd

class ContextBuilder:
    """上下文构建器 - 将市场数据转换为 LLM 可理解的格式"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def build_entry_context(self, dataframe: pd.DataFrame, metadata: Dict) -> Dict[str, Any]:
        """构建入场决策上下文"""
        lookback = self.config["lookback_candles"]
        recent_data = dataframe.tail(lookback)

        context = {
            "pair": metadata["pair"],
            "current_time": str(dataframe.iloc[-1]["date"]),
            "current_candle": self._format_candle(dataframe.iloc[-1]),
            "market_summary": self._summarize_market(recent_data),
        }

        if self.config["include_indicators"]:
            context["indicators"] = self._extract_indicators(dataframe.iloc[-1])

        if self.config["include_recent_trades"]:
            context["recent_candles"] = self._format_recent_candles(recent_data, num=10)

        return context

    def build_exit_context(self, trade, current_rate: float, dataframe: pd.DataFrame) -> Dict[str, Any]:
        """构建出场决策上下文"""
        context = {
            "pair": trade.pair,
            "entry_price": trade.open_rate,
            "current_price": current_rate,
            "current_profit_pct": trade.calc_profit_ratio(current_rate) * 100,
            "current_profit_abs": trade.calc_profit(current_rate),
            "holding_duration_minutes": (datetime.utcnow() - trade.open_date).total_seconds() / 60,
            "stop_loss": trade.stop_loss,
            "max_rate": trade.max_rate,
            "entry_tag": trade.enter_tag,
        }

        if self.config["include_indicators"]:
            context["current_indicators"] = self._extract_indicators(dataframe.iloc[-1])

        return context

    def build_stake_context(self, pair: str, current_rate: float, dataframe: pd.DataFrame, available_balance: float) -> Dict[str, Any]:
        """构建仓位管理上下文"""
        return {
            "pair": pair,
            "current_price": current_rate,
            "available_balance": available_balance,
            "market_summary": self._summarize_market(dataframe.tail(self.config["lookback_candles"])),
            "volatility": self._calculate_volatility(dataframe),
        }

    def _format_candle(self, row) -> Dict:
        """格式化单根 K 线"""
        return {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"])
        }

    def _summarize_market(self, df: pd.DataFrame) -> str:
        """总结市场状态"""
        recent_returns = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
        trend = "bullish" if recent_returns > 2 else "bearish" if recent_returns < -2 else "neutral"
        return f"Recent {len(df)} candles: {trend} trend, {recent_returns:.2f}% change"

    def _extract_indicators(self, row) -> Dict:
        """提取技术指标"""
        indicators = {}
        for name in self.config["include_indicators"]:
            if name in row.index:
                indicators[name] = float(row[name])
        return indicators

    def _format_recent_candles(self, df: pd.DataFrame, num: int = 10) -> list:
        """格式化最近的 K 线"""
        return [self._format_candle(df.iloc[i]) for i in range(-num, 0)]

    def _calculate_volatility(self, df: pd.DataFrame) -> float:
        """计算波动率"""
        returns = df["close"].pct_change().dropna()
        return float(returns.std() * 100)
```

---

## 策略实现

### LLM 策略基类

```python
# freqtrade/strategy/LLMStrategy.py

from freqtrade.strategy import IStrategy
from freqtrade.llm.engine import LLMDecisionEngine, LLMRequest
from freqtrade.llm.context_builder import ContextBuilder
from typing import Optional
import pandas as pd

class LLMStrategy(IStrategy):
    """
    LLM 辅助策略抽象基类

    子类可以重写特定方法来自定义行为
    """

    # 必须在子类中定义
    INTERFACE_VERSION = 3

    # LLM 引擎（由 bot_start 初始化）
    llm_engine: Optional[LLMDecisionEngine] = None

    def bot_start(self, **kwargs) -> None:
        """机器人启动时初始化 LLM 引擎"""
        if self.config.get("llm_config", {}).get("enabled", False):
            self.llm_engine = LLMDecisionEngine(
                config=self.config,
                strategy_name=self.__class__.__name__
            )
            self.logger.info(f"LLM Decision Engine initialized with provider: {self.config['llm_config']['provider']}")
        else:
            self.logger.warning("LLM is disabled in config, strategy will use default behavior")

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        计算技术指标（子类应重写此方法添加必要指标）
        """
        # 子类必须实现
        raise NotImplementedError("populate_indicators must be implemented in subclass")

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        使用 LLM 判断入场信号
        """
        if not self.llm_engine:
            return self._populate_entry_trend_fallback(dataframe, metadata)

        # 只在最后一根 K 线做决策
        if len(dataframe) < 1:
            return dataframe

        # 构建上下文
        context = self.llm_engine.context_builder.build_entry_context(dataframe, metadata)

        # 调用 LLM
        request = LLMRequest(
            decision_point="entry",
            pair=metadata["pair"],
            context=context
        )
        response = self.llm_engine.decide(request)

        # 应用决策
        if response.decision == "buy":
            dataframe.loc[dataframe.index[-1], "enter_long"] = 1
            dataframe.loc[dataframe.index[-1], "enter_tag"] = f"llm_entry_conf{int(response.confidence*100)}"
        elif response.decision == "sell" and self.can_short:
            dataframe.loc[dataframe.index[-1], "enter_short"] = 1
            dataframe.loc[dataframe.index[-1], "enter_tag"] = f"llm_short_conf{int(response.confidence*100)}"

        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs
    ) -> Optional[str]:
        """
        使用 LLM 判断是否出场
        """
        if not self.llm_engine:
            return self._custom_exit_fallback(pair, trade, current_time, current_rate, current_profit)

        # 获取当前 dataframe
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

        # 构建上下文
        context = self.llm_engine.context_builder.build_exit_context(trade, current_rate, dataframe)

        # 调用 LLM
        request = LLMRequest(
            decision_point="exit",
            pair=pair,
            context=context,
            trade_id=trade.id
        )
        response = self.llm_engine.decide(request)

        # 应用决策
        if response.decision in ["sell", "exit"]:
            return f"llm_exit_{response.reasoning[:20]}"

        return None

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """
        使用 LLM 动态调整仓位大小
        """
        if not self.llm_engine:
            return proposed_stake

        # 获取可用余额
        available_balance = self.wallets.get_free(self.config["stake_currency"])

        # 获取当前 dataframe
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

        # 构建上下文
        context = self.llm_engine.context_builder.build_stake_context(
            pair, current_rate, dataframe, available_balance
        )

        # 调用 LLM
        request = LLMRequest(
            decision_point="stake",
            pair=pair,
            context=context
        )
        response = self.llm_engine.decide(request)

        # 应用决策
        if response.decision == "default":
            return proposed_stake

        stake_multiplier = response.parameters.get("stake_multiplier", 1.0)
        point_config = self.llm_engine.config["decision_points"]["stake"]

        # 限制倍数范围
        stake_multiplier = max(
            point_config["min_stake_multiplier"],
            min(stake_multiplier, point_config["max_stake_multiplier"])
        )

        adjusted_stake = proposed_stake * stake_multiplier

        # 确保在允许范围内
        if min_stake:
            adjusted_stake = max(adjusted_stake, min_stake)
        adjusted_stake = min(adjusted_stake, max_stake)

        return adjusted_stake

    def adjust_trade_position(
        self,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs
    ) -> Optional[float]:
        """
        使用 LLM 判断是否加仓或减仓
        """
        if not self.llm_engine:
            return None

        # 获取当前 dataframe
        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)

        # 构建上下文
        context = {
            "pair": trade.pair,
            "current_profit_pct": current_profit * 100,
            "current_rate": current_rate,
            "entry_rate": trade.open_rate,
            "stake_amount": trade.stake_amount,
            "holding_duration_minutes": (current_time - trade.open_date).total_seconds() / 60,
            "market_summary": self.llm_engine.context_builder._summarize_market(dataframe.tail(50))
        }

        # 调用 LLM
        request = LLMRequest(
            decision_point="adjust_position",
            pair=trade.pair,
            context=context,
            trade_id=trade.id
        )
        response = self.llm_engine.decide(request)

        # 应用决策
        if response.decision == "no_change":
            return None

        adjustment_ratio = response.parameters.get("adjustment_ratio", 0.0)
        point_config = self.llm_engine.config["decision_points"]["adjust_position"]
        max_ratio = point_config["max_adjustment_ratio"]

        # 限制调整比例
        adjustment_ratio = max(-max_ratio, min(adjustment_ratio, max_ratio))

        # 计算调整金额
        adjustment_stake = trade.stake_amount * adjustment_ratio

        return adjustment_stake if abs(adjustment_stake) > min_stake else None

    def leverage(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs
    ) -> float:
        """
        使用 LLM 动态调整杠杆
        """
        if not self.llm_engine:
            return proposed_leverage

        # 获取当前 dataframe
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

        # 构建上下文
        context = {
            "pair": pair,
            "current_rate": current_rate,
            "proposed_leverage": proposed_leverage,
            "max_leverage": max_leverage,
            "volatility": self.llm_engine.context_builder._calculate_volatility(dataframe),
            "market_summary": self.llm_engine.context_builder._summarize_market(dataframe.tail(50))
        }

        # 调用 LLM
        request = LLMRequest(
            decision_point="leverage",
            pair=pair,
            context=context
        )
        response = self.llm_engine.decide(request)

        # 应用决策
        if response.decision == "default":
            return proposed_leverage

        llm_leverage = response.parameters.get("leverage", proposed_leverage)
        point_config = self.llm_engine.config["decision_points"]["leverage"]

        # 限制杠杆范围
        llm_leverage = max(
            point_config["min_leverage"],
            min(llm_leverage, point_config["max_leverage"], max_leverage)
        )

        return llm_leverage

    # Fallback 方法（当 LLM 不可用时的默认行为）

    def _populate_entry_trend_fallback(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """LLM 不可用时的入场逻辑（子类可重写）"""
        # 默认不入场
        return dataframe

    def _custom_exit_fallback(self, pair, trade, current_time, current_rate, current_profit) -> Optional[str]:
        """LLM 不可用时的出场逻辑（子类可重写）"""
        return None
```

### 示例策略实现

```python
# user_data/strategies/MyLLMStrategy.py

from freqtrade.strategy.LLMStrategy import LLMStrategy
import pandas as pd
import talib.abstract as ta

class MyLLMStrategy(LLMStrategy):
    """
    基于 LLM 的交易策略示例
    """

    # 策略参数
    timeframe = "5m"
    stoploss = -0.10
    trailing_stop = False
    use_custom_stoploss = False

    minimal_roi = {
        "0": 0.10,
        "30": 0.05,
        "60": 0.03,
        "120": 0.01
    }

    # 仓位管理
    position_adjustment_enable = True
    max_entry_position_adjustment = 3

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        计算所需的技术指标
        """
        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # Bollinger Bands
        bollinger = ta.BBANDS(dataframe, timeperiod=20)
        dataframe["bb_lower"] = bollinger["lowerband"]
        dataframe["bb_middle"] = bollinger["middleband"]
        dataframe["bb_upper"] = bollinger["upperband"]

        # EMA
        dataframe["ema_9"] = ta.EMA(dataframe, timeperiod=9)
        dataframe["ema_21"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["ema_50"] = ta.EMA(dataframe, timeperiod=50)

        # Volume
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()

        return dataframe

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        """
        我们使用 custom_exit，所以这里不需要设置退出信号
        """
        return dataframe
```

---

## Exporter 指标

### LLM 指标采集器

```python
# exporter/metrics/llm.py

from typing import Generator
from exporter.metrics.base import MetricSample
from exporter.api import FreqtradeAPI
from datetime import datetime, timedelta

def collect(api: FreqtradeAPI) -> Generator[MetricSample, None, None]:
    """采集 LLM 相关指标"""

    # 从数据库查询统计信息
    from freqtrade.persistence import Trade
    from freqtrade.persistence.llm_models import LLMDecision, LLMPerformanceMetric
    from sqlalchemy import func

    session = Trade.session

    # 1. 总调用次数
    total_calls = session.query(func.count(LLMDecision.id)).scalar()
    yield MetricSample(
        name="freqtrade_llm_total_calls",
        value=total_calls,
        description="LLM 总调用次数",
        metric_type="counter"
    )

    # 2. 成功率
    success_calls = session.query(func.count(LLMDecision.id)).filter(LLMDecision.success == True).scalar()
    success_rate = (success_calls / total_calls * 100) if total_calls > 0 else 0
    yield MetricSample(
        name="freqtrade_llm_success_rate",
        value=success_rate,
        description="LLM 调用成功率（%）",
        metric_type="gauge"
    )

    # 3. 按决策点统计
    decision_stats = session.query(
        LLMDecision.decision_point,
        func.count(LLMDecision.id).label("count"),
        func.avg(LLMDecision.latency_ms).label("avg_latency"),
        func.avg(LLMDecision.confidence).label("avg_confidence")
    ).filter(
        LLMDecision.success == True
    ).group_by(LLMDecision.decision_point).all()

    for stat in decision_stats:
        yield MetricSample(
            name="freqtrade_llm_decision_point_calls",
            value=stat.count,
            description="按决策点的调用次数",
            metric_type="counter",
            labels={"decision_point": stat.decision_point}
        )

        yield MetricSample(
            name="freqtrade_llm_decision_point_latency_ms",
            value=stat.avg_latency,
            description="按决策点的平均延迟（毫秒）",
            metric_type="gauge",
            labels={"decision_point": stat.decision_point}
        )

        if stat.avg_confidence:
            yield MetricSample(
                name="freqtrade_llm_decision_point_confidence",
                value=stat.avg_confidence,
                description="按决策点的平均置信度",
                metric_type="gauge",
                labels={"decision_point": stat.decision_point}
            )

    # 4. 最近1小时的成本
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    recent_cost = session.query(func.sum(LLMDecision.cost_usd)).filter(
        LLMDecision.created_at >= one_hour_ago,
        LLMDecision.success == True
    ).scalar() or 0.0

    yield MetricSample(
        name="freqtrade_llm_cost_usd_1h",
        value=recent_cost,
        description="最近1小时的 LLM 成本（USD）",
        metric_type="gauge"
    )

    # 5. 累计成本
    total_cost = session.query(func.sum(LLMDecision.cost_usd)).filter(
        LLMDecision.success == True
    ).scalar() or 0.0

    yield MetricSample(
        name="freqtrade_llm_total_cost_usd",
        value=total_cost,
        description="LLM 累计成本（USD）",
        metric_type="counter"
    )

    # 6. 按 provider 统计
    provider_stats = session.query(
        LLMDecision.provider,
        func.count(LLMDecision.id).label("count")
    ).filter(
        LLMDecision.success == True
    ).group_by(LLMDecision.provider).all()

    for stat in provider_stats:
        yield MetricSample(
            name="freqtrade_llm_provider_calls",
            value=stat.count,
            description="按提供商的调用次数",
            metric_type="counter",
            labels={"provider": stat.provider}
        )

    # 7. LLM 入场决策表现
    llm_entry_trades = session.query(Trade).join(
        LLMDecision,
        (Trade.id == LLMDecision.trade_id) & (LLMDecision.decision_point == "entry")
    ).filter(Trade.is_open == False).all()

    if llm_entry_trades:
        winning_trades = sum(1 for t in llm_entry_trades if t.close_profit > 0)
        win_rate = (winning_trades / len(llm_entry_trades) * 100)

        yield MetricSample(
            name="freqtrade_llm_entry_win_rate",
            value=win_rate,
            description="LLM 入场决策的胜率（%）",
            metric_type="gauge"
        )
```

### 注册采集器

```python
# exporter/metrics/__init__.py

from exporter.metrics import (
    system,
    balances,
    trades,
    profitability,
    performance,
    locks,
    stats,
    tags,
    timeprofits,
    pairlists,
    llm  # 新增
)

COLLECTORS: tuple[Collector, ...] = (
    system.collect,
    balances.collect,
    trades.collect,
    profitability.collect,
    performance.collect,
    locks.collect,
    stats.collect,
    tags.collect,
    timeprofits.collect,
    pairlists.collect,
    llm.collect,  # 新增
)
```

---

## 使用示例

### 1. 配置文件

创建 `user_data/config_llm.json`:

```json
{
  "strategy": "MyLLMStrategy",
  "max_open_trades": 3,
  "stake_currency": "USDT",
  "stake_amount": "unlimited",
  "dry_run": true,
  "timeframe": "5m",

  "exchange": {
    "name": "binance",
    "key": "your_key",
    "secret": "your_secret",
    "ccxt_config": {},
    "ccxt_async_config": {},
    "pair_whitelist": [
      "BTC/USDT",
      "ETH/USDT"
    ]
  },

  "llm_config": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": "${OPENAI_API_KEY}",
    "timeout": 30,
    "max_retries": 3,
    "temperature": 0.1,

    "decision_points": {
      "entry": {
        "enabled": true,
        "cache_ttl": 60,
        "confidence_threshold": 0.7,
        "prompt_template": "entry.j2"
      },
      "exit": {
        "enabled": true,
        "cache_ttl": 30,
        "confidence_threshold": 0.6,
        "prompt_template": "exit.j2"
      },
      "stake": {
        "enabled": true,
        "cache_ttl": 300,
        "min_stake_multiplier": 0.5,
        "max_stake_multiplier": 2.0,
        "prompt_template": "stake.j2"
      },
      "adjust_position": {
        "enabled": false
      },
      "leverage": {
        "enabled": false
      }
    },

    "context": {
      "lookback_candles": 100,
      "include_indicators": ["rsi", "macd", "bb_upper", "bb_lower", "ema_9", "ema_21"],
      "include_orderbook": false,
      "include_recent_trades": true,
      "include_funding_rate": false,
      "include_portfolio_state": true
    },

    "performance": {
      "log_to_database": true,
      "log_prompts": false,
      "log_responses": true,
      "export_metrics": true
    }
  }
}
```

### 2. Prompt 模板

创建 `user_data/llm_prompts/entry.j2`:

```jinja
You are a professional cryptocurrency trading analyst. Analyze the following market data and decide whether to enter a LONG position.

## Market Information
- **Pair**: {{ pair }}
- **Current Time**: {{ current_time }}
- **Current Price**: ${{ current_candle.close }}

## Technical Indicators
{% if indicators %}
{% for key, value in indicators.items() %}
- **{{ key }}**: {{ "%.2f"|format(value) }}
{% endfor %}
{% endif %}

## Market Summary
{{ market_summary }}

## Recent Candles (Last 10)
{% if recent_candles %}
| Time | Open | High | Low | Close | Volume |
|------|------|------|-----|-------|--------|
{% for candle in recent_candles %}
| {{ loop.index }} | {{ "%.2f"|format(candle.open) }} | {{ "%.2f"|format(candle.high) }} | {{ "%.2f"|format(candle.low) }} | {{ "%.2f"|format(candle.close) }} | {{ "%.0f"|format(candle.volume) }} |
{% endfor %}
{% endif %}

## Your Task
Based on the above data, decide whether to:
1. **BUY** - Enter a long position
2. **HOLD** - Do not enter a position

Provide your response in **JSON format only**:

```json
{
    "decision": "buy" or "hold",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 100 words)",
    "parameters": {}
}
```

**Guidelines**:
- Confidence above 0.7 is required for entry
- Consider trend, momentum, and support/resistance
- Be conservative - only enter high-probability setups
```

创建 `user_data/llm_prompts/exit.j2`:

```jinja
You are a professional cryptocurrency trading analyst. Analyze the current position and decide whether to EXIT.

## Trade Information
- **Pair**: {{ pair }}
- **Entry Price**: ${{ entry_price }}
- **Current Price**: ${{ current_price }}
- **Current Profit**: {{ "%.2f"|format(current_profit_pct) }}%
- **Current Profit (Absolute)**: ${{ "%.2f"|format(current_profit_abs) }}
- **Holding Duration**: {{ "%.1f"|format(holding_duration_minutes) }} minutes
- **Stop Loss**: ${{ stop_loss }}
- **Max Rate**: ${{ max_rate }}
- **Entry Tag**: {{ entry_tag }}

## Current Market Indicators
{% if current_indicators %}
{% for key, value in current_indicators.items() %}
- **{{ key }}**: {{ "%.2f"|format(value) }}
{% endfor %}
{% endif %}

## Your Task
Decide whether to:
1. **EXIT** - Close the position now
2. **HOLD** - Keep the position open

Provide your response in **JSON format only**:

```json
{
    "decision": "exit" or "hold",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 100 words)",
    "parameters": {}
}
```

**Exit Guidelines**:
- Take profit when momentum weakens
- Cut losses early if trend reverses
- Consider holding duration and profit target
```

创建 `user_data/llm_prompts/stake.j2`:

```jinja
You are a professional cryptocurrency portfolio manager. Determine the appropriate position size for this trade.

## Market Information
- **Pair**: {{ pair }}
- **Current Price**: ${{ current_price }}
- **Available Balance**: ${{ "%.2f"|format(available_balance) }}

## Market Conditions
{{ market_summary }}

- **Volatility**: {{ "%.2f"|format(volatility) }}%

## Your Task
Determine the position size multiplier (0.5 - 2.0):
- **0.5**: Half the default size (low confidence/high risk)
- **1.0**: Default size
- **2.0**: Double size (high confidence/low risk)

Provide your response in **JSON format only**:

```json
{
    "decision": "adjust" or "default",
    "confidence": 0.0-1.0,
    "reasoning": "Brief explanation (max 50 words)",
    "parameters": {
        "stake_multiplier": 0.5-2.0
    }
}
```

**Guidelines**:
- Higher volatility = smaller position
- Strong trend + low volatility = larger position
- Be conservative with portfolio risk
```

### 3. 启动策略

```bash
# 设置环境变量
export OPENAI_API_KEY="sk-your-key-here"

# 启动 dry-run 模式
freqtrade trade -c user_data/config_llm.json

# 启动 live 模式（谨慎！）
freqtrade trade -c user_data/config_llm.json --dry-run=false
```

### 4. 查询 LLM 决策日志

```python
# Python 脚本查询
from freqtrade.persistence import Trade
from freqtrade.persistence.llm_models import LLMDecision

Trade.session_factory = ...  # 初始化 session

# 查询最近的 LLM 决策
decisions = Trade.session.query(LLMDecision)\
    .filter(LLMDecision.success == True)\
    .order_by(LLMDecision.created_at.desc())\
    .limit(10)\
    .all()

for d in decisions:
    print(f"[{d.created_at}] {d.pair} {d.decision_point}: {d.decision} (conf: {d.confidence:.2f})")
    print(f"  Reasoning: {d.reasoning}")
    print(f"  Latency: {d.latency_ms}ms, Cost: ${d.cost_usd:.4f}")
```

### 5. 监控 Prometheus 指标

```bash
# 启动 Exporter
python exporter/freqtrade_exporter.py --host 0.0.0.0 --port 9999

# 查看指标
curl http://localhost:9999/metrics | grep llm
```

输出示例：
```
# HELP freqtrade_llm_total_calls LLM 总调用次数
# TYPE freqtrade_llm_total_calls counter
freqtrade_llm_total_calls 1523

# HELP freqtrade_llm_success_rate LLM 调用成功率（%）
# TYPE freqtrade_llm_success_rate gauge
freqtrade_llm_success_rate 98.5

# HELP freqtrade_llm_decision_point_latency_ms 按决策点的平均延迟（毫秒）
# TYPE freqtrade_llm_decision_point_latency_ms gauge
freqtrade_llm_decision_point_latency_ms{decision_point="entry"} 850.5
freqtrade_llm_decision_point_latency_ms{decision_point="exit"} 650.2

# HELP freqtrade_llm_total_cost_usd LLM 累计成本（USD）
# TYPE freqtrade_llm_total_cost_usd counter
freqtrade_llm_total_cost_usd 12.45

# HELP freqtrade_llm_entry_win_rate LLM 入场决策的胜率（%）
# TYPE freqtrade_llm_entry_win_rate gauge
freqtrade_llm_entry_win_rate 62.5
```

---

## 扩展指南

### 1. 添加新的 LLM 提供商

创建 `freqtrade/llm/providers/my_provider.py`:

```python
from freqtrade.llm.providers.base import LLMProvider

class MyCustomProvider(LLMProvider):
    def __init__(self, config: Dict[str, Any]):
        # 初始化你的客户端
        pass

    def complete(self, prompt: str, temperature: float = 0.1) -> str:
        # 实现 API 调用
        pass

    def get_usage_info(self) -> Dict[str, Any]:
        # 返回使用信息
        return {"tokens_used": 0, "cost_usd": 0.0}
```

在 `engine.py` 中注册:
```python
def _init_provider(self):
    provider_name = self.config["provider"]
    if provider_name == "openai":
        return OpenAIProvider(self.config)
    elif provider_name == "anthropic":
        return AnthropicProvider(self.config)
    elif provider_name == "my_custom":
        return MyCustomProvider(self.config)
    else:
        raise ValueError(f"Unknown provider: {provider_name}")
```

### 2. 添加新的决策点

假设要添加 `rebalance` 决策点：

1. **更新配置**:
```json
"decision_points": {
  "rebalance": {
    "enabled": true,
    "cache_ttl": 3600,
    "confidence_threshold": 0.7,
    "prompt_template": "rebalance.j2"
  }
}
```

2. **创建 Prompt 模板** `user_data/llm_prompts/rebalance.j2`

3. **在策略中实现**:
```python
def custom_rebalance(self) -> Dict[str, float]:
    """自定义重平衡逻辑"""
    request = LLMRequest(
        decision_point="rebalance",
        pair="portfolio",
        context=self._build_portfolio_context()
    )
    response = self.llm_engine.decide(request)
    return response.parameters.get("allocations", {})
```

### 3. 自定义上下文构建

继承 `ContextBuilder`:
```python
class MyContextBuilder(ContextBuilder):
    def build_entry_context(self, dataframe, metadata):
        context = super().build_entry_context(dataframe, metadata)

        # 添加自定义数据
        context["my_custom_indicator"] = self._calculate_custom_indicator(dataframe)
        context["market_sentiment"] = self._fetch_sentiment_data(metadata["pair"])

        return context
```

### 4. 多模型集成（Ensemble）

```python
class EnsembleLLMEngine(LLMDecisionEngine):
    """集成多个 LLM 的决策"""

    def __init__(self, configs: List[Dict], strategy_name: str):
        self.engines = [
            LLMDecisionEngine(config, strategy_name)
            for config in configs
        ]

    def decide(self, request: LLMRequest) -> LLMResponse:
        responses = [engine.decide(request) for engine in self.engines]

        # 投票或加权平均
        return self._aggregate_responses(responses)

    def _aggregate_responses(self, responses: List[LLMResponse]) -> LLMResponse:
        # 简单投票
        from collections import Counter
        decisions = [r.decision for r in responses]
        most_common = Counter(decisions).most_common(1)[0][0]

        # 平均置信度
        avg_confidence = sum(r.confidence for r in responses) / len(responses)

        return LLMResponse(
            decision=most_common,
            confidence=avg_confidence,
            reasoning=f"Ensemble of {len(responses)} models",
            parameters={},
            latency_ms=sum(r.latency_ms for r in responses),
            tokens_used=sum(r.tokens_used or 0 for r in responses),
            cost_usd=sum(r.cost_usd or 0 for r in responses),
            cached=False
        )
```

### 5. A/B 测试框架

```python
class ABTestLLMStrategy(LLMStrategy):
    """A/B 测试不同的 LLM 配置"""

    def bot_start(self, **kwargs):
        # 初始化两个引擎
        self.engine_a = LLMDecisionEngine(self.config_a, "strategy_a")
        self.engine_b = LLMDecisionEngine(self.config_b, "strategy_b")

        self.ab_ratio = 0.5  # 50% 流量给 A，50% 给 B

    def populate_entry_trend(self, dataframe, metadata):
        import random

        # 随机选择引擎
        engine = self.engine_a if random.random() < self.ab_ratio else self.engine_b

        # 使用选中的引擎决策
        # ...
```

---

## 附录

### A. 完整文件清单

| 文件路径 | 说明 |
|---------|------|
| `freqtrade/llm/engine.py` | LLM 决策引擎核心 |
| `freqtrade/llm/context_builder.py` | 上下文构建器 |
| `freqtrade/llm/prompts/manager.py` | Prompt 管理器 |
| `freqtrade/llm/providers/base.py` | 提供商抽象基类 |
| `freqtrade/llm/providers/openai.py` | OpenAI 提供商 |
| `freqtrade/llm/providers/anthropic.py` | Anthropic 提供商 |
| `freqtrade/llm/providers/ollama.py` | Ollama 本地模型提供商 |
| `freqtrade/persistence/llm_models.py` | LLM 数据库模型 |
| `freqtrade/strategy/LLMStrategy.py` | LLM 策略基类 |
| `exporter/metrics/llm.py` | LLM 指标采集器 |
| `user_data/strategies/MyLLMStrategy.py` | 示例策略 |
| `user_data/llm_prompts/entry.j2` | 入场 Prompt 模板 |
| `user_data/llm_prompts/exit.j2` | 出场 Prompt 模板 |
| `user_data/llm_prompts/stake.j2` | 仓位管理 Prompt 模板 |
| `user_data/config_llm.json` | LLM 配置示例 |
| `docs/llm-strategy-design.md` | 本设计文档 |

### B. 依赖库

```txt
# requirements-llm.txt
openai>=1.0.0
anthropic>=0.25.0
jinja2>=3.0.0
cachetools>=5.0.0
```

### C. 环境变量

```bash
# .env
OPENAI_API_KEY=sk-your-key
ANTHROPIC_API_KEY=sk-ant-your-key
FREQTRADE_DB_URL=sqlite:///user_data/tradesv3.sqlite
```

### D. 成本估算

| LLM 提供商 | 模型 | 输入成本 | 输出成本 | 预估每决策成本 |
|-----------|------|---------|---------|--------------|
| OpenAI | GPT-4o | $5/1M tokens | $15/1M tokens | ~$0.005 |
| OpenAI | GPT-4o-mini | $0.15/1M tokens | $0.6/1M tokens | ~$0.0002 |
| Anthropic | Claude 3.5 Sonnet | $3/1M tokens | $15/1M tokens | ~$0.004 |
| Anthropic | Claude 3 Haiku | $0.25/1M tokens | $1.25/1M tokens | ~$0.0003 |
| Ollama | Llama 3 (本地) | 免费 | 免费 | $0 |

**月度成本估算**（假设每分钟 1 次决策）:
- GPT-4o: ~$216/月
- GPT-4o-mini: ~$8.6/月
- Claude 3.5 Sonnet: ~$172/月
- Claude 3 Haiku: ~$13/月
- Ollama (本地): $0

### E. 性能基准

| 提供商 | 模型 | 平均延迟 | P95 延迟 | 建议 cache_ttl |
|--------|------|---------|---------|--------------|
| OpenAI | GPT-4o | 800ms | 1500ms | 60s |
| OpenAI | GPT-4o-mini | 400ms | 800ms | 30s |
| Anthropic | Claude 3.5 Sonnet | 1000ms | 2000ms | 60s |
| Anthropic | Claude 3 Haiku | 500ms | 1000ms | 30s |
| Ollama | Llama 3 (本地 GPU) | 200ms | 500ms | 15s |

### F. 安全注意事项

1. **API 密钥管理**:
   - 使用环境变量，不要硬编码
   - 定期轮换密钥
   - 使用 secrets 管理工具

2. **Prompt 注入防护**:
   - 不要直接将用户输入放入 Prompt
   - 验证和清理所有外部数据
   - 使用结构化输出（JSON mode）

3. **成本控制**:
   - 设置每日/月度预算
   - 监控 API 使用量
   - 使用缓存减少重复调用
   - 考虑使用更便宜的模型

4. **错误处理**:
   - 始终有 fallback 机制
   - 记录所有错误
   - 设置超时和重试限制

5. **数据隐私**:
   - 不要将敏感信息发送给 LLM
   - 遵守数据保护法规
   - 考虑使用本地模型

---

## 总结

本设计方案提供了一个完整的、模块化的 LLM 辅助交易策略框架，具备以下特点:

- **通用性**: 支持多种 LLM 提供商和模型
- **灵活性**: 可配置的决策点和 Prompt 模板
- **可观测性**: 完整的日志、数据库记录和 Prometheus 指标
- **可扩展性**: 模块化设计，易于添加新功能
- **可靠性**: 缓存、重试、fallback 机制
- **成本优化**: 缓存和可配置的调用策略

下一步建议:
1. 实现核心模块（engine.py, providers, context_builder）
2. 创建数据库迁移脚本
3. 编写单元测试和集成测试
4. 在 dry-run 模式下充分测试
5. 收集真实数据并调优 Prompt
6. 逐步上线到生产环境

祝你交易顺利！
