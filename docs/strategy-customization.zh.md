# 策略自定义指南

本文介绍如何自定义策略、添加指标以及设置交易规则。初次开发策略前，建议先阅读：

- [策略入门](strategy-101.md)：快速了解策略开发流程
- [机器人基础知识](bot-basics.md)：掌握机器人整体运行逻辑

## 创建策略模板

推荐通过命令生成模板：

```bash
freqtrade new-strategy --strategy AwesomeStrategy
```

此命令会在 `user_data/strategies/AwesomeStrategy.py` 创建名为 `AwesomeStrategy` 的策略。

!!! Note
    命令中的“策略名”指类名，而非文件名；大部命令均使用类名。

可选模板级别：

* `--template minimal`：仅保留基本结构
* `--template advanced`：包含所有回调与示例

## 策略结构

一个完整的策略通常包含以下部分：

- 蜡烛数据（OHLCV）
- 指标计算
- 入场逻辑
  - 信号
- 出场逻辑
  - 信号
  - `minimal_roi`
  - 自定义回调
- 止损
  - 固定止损
  - 追踪止损
  - 自定义回调
- 定价策略（可选）
- 仓位调整（可选）

默认示例策略 `SampleStrategy` 位于 `user_data/strategies/sample_strategy.py`。

策略执行模式包括：

- 回测
- Hyperopt
- Dry-run（前向测试）
- 真实交易
- FreqAI（独立文档）

**实际测试时务必先使用 Dry-run，以免造成损失。**

## DataFrame 与指标

Freqtrade 使用 pandas DataFrame 存储蜡烛数据。每行对应一根蜡烛，含 `date`、`open`、`high`、`low`、`close`、`volume` 等字段。

### 指标计算

在 `populate_indicators()` 中定义指标，示例：

```python
def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe["ema_short"] = ta.EMA(dataframe, timeperiod=12)
    dataframe["cci"] = ta.CCI(dataframe, timeperiod=20)
    return dataframe
```

### DataFrame 行使用技巧

常用方法包括：

* `dataframe.loc[condition, 'column'] = value`
* `dataframe['column'].shift(1)`
* `dataframe['column'].rolling(window).mean()`

避免使用 `for` 循环逐行处理，尽量采用矢量化操作。

## 入场信号

在 `populate_entry_trend()` 中设置入场逻辑，并向 `enter_long`（或 `enter_short`）赋值 1 即可生成信号：

```python
def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe.loc[
        (dataframe["ema_short"] > dataframe["ema_long"]) &
        (dataframe["volume"] > 0),
        "enter_long"
    ] = 1
    return dataframe
```

### 入场标签（`enter_tag`）

可通过 `enter_tag` 存储额外信息，用于回测分析或自定义回调：

```python
dataframe.loc[
    condition,
    ["enter_long", "enter_tag"]
] = (1, "ema_cross")
```

## 出场逻辑

出场包含以下机制：

1. `populate_exit_trend()` 中的信号（设定 `exit_long` 或 `exit_short`）。
2. `minimal_roi` 表定义的收益率门槛。
3. 止损（固定或追踪）。
4. 自定义回调 `custom_exit()`。

### Minimal ROI

`minimal_roi` 为时间-收益率映射（分钟 -> 比例）：

```json
"minimal_roi": {
    "0": 0.04,
    "30": 0.02,
    "60": 0.01
}
```

上述表示：

* 持仓达到 4% 收益即可立即平仓；
* 超过 30 分钟后可在 2% 平仓；
* 超过 60 分钟后在 1% 时平仓。

### 固定止损

在策略中定义 `stoploss`（相对比例）：

```python
stoploss = -0.1  # -10%
```

### 追踪止损

启用追踪止损：

```python
trailing_stop = True
trailing_stop_positive = 0.01
trailing_stop_positive_offset = 0.02
```

## 多周期与信息性交易对

可使用 `informative_pairs` 加载额外周期或其他交易对的数据。

示例：加载 1 小时周期并合并至主周期：

```python
informative_timeframe = "1h"

def informative_pairs(self):
    return [(pair, informative_timeframe) for pair in self.dp.current_whitelist()]

def populate_indicators(self, dataframe, metadata):
    informative = self.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=informative_timeframe)
    informative["ema_1h"] = ta.EMA(informative, timeperiod=24)
    dataframe = merge_informative_pair(dataframe, informative, self.timeframe, informative_timeframe)
    return dataframe
```

## 自定义回调

策略可覆写多种回调（详见 [strategy-callbacks](strategy-callbacks.zh.md)），例如：

* `custom_stake_amount()`：动态调整下单金额
* `custom_stoploss()`：自定义止损逻辑
* `custom_exit()`：自定义平仓逻辑
* `adjust_trade_position()`：分批加仓/减仓
* `leverage()`：设置杠杆

示例 `custom_stoploss()`：

```python
def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
    if current_profit > 0.05:
        return -0.02
    return None  # 保持原始止损
```

## 风险管理与仓位控制

### 最大持仓数

通过配置 `max_open_trades` 限制同时持仓数量。

### 每笔仓位金额

策略可覆写 `custom_stake_amount()` 实现动态仓位。例如：

```python
def custom_stake_amount(self, pair, current_time, current_rate,
                        proposed_stake, min_stake, max_stake,
                        leverage, entry_tag, side, **kwargs):
    if some_condition:
        return max_stake
    return proposed_stake
```

## 常见错误与调试

1. **前视偏差**：不要在 `populate_*` 中使用 `shift(-1)`、`iloc[-1]` 或 `.mean()`（需改用 `rolling()`）。可使用 `lookahead-analysis` 与 `recursive-analysis` 检测。
2. **信号冲突**：同一蜡烛若同时输出 `enter_long` 与 `exit_long` 等相互冲突信号，机器人会忽略入场。
3. **滞后指标**：注意指标滞后导致的迟滞，可结合多周期或自定义逻辑优化。

调试方法：

* `print(dataframe.tail())`：在 `populate_entry_trend()` 中输出末尾几行以检查数据。
* `freqtrade plot-dataframe`：可视化信号（详见 [plotting.zh.md](plotting.zh.md)）。
* `freqtrade backtesting`：快速验证策略行为。

## 策略继承与版本管理

策略可以继承父策略并覆盖部分属性或方法：

```python
class MyStrategyBase(IStrategy):
    stoploss = -0.1

class MyStrategyV2(MyStrategyBase):
    stoploss = -0.05
```

可实现 `version()` 方法用于自定义版本控制。建议配合 Git 等外部版本管理工具。

## 下一步

完成策略后，可继续阅读：

* [回测](backtesting.zh.md)
* [Hyperopt](hyperopt.zh.md)
* [高级策略技巧](strategy-advanced.zh.md)
