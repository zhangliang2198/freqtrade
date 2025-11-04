# LLM HTTP 通用方式 - 迁移指南

> **重大更新**: LLM 集成已重构为通用 HTTP 方式，无需额外 SDK 库！

## 🎉 主要改进

### 1. **零额外依赖**
- ❌ 旧方式：需要安装 `openai`, `anthropic` 等库
- ✅ 新方式：只需 `jinja2` (用于 Prompt 模板)

### 2. **完全通用**
- ❌ 旧方式：每个提供商需要专用代码
- ✅ 新方式：通过配置支持任意 LLM API

### 3. **更易扩展**
- ❌ 旧方式：添加新提供商需要编写 Python 代码
- ✅ 新方式：添加新提供商只需一个 JSON 配置文件

## 架构对比

### 旧架构
```
LLMStrategy → LLMEngine → [OpenAIProvider, AnthropicProvider, OllamaProvider]
                              ↓需要专用SDK     ↓需要专用SDK          ↓需要专用SDK
                           openai库        anthropic库          requests
```

### 新架构
```
LLMStrategy → LLMEngine → HttpLLMProvider
                              ↓仅使用 requests (已内置)
                           任意 LLM API
```

## 配置迁移

### 旧配置格式

```json
{
    "llm_config": {
        "enabled": true,
        "provider": "openai",      // 旧字段
        "model": "gpt-4o",
        "api_key": "${OPENAI_API_KEY}",
        "base_url": null,
        "timeout": 30
    }
}
```

### 新配置格式

```json
{
    "llm_config": {
        "enabled": true,
        "provider_type": "http",    // 新字段，固定为 "http"
        "model": "gpt-4o",
        "api_url": "https://api.openai.com/v1/chat/completions",  // 新字段
        "api_key": "${OPENAI_API_KEY}",
        "timeout": 30,

        "headers": {                 // 新字段：HTTP 请求头
            "Authorization": "Bearer {api_key}"
        },

        "request_body": {            // 新字段：请求体模板
            "model": "{model}",
            "messages": [
                {"role": "user", "content": "{prompt}"}
            ]
        },

        "response_path": {           // 新字段：响应解析
            "content_path": "choices.0.message.content"
        },

        "cost_config": {             // 新字段：成本计算
            "input_cost_per_million": 5.0,
            "output_cost_per_million": 15.0
        }
    }
}
```

## 迁移步骤

### 步骤 1: 更新依赖

```bash
# 卸载旧库（可选）
pip uninstall openai anthropic

# 只保留必要的库
pip install jinja2
```

### 步骤 2: 选择提供商配置

我们为常见提供商提供了配置模板：

```bash
ls config_examples/llm_providers/
# openai.json
# openai-mini.json  (推荐：性价比高)
# anthropic.json
# anthropic-haiku.json
# ollama.json  (推荐：完全免费)
# deepseek.json  (推荐：超低成本)
# qwen.json
```

### 步骤 3: 更新配置文件

方式 A: 复制完整配置
```bash
# 查看提供商配置
cat config_examples/llm_providers/openai-mini.json

# 复制到你的 config.json 的 llm_config 部分
```

方式 B: 使用配置示例
```bash
# 使用更新后的配置示例
cp config_examples/config_llm.example.json user_data/config_llm.json
# 已包含 HTTP 方式的完整配置
```

### 步骤 4: 测试

```bash
# Dry-run 测试
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy

# 查看日志确认 HTTP 方式正常工作
tail -f user_data/logs/freqtrade.log | grep "HTTP LLM"
```

## 提供商配置模板

### OpenAI (GPT-4o-mini) - 推荐

```json
{
    "provider_type": "http",
    "model": "gpt-4o-mini",
    "api_url": "https://api.openai.com/v1/chat/completions",
    "api_key": "${OPENAI_API_KEY}",
    "headers": {
        "Authorization": "Bearer {api_key}"
    },
    "request_body": {
        "model": "{model}",
        "messages": [{"role": "user", "content": "{prompt}"}],
        "response_format": {"type": "json_object"}
    },
    "response_path": {
        "content_path": "choices.0.message.content"
    },
    "cost_config": {
        "input_cost_per_million": 0.15,
        "output_cost_per_million": 0.6
    }
}
```

### Anthropic (Claude 3 Haiku) - 快速且便宜

```json
{
    "provider_type": "http",
    "model": "claude-3-haiku-20240307",
    "api_url": "https://api.anthropic.com/v1/messages",
    "api_key": "${ANTHROPIC_API_KEY}",
    "headers": {
        "x-api-key": "{api_key}",
        "anthropic-version": "2023-06-01"
    },
    "request_body": {
        "model": "{model}",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "{prompt}"}]
    },
    "response_path": {
        "content_path": "content.0.text"
    },
    "cost_config": {
        "input_cost_per_million": 0.25,
        "output_cost_per_million": 1.25
    }
}
```

### Ollama (本地) - 完全免费

```json
{
    "provider_type": "http",
    "model": "llama3",
    "api_url": "http://localhost:11434/api/generate",
    "headers": {},
    "request_body": {
        "model": "{model}",
        "prompt": "{prompt}",
        "stream": false,
        "format": "json"
    },
    "response_path": {
        "content_path": "response"
    },
    "cost_config": {
        "input_cost_per_million": 0.0,
        "output_cost_per_million": 0.0
    }
}
```

### DeepSeek - 超低成本

```json
{
    "provider_type": "http",
    "model": "deepseek-chat",
    "api_url": "https://api.deepseek.com/v1/chat/completions",
    "api_key": "${DEEPSEEK_API_KEY}",
    "headers": {
        "Authorization": "Bearer {api_key}"
    },
    "request_body": {
        "model": "{model}",
        "messages": [{"role": "user", "content": "{prompt}"}],
        "response_format": {"type": "json_object"}
    },
    "response_path": {
        "content_path": "choices.0.message.content"
    },
    "cost_config": {
        "input_cost_per_million": 0.27,
        "output_cost_per_million": 1.10
    }
}
```

## 占位符说明

配置中可以使用以下占位符：

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `{api_key}` | API 密钥 | `"Authorization": "Bearer {api_key}"` |
| `{model}` | 模型名称 | `"model": "{model}"` |
| `{prompt}` | 用户提示词 | `"content": "{prompt}"` |
| `{temperature}` | 温度参数 | `"temperature": "{temperature}"` |

## 响应路径语法

使用点号 `.` 表示 JSON 路径：

| 路径 | 说明 | 对应的 Python |
|------|------|--------------|
| `"choices.0.message.content"` | 数组索引用数字 | `response["choices"][0]["message"]["content"]` |
| `"content.0.text"` | 嵌套路径 | `response["content"][0]["text"]` |
| `"response"` | 顶层字段 | `response["response"]` |

如果未指定路径，系统会自动尝试常见格式。

## 兼容性说明

### 旧代码仍然可用

旧的专用提供商代码仍然保留（标记为 deprecated）：

```json
{
    "llm_config": {
        "provider_type": "openai_legacy",  // 使用旧代码
        // ...
    }
}
```

但我们**强烈推荐**使用新的 HTTP 方式。

### 逐步迁移

1. 先在测试环境使用 HTTP 方式
2. 确认工作正常后再切换生产环境
3. 可以同时运行两个配置进行对比

## 成本对比

| 提供商 | 成本/决策 | 月成本 (5m 时间框架) |
|--------|----------|-------------------|
| **Ollama (本地)** | **$0** | **$0** |
| **DeepSeek** | $0.0007 | ~$6 |
| **GPT-4o-mini** | $0.0004 | ~$3.5 |
| **Claude Haiku** | $0.0007 | ~$6 |
| GPT-4o | $0.010 | ~$86 |

## 性能对比

| 提供商 | 平均延迟 | 本地/云端 |
|--------|---------|----------|
| **Ollama** | 200ms | 本地 |
| GPT-4o-mini | 400ms | 云端 |
| Claude Haiku | 500ms | 云端 |
| DeepSeek | 600ms | 云端 |
| GPT-4o | 800ms | 云端 |

## 文件变更清单

### 新增文件

```
freqtrade/llm/providers/http_provider.py  # HTTP 通用提供商
config_examples/llm_providers/
├── README.md
├── openai.json
├── openai-mini.json
├── anthropic.json
├── anthropic-haiku.json
├── ollama.json
├── deepseek.json
└── qwen.json
docs/llm-quick-start-http.md             # HTTP 快速入门
docs/llm-http-migration.md               # 本文档
```

### 修改文件

```
freqtrade/llm/providers/__init__.py       # 导出 HttpLLMProvider
freqtrade/llm/engine.py                   # 使用 provider_type
config_examples/config_llm.example.json   # 更新为 HTTP 配置
requirements-llm.txt                      # 移除 openai, anthropic
requirements-add.txt                      # 移除 openai, anthropic
```

### 保留文件 (标记为 deprecated)

```
freqtrade/llm/providers/openai_provider.py
freqtrade/llm/providers/anthropic_provider.py
freqtrade/llm/providers/ollama_provider.py
```

## 常见问题

### Q: 旧配置还能用吗？

A: 可以，但需要将 `"provider": "openai"` 改为 `"provider_type": "openai_legacy"`。不过我们强烈推荐迁移到 HTTP 方式。

### Q: HTTP 方式有什么限制吗？

A: 几乎没有。只要 LLM 提供 HTTP API，就可以通过配置使用。

### Q: 如何添加新的 LLM 提供商？

A: 创建一个 JSON 配置文件即可，无需编写代码。参考 `config_examples/llm_providers/` 中的示例。

### Q: 性能会受影响吗？

A: 不会。HTTP 方式使用 `requests` 库，性能与专用 SDK 相当或更好（因为减少了中间层）。

### Q: 成本计算准确吗？

A: 是的。`cost_config` 可以精确配置每个提供商的定价。

## 获取帮助

- 查看提供商配置: `config_examples/llm_providers/README.md`
- 快速入门: `docs/llm-quick-start-http.md`
- 设计文档: `docs/llm-strategy-design.md`
- GitHub Issues: https://github.com/freqtrade/freqtrade/issues

## 总结

✅ **更简单**: 无需额外 SDK，只需 requests
✅ **更通用**: 支持任意 LLM API
✅ **更灵活**: 通过配置即可适配
✅ **更便宜**: 支持本地模型（Ollama）和低成本选项（DeepSeek）

**立即迁移到 HTTP 方式，享受更好的 LLM 集成体验！** 🚀
