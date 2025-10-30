# Freqtrade 策略入门 101

本文旨在帮助你快速上手策略开发。默认你已经了解交易基础，并读过 [Freqtrade 基础](bot-basics.md)。

## 基础概念

* **策略**：一个 Python 类，定义入场与出场逻辑。
* **交易对（Pair）**：组合了交易资产（币种）与计价货币（stake）。
* **蜡烛数据（Candles）**：由 `date`、`open`、`high`、`low`、`close`、`volume` 六项组成。
* **技术指标（Indicators）**：对蜡烛数据进行计算得到的二次数据。
* **信号（Signals）**：基于指标分析得出的入场/出场触发条件。
* **订单（Order）/交易（Trade）**：策略依据信号在交易所执行的实际操作。

Freqtrade 支持 **多头（long）** 与 **空头（short）** 两种方向：

- 多头：使用计价货币买入资产，价格上涨时卖出获利。
- 空头：借入资产卖出，价格下跌后买入归还获利（需杠杆/合约支持）。

本文聚焦现货多头，帮助你快速建立策略基础。

## 策略结构概览

### DataFrame

策略以 pandas DataFrame 存储数据，每行代表一根蜡烛，列包括：`date`、`open`、`high`、`low`、`close`、`volume` 等。每个交易对拥有独立 DataFrame，索引为时间。

### 指标计算

`populate_indicators` 函数用于向 DataFrame 添加指标，如 RSI、布林带等：

```python
def populate_indicators(self, dataframe, metadata):
    dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
    return dataframe
```

### 入场/出场信号

* `populate_entry_trend`：设置 `enter_long`/`enter_short` 列为 1 表示发出入场信号。
* `populate_exit_trend`：设置 `exit_long`/`exit_short` 列为 1 表示发出出场信号。

示例：

```python
dataframe.loc[
    (dataframe["rsi"] < 30),
    "enter_long"
] = 1
```

## 简单示例

```python
class MyStrategy(IStrategy):
    timeframe = "15m"
    stoploss = -0.10
    minimal_roi = {"0": 0.01}

    def populate_indicators(self, dataframe, metadata):
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[dataframe["rsi"] < 30, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[dataframe["rsi"] > 70, "exit_long"] = 1
        return dataframe
```

执行逻辑：

1. EMA、RSI 等指标计算写入 DataFrame；
2. 当 `enter_long` 为 1 时，机器人尝试开仓；
3. `exit_long` 为 1 时，机器人尝试平仓；
4. `minimal_roi`、`stoploss` 等会自动在回测/实时中生效。

## 调仓与风险

默认每笔交易使用配置中的 `stake_amount`，最多同时持有 `max_open_trades` 笔。可通过 `custom_stake_amount()` 回调动调仓位。

例：分散仓位：

```python
def custom_stake_amount(self, pair, current_time, current_rate,
                        proposed_stake, min_stake, max_stake,
                        leverage, entry_tag, side, **kwargs):
    return self.wallets.get_total_stake_amount() / self.config["max_open_trades"]
```

## 多时间框架与信息性交易对

可通过 `informative_pairs` 加载其他时间框架或交易对数据，并用 `merge_informative_pair` 合并，构建更复杂的策略结构。

## 策略测试流程

1. **回测**：使用历史数据检验策略表现。
2. **Dry-run**：模拟实时，检验策略与回测结果是否一致。
3. **实盘**：仅在前两步验证充分后进行。

!!! Warning
    回测假设所有订单都会成交，实际可能因为滑点、成交量等因素导致差异。请务必进行 Dry-run 验证。

## 策略监控

Freqtrade 提供多种运行监控方式：

- [FreqUI](freq-ui.md)：Web 界面查看持仓/回测。
- [Telegram](telegram-usage.zh.md)：推送与控制接口。
- [REST API](rest-api.md)：自定义程序调用。
- [Webhooks](webhook-config.zh.md)：推送至第三方（如 Discord）。

日志默认输出到终端，可使用 `--logfile` 写入文件。

## 常用命令

- `freqtrade backtesting`：运行回测。
- `freqtrade trade --dry-run`：开启 Dry-run。
- `freqtrade plot-dataframe`：绘制信号图。
- `freqtrade list-strategies`：查看可用策略列表。

## 常见问题与排查

* 策略回测表现亮眼但 Dry-run 表现平平？检查是否存在 [前视偏差](lookahead-analysis.zh.md) 或指标准确性问题。
* 多信号冲突：同一时间设定多个互斥信号时，策略可能无法执行入场。
* 计算量大：信号计算耗时过长会造成延迟，需适当减少交易对或优化指标。

## 下一步

基础策略搭建完成后，可继续阅读：

- [策略自定义](strategy-customization.zh.md)
- [策略回调](strategy-callbacks.zh.md)
- [高级策略技巧](strategy-advanced.zh.md)

在深入开发前，务必多次回测与 Dry-run，确保策略逻辑稳健。祝你策略开发顺利！ 🎯
