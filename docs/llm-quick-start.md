# LLM 辅助交易策略 - 快速入门

## 概述

LLM 辅助交易策略允许您使用大语言模型（如 GPT-4、Claude）来做出交易决策。这个系统在以下关键决策点使用 LLM：

- **入场决策** (`populate_entry_trend`)：分析市场数据，决定是否开仓
- **出场决策** (`custom_exit`)：判断是否平仓
- **仓位管理** (`custom_stake_amount`)：动态调整开仓金额
- **加仓决策** (`adjust_trade_position`)：判断是否加仓或减仓
- **杠杆控制** (`leverage`)：根据市场状况调整杠杆。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements-llm.txt
```

### 2. 设置 API 密钥

根据您选择的 LLM 提供商设置环境变量：

**OpenAI:**
```bash
export OPENAI_API_KEY="sk-your-key-here"
```

**Anthropic (Claude):**
```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

**Ollama (本地模型):**
```bash
# 确保 Ollama 正在运行
ollama serve
```

### 3. 配置文件

复制示例配置：

```bash
cp config_examples/config_llm.example.json user_data/config_llm.json
```

编辑 `user_data/config_llm.json`，根据需要调整配置：

```json
{
    "llm_config": {
        "enabled": true,
        "provider": "openai",  // 或 "anthropic", "ollama"
        "model": "gpt-4o",     // 或 "claude-3-5-sonnet-20241022", "llama3"
        "api_key": "${OPENAI_API_KEY}",

        "decision_points": {
            "entry": {
                "enabled": true,
                "confidence_threshold": 0.7  // 只有高置信度才入场
            },
            "exit": {
                "enabled": true,
                "confidence_threshold": 0.6
            }
        }
    }
}
```

### 4. 运行策略

**Dry-run 模式（推荐先测试）：**
```bash
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy
```

**Live 模式（谨慎使用！）：**
```bash
freqtrade trade -c user_data/config_llm.json --strategy ExampleLLMStrategy --dry-run=false
```

## 监控 LLM 使用

### 1. 查看日志

LLM 决策会记录在数据库中，可以通过 Freqtrade UI 或直接查询数据库查看：

```python
from freqtrade.persistence import Trade
from freqtrade.persistence.llm_models import LLMDecision

# 查询最近的 LLM 决策
decisions = Trade.session.query(LLMDecision)\
    .order_by(LLMDecision.created_at.desc())\
    .limit(10).all()

for d in decisions:
    print(f"{d.pair} {d.decision_point}: {d.decision} (confidence: {d.confidence:.2f})")
```

### 2. Prometheus 指标

启动 exporter 来监控 LLM 使用：

```bash
cd exporter
python freqtrade_exporter.py --host 0.0.0.0 --port 9999
```

访问 `http://localhost:9999/metrics` 查看指标：

- `freqtrade_llm_total_calls` - 总调用次数
- `freqtrade_llm_success_rate` - 成功率
- `freqtrade_llm_total_cost_usd` - 累计成本
- `freqtrade_llm_entry_win_rate` - 入场决策胜率

### 3. Grafana 仪表板

导入 `exporter/grafana/freqtrade_dashboard.json` 到 Grafana 以可视化指标。

## 自定义策略

创建您自己的 LLM 策略：

```python
# user_data/strategies/MyLLMStrategy.py

from freqtrade.strategy.LLMStrategy import LLMStrategy
import talib.abstract as ta
import pandas as pd

class MyLLMStrategy(LLMStrategy):
    timeframe = "5m"
    stoploss = -0.10

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict):
        # 添加您的技术指标
        dataframe['rsi'] = ta.RSI(dataframe)
        dataframe['macd'] = ta.MACD(dataframe)['macd']
        # ... 更多指标

        return dataframe
```

## 自定义 Prompt 模板

编辑 `user_data/llm_prompts/entry.j2` 来自定义入场决策的 Prompt：

```jinja
You are a crypto trading expert. Based on these indicators:

## Technical Analysis
- RSI: {{ indicators.rsi }}
- MACD: {{ indicators.macd }}

## Your custom instructions here...

Respond in JSON:
{
    "decision": "buy" | "sell" | "hold",
    "confidence": 0.0-1.0,
    "reasoning": "why?",
    "parameters": {}
}
```

## 成本管理

### 预估成本

每次 LLM 调用的成本取决于模型和使用的 token 数量：

| 提供商 | 模型 | 预估成本/决策 |
|--------|------|---------------|
| OpenAI | GPT-4o | ~$0.005 |
| OpenAI | GPT-4o-mini | ~$0.0002 |
| Anthropic | Claude 3.5 Sonnet | ~$0.004 |
| Anthropic | Claude 3 Haiku | ~$0.0003 |
| Ollama | Llama 3 (本地) | $0 |

**月度成本估算**（假设每分钟 1 次决策）：
- GPT-4o: ~$216/月
- GPT-4o-mini: ~$8.6/月
- Claude Haiku: ~$13/月
- Ollama (本地): $0

### 降低成本的技巧

1. **使用缓存**：配置 `cache_ttl` 来复用相同上下文的决策
2. **选择便宜的模型**：GPT-4o-mini 或 Claude Haiku 性能不错且便宜
3. **使用本地模型**：Ollama + Llama 3 完全免费
4. **减少上下文**：`lookback_candles` 和 `include_indicators` 只包含必要的数据
5. **提高置信度阈值**：更高的 `confidence_threshold` 减少交易频率

## 常见问题

### Q: LLM 决策失败了怎么办？

A: 策略会自动使用 fallback 逻辑（可在策略中自定义）。检查日志中的错误信息。

### Q: 如何测试 LLM 集成是否正常工作？

A: 运行 dry-run 模式并监控日志，应该看到类似这样的消息：
```
LLM decision for BTC/USDT entry: buy (confidence: 0.85, latency: 850ms, cost: $0.0045)
```

### Q: 可以混合使用 LLM 和传统指标吗？

A: 可以！您可以只在某些决策点启用 LLM（如 entry），其他决策点使用传统逻辑。

### Q: LLM 延迟会影响交易吗？

A: LLM 响应通常需要 500-2000ms。使用缓存可以大大减少延迟。对于高频交易不太适合，但对于 5m-1h 时间框架很合适。

## 安全注意事项

1. **从 dry-run 开始**：始终先在 dry-run 模式下充分测试
2. **设置止损**：LLM 可能出错，务必配置 `stoploss`
3. **监控成本**：定期检查 `freqtrade_llm_total_cost_usd` 指标
4. **保护 API 密钥**：使用环境变量，不要提交到 git
5. **限制仓位**：`max_open_trades` 设置合理的限制

## 进阶用法

详细文档请参考：
- [完整设计文档](llm-strategy-design.md)
- [API 参考](../freqtrade/llm/)
- [示例策略](../user_data/strategies/ExampleLLMStrategy.py)

## 获取帮助

- GitHub Issues: https://github.com/freqtrade/freqtrade/issues
- Discord: https://discord.gg/freqtrade
- 文档: https://www.freqtrade.io/

祝交易顺利！🚀
