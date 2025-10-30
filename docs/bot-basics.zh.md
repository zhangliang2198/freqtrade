# Freqtrade 基础知识

本页介绍 Freqtrade 的基本概念以及它的运行方式。

## Freqtrade 术语

* **Strategy（策略）**：你的交易策略，告诉机器人该如何操作。
* **Trade（交易）**：已开仓的持仓。
* **Open Order（未完成订单）**：已经在交易所下单但尚未完全成交的订单。
* **Pair（交易对）**：可交易的货币对，一般格式为基币/计价币，例如现货的 `XRP/USDT`，期货的 `XRP/USDT:USDT`。
* **Timeframe（周期）**：蜡烛图时间周期，例如 `"5m"`、`"1h"` 等。
* **Indicators（指标）**：技术指标，如 SMA、EMA、RSI 等。
* **Limit order（限价单）**：在设定的限价或更优价格执行的订单。
* **Market order（市价单）**：保证成交，但可能因订单规模对价格产生冲击。
* **Current Profit（当前利润）**：该笔交易目前未实现的利润，是机器人和界面中主要使用的数值。
* **Realized Profit（已实现利润）**：已经实现的利润，仅在配合[部分平仓](strategy-callbacks.md#adjust-trade-position)时相关，该章节也解释了其计算逻辑。
* **Total Profit（总利润）**：已实现和未实现利润之和。相对利润（%）是以该笔交易的总投入计算的。

## 手续费处理

Freqtrade 的所有利润计算都包含手续费。对于回测、Hyperopt、模拟实盘（Dry-run）模式，将使用交易所的默认手续费（交易所最低费率档位）。实际运行时，使用交易所实际应用的费用（包括 BNB 折扣等）。

## 交易对命名

Freqtrade 遵循 [ccxt 的货币命名约定](https://docs.ccxt.com/#/README?id=consistency-of-base-and-quote-currencies)。
在错误的市场中使用错误的命名通常会导致机器人无法识别该交易对，并出现诸如 “this pair is not available” 之类的错误。

### 现货交易对命名

现货交易对命名格式为 `base/quote`，比如 `ETH/USDT`。

### 合约交易对命名

合约（期货/永续）交易对命名格式为 `base/quote:settle`，比如 `ETH/USDT:USDT`。

## 机器人执行逻辑

以 Dry-run 或实盘模式（`freqtrade trade`）启动 freqtrade 时，机器人会开始循环迭代，并执行回调 `bot_start()`。

默认情况下，机器人循环每隔几秒（`internals.process_throttle_secs`）运行一次，执行以下步骤：

* 从持久化存储中加载未结交易。
* 计算当前可交易的交易对列表。
* 下载交易对列表（包括所有[信息性交易对](strategy-customization.md#get-data-for-non-tradeable-pairs)）的 OHLCV 数据。  
  为避免不必要的网络流量，该步骤每根蜡烛只执行一次。
* 调用策略回调 `bot_loop_start()`。
* 对每个交易对执行策略分析。
  * 调用 `populate_indicators()`
  * 调用 `populate_entry_trend()`
  * 调用 `populate_exit_trend()`
* 更新未结订单的交易所状态。
  * 对已成交订单调用策略回调 `order_filled()`。
  * 检查未结订单的超时情况。
    * 对未结买入订单调用 `check_entry_timeout()` 策略回调。
    * 对未结卖出订单调用 `check_exit_timeout()` 策略回调。
    * 对未结订单调用 `adjust_order_price()` 策略回调。
      * 如果未实现 `adjust_order_price()`，则对未结买入单调用 `adjust_entry_price()` 策略回调。
      * 如果未实现 `adjust_order_price()`，则对未结卖出单调用 `adjust_exit_price()` 策略回调。
* 检查现有持仓并在需要时下达卖出订单。
  * 考虑止损、ROI、退出信号、`custom_exit()` 与 `custom_stoploss()`。
  * 基于 `exit_pricing` 配置或 `custom_exit_price()` 回调确定退出价格。
  * 在下达卖出订单之前，调用策略回调 `confirm_trade_exit()`。
* 若启用了持仓调整，则对未结交易调用 `adjust_trade_position()` 并在需要时下达追加订单。
* 检查交易名额是否仍有剩余（`max_open_trades` 是否已达到上限）。
* 检查入场信号并尝试开仓。
  * 基于 `entry_pricing` 配置或 `custom_entry_price()` 回调确定买入价格。
  * 在保证金与合约模式下，调用策略回调 `leverage()` 以确定所需杠杆。
  * 通过 `custom_stake_amount()` 回调确定下单金额。
  * 在下达买入订单之前，调用策略回调 `confirm_trade_entry()`。

该循环会持续重复，直到机器人被停止。

## 回测 / Hyperopt 执行逻辑

[回测](backtesting.md) 或 [Hyperopt](hyperopt.md) 仅执行上述逻辑的一部分，因为大部分交易操作都在完全模拟的环境中进行。

* 为配置的交易对列表加载历史数据。
* 调用一次 `bot_start()`。
* 计算指标（对每个交易对调用一次 `populate_indicators()`）。
* 计算买入/卖出信号（对每个交易对调用一次 `populate_entry_trend()` 与 `populate_exit_trend()`）。
* 在每根蜡烛上循环，模拟买卖过程。
  * 调用策略回调 `bot_loop_start()`。
  * 检查订单超时，使用 `unfilledtimeout` 配置或策略回调 `check_entry_timeout()` / `check_exit_timeout()`。
  * 对未结订单调用 `adjust_order_price()` 策略回调。
    * 如果未实现 `adjust_order_price()`，则对未结买入单调用 `adjust_entry_price()` 策略回调。
    * 如果未实现 `adjust_order_price()`，则对未结卖出单调用 `adjust_exit_price()` 策略回调。
  * 检查交易入场信号（`enter_long` / `enter_short` 列）。
  * 确认交易开仓/平仓（若策略中实现，则调用 `confirm_trade_entry()` 与 `confirm_trade_exit()`）。
  * 若策略实现了 `custom_entry_price()`，则调用它来确定买入价格（价格会被调整到开仓蜡烛范围内）。
  * 在保证金与合约模式下，调用策略回调 `leverage()` 以确定所需杠杆。
  * 通过 `custom_stake_amount()` 回调确定下单金额。
  * 若启用了持仓调整，则调用 `adjust_trade_position()` 判断是否需要追加订单。
  * 对已成交的买单调用策略回调 `order_filled()`。
  * 调用 `custom_stoploss()` 与 `custom_exit()` 查找自定义退出点。
  * 对基于退出信号、自定义退出和部分平仓的情况，调用 `custom_exit_price()` 确定卖出价格（价格会调整到平仓蜡烛范围内）。
  * 对已成交的卖单调用策略回调 `order_filled()`。
* 生成回测报告。

!!! Note
    回测与 Hyperopt 的计算都会包含交易所默认手续费。可以通过 `--fee` 参数为回测 / Hyperopt 指定自定义费率。

!!! Warning "回调调用频率"
    回测每根蜡烛最多调用一次各类回调（`--timeframe-detail` 会将频率调整为每根“细分蜡烛”一次）。
    实盘中大多数回调会在每次主循环迭代调用一次（通常约每 5 秒），这可能导致回测与实盘结果不一致。
