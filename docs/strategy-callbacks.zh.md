# 策略回调指南

除 `populate_indicators()`、`populate_entry_trend()`、`populate_exit_trend()` 等主要函数外，Freqtrade 还提供多种回调用于微调策略行为。回调会在特定时机触发，应尽量保持轻量化，避免耗时操作。以下为可用回调及注意事项。

!!! Tip "调用顺序"
    回调的触发顺序详见[机器人执行流程](bot-basics.md#bot-execution-logic)。

--8<-- "includes/strategy-imports.md"

## `bot_start()`

机器人初始化后调用一次，可用于加载外部资源或设定初始状态：

```python
class MyStrategy(IStrategy):
    def bot_start(self, **kwargs) -> None:
        if self.config["runmode"].value in ("live", "dry_run"):
            self.remote_data = requests.get("https://...")
```

在 Hyperopt 中仅启动时运行一次。

## `bot_loop_start()`

每次主循环开头调用（Dry/Live 模式约每 5 秒）。适合执行与交易对无关的操作，如缓存外部数据。

```python
def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
    if self.config["runmode"].value == "dry_run":
        self.remote_data = requests.get("https://...")
```

## `custom_stake_amount()`

在下单前触发，可自定义仓位金额：

```python
def custom_stake_amount(self, pair, current_time, current_rate,
                        proposed_stake, min_stake, max_stake,
                        leverage, entry_tag, side, **kwargs):
    if self.wallets.get_free('USDT') > 1000:
        return max_stake
    return proposed_stake
```

如抛出异常，系统会使用 `proposed_stake` 回退。

## `confirm_trade_entry()`

开仓前调用，返回 `True`/`False` 决定是否执行该信号。可用于过滤信号或调整订单类型。

```python
def confirm_trade_entry(self, pair, order_type, amount, rate,
                        time_in_force, current_time, entry_tag,
                        side, **kwargs):
    if entry_tag == "test" and side == "long":
        return False
    return True
```

## `custom_entry_price()` / `custom_exit_price()`

用于修改入场/平仓价格，常用于限价单微调。需要返回新的价格。

```python
def custom_entry_price(self, pair, current_time, proposed_rate, entry_tag, side, **kwargs):
    return proposed_rate * 0.999  # 优先以更低价格挂单
```

!!! Note
    若回调返回 `None`，将保持原价。

## `adjust_entry_price()` / `adjust_trade_position()`

* `adjust_entry_price()`：针对当前未成交的订单动态调整价格。
* `adjust_trade_position()`：管理加仓/减仓逻辑。

示例（平滑地跟随 EMA）：

```python
def adjust_entry_price(self, trade, order, pair, current_time, proposed_rate, current_order_rate,
                       entry_tag, side, **kwargs):
    dataframe, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)
    new_rate = dataframe.iloc[-1]["ema_50"]
    return new_rate
```

`adjust_trade_position()` 返回 `(amount, reason)`，可定制分批加仓策略。

## `custom_stoploss()`

每根蜡烛检查一次止损逻辑，可返回新的止损相对值（例如 `-0.02`）或 `None` 维持原值。

```python
def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
    if current_profit > 0.03:
        return -0.01
    return None
```

## `custom_exit()`

自定义平仓信号，返回 `(True, "exit_tag")` 表示立即平仓并写入原因。

```python
def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
    if current_profit > 0.05:
        return True, "take_profit"
    return False, None
```

## `custom_roi()`

可动态调整 ROI 表，以 `{分钟: 盈利比例}` 描述。例如在特定时间后收紧收益要求。

```python
def custom_roi(self, pair, trade, current_time, current_profit, current_profit_pct,
               entry_tag, **kwargs):
    return {"0": 0.03, "60": 0.01}
```

## `confirm_trade_exit()`

平仓前触发，可选择阻止平仓：

```python
def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                       current_time, exit_reason, side, **kwargs):
    if exit_reason == "roi" and trade.close_profit < 0.01:
        return False
    return True
```

## `check_entry_timeout()` / `check_exit_timeout()`

可自定义订单超时处理逻辑（默认依据 `unfilledtimeout`）。

```python
def check_entry_timeout(self, pair, trade, order, current_time, **kwargs):
    if current_time - order.time > timedelta(minutes=5):
        return True  # 取消订单
    return False
```

## `leverage()`

指定杠杆倍数（期货/保证金模式）：

```python
def leverage(self, pair, current_time, current_rate, proposed_leverage, max_leverage,
             side, **kwargs):
    return min(proposed_leverage, 3)
```

## `order_filled()`

订单成交时触发，可用于记录信息或更新内部状态。

```python
def order_filled(self, trade, order, pair, current_time, **kwargs):
    if order.ft_order_side == "entry":
        self.log("Entry filled for %s" % pair)
```

## 自定义数据存储

可使用 `trade.set_custom_data(key, value)` 保存自定义信息，并用 `get_custom_data()` 获取。适合记录加仓次数、入场类型等。

!!! Warning
    仅支持可序列化的数据类型（如 `int`、`float`、`str`、`bool`），避免存储大量数据造成数据库膨胀。

示例：

```python
count = trade.get_custom_data("entry_adjusts", default=0)
trade.set_custom_data("entry_adjusts", count + 1)
```

## 示例：信号过滤

利用多个回调调整策略流程：

```python
def custom_stake_amount(...):
    # 动态调整仓位

def confirm_trade_entry(...):
    # 过滤模拟信号

def custom_exit(...):
    # 条件平仓
```

## 注意事项

1. 回调执行频繁，请确保计算量足够轻。
2. 仅当策略确实需要时才实现回调。
3. 在回调内获取 DataFrame 时可使用 `self.dp.get_analyzed_dataframe()`。
4. 若回调涉及网络请求，需考虑失败重试或缓存机制。

更多高级用法可参考[高级策略篇](strategy-advanced.zh.md)。
