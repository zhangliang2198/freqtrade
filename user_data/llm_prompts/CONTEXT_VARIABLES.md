# LLM 上下文变量完整指南

本文档列出了所有可在 LLM 提示模板（Jinja2 模板）中使用的上下文变量。

## 📋 目录

1. [基础市场信息](#基础市场信息)
2. [账户信息](#账户信息-account-info)
3. [钱包信息](#钱包信息-wallet-info)
4. [持仓信息](#持仓信息-position-info)
5. [已平仓统计](#已平仓统计-closed-trades)
6. [技术指标](#技术指标)
7. [交易相关信息](#交易相关信息-仅-exit-adjust_position)
8. [配置控制](#配置控制)
9. [完整示例模板](#完整示例模板)

---

## 基础市场信息

所有决策点都可用的基础变量：

| 变量名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `pair` | string | 交易对名称 | "BTC/USDT" |
| `current_time` | string | 当前时间 | "2024-01-15 10:30:00" |
| `current_candle` | dict | 当前K线数据 | `{open: 50000, high: 51000, low: 49500, close: 50500, volume: 1234}` |
| `market_summary` | string | 市场概况文本 | "最近 100 根K线: bullish 趋势, +2.50% 变化, 1.23% 波动率" |
| `volatility` | float | 波动率百分比（仅 stake/leverage） | 1.23 |
| `indicators` | dict | 技术指标字典 | `{rsi: 65.5, ema_20: 50000, ...}` |
| `recent_candles` | list[dict] | 最近N根K线（如启用） | `[{open: ..., close: ...}, ...]` |

---

## 账户信息 (Account Info)

当启用账户分离模式时可用（`strategy_account.enabled: true`）：

| 变量名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `account_mode_enabled` | bool | 是否启用账户分离 | true |
| `account_long_initial` | float | 多头账户初始资金 | 5000.00 |
| `account_short_initial` | float | 空头账户初始资金 | 5000.00 |
| `account_long_available` | float | 多头账户可用余额 | 3500.00 |
| `account_short_available` | float | 空头账户可用余额 | 4200.00 |
| `account_long_used` | float | 多头账户已使用资金 | 1500.00 |
| `account_short_used` | float | 空头账户已使用资金 | 800.00 |

### 使用示例：

```jinja2
{% if account_mode_enabled %}
## 账户状态
- **多头账户**: {{ "%.2f"|format(account_long_available) }} / {{ "%.2f"|format(account_long_initial) }} USDT 可用
- **空头账户**: {{ "%.2f"|format(account_short_available) }} / {{ "%.2f"|format(account_short_initial) }} USDT 可用
- **多头使用率**: {{ "%.1f"|format(account_long_used / account_long_initial * 100) }}%
- **空头使用率**: {{ "%.1f"|format(account_short_used / account_short_initial * 100) }}%
{% endif %}
```

---

## 钱包信息 (Wallet Info)

始终可用的钱包余额信息：

| 变量名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `wallet_total_balance` | float | 钱包总余额 | 10000.00 |
| `wallet_free_balance` | float | 钱包可用余额 | 7500.00 |
| `wallet_used_balance` | float | 钱包已使用资金 | 2500.00 |
| `wallet_starting_balance` | float | 钱包初始余额 | 10000.00 |

### 使用示例：

```jinja2
## 钱包状态
- **总余额**: ${{ "%.2f"|format(wallet_total_balance) }}
- **可用**: ${{ "%.2f"|format(wallet_free_balance) }}
- **使用中**: ${{ "%.2f"|format(wallet_used_balance) }}
- **资金使用率**: {{ "%.1f"|format(wallet_used_balance / wallet_total_balance * 100) }}%
```

---

## 持仓信息 (Position Info)

详细的持仓统计和当前交易对持仓列表：

### 汇总统计

| 变量名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `positions_total_count` | int | 总持仓数量 | 5 |
| `positions_long_count` | int | 多头持仓数量 | 3 |
| `positions_short_count` | int | 空头持仓数量 | 2 |
| `positions_long_stake_total` | float | 多头总投入 | 1500.00 |
| `positions_short_stake_total` | float | 空头总投入 | 800.00 |
| `positions_long_profit_total` | float | 多头浮动盈亏总额 | 150.00 |
| `positions_short_profit_total` | float | 空头浮动盈亏总额 | -50.00 |
| `positions_long_profit_pct` | float | 多头浮动盈亏百分比 | 10.00 |
| `positions_short_profit_pct` | float | 空头浮动盈亏百分比 | -6.25 |
| `positions_at_risk_count` | int | 亏损持仓数量 | 2 |
| `positions_in_profit_count` | int | 盈利持仓数量 | 3 |
| `max_single_position_stake` | float | 最大单笔持仓金额 | 500.00 |
| `avg_position_stake` | float | 平均持仓金额 | 300.00 |

### 当前交易对持仓详情

`current_pair_positions` 是一个列表，包含当前交易对的所有持仓：

```python
current_pair_positions = [
    {
        "trade_id": 123,
        "pair": "BTC/USDT",
        "side": "long",
        "open_rate": 50000.0,
        "current_rate": 51000.0,
        "stake_amount": 500.0,
        "open_date": "2024-01-15 08:00:00",
        "holding_minutes": 150.0,
        "profit_abs": 10.0,
        "profit_pct": 2.0,
        "leverage": 1.0
    },
    ...
]
```

### 使用示例：

```jinja2
## 持仓概览
- **总持仓**: {{ positions_total_count }} 个 (多头: {{ positions_long_count }}, 空头: {{ positions_short_count }})
- **多头投入**: ${{ "%.2f"|format(positions_long_stake_total) }} (盈亏: {{ "%.2f"|format(positions_long_profit_pct) }}%)
- **空头投入**: ${{ "%.2f"|format(positions_short_stake_total) }} (盈亏: {{ "%.2f"|format(positions_short_profit_pct) }}%)

## 风险评估
- **盈利持仓**: {{ positions_in_profit_count }} / {{ positions_total_count }}
- **亏损持仓**: {{ positions_at_risk_count }} / {{ positions_total_count }}
{% if positions_total_count > 0 %}
- **最大单笔**: ${{ "%.2f"|format(max_single_position_stake) }} (占比{{ "%.1f"|format(max_single_position_stake / (positions_long_stake_total + positions_short_stake_total) * 100) }}%)
- **平均仓位**: ${{ "%.2f"|format(avg_position_stake) }}
{% endif %}

{% if current_pair_positions|length > 0 %}
## 当前交易对持仓
{% for pos in current_pair_positions %}
- **订单 #{{ pos.trade_id }}** ({{ pos.side|upper }})
  - 开仓价: ${{ "%.2f"|format(pos.open_rate) }}
  - 当前价: ${{ "%.2f"|format(pos.current_rate) }}
  - 投入: ${{ "%.2f"|format(pos.stake_amount) }}
  - 持有时长: {{ "%.0f"|format(pos.holding_minutes) }} 分钟
  - 盈亏: ${{ "%.2f"|format(pos.profit_abs) }} ({{ "%.2f"|format(pos.profit_pct) }}%)
  - 杠杆: {{ "%.1f"|format(pos.leverage) }}x
{% endfor %}
{% else %}
当前交易对无持仓
{% endif %}
```

---

## 已平仓统计 (Closed Trades)

历史交易统计信息：

| 变量名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `closed_trades_total` | int | 总平仓数量 | 50 |
| `closed_long_count` | int | 多头平仓数量 | 30 |
| `closed_short_count` | int | 空头平仓数量 | 20 |
| `closed_long_profit` | float | 多头已实现盈亏 | 500.00 |
| `closed_short_profit` | float | 空头已实现盈亏 | -150.00 |
| `closed_total_profit` | float | 总已实现盈亏 | 350.00 |

### 使用示例：

```jinja2
## 历史交易统计
- **已平仓**: {{ closed_trades_total }} 笔 (多头: {{ closed_long_count }}, 空头: {{ closed_short_count }})
- **多头累计盈亏**: ${{ "%.2f"|format(closed_long_profit) }}
- **空头累计盈亏**: ${{ "%.2f"|format(closed_short_profit) }}
- **总盈亏**: ${{ "%.2f"|format(closed_total_profit) }}
{% if closed_trades_total > 0 %}
- **平均每笔盈亏**: ${{ "%.2f"|format(closed_total_profit / closed_trades_total) }}
{% endif %}
```

---

## 技术指标

`indicators` 字典包含所有配置的技术指标，具体内容取决于策略的 `populate_indicators()` 实现。

### 常见指标示例：

```jinja2
{% if indicators %}
## 技术指标
- **RSI**: {{ "%.2f"|format(indicators.rsi) }}
- **MACD**: {{ "%.4f"|format(indicators.macd) }}
- **布林带上轨**: ${{ "%.2f"|format(indicators.bb_upper) }}
- **布林带下轨**: ${{ "%.2f"|format(indicators.bb_lower) }}
- **EMA(20)**: ${{ "%.2f"|format(indicators.ema_20) }}
- **成交量**: {{ "%.0f"|format(indicators.volume) }}
{% endif %}
```

### 自动检测所有指标：

配置文件中设置 `include_indicators: true` 将自动包含所有指标：

```yaml
llm_config:
  context:
    include_indicators: true  # 或者指定列表: ["rsi", "macd", "ema_20"]
```

---

## 交易相关信息 (仅 exit, adjust_position)

这些变量仅在 `exit` 和 `adjust_position` 决策点可用：

### 通用交易信息

| 变量名 | 类型 | 说明 | 决策点 |
|--------|------|------|--------|
| `side` | string | 持仓方向 ("long" 或 "short") | exit, adjust_position |
| `entry_price` | float | 入场价格 | exit, adjust_position |
| `current_price` | float | 当前价格 | exit, adjust_position |
| `current_rate` | float | 当前价格（同 current_price） | exit, adjust_position |
| `current_profit_pct` | float | 当前盈亏百分比 | exit, adjust_position |
| `current_profit_abs` | float | 当前盈亏绝对值 | exit, adjust_position |
| `holding_duration_minutes` | float | 持仓时长（分钟） | exit, adjust_position |
| `entry_tag` | string | 入场标签 | exit, adjust_position |
| `current_leverage` | float | 当前杠杆倍数 | exit, adjust_position |
| `max_leverage` | float | 最大允许杠杆 | exit, adjust_position |

### Exit 专用变量

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `stop_loss` | float | 止损价格 |
| `max_rate` | float | 最高价格 |
| `min_rate` | float | 最低价格 |
| `max_profit_pct` | float | 最高盈利百分比 |
| `drawdown_from_high_pct` | float | 从最高点的回撤百分比 |

### Adjust Position 专用变量

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `stake_amount` | float | 首次入场投入金额 |
| `entry_rate` | float | 首次入场价格 |
| `average_entry_rate` | float | 平均入场成本 |
| `profit_from_average_pct` | float | 相对平均成本的盈亏百分比 |
| `nr_of_entries` | int | 入场次数（包括首次和所有加仓） |
| `max_adjustments` | int | 最大允许调整次数（0=无限制） |
| `remaining_adjustments` | int | 剩余可调整次数 |
| `total_stake_amount` | float | 总投入金额（包括所有加仓） |
| `position_percent_of_account` | float | 该持仓占账户总资金的百分比 |
| `account_total_balance` | float | 账户总资金 |
| `min_stake_per_trade` | float | 最小开单额度（系统配置） |

### 调仓历史记录

`adjustment_history` 是一个列表，包含近期的所有调仓记录：

```python
adjustment_history = [
    {
        "action": "add",           # 或 "reduce"
        "price": 42300.0,          # 操作时价格
        "stake_amount": 500.0,     # 本次投入/减少金额
        "order_type": "limit",     # 订单类型
        "minutes_ago": 15.0        # 距离现在的分钟数
    },
    ...
]
```

### 使用示例：

```jinja2
{% if adjustment_history %}
## 近期调仓记录
{% for record in adjustment_history %}
**{{ loop.index }}.** {{ "%.0f"|format(record.minutes_ago) }}分钟前 |
**{{ record.action|upper }}** @ ${{ "%.6f"|format(record.price) }} |
投入${{ "%.2f"|format(record.stake_amount) }} | {{ record.order_type }}
{% endfor %}
**分析提示**: 该持仓经过{{ adjustment_history|length }}次调整。
{% endif %}
```

---

## 风险指标 (Risk Metrics)

当启用风险指标时（`include_risk_metrics: true`，默认启用），以下变量在 `exit` 和 `adjust_position` 决策点可用：

### 止损相关

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `stop_loss` | float | 当前止损价格 |
| `stop_loss_distance_pct` | float | 距离止损的百分比距离（正数=安全，负数=已触发） |
| `initial_stop_loss` | float | 初始止损价格 |
| `initial_stop_loss_pct` | float | 初始止损百分比（已乘100） |
| `is_stop_loss_trailing` | bool | 是否启用跟踪止损 |

### 清算相关（杠杆交易）

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `liquidation_price` | float | 清算价格 |
| `liquidation_distance_pct` | float | 距离清算价的百分比距离（正数=安全，负数=已清算） |
| `stoploss_or_liquidation` | float | 有效止损/清算价（更危险的那个） |

### 距离计算逻辑

**多头**:
- `stop_loss_distance_pct = (当前价 - 止损价) / 当前价 * 100`
- `liquidation_distance_pct = (当前价 - 清算价) / 当前价 * 100`

**空头**:
- `stop_loss_distance_pct = (止损价 - 当前价) / 当前价 * 100`
- `liquidation_distance_pct = (清算价 - 当前价) / 当前价 * 100`

**解读**:
- 正数 = 安全距离
- 负数 = 已触发止损或清算
- 距离越小，风险越高

### 使用示例：

```jinja2
## 风险指标
{%- if stop_loss %}
- **止损价**: ${{ "%.6f"|format(stop_loss) }} | **距止损**: {{ "%.2f"|format(stop_loss_distance_pct) }}%
{%- if initial_stop_loss %}
- **初始止损**: ${{ "%.6f"|format(initial_stop_loss) }} ({{ "%.2f"|format(initial_stop_loss_pct) }}%)
{%- endif %}
{%- if is_stop_loss_trailing %}
- **跟踪止损**: 已启用
{%- endif %}
{%- endif %}
{%- if liquidation_price %}
- **清算价**: ${{ "%.6f"|format(liquidation_price) }} | **距清算**: {{ "%.2f"|format(liquidation_distance_pct) }}%
- **有效止损/清算价**: ${{ "%.6f"|format(stoploss_or_liquidation) }}
{%- endif %}
```

---

## 技术指标（多周期支持）

### 主周期指标

`main_indicators` 字典包含主交易周期的所有技术指标：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `main_timeframe` | string | 主交易周期 (如 "5m", "15m") |
| `main_indicators` | dict | 主周期技术指标字典 |

### 信息周期指标

`informative_timeframes` 是一个列表，包含所有信息周期的指标：

```python
informative_timeframes = [
    {
        "timeframe": "15m",
        "indicators": {
            "rsi": 65.5,
            "macd": 0.0023,
            ...
        }
    },
    {
        "timeframe": "1h",
        "indicators": {...}
    }
]
```

### 原始K线数据

当启用 `include_raw_candles_in_summary: true` 时可用：

**主周期K线**:
```python
market_data = {
    "raw_candles": [
        {
            "date": "2025-11-14 10:00:00",
            "open": 42300.0,
            "high": 42450.0,
            "low": 42250.0,
            "close": 42400.0,
            "volume": 1250.0
        },
        ...
    ]
}
```

**信息周期K线**:
```python
informative_candles = {
    "15m": [
        {
            "date": "2025-11-14 09:45:00",
            "open": 42200.0,
            ...
        },
        ...
    ],
    "1h": [...]
}
```

### 使用示例：

```jinja2
{% if main_indicators %}
## 技术指标 ({{ main_timeframe }})
{% for key, value in main_indicators.items() -%}
- **{{ key }}**: {{ "%.4f"|format(value) if value is number else value }}
{% endfor -%}
{% endif -%}

{%- if informative_timeframes %}
{% for tf_data in informative_timeframes -%}
## 参考指标 ({{ tf_data.timeframe }})
{% for key, value in tf_data.indicators.items() -%}
- **{{ key }}**: {{ "%.4f"|format(value) if value is number else value }}
{% endfor %}
{% endfor -%}
{% endif -%}

{%- if market_data and market_data.raw_candles %}
## 原始K线数据 {{ timeframe }} (最近{{ market_data.raw_candles|length }}根)
{% for candle in market_data.raw_candles -%}
- **{{ candle.date }}**: {'open': {{ candle.open }}, 'high': {{ candle.high }}, 'low': {{ candle.low }}, 'close': {{ candle.close }}, 'volume': {{ candle.volume }}}
{% endfor -%}
{% endif -%}

{%- if informative_candles %}
{% for tf, candles in informative_candles.items() -%}
## 信息对K线数据 {{ tf }} (最近{{ candles|length }}根)
{% for candle in candles -%}
- **{{ candle.date }}**: {'open': {{ candle.open }}, 'high': {{ candle.high }}, 'low': {{ candle.low }}, 'close': {{ candle.close }}, 'volume': {{ candle.volume }}}
{% endfor -%}
{% endfor -%}
{% endif -%}
```

---

## Stake 和 Leverage 决策专用变量

### Stake 决策点

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `available_balance` | float | 可用余额 |
| `volatility` | float | 波动率百分比 |
| `stake_multiplier_limits` | dict | 仓位倍数限制 |

`stake_multiplier_limits` 结构：
```python
{
    "min": 0.5,  # 最小仓位倍数
    "max": 2.0   # 最大仓位倍数
}
```

**最大/最小额度信息**:
```python
max_stake_per_trade = {
    "description": "💰 最大开单额度",
    "mode": "percent" | "fixed",
    "percent_value": 10.0,  # 如果是百分比模式
    "available_balance": 5000.0,
    "max_stake_amount": 500.0
}

min_stake_per_trade = {
    "description": "📌 最小开单额度",
    "mode": "percent" | "fixed",
    "percent_value": 2.0,   # 如果是百分比模式
    "total_balance": 10000.0,
    "min_stake_amount": 100.0
}
```

### Leverage 决策点

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `proposed_leverage` | float | 建议的杠杆倍数 |
| `current_leverage` | float | 当前杠杆倍数 |
| `max_leverage` | float | 最大允许杠杆 |
| `leverage_limits` | dict | 杠杆限制 |
| `volatility` | float | 波动率百分比 |

`leverage_limits` 结构：
```python
{
    "min": 1.0,   # 最小杠杆
    "max": 20.0   # 最大杠杆
}
```

### 使用示例：

```jinja2
## Stake 决策框架
{% set stake_min = stake_multiplier_limits.min if stake_multiplier_limits and stake_multiplier_limits.min is not none else 0.5 %}
{% set stake_max = stake_multiplier_limits.max if stake_multiplier_limits and stake_multiplier_limits.max is not none else 2.0 %}

根据技术信号强度确定仓位倍数（{{ "%.1f"|format(stake_min) }}x - {{ "%.1f"|format(stake_max) }}x）

{% if max_stake_per_trade %}
{{ max_stake_per_trade.description }}
{% if max_stake_per_trade.mode == "percent" %}
- **模式**: 百分比 ({{ "%.0f"|format(max_stake_per_trade.percent_value) }}%)
- **当前可用**: ${{ "%.2f"|format(max_stake_per_trade.available_balance) }}
- **本单最大**: ${{ "%.2f"|format(max_stake_per_trade.max_stake_amount) }}
{% endif %}
{% endif %}

## Leverage 决策框架
{% set leverage_min = leverage_limits["min"] if leverage_limits and leverage_limits["min"] is not none else 1.0 %}
{% set leverage_max = leverage_limits["max"] if leverage_limits and leverage_limits["max"] is not none else max_leverage %}

根据技术信号和市场环境确定杠杆倍数（{{ "%.1f"|format(leverage_min) }}x - {{ "%.1f"|format(leverage_max) }}x）
- **建议杠杆**: {{ "%.1f"|format(proposed_leverage) }}x
- **波动率**: {{ "%.2f"|format(volatility) }}%
```

---

## 账户信息（Account Info）扩展

在账户分离模式下，还有以下附加变量：

| 变量名 | 类型 | 说明 |
|--------|------|------|
| `account_long_total` | float | 多头账户总价值（包括已用） |
| `account_short_total` | float | 空头账户总价值（包括已用） |

### 使用示例：

```jinja2
{% if account_mode_enabled %}
## 账户分离模式
- **多头账户**: 可用${{ "%.2f"|format(account_long_available) }} | 总计${{ "%.2f"|format(account_long_total or 0) }}
- **空头账户**: 可用${{ "%.2f"|format(account_short_available) }} | 总计${{ "%.2f"|format(account_short_total or 0) }}
- **账户总价值**: ${{ "%.2f"|format((account_long_total or 0) + (account_short_total or 0)) }}

{% set long_usage = account_long_used / account_long_initial if account_long_initial > 0 else 0 %}
{% set short_usage = account_short_used / account_short_initial if account_short_initial > 0 else 0 %}
- **多头使用率**: {{ "%.1f"|format(long_usage * 100) }}%
- **空头使用率**: {{ "%.1f"|format(short_usage * 100) }}%
{% endif %}
```

---

## 配置控制

在 `config.json` 的 `llm_config.context` 部分可以控制是否包含某些信息：

```json
{
  "llm_config": {
    "context": {
      "lookback_candles": 32,
      "include_indicators": true,
      "include_raw_candles_in_summary": true,
      "include_orderbook": false,
      "include_funding_rate": false,
      "include_portfolio_state": true,
      "include_account_info": true,
      "include_wallet_info": true,
      "include_positions_info": true,
      "include_closed_trades_info": true,
      "include_risk_metrics": true,
      "adjustment_history_limit": 999
    }
  }
}
```

### 配置项说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `lookback_candles` | int | 32 | 回看K线数量 |
| `include_indicators` | bool | true | 包含技术指标 |
| `include_raw_candles_in_summary` | bool | true | 包含原始K线数据 |
| `include_orderbook` | bool | false | 包含订单簿数据 |
| `include_funding_rate` | bool | false | 包含资金费率 |
| `include_portfolio_state` | bool | true | 包含投资组合状态 |
| `include_account_info` | bool | true | 包含账户信息 |
| `include_wallet_info` | bool | true | 包含钱包信息 |
| `include_positions_info` | bool | true | 包含持仓信息 |
| `include_closed_trades_info` | bool | true | 包含已平仓统计 |
| `include_risk_metrics` | bool | true | 包含风险指标（止损距离、清算距离） |
| `adjustment_history_limit` | int | 999 | 调仓历史记录最大数量 |

---

## 完整示例模板

### Entry 决策模板示例

```jinja2
您是一名专业的加密货币交易分析师。分析市场数据并决定是否入场。

## 市场信息
- **交易对**: {{ pair }}
- **当前时间**: {{ current_time }}
- **当前价格**: ${{ "%.4f"|format(current_candle.close) }}
- **24小时变化**: {{ "%.2f"|format((current_candle.close / current_candle.open - 1) * 100) }}%

## 技术指标
{% if indicators %}
{% for key, value in indicators.items() %}
- **{{ key }}**: {{ "%.4f"|format(value) if value is number else value }}
{% endfor %}
{% endif %}

## 资金状况
{% if account_mode_enabled %}
### 账户分离模式
- **多头账户可用**: ${{ "%.2f"|format(account_long_available) }} / ${{ "%.2f"|format(account_long_initial) }}
- **空头账户可用**: ${{ "%.2f"|format(account_short_available) }} / ${{ "%.2f"|format(account_short_initial) }}
- **多头使用率**: {{ "%.1f"|format(account_long_used / account_long_initial * 100) }}%
- **空头使用率**: {{ "%.1f"|format(account_short_used / account_short_initial * 100) }}%
{% else %}
- **钱包总余额**: ${{ "%.2f"|format(wallet_total_balance) }}
- **可用余额**: ${{ "%.2f"|format(wallet_free_balance) }}
- **资金使用率**: {{ "%.1f"|format(wallet_used_balance / wallet_total_balance * 100) }}%
{% endif %}

## 当前持仓
- **总持仓**: {{ positions_total_count }} 个 (多头: {{ positions_long_count }}, 空头: {{ positions_short_count }})
- **多头浮动盈亏**: ${{ "%.2f"|format(positions_long_profit_total) }} ({{ "%.2f"|format(positions_long_profit_pct) }}%)
- **空头浮动盈亏**: ${{ "%.2f"|format(positions_short_profit_total) }} ({{ "%.2f"|format(positions_short_profit_pct) }}%)

{% if current_pair_positions|length > 0 %}
### 该交易对已有持仓
{% for pos in current_pair_positions %}
- **订单 #{{ pos.trade_id }}** ({{ pos.side|upper }}):
  开仓 ${{ "%.2f"|format(pos.open_rate) }},
  现价 ${{ "%.2f"|format(pos.current_rate) }},
  盈亏 {{ "%.2f"|format(pos.profit_pct) }}%
{% endfor %}
{% endif %}

## 历史表现
- **已平仓**: {{ closed_trades_total }} 笔
- **累计盈亏**: ${{ "%.2f"|format(closed_total_profit) }}
{% if closed_trades_total > 0 %}
- **平均每笔**: ${{ "%.2f"|format(closed_total_profit / closed_trades_total) }}
{% endif %}

## 您的任务
基于以上信息，决定是否：
1. **买入** - 开多头仓位
2. **卖出** - 开空头仓位
3. **观望** - 不入场

**重要考虑因素**:
- 当前资金使用率和风险敞口
- 该交易对是否已有持仓
- 技术指标信号强度
- 历史表现和账户健康度

**响应格式**（仅JSON）：
```json
{
    "decision": "buy" | "sell" | "hold",
    "confidence": 0.0-1.0,
    "reasoning": "简要说明为何做此决策，考虑资金状况和持仓情况",
    "parameters": {}
}
```
```

### Exit 决策模板示例

```jinja2
您是一名专业的加密货币交易分析师。分析当前持仓并决定是否退出。

## 当前持仓信息
- **交易对**: {{ pair }}
- **入场价格**: ${{ "%.4f"|format(entry_price) }}
- **当前价格**: ${{ "%.4f"|format(current_price) }}
- **盈亏**: ${{ "%.2f"|format(current_profit_abs) }} ({{ "%.2f"|format(current_profit_pct) }}%)
- **持有时长**: {{ "%.0f"|format(holding_duration_minutes) }} 分钟 ({{ "%.1f"|format(holding_duration_minutes / 60) }} 小时)
- **止损价**: ${{ "%.4f"|format(stop_loss) }}
{% if max_rate %}
- **最高价**: ${{ "%.4f"|format(max_rate) }} (回撤: {{ "%.2f"|format((max_rate - current_price) / max_rate * 100) }}%)
{% endif %}

## 资金状况
- **钱包可用**: ${{ "%.2f"|format(wallet_free_balance) }}
- **总持仓数**: {{ positions_total_count }} 个
- **多头持仓盈亏**: {{ "%.2f"|format(positions_long_profit_pct) }}%
- **空头持仓盈亏**: {{ "%.2f"|format(positions_short_profit_pct) }}%

## 技术指标
{% if indicators %}
{% for key, value in indicators.items() %}
- **{{ key }}**: {{ "%.4f"|format(value) if value is number else value }}
{% endfor %}
{% endif %}

## 您的任务
决定是否退出当前持仓。

**考虑因素**:
- 当前盈亏和目标盈利
- 技术指标是否显示趋势反转
- 持仓时长和机会成本
- 整体持仓表现和风险管理

**响应格式**（仅JSON）：
```json
{
    "decision": "exit" | "hold",
    "confidence": 0.0-1.0,
    "reasoning": "简要说明退出或持有的理由",
    "parameters": {}
}
```
```

---

## 变量速查表

### 按决策点分类

| 决策点 | 可用变量组 |
|--------|-----------|
| `entry` | 基础市场 + 账户 + 钱包 + 持仓 + 已平仓 + 技术指标 + K线数据 |
| `exit` | 基础市场 + 账户 + 钱包 + 持仓 + 已平仓 + 技术指标 + K线数据 + 交易信息 + **风险指标** |
| `stake` | 基础市场 + 账户 + 钱包 + 持仓 + 已平仓 + 技术指标 + K线数据 + 波动率 + 额度限制 |
| `adjust_position` | 基础市场 + 账户 + 钱包 + 持仓 + 已平仓 + 技术指标 + K线数据 + 交易信息 + **风险指标** + **调仓历史** |
| `leverage` | 基础市场 + 账户 + 钱包 + 持仓 + 已平仓 + 技术指标 + K线数据 + 波动率 + 杠杆限制 |

### 关键变量快速索引

**基础信息**:
- `pair`, `timeframe`, `current_time`, `current_candle`, `market_summary`

**价格和盈亏**:
- `current_price` / `current_rate`, `entry_price` / `entry_rate`
- `current_profit_pct`, `current_profit_abs`
- `average_entry_rate`, `profit_from_average_pct`

**风险指标** (⭐ 新增):
- `stop_loss`, `stop_loss_distance_pct`, `initial_stop_loss`
- `liquidation_price`, `liquidation_distance_pct`
- `stoploss_or_liquidation`, `is_stop_loss_trailing`

**调仓相关**:
- `nr_of_entries`, `max_adjustments`, `remaining_adjustments`
- `stake_amount`, `total_stake_amount`
- `adjustment_history`, `position_percent_of_account`
- `min_stake_per_trade`

**账户和资金**:
- `wallet_total_balance`, `wallet_free_balance`, `wallet_used_balance`
- `account_long_available`, `account_short_available`
- `account_long_used`, `account_short_used`

**持仓统计**:
- `positions_total_count`, `positions_long_count`, `positions_short_count`
- `positions_in_profit_count`, `positions_at_risk_count`
- `positions_long_profit_pct`, `positions_short_profit_pct`
- `current_pair_positions`, `max_single_position_stake`, `avg_position_stake`

**技术指标**:
- `main_timeframe`, `main_indicators`
- `informative_timeframes`, `informative_candles`
- `market_data.raw_candles`

**杠杆和仓位**:
- `current_leverage`, `max_leverage`, `proposed_leverage`
- `leverage_limits`, `stake_multiplier_limits`
- `volatility`, `available_balance`

---

## 最佳实践

1. **风险管理**: 在模板中强调资金使用率，避免过度集中
   ```jinja2
   {% if wallet_used_balance / wallet_total_balance > 0.8 %}
   ⚠️ 警告: 资金使用率已超过 80%，建议谨慎开仓
   {% endif %}
   ```

2. **持仓检查**: 避免同一交易对过度持仓
   ```jinja2
   {% if current_pair_positions|length >= 3 %}
   ⚠️ 该交易对已有 {{ current_pair_positions|length }} 个持仓，避免过度集中
   {% endif %}
   ```

3. **账户平衡**: 提醒 LLM 保持多空账户平衡
   ```jinja2
   {% if account_mode_enabled %}
   {% set long_usage = account_long_used / account_long_initial %}
   {% set short_usage = account_short_used / account_short_initial %}
   {% if long_usage > short_usage + 0.3 %}
   提示: 多头账户使用率 ({{ "%.1f"|format(long_usage * 100) }}%) 显著高于空头账户
   {% endif %}
   {% endif %}
   ```

4. **历史表现**: 参考历史盈亏调整策略
   ```jinja2
   {% if closed_trades_total > 10 %}
   {% set avg_profit = closed_total_profit / closed_trades_total %}
   历史平均每笔盈亏: ${{ "%.2f"|format(avg_profit) }}
   {% endif %}
   ```

---

## 常见问题

**Q: 如何禁用某些信息以减少 token 消耗？**

A: 在配置文件中设置对应的 `include_*` 选项为 `false`：
```json
{
  "llm_config": {
    "context": {
      "include_positions_info": false,
      "include_closed_trades_info": false
    }
  }
}
```

**Q: `current_pair_positions` 为空是什么情况？**

A: 表示当前交易对没有任何持仓（多头或空头都没有）。

**Q: 账户信息为什么都是 0？**

A: 可能未启用账户分离模式，请检查配置：
```json
{
  "strategy_account": {
    "enabled": true,
    "long_initial_balance": 5000,
    "short_initial_balance": 5000
  }
}
```

**Q: 如何在模板中进行条件判断？**

A: 使用 Jinja2 语法：
```jinja2
{% if positions_total_count > 10 %}
持仓过多，建议谨慎开仓
{% elif positions_total_count == 0 %}
当前无持仓，可以考虑入场
{% endif %}
```

---

## 更新日志

- **v1.2** (2025-11-14):
  - ⭐ **重大更新**: 添加风险指标系统 (`include_risk_metrics`)
    - 止损相关: `stop_loss`, `stop_loss_distance_pct`, `initial_stop_loss`, `initial_stop_loss_pct`, `is_stop_loss_trailing`
    - 清算相关: `liquidation_price`, `liquidation_distance_pct`, `stoploss_or_liquidation`
  - 添加调仓历史记录 `adjustment_history`
  - 添加调仓专用变量: `average_entry_rate`, `profit_from_average_pct`, `total_stake_amount`, `position_percent_of_account`, `min_stake_per_trade`
  - 添加技术指标多周期支持: `main_timeframe`, `main_indicators`, `informative_timeframes`, `informative_candles`
  - 添加原始K线数据: `market_data.raw_candles`
  - 添加 Stake/Leverage 专用变量: `stake_multiplier_limits`, `leverage_limits`, `max_stake_per_trade`, `min_stake_per_trade`
  - 完善配置控制选项文档
  - 添加关键变量快速索引

- **v1.1** (2024-06):
  - 添加 `current_leverage`, `max_leverage` 杠杆相关变量
  - 添加 `max_rate`, `min_rate` 最高/最低价
  - 完善持仓信息结构

- **v1.0** (2024-01):
  - 初始版本，添加账户、钱包、持仓、已平仓统计的细粒度变量
