## 保护机制

保护机制可以在出现异常事件或特定市场状况时，临时停止交易（针对单一交易对或所有交易对）。所有保护的结束时间都会向上取整到下一根蜡烛，以避免蜡烛内部出现意外买入。

!!! Tip "使用建议"
    并非所有保护都适用于每个策略，参数需要根据策略调校以获得最佳效果。每种保护可以配置多次，以实现短期/长期等多层防护。

!!! Note "回测"
    回测与 Hyperopt 支持保护机制，但必须通过命令行参数 `--enable-protections` 显式开启。

### 可用保护

* [`StoplossGuard`](#stoploss-guard)：在一定时间窗口内触发指定次数的止损时暂停交易。
* [`MaxDrawdown`](#maxdrawdown)：达到最大回撤阈值时暂停交易。
* [`LowProfitPairs`](#low-profit-pairs)：锁定近期收益不佳的交易对。
* [`CooldownPeriod`](#cooldown-period)：平仓后进入冷却期，短时间内不再入场。

### 通用参数

| 参数 | 说明 |
|------|------|
| `method` | 使用的保护名称（参考上表）。 |
| `stop_duration_candles` / `stop_duration` | 锁定持续时间（蜡烛数或分钟，不可同时使用）。 |
| `lookback_period_candles` / `lookback_period` | 回溯时间范围（蜡烛数或分钟，部分保护可能忽略）。 |
| `trade_limit` | 至少满足的交易次数（部分保护使用）。 |
| `unlock_at` | 指定时间自动解锁（格式 `HH:MM`）。 |

!!! Note "时间单位"
    以上持续时间或回溯区间可根据需求设置为“蜡烛数”或“分钟”。示例以蜡烛数为主，方便在不同时间框架下调参。

#### Stoploss Guard

在最近 `lookback_period` 内若出现 `trade_limit` 次止损，暂停交易 `stop_duration`。默认针对所有交易对，可通过 `only_per_pair` 限制为单个交易对，或在期货模式下通过 `only_per_side` 仅锁定多头/空头方向。`required_profit` 可设定止损的最小亏损阈值（默认 0，即任何亏损都生效）。

```python
@property
def protections(self):
    return [{
        "method": "StoplossGuard",
        "lookback_period_candles": 24,
        "trade_limit": 4,
        "stop_duration_candles": 4,
        "required_profit": 0.0,
        "only_per_pair": False,
        "only_per_side": False
    }]
```

#### MaxDrawdown

在设定窗口内统计累计回撤，若超过 `max_allowed_drawdown`，暂停交易 `stop_duration`。常用于在连续亏损后让市场“冷静”一段时间。

```python
@property
def protections(self):
    return [{
        "method": "MaxDrawdown",
        "lookback_period_candles": 48,
        "trade_limit": 20,
        "stop_duration_candles": 12,
        "max_allowed_drawdown": 0.2
    }]
```

#### Low Profit Pairs

按交易对统计近期整体收益率，若低于 `required_profit`，锁定该交易对一段时间。期货模式下同样支持 `only_per_side` 分方向锁定。

```python
@property
def protections(self):
    return [{
        "method": "LowProfitPairs",
        "lookback_period_candles": 6,
        "trade_limit": 2,
        "stop_duration": 60,
        "required_profit": 0.02,
        "only_per_pair": False
    }]
```

#### Cooldown Period

平仓后进入冷却期，防止同一交易对在短时间内反复入场。

```python
@property
def protections(self):
    return [{
        "method": "CooldownPeriod",
        "stop_duration_candles": 2
    }]
```

!!! Note
    冷却保护仅作用于单一交易对，不会全局锁定；也不依赖 `lookback_period`。

### 综合示例

以下为 1 小时时间框架的综合配置：

```python
class AwesomeStrategy(IStrategy):
    timeframe = "1h"

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 5},
            {"method": "MaxDrawdown", "lookback_period_candles": 48,
             "trade_limit": 20, "stop_duration_candles": 4, "max_allowed_drawdown": 0.2},
            {"method": "StoplossGuard", "lookback_period_candles": 24,
             "trade_limit": 4, "stop_duration_candles": 2, "only_per_pair": False},
            {"method": "LowProfitPairs", "lookback_period_candles": 6,
             "trade_limit": 2, "stop_duration_candles": 60, "required_profit": 0.02},
            {"method": "LowProfitPairs", "lookback_period_candles": 24,
             "trade_limit": 4, "stop_duration_candles": 2, "required_profit": 0.01}
        ]
```

以上配置依序执行，形成由短至长的防护墙，帮助策略抵御极端行情。
