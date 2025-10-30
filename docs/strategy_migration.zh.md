# 策略从 V2 迁移到 V3 指南

为支持杠杆/做空等新交易模式，策略接口做了调整。如果你计划使用非现货市场，请参考本指南迁移至新格式。现货用户暂时可继续沿用旧接口，但建议尽早升级。

## 快速检查清单

> 以下仅列出核心差异，详情请阅读对应章节。

- 命名变化：
  - `populate_buy_trend()` → `populate_entry_trend()`
  - `populate_sell_trend()` → `populate_exit_trend()`
  - `custom_sell()` → `custom_exit()`
  - `check_buy_timeout()` → `check_entry_timeout()`
  - `check_sell_timeout()` → `check_exit_timeout()`
  - `buy` / `sell` 列 → `enter_long` / `exit_long`
  - 新增 `enter_short`、`exit_short`
  - `buy_tag` → `enter_tag`（兼容多空）
- 回调新增参数 `side`（无 trade 对象时）：
  - `custom_stake_amount`
  - `confirm_trade_entry`
  - `custom_entry_price`
- `confirm_trade_exit` 参数改名
- Trade 对象新增/调整字段：
  - 新增 `is_short`、`entry_side`、`exit_side`、`trade_direction`
  - `sell_reason` → `exit_reason`
  - `nr_of_successful_buys` → `nr_of_successful_entries`
- 新增 `leverage()` 回调
- 信息性交易对（informative pairs）元组支持第三个元素标记蜡烛类型；`@informative` 装饰器新增 `candle_type`
- `stoploss_from_open/absolute` 辅助函数增加 `is_short` 参数
- `INTERFACE_VERSION` 应设为 3
- 配置项重命名：
  - `bid_strategy` / `ask_strategy` → `entry_pricing` / `exit_pricing`
  - `use_sell_signal` 等均调整为 `exit` 前缀（详见配置章节）
- 远程接口、Webhook、Telegram 等术语同步更新
- 命令名称：`forcebuy`、`forcesell` 等改为 `force_entry`、`force_exit`

## 详细说明

### `populate_entry_trend` / `populate_exit_trend`

将 `buy` 列改为 `enter_long`，`sell` 改为 `exit_long`，并更名函数：

```python
def populate_entry_trend(...):
    dataframe.loc[condition, ["enter_long", "enter_tag"]] = (1, "signal")
```

若策略需要做空，请新增 `enter_short`、`exit_short` 列。

### Fallback 回调 & 参数

所有回调（如 `custom_stake_amount`）在期货模式下新增 `side` 参数，以区分多/空逻辑：

```python
def custom_stake_amount(..., side: str, **kwargs):
    if side == "short": ...
```

### Trade 对象

迁移后可通过以下新字段判断仓位方向：

```python
trade.is_short      # 是否空头
trade.entry_side    # "buy" / "sell"
trade.exit_side
trade.trade_direction  # "long" / "short"
```

`trade.nr_of_successful_entries` 取代旧字段，保持回调一致性。

### `adjust_trade_position()` 更名字段

若使用 `nr_of_successful_buys`，请改为 `nr_of_successful_entries`。

### Leveraged 回调

新增 `leverage()` 用于返回杠杆倍数：

```python
def leverage(self, pair, current_time, current_rate, proposed_leverage,
             max_leverage, side, **kwargs):
    return min(proposed_leverage, 3)
```

### 信息性交易对

Informative pair 元组现在可包含第三个参数指定蜡烛类型（如 `CandleType.FUTURES`）。`@informative` 装饰器也支持 `candle_type` 关键字。

### 辅助函数

`stoploss_from_open()`、`stoploss_from_absolute()` 需传入 `is_short`，以正确计算止损。

### `INTERFACE_VERSION`

在策略中显式设置：

```python
INTERFACE_VERSION = 3
```

### 策略/配置重命名

- `order_time_in_force`：
  ```json
  "order_time_in_force": {"entry": "GTC", "exit": "GTC"}
  ```
- `order_types`、`unfilledtimeout`、`ignore_roi_if_entry_signal` 等均需改为 `entry`/`exit` 命名空间
- `entry_pricing`/`exit_pricing` 替代原 `bid_strategy`/`ask_strategy`

### Terminology 变化

| 旧术语 | 新术语 |
|--------|--------|
| buy / sell | entry / exit |
| forcebuy / forcesell | force_entry / force_exit |
| emergency_sell | emergency_exit |
| custom_sell | custom_exit |
| sell_profit_only | exit_profit_only |
| sell_profit_offset | exit_profit_offset |
| use_sell_signal | use_exit_signal |
| ignore_roi_if_buy_signal | ignore_roi_if_entry_signal |

Webhook、Telegram 通知等也同步采用 entry/exit 术语。

### 示例：配置文件

```json
"order_types": {
  "entry": "limit",
  "exit": "limit",
  "stoploss": "market"
},
"unfilledtimeout": {
  "entry": {"enabled": true, "timeout": 10},
  "exit": {"enabled": true, "timeout": 10}
}
```

### 迁移流程建议

1. 更新策略文件的函数、字段、命名空间；
2. 设置 `INTERFACE_VERSION = 3`；
3. 使用 `freqtrade strategy-updater` 辅助转换（记得审查结果）；
4. 执行回测、Dry-run 验证结果；
5. 若使用 FreqAI、自定义模型，参照文档迁移标签、管线等逻辑。

### FreqAI 相关调整

若策略定义了 `set_freqai_targets()`，需将目标列名称从 `#s-` 更改为 `&-xxx`。同时 FreqAI 数据管线需要改用 `define_data_pipeline()` 与 `define_label_pipeline()`。

### 其它注意事项

- 自定义回调中引用的卖出理由需改用 `exit_reason`
- FreqAI 模型基线或自定义数据清洗函数已统一到新管线
- `trade.nr_of_successful_buys`、`buy_tag` 等旧字段请全面替换

## 小结

迁移至 V3 主要涉及：

* 统一 entry/exit 命名
* 支持多空方向及杠杆回调
* 调整配置项命名
* 补齐 Trade 对象字段

完成上述修改后，即可充分利用做空、杠杆等新特性。迁移结束后，务必重新回测/ Dry-run，确认策略行为与预期一致。
