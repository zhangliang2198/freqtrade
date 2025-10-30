## 订单使用的价格

常规订单的价格可以通过参数结构 `entry_pricing`（用于交易入场）和 `exit_pricing`（用于交易出场）进行控制。
价格始终在下订单之前检索，要么通过查询交易所行情，要么通过使用订单簿数据。

!!! Note
    Freqtrade 使用的订单簿数据是通过 ccxt 的函数 `fetch_order_book()` 从交易所检索的数据，即通常是来自 L2 聚合订单簿的数据，而行情数据是 ccxt 的 `fetch_ticker()`/`fetch_tickers()` 函数返回的结构。有关更多详细信息，请参考 ccxt 库[文档](https://github.com/ccxt/ccxt/wiki/Manual#market-data)。

!!! Warning "使用市价订单"
    使用市价订单时，请阅读[市价订单定价](#市价订单定价)部分。

### 入场价格

#### 入场价格侧

配置设置 `entry_pricing.price_side` 定义机器人在买入时查看订单簿的哪一侧。

以下显示了一个订单簿。

``` explanation
...
103
102
101  # ask
-------------当前价差
99   # bid
98
97
...
```

如果 `entry_pricing.price_side` 设置为 `"bid"`，那么机器人将使用 99 作为入场价格。
同样，如果 `entry_pricing.price_side` 设置为 `"ask"`，那么机器人将使用 101 作为入场价格。

根据订单方向（_long_/_short_），这将导致不同的结果。因此，我们建议为此配置使用 `"same"` 或 `"other"`。
这将导致以下定价矩阵：

| 方向 | 订单 | 设置 | 价格 | 跨越价差 |
|------ |--------|-----|-----|-----|
| long  | buy  | ask   | 101 | yes |
| long  | buy  | bid   | 99  | no  |
| long  | buy  | same  | 99  | no  |
| long  | buy  | other | 101 | yes |
| short | sell | ask   | 101 | no  |
| short | sell | bid   | 99  | yes |
| short | sell | same  | 101 | no  |
| short | sell | other | 99  | yes |

使用订单簿的另一侧通常保证更快地成交订单，但机器人也可能最终支付比必要更多的费用。
即使使用限价买入订单，也很可能会应用吃单费而不是挂单费。
此外，价差"另一"侧的价格高于订单簿中"bid"侧的价格，因此订单的行为类似于市价订单（但有最高价格）。

#### 启用订单簿的入场价格

当启用订单簿进入交易时（`entry_pricing.use_order_book=True`），Freqtrade 从订单簿中获取 `entry_pricing.order_book_top` 条目，并使用配置侧（`entry_pricing.price_side`）的订单簿中指定为 `entry_pricing.order_book_top` 的条目。1 指定订单簿中最上面的条目，而 2 将使用订单簿中的第 2 个条目，依此类推。

#### 未启用订单簿的入场价格

以下部分使用 `side` 作为配置的 `entry_pricing.price_side`（默认为 `"same"`）。

当不使用订单簿时（`entry_pricing.use_order_book=False`），如果行情中最佳的 `side` 价格低于行情中最后交易的 `last` 价格，Freqtrade 会使用该价格。否则（当 `side` 价格高于 `last` 价格时），它会根据 `entry_pricing.price_last_balance` 计算 `side` 和 `last` 价格之间的利率。

`entry_pricing.price_last_balance` 配置参数控制此行为。值为 `0.0` 将使用 `side` 价格，而 `1.0` 将使用 `last` 价格，介于两者之间的值将在 ask 和 last 价格之间进行插值。

#### 检查市场深度

当启用检查市场深度（`entry_pricing.check_depth_of_market.enabled=True`）时，入场信号会根据每个订单簿侧的订单簿深度（所有金额的总和）进行过滤。

然后将订单簿 `bid`（买入）侧深度除以订单簿 `ask`（卖出）侧深度，并将结果 delta 与 `entry_pricing.check_depth_of_market.bids_to_ask_delta` 参数的值进行比较。只有当订单簿 delta 大于或等于配置的 delta 值时，才会执行入场订单。

!!! Note
    delta 值低于 1 意味着 `ask`（卖出）订单簿侧深度大于 `bid`（买入）订单簿侧的深度，而值大于 1 意味着相反（买入侧的深度高于卖出侧的深度）。

### 出场价格

#### 出场价格侧

配置设置 `exit_pricing.price_side` 定义机器人在退出交易时查看价差的哪一侧。

以下显示了一个订单簿：

``` explanation
...
103
102
101  # ask
-------------当前价差
99   # bid
98
97
...
```

如果 `exit_pricing.price_side` 设置为 `"ask"`，那么机器人将使用 101 作为退出价格。
同样，如果 `exit_pricing.price_side` 设置为 `"bid"`，那么机器人将使用 99 作为退出价格。

根据订单方向（_long_/_short_），这将导致不同的结果。因此，我们建议为此配置使用 `"same"` 或 `"other"`。
这将导致以下定价矩阵：

| 方向 | 订单 | 设置 | 价格 | 跨越价差 |
|------ |--------|-----|-----|-----|
| long  | sell | ask   | 101 | no  |
| long  | sell | bid   | 99  | yes |
| long  | sell | same  | 101 | no  |
| long  | sell | other | 99  | yes |
| short | buy  | ask   | 101 | yes |
| short | buy  | bid   | 99  | no  |
| short | buy  | same  | 99  | no  |
| short | buy  | other | 101 | yes |

#### 启用订单簿的出场价格

当启用订单簿退出时（`exit_pricing.use_order_book=True`），Freqtrade 在订单簿中获取 `exit_pricing.order_book_top` 条目，并使用配置侧（`exit_pricing.price_side`）中指定为 `exit_pricing.order_book_top` 的条目作为交易退出价格。

1 指定订单簿中最上面的条目，而 2 将使用订单簿中的第 2 个条目，依此类推。

#### 未启用订单簿的出场价格

以下部分使用 `side` 作为配置的 `exit_pricing.price_side`（默认为 `"ask"`）。

当不使用订单簿时（`exit_pricing.use_order_book=False`），如果行情中最佳的 `side` 价格高于行情中最后交易的 `last` 价格，Freqtrade 会使用该价格。否则（当 `side` 价格低于 `last` 价格时），它会根据 `exit_pricing.price_last_balance` 计算 `side` 和 `last` 价格之间的利率。

`exit_pricing.price_last_balance` 配置参数控制此行为。值为 `0.0` 将使用 `side` 价格，而 `1.0` 将使用 last 价格，介于两者之间的值将在 `side` 和 last 价格之间进行插值。

### 市价订单定价

使用市价订单时，应将价格配置为使用订单簿的"正确"侧，以允许实际的价格检测。
假设入场和出场都使用市价订单，必须使用类似于以下的配置

``` jsonc
  "order_types": {
    "entry": "market",
    "exit": "market"
    // ...
  },
  "entry_pricing": {
    "price_side": "other",
    // ...
  },
  "exit_pricing":{
    "price_side": "other",
    // ...
  },
```

显然，如果只有一侧使用限价订单，则可以使用不同的定价组合。
