# LLM 辅助交易策略 - 快速入门 (HTTP 通用方式)

## 概述

**重大更新**：现在使用统一的 HTTP 接口调用所有 LLM，无需安装任何额外的 SDK 库！

只需要配置 API URL、请求格式和响应格式，就可以支持任何 LLM 提供商。

## 优势

✅ **零额外依赖** - 只需 `jinja2`（用于 Prompt 模板）
✅ **通用性强** - 支持任何提供 HTTP API 的 LLM
✅ **配置灵活** - 通过 JSON 配置适配不同提供商
✅ **易于扩展** - 添加新提供商只需一个配置文件

## 快速开始

### 1. 安装依赖（只需 jinja2）

```bash
pip install jinja2
```

就这么简单！不需要 `openai`、`anthropic` 等库。

### 2. 选择 LLM 提供商

我们提供了多个提供商的配置模板：

| 提供商 | 成本 | 配置文件 | 推荐场景 |
|--------|------|---------|---------|
| **OpenAI GPT-4o-mini** | 💰 $0.0004/决策 | `openai-mini.json` | **最佳性价比** |
| **Ollama** | 💰 **完全免费** | `ollama.json` | **零成本方案** |
| **DeepSeek** | 💰 $0.0007/决策 | `deepseek.json` | **超低成本** |
| **Claude Haiku** | 💰 $0.0007/决策 | `anthropic-haiku.json` | **快速响应** |
| OpenAI GPT-4o | 💰 $0.010/决策 | `openai.json` | 高质量决策 |
| Claude 3.5 | 💰 $0.009/决策 | `anthropic.json` | 高质量决策 |
| 通义千问 | 💰 $0.001/决策 | `qwen.json` | 国内用户 |

### 3. 配置 API

#### 方式 A: 使用预设配置（推荐）

```bash
# 查看提供商配置
ls config_examples/llm_providers/
# openai.json openai-mini.json anthropic.json ollama.json deepseek.json qwen.json

# 复制主配置
cp config_examples/config_llm.example.json user_data/config_llm.json

# 选择一个提供商配置，复制其内容到 config_llm.json 的 llm_config 部分
cat config_examples/llm_providers/openai-mini.json
```

#### 方式 B: 手动配置

编辑 `user_data/config_llm.json`，添加 LLM 配置：

```json
{
    "llm_config": {
        "enabled": true,
        "provider_type": "http",
        "model": "gpt-4o-mini",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "api_key": "${OPENAI_API_KEY}",

        "headers": {
            "Content-Type": "application/json",
            "Authorization": "Bearer {api_key}"
        },

        "request_body": {
            "model": "{model}",
            "messages": [
                {"role": "system", "content": "You are a crypto trading expert."},
                {"role": "user", "content": "{prompt}"}
            ],
            "temperature": "{temperature}",
            "response_format": {"type": "json_object"}
        },

        "response_path": {
            "content_path": "choices.0.message.content",
            "ensure_json": true
        },

        "cost_config": {
            "input_cost_per_million": 0.15,
            "output_cost_per_million": 0.6
        },

        "decision_points": {
            "entry": {"enabled": true, "confidence_threshold": 0.7},
            "exit": {"enabled": true, "confidence_threshold": 0.6}
        }
    }
}
```

### 4. 设置 API 密钥

```bash
# OpenAI
export OPENAI_API_KEY="sk-your-key"

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-your-key"

# DeepSeek
export DEEPSEEK_API_KEY="sk-your-key"

# 通义千问
export DASHSCOPE_API_KEY="sk-your-key"

# Ollama 不需要 API Key (本地运行)
```

### 5. 运行策略

```bash
# Dry-run 模式（推荐先测试）
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy

# Live 模式（谨慎！）
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy --dry-run=false
```

## 配置详解

### HTTP 请求配置

#### 占位符

在 `headers` 和 `request_body` 中可以使用以下占位符：

- `{api_key}` - 替换为 API 密钥
- `{model}` - 替换为模型名称
- `{prompt}` - 替换为用户提示词
- `{temperature}` - 替换为温度参数

#### 响应解析

`response_path` 配置如何从响应中提取内容：

```json
{
    "response_path": {
        "content_path": "choices.0.message.content",  // JSON 路径（使用 . 分隔）
        "usage_path": "usage",                         // Token 使用信息路径
        "ensure_json": true                            // 自动提取 JSON
    }
}
```

**路径语法**：
- `"choices.0.message.content"` → `response["choices"][0]["message"]["content"]`
- 数字表示数组索引

## 使用示例

### 示例 1: 使用 GPT-4o-mini (最佳性价比)

```bash
# 1. 设置 API Key
export OPENAI_API_KEY="sk-..."

# 2. 复制配置
cat > user_data/config_llm.json << 'EOF'
{
    "strategy": "ExampleLLMStrategy",
    "llm_config": {
        "enabled": true,
        "provider_type": "http",
        "model": "gpt-4o-mini",
        "api_url": "https://api.openai.com/v1/chat/completions",
        "api_key": "${OPENAI_API_KEY}",
        "headers": {
            "Authorization": "Bearer {api_key}"
        },
        "request_body": {
            "model": "{model}",
            "messages": [
                {"role": "user", "content": "{prompt}"}
            ],
            "response_format": {"type": "json_object"}
        },
        "response_path": {
            "content_path": "choices.0.message.content"
        },
        "cost_config": {
            "input_cost_per_million": 0.15,
            "output_cost_per_million": 0.6
        },
        "decision_points": {
            "entry": {"enabled": true}
        }
    }
}
EOF

# 3. 运行
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy
```

### 示例 2: 使用 Ollama (完全免费)

```bash
# 1. 安装并启动 Ollama
ollama pull llama3
ollama serve &

# 2. 复制 Ollama 配置
cp config_examples/llm_providers/ollama.json user_data/ollama_config.json

# 3. 在主配置中引用
cat user_data/config_llm.json  # 将 ollama_config.json 的内容复制到 llm_config

# 4. 运行（无需 API Key！）
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy
```

### 示例 3: 使用 DeepSeek (超便宜)

```bash
# 1. 设置 API Key
export DEEPSEEK_API_KEY="sk-..."

# 2. 使用 DeepSeek 配置
# 复制 config_examples/llm_providers/deepseek.json 到你的配置

# 3. 运行
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy
```

## 监控和调试

### 查看日志

```bash
# 实时日志
tail -f user_data/logs/freqtrade.log | grep LLM

# 应该看到类似：
# LLM decision for BTC/USDT entry: buy (confidence: 0.85, latency: 450ms, cost: $0.0004)
```

### 查询数据库

```python
from freqtrade.persistence import Trade
from freqtrade.persistence.llm_models import LLMDecision

# 最近 10 次决策
decisions = Trade.session.query(LLMDecision)\
    .order_by(LLMDecision.created_at.desc())\
    .limit(10).all()

for d in decisions:
    print(f"{d.pair} {d.decision_point}: {d.decision} (conf: {d.confidence:.2f}, cost: ${d.cost_usd:.4f})")
```

### Prometheus 指标

```bash
# 启动 exporter
python exporter/freqtrade_exporter.py --port 9999

# 查看 LLM 指标
curl http://localhost:9999/metrics | grep llm

# 关键指标:
# - freqtrade_llm_total_calls: 总调用次数
# - freqtrade_llm_total_cost_usd: 累计成本
# - freqtrade_llm_success_rate: 成功率
# - freqtrade_llm_entry_win_rate: 入场决策胜率
```

## 成本管理

### 月度成本估算

假设 5 分钟时间框架，每 5 分钟 1 次决策：

| 提供商 | 每次 | 每天 | 每月 |
|--------|------|------|------|
| **Ollama (本地)** | **$0** | **$0** | **$0** |
| **DeepSeek** | $0.0007 | $0.20 | $6 |
| **GPT-4o-mini** | $0.0004 | $0.12 | $3.5 |
| **Claude Haiku** | $0.0007 | $0.20 | $6 |
| GPT-4o | $0.010 | $2.88 | $86 |

### 降低成本技巧

1. **使用缓存**：
```json
{
    "decision_points": {
        "entry": {
            "cache_ttl": 300  // 5分钟缓存，相同市场条件复用决策
        }
    }
}
```

2. **减少上下文**：
```json
{
    "context": {
        "lookback_candles": 50,  // 减少历史数据
        "include_indicators": ["rsi", "macd"]  // 只包含必要指标
    }
}
```

3. **使用便宜/免费模型**：
   - **Ollama**: 完全免费
   - **DeepSeek**: 超便宜
   - **GPT-4o-mini**: OpenAI 最便宜的选项

4. **提高置信度阈值**：
```json
{
    "decision_points": {
        "entry": {
            "confidence_threshold": 0.8  // 只在高置信度时入场
        }
    }
}
```

## 添加自定义 LLM

你可以添加任何提供 HTTP API 的 LLM：

```json
{
    "llm_config": {
        "provider_type": "http",
        "model": "your-model",
        "api_url": "https://your-api.com/v1/chat",
        "api_key": "${YOUR_API_KEY}",

        "headers": {
            "Authorization": "Bearer {api_key}"
        },

        "request_body": {
            "model": "{model}",
            "input": "{prompt}"
        },

        "response_path": {
            "content_path": "output.text",
            "ensure_json": true
        },

        "cost_config": {
            "input_cost_per_million": 1.0,
            "output_cost_per_million": 2.0
        }
    }
}
```

## 常见问题

### Q: 响应不是 JSON 格式怎么办？

A: 确保设置 `"ensure_json": true`，系统会自动提取 JSON。也可以在 prompt 中强调 JSON 格式。

### Q: 如何知道响应路径？

A: 查看 API 文档，或者先手动调用一次查看响应结构。常见路径：
- OpenAI: `"choices.0.message.content"`
- Anthropic: `"content.0.text"`
- 其他: 如果未指定会自动尝试常见路径

### Q: Ollama 延迟太高？

A: 使用 GPU 加速：
```bash
# 安装 CUDA 版本的 Ollama
# 或使用更小的模型
ollama pull llama3:8b  # 使用 8B 参数版本而非 70B
```

### Q: 如何测试配置是否正确？

A: 运行 dry-run 模式并查看日志，应该看到 LLM 决策日志。

## 下一步

- 📖 [完整设计文档](llm-strategy-design.md) - 深入了解架构
- 📊 [提供商配置模板](../config_examples/llm_providers/) - 查看所有支持的提供商
- 💡 [示例策略](../user_data/strategies/ExampleLLMStrategy.py) - 学习如何创建策略

## 获取帮助

- 配置问题: 查看 `config_examples/llm_providers/README.md`
- GitHub Issues: https://github.com/freqtrade/freqtrade/issues
- Discord: https://discord.gg/freqtrade

祝交易顺利！🚀
