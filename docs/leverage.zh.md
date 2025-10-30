# 杠杆交易

!!! Warning "测试阶段功能"
    该功能仍处于测试阶段。如发现异常或疑似问题，请通过 Discord 或 GitHub Issue 告知我们。

!!! Note "同一账户不可运行多个机器人"
    杠杆 / 保证金交易模式下，Freqtrade 假设自己是账户唯一使用者，并基于此计算清算价。因此无法在同一账户上同时运行两个机器人。

!!! Danger "杠杆交易风险极高"
    若策略尚未在现货市场的真实运行中证明可持续盈利，请勿贸然使用杠杆 > 1。务必检查策略的止损设置：例如在 2 倍杠杆下，止损 0.5（50%）过于宽松，仓位会在触及该止损前被强制平仓。
    使用本软件或此模式造成的任何损失，Freqtrade 概不负责。

    只有在充分了解 Freqtrade 工作原理及策略细节的前提下，才应尝试高级交易模式。
    永远不要投入超过你承受能力的资金。

若你已有一套策略，需阅读[策略迁移指南](strategy_migration.md#strategy-migration-between-v2-and-v3)，将 freqtrade v2 策略迁移到可做空 / 交易合约的 v3 版本。

## 做空

当 [`trading_mode`](#理解-trading_mode) 为 `spot` 时无法做空。若需做空，需将 `trading_mode` 设为 `margin`（目前不可用）或 [`futures`](#期货)，并将 [`margin_mode`](#保证金模式) 设置为 [`cross`](#全仓模式) 或 [`isolated`](#逐仓模式)。

策略类还必须设置 `can_short = True` 才能触发做空信号。

如何设置做空的入场与退出信号，请参阅[策略自定义](strategy-customization.md#entry-signal-rules)。

## 理解 `trading_mode`

可选值：`spot`（默认）、`margin`（*当前不可用*）、`futures`。

### Spot

常规（低风险）模式，仅支持多头交易，无杠杆，无清算。当资产价格波动时，盈亏等于资产价格变动（扣除手续费）。

### 杠杆交易模式

杠杆意味着从交易所借入资金进行交易。借入的资金需全额偿还（可能包含利息），盈亏由你承担。

由于借入资金必须偿还，交易所在发现账户总资产跌至某个水平时会**强制平仓**（清算），以确保能顺利收回借出的资产，并会额外收取**清算手续费**。

因此，**若你不清楚杠杆交易的细节，请不要尝试。杠杆交易风险极高，资产价值可能在短时间内归零且无法挽回。**

#### Margin（当前不可用）

在现货市场中交易，但交易所按选择的杠杆倍数向你出借资产。交易完成后需连本带息归还，利润 / 亏损会被杠杆倍数放大。

#### Futures

永续合约（Perpetual Swap/Futures）是一种与基础资产价格紧密挂钩的衍生品，合约本身没有到期日。你交易的是合约而非实际资产。

除了价格波动带来的损益外，交易者之间还会交换**资金费率**，该费用取决于合约价格与标的资产之间的价差（不同交易所的计算方式不同）。

若要使用期货模式，需要将 `trading_mode` 设为 `futures`，并选择保证金模式（目前仅支持逐仓）：

```json
"trading_mode": "futures",
"margin_mode": "isolated"
```

##### 交易对命名

Freqtrade 遵循 [ccxt 的期货命名规范](https://docs.ccxt.com/#/README?id=perpetual-swap-perpetual-future)，格式为 `base/quote:settle`，例如 `ETH/USDT:USDT`。

### 保证金模式

除了 `trading_mode`，还需配置 `margin_mode`。当前仅支持逐仓，但建议你提前设置，以便后续更新时无缝切换。

可选值：`isolated`、`cross`。

#### 逐仓模式（Isolated）

每个交易对拥有独立的保证金账户：

```json
"margin_mode": "isolated"
```

#### 全仓模式（Cross）

所有交易对共享一个保证金账户，需要时从总余额中挪用保证金以避免被清算：

```json
"margin_mode": "cross"
```

请参阅[各交易所说明](exchanges.md)，了解哪些交易所支持全仓，以及它们的差异。

!!! Warning "提高被清算风险"
    全仓模式会提高账户整体的清算风险，因为所有仓位共用同一份保证金。一笔亏损会影响其他仓位的清算价格。
    此外，Dry-run 或回测模式下，仓位之间的交叉影响可能无法完全模拟。

## 设置杠杆

不同策略和风险偏好需要不同的杠杆倍数。除了在配置文件中设定固定杠杆，还可以使用[策略回调 `leverage()`](strategy-callbacks.md#leverage-callback) 动态调整（按交易对或其他条件）。

若未实现该回调，默认杠杆为 1（即不使用杠杆）。

!!! Warning
    杠杆越高，风险越大。务必完全理解杠杆的影响后再使用。

## 理解 `liquidation_buffer`

默认值 `0.05`。

该参数用于在清算价与止损价之间留出安全缓冲，避免仓位触及清算。人为设定的安全清算价计算方式如下：

```
freqtrade_liquidation_price = liquidation_price ± (abs(open_rate - liquidation_price) * liquidation_buffer)
```

* 对多头：`±` 取 `+`
* 对空头：`±` 取 `-`

可选值为 0.0 ~ 0.99 之间的浮点数。

**示例**：以 10 USDT 开仓，多头清算价为 8 USDT，若 `liquidation_buffer = 0.05`，则最小止损价为 `8 + ((10 - 8) * 0.05) = 8.1`。

!!! Danger "`liquidation_buffer` 设为 0.0 或过低将极易触发清算"
    目前 Freqtrade 能计算清算价，但不会计算清算手续费。若缓冲过小，仓位可能遭清算，且由于未纳入清算费用，机器人统计的盈亏将不准确。若你确实需要较低缓冲，建议在交易所支持的情况下启用 `stoploss_on_exchange`。

## 资金费率缺失

期货合约通常提供 K 线、标记价格和资金费率，但部分交易所可能缺失历史资金费率。这会导致回测在较早时间段报错 `No data found. Terminating.`。此时可在配置中添加 `futures_funding_rate`（详见 [configuration.md](configuration.md)），除非你非常确定资金费率值，否则建议设为 `0`。设置非零值会对策略中的收益计算（如 `custom_exit`、`custom_stoploss`）产生巨大影响。

!!! Warning "会导致回测不准确"
    该设置不会覆盖交易所已有的资金费率，但会让缺失资金费率的历史区间出现误差，回测结果因此不准确。

### 开发者说明

#### 保证金模式

* 做空：在平仓时需要买回用于支付利息的资产，因此平仓买入量会大于开仓卖出量。
* 做多：利息直接从用户现有资产扣除，不需要额外买入，在平仓时从 `close_value` 中扣除。
* 交易进行期间，所有手续费都会纳入 `current_profit` 计算。

#### 期货模式

资金费率会直接加减到交易总额中。
