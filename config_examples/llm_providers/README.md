# LLM 提供商配置模板

这个目录包含了各大 LLM 提供商的配置模板。所有提供商都使用统一的 HTTP 接口，不需要安装额外的库。

## 使用方法

1. **选择提供商**：从下面的表格中选择一个 LLM 的提供商
2. **复制配置**：将对应的 JSON 文件内容复制到你的 `config.json` 的 `llm_config` 部分
3. **设置 API Key**：设置环境变量或直接填写 API Key
4. **运行策略**：使用 Freqtrade 运行你的 LLM 策略

## 支持的提供商

| 提供商 | 配置文件 | 模型 | 成本/百万token (输入/输出) | 推荐用途 |
|--------|---------|------|---------------------------|----------|
| **OpenAI GPT-4o** | `openai.json` | gpt-4o | $5/$15 | 高质量决策 |
| **OpenAI GPT-4o-mini** | `openai-mini.json` | gpt-4o-mini | $0.15/$0.6 | **性价比之选** |
| **Anthropic Claude 3.5** | `anthropic.json` | claude-3-5-sonnet | $3/$15 | 高质量决策 |
| **Anthropic Haiku** | `anthropic-haiku.json` | claude-3-haiku | $0.25/$1.25 | **便宜且快** |
| **DeepSeek** | `deepseek.json` | deepseek-chat | $0.27/$1.10 | **超低成本** |
| **Ollama** | `ollama.json` | llama3/mistral/等 | **免费** | **本地运行，零成本** |
| **通义千问** | `qwen.json` | qwen-turbo | ~$0.5/$1.5 | 国内用户 |

## 快速开始示例

### 使用 OpenAI GPT-4o-mini (推荐新手)

```bash
# 1. 设置 API Key
export OPENAI_API_KEY="sk-your-key-here"

# 2. 在 config.json 中添加配置
cat config_examples/llm_providers/openai-mini.json
# 复制内容到 config.json 的 llm_config 部分

# 3. 运行
freqtrade trade -c config.json --strategy ExampleLLMStrategy
```

### 使用 Ollama (完全免费)

```bash
# 1. 安装并启动 Ollama
ollama pull llama3
ollama serve

# 2. 在 config.json 中添加配置
cat config_examples/llm_providers/ollama.json
# 复制内容到 config.json 的 llm_config 部分

# 3. 运行
freqtrade trade -c config.json --strategy ExampleLLMStrategy
```

## 配置说明

每个配置文件包含以下部分：

### 1. 基本配置
```json
{
    "provider_type": "http",        // 固定为 "http"
    "model": "gpt-4o",              // 模型名称
    "api_url": "https://...",       // API 端点
    "api_key": "${API_KEY}",        // API 密钥（支持环境变量）
    "timeout": 30,                  // 超时时间（秒）
    "max_retries": 3,               // 最大重试次数
    "temperature": 0.1              // 温度参数 (0.0-1.0)
}
```

### 2. HTTP 请求配置
```json
{
    "headers": {
        "Authorization": "Bearer {api_key}"  // {api_key} 会被替换
    },

    "request_body": {
        "model": "{model}",          // {model} 会被替换
        "messages": [
            {
                "role": "user",
                "content": "{prompt}"  // {prompt} 会被替换
            }
        ],
        "temperature": "{temperature}"  // {temperature} 会被替换
    }
}
```

**支持的占位符**:
- `{api_key}` - API 密钥
- `{model}` - 模型名称
- `{prompt}` - 用户提示词
- `{temperature}` - 温度参数

### 3. 响应解析配置
```json
{
    "response_path": {
        "content_path": "choices.0.message.content",  // JSON 路径
        "usage_path": "usage",                         // token 使用信息路径
        "ensure_json": true                            // 确保返回 JSON
    }
}
```

**JSON 路径语法**:
- 使用 `.` 分隔层级：`"choices.0.message.content"`
- 数字表示数组索引：`"choices.0"` 表示 `choices[0]`
- 自动尝试常见路径如果未指定

### 4. 成本配置
```json
{
    "cost_config": {
        "input_cost_per_million": 5.0,    // 输入 token 成本（每百万）
        "output_cost_per_million": 15.0   // 输出 token 成本（每百万）
    }
}
```

## 添加自定义提供商

你可以轻松添加任何兼容的 LLM API：

```json
{
    "provider_type": "http",
    "model": "your-model",
    "api_url": "https://your-api.com/endpoint",
    "api_key": "${YOUR_API_KEY}",

    "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer {api_key}"
    },

    "request_body": {
        "model": "{model}",
        "prompt": "{prompt}"
    },

    "response_path": {
        "content_path": "response.text",
        "ensure_json": true
    },

    "cost_config": {
        "input_cost_per_million": 0.0,
        "output_cost_per_million": 0.0
    }
}
```

## 成本对比

假设每分钟 1 次决策，每次 1000 tokens：

| 提供商 | 每次成本 | 每小时 | 每天 | 每月 |
|--------|---------|--------|------|------|
| GPT-4o | $0.010 | $0.60 | $14.40 | $432 |
| GPT-4o-mini | $0.0004 | $0.024 | $0.58 | $17 |
| Claude Haiku | $0.0007 | $0.042 | $1.01 | $30 |
| DeepSeek | $0.0007 | $0.042 | $1.01 | $30 |
| **Ollama** | **$0** | **$0** | **$0** | **$0** |

## 性能对比

| 提供商 | 平均延迟 | 推荐时间框架 | 推荐 cache_ttl |
|--------|---------|-------------|----------------|
| GPT-4o | 800ms | 5m+ | 60s |
| GPT-4o-mini | 400ms | 1m+ | 30s |
| Claude Haiku | 500ms | 5m+ | 30s |
| DeepSeek | 600ms | 5m+ | 45s |
| Ollama (本地) | 200ms | 1m+ | 15s |

## 环境变量

建议使用环境变量管理 API 密钥：

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# DeepSeek
export DEEPSEEK_API_KEY="sk-..."

# 阿里云
export DASHSCOPE_API_KEY="sk-..."
```

配置中使用 `${VAR_NAME}` 语法引用：
```json
{
    "api_key": "${OPENAI_API_KEY}"
}
```

## 故障排查

### 问题：API 调用失败
- 检查 API Key 是否正确
- 检查网络连接
- 查看日志中的错误信息

### 问题：返回不是 JSON
- 确保 `ensure_json: true`
- 在 prompt 中强调 JSON 格式
- 调整 `response_path.content_path`

### 问题：成本太高
- 使用便宜的模型（GPT-4o-mini, Claude Haiku, DeepSeek）
- 增加 `cache_ttl` 以复用决策
- 减少 `lookback_candles` 和 `include_indicators`
- 使用 Ollama 完全免费

## 获取帮助

- 查看完整文档：`docs/llm-strategy-design.md`
- 快速入门：`docs/llm-quick-start.md`
- GitHub Issues: https://github.com/freqtrade/freqtrade/issues
