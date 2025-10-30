# 交易对象（Trade Object）

## Trade

Freqtrade 每次开仓都会生成一个 `Trade` 对象，并将其持久化到数据库中。你会在策略回调等场景频繁接触到它。策略接收到的 `Trade` 对象不可直接修改，但可通过回调函数的返回值间接影响其状态。

## Trade 可用属性

下表列出 `Trade` 常用属性，可通过 `trade.<属性>` 访问（例如 `trade.pair`）。

| 属性 | 类型 | 说明 |
|------|------|------|
| `pair` | string | 交易对，例如 `BTC/USDT`。 |
| `safe_base_currency` | string | 向后兼容的基础货币。 |
| `safe_quote_currency` | string | 向后兼容的计价货币。 |
| `is_open` | bool | 交易是否仍在持仓中。 |
| `exchange` | string | 所使用的交易所。 |
| `open_rate` | float | 实际成交的开仓价格（若有加仓则为平均价格）。 |
| `open_rate_requested` | float | 下单时请求的开仓价格。 |
| `open_trade_value` | float | 开仓时的持仓价值（含手续费）。 |
| `close_rate` | float | 平仓价格，仅在 `is_open=False` 时存在。 |
| `close_rate_requested` | float | 下单时请求的平仓价格。 |
| `safe_close_rate` | float | 平仓价或请求价的安全值（若都无则为 0）。 |
| `stake_amount` | float | 投入的计价货币金额。 |
| `max_stake_amount` | float | 本交易使用的最大投入（所有入场订单之和）。 |
| `amount` | float | 当前持有的基础货币数量。初始下单未成交前为 0。 |
| `amount_requested` | float | 初始下单请求的数量。 |
| `open_date` | datetime | 开仓时间（建议使用 `open_date_utc`）。 |
| `open_date_utc` | datetime | 开仓时间（UTC）。 |
| `close_date` | datetime | 平仓时间（建议使用 `close_date_utc`）。 |
| `close_date_utc` | datetime | 平仓时间（UTC）。 |
| `close_profit` | float | 平仓时的相对收益，`0.01` 代表 1%。 |
| `close_profit_abs` | float | 平仓时的绝对收益（计价货币）。 |
| `realized_profit` | float | 已实现收益（计价货币），适用于部分止盈/止损。 |
| `leverage` | float | 使用的杠杆（现货默认为 1）。 |
| `enter_tag` | string | 入场时使用的标签。 |
| `exit_reason` | string | 平仓原因。 |
| `exit_order_status` | string | 平仓订单状态。 |
| `strategy` | string | 使用的策略名称。 |
| `timeframe` | int | 策略使用的时间周期。 |
| `is_short` | bool | 是否为空头仓位。 |
| `orders` | Order[] | 关联的订单列表（包括已成交与已取消）。 |
| `date_last_filled_utc` | datetime | 最后一次成交时间。 |
| `date_entry_fill_utc` | datetime | 首次入场成交时间。 |
| `entry_side` | "buy"/"sell" | 入场方向。 |
| `exit_side` | "buy"/"sell" | 平仓方向。 |
| `trade_direction` | "long"/"short" | 文字形式的仓位方向。 |
| `max_rate` | float | 交易期间的最高价（估算，可能不精确）。 |
| `min_rate` | float | 交易期间的最低价（估算，可能不精确）。 |
| `nr_of_successful_entries` | int | 成功（成交）的入场订单数。 |
| `nr_of_successful_exits` | int | 成功的平仓订单数。 |
| `has_open_position` | bool | 是否持有仓位（`amount > 0`）。 |
| `has_open_orders` | bool | 是否存在未完成的普通订单。 |
| `has_open_sl_orders` | bool | 是否存在未完成的止损订单。 |
| `open_orders` | Order[] | 当前未完成的普通订单。 |
| `open_sl_orders` | Order[] | 当前未完成的止损订单。 |
| `fully_canceled_entry_order_count` | int | 被完全取消的入场订单数。 |
| `canceled_exit_order_count` | int | 被取消的平仓订单数。 |

### 止损相关属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `stop_loss` | float | 当前止损绝对值。 |
| `stop_loss_pct` | float | 当前止损相对值。 |
| `initial_stop_loss` | float | 初始止损绝对值。 |
| `initial_stop_loss_pct` | float | 初始止损相对值。 |
| `stop_loss_ratio` | float | 当前止损相对于开仓价的比例。 |
| `initial_stop_loss_ratio` | float | 初始止损比例。 |

## Trade 对象基础用法

### 获取持仓中的交易

```python
from freqtrade.persistence import Trade

open_trades = Trade.get_trades([Trade.is_open.is_(True)])
```

### 获取特定交易

```python
trade = Trade.get_trades([Trade.id == trade_id]).first()
```

### 访问策略中的 Trade 属性

在策略回调中可直接使用传入的 `trade`：

```python
def custom_exit(..., trade: Trade, ...):
    if trade.enter_tag == "my_signal" and trade.close_profit > 0.02:
        return "exit_signal", None
```

## 类方法

`Trade` 提供多种类方法，便于策略或脚本获取统计数据：

* `get_total_closed_profit()`：总已平仓收益（计价货币）。
* `get_total_closed_percent()`：总已平仓收益率。
* `get_total_open_profit()`：当前未平仓收益（绝对值）。
* `total_open_trades_stakes()`：当前所有持仓使用的计价货币总额。
* `get_total_trade_volume()`：交易量统计（需交易所支持）。

示例：

```python
from freqtrade.persistence import Trade

profit = Trade.get_total_closed_profit()
```

!!! Note
    某些类方法在回测/Hyperopt 模式下不可用，请在调用前检查 `self.config['runmode']`。

## Order 对象

`Order` 表示交易所订单（Dry-run 时则为模拟订单），始终与某个 Trade 关联。

| 属性 | 类型 | 说明 |
|------|------|------|
| `trade` | Trade | 关联的交易。 |
| `ft_pair` | string | 订单交易对。 |
| `ft_is_open` | bool | 订单是否仍开着。 |
| `ft_order_side` | string | 订单方向（buy/sell/stoploss）。 |
| `ft_cancel_reason` | string | 取消原因。 |
| `ft_order_tag` | string | 自定义订单标签。 |
| `order_id` | string | 交易所订单 ID。 |
| `order_type` | string | 订单类型（市价/限价/止损等）。 |
| `status` | string | 订单状态（open/closed/canceled 等）。 |
| `side` | string | `buy` 或 `sell`。 |
| `price` | float | 下单价格。 |
| `average` | float | 成交均价。 |
| `amount` | float | 下单数量（基础货币）。 |
| `filled` | float | 已成交数量（建议使用 `safe_filled`）。 |
| `safe_filled` | float | 保证非空的成交数量。 |
| `safe_amount` | float | 保证非空的下单数量。 |
| `safe_price` | float | 价格的安全值（依次回落到 average/price/stop_price/ft_price）。 |
| `safe_placement_price` | float | 实际下单价格。 |
| `remaining` | float | 未成交数量（建议使用 `safe_remaining`）。 |
| `safe_remaining` | float | 保证非空的未成交数量。 |
| `safe_cost` | float | 订单成本（成交金额，保证非空）。 |
| `safe_fee_base` | float | 手续费（基础货币）。 |
| `safe_amount_after_fee` | float | 扣除手续费后的数量。 |
| `cost` | float | 订单成本（不同交易所或合约模式下含义可能不同）。 |
| `stop_price` | float | 止损（触发）价。 |
| `stake_amount` | float | 计价货币金额。 |
| `stake_amount_filled` | float | 实际成交的计价货币金额。 |
| `order_date` | datetime | 下单时间（建议用 `order_date_utc`）。 |
| `order_date_utc` | datetime | 下单时间（UTC）。 |
| `order_filled_date` | datetime | 成交时间（建议用 `order_filled_utc`）。 |
| `order_filled_utc` | datetime | 成交时间（UTC）。 |
| `order_update_date` | datetime | 最后更新时间。 |

在策略开发中，可通过 `trade.orders` 获取订单列表，进而判断是否需调整或取消订单。
