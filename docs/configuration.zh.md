# 配置机器人

Freqtrade 拥有大量可配置的功能与选项。默认情况下，它们通过配置文件进行管理（见下文）。

## Freqtrade 配置文件

机器人在运行过程中会使用一组配置参数，这些参数共同构成机器人的配置。通常它会从一个配置文件（Freqtrade 配置文件）读取这些设置。

默认情况下，机器人会从当前工作目录下的 `config.json` 文件加载配置。

你可以使用 `-c/--config` 命令行选项指定机器人应使用的其他配置文件。

如果你使用的是[快速上手](docker_quickstart.md#docker-quick-start)（Quick start）方法来安装机器人，那么安装脚本应该已经为你创建好了默认配置文件（`config.json`）。

若未生成默认配置文件，建议运行 `freqtrade new-config --config user_data/config.json` 来生成一个基础配置。

Freqtrade 配置文件采用 JSON 格式。

除标准 JSON 语法外，配置文件还支持单行注释 `// ...`、多行注释 `/* ... */`，以及列表末尾的尾随逗号。

如果你不熟悉 JSON 格式也无需担心——使用任意文本编辑器打开配置文件，修改需要的参数后保存，再重启机器人（或在停止后重新运行）即可。机器人会在启动时验证配置文件语法，若存在错误会标明问题所在的行。

### 环境变量

你可以通过环境变量设置 Freqtrade 配置中的选项，该方式优先级高于配置文件或策略中的同名值。

环境变量必须以前缀 `FREQTRADE__` 开头才会被加载到 Freqtrade 配置中。

`__` 用作层级分隔符，因此格式应为 `FREQTRADE__{section}__{key}`。例如，`export FREQTRADE__STAKE_AMOUNT=200` 会在配置中生成 `{stake_amount: 200}`。

更进一步的例子是 `export FREQTRADE__EXCHANGE__KEY=<yourExchangeKey>`，用于将交易所 API Key 保存在环境变量中。该值会被写入配置的 `exchange.key` 字段。借助这种机制，所有配置项都可以通过环境变量覆盖。

请注意，环境变量会覆盖配置文件中的对应值，但命令行参数的优先级永远最高。

常见示例：

``` bash
FREQTRADE__TELEGRAM__CHAT_ID=<telegramchatid>
FREQTRADE__TELEGRAM__TOKEN=<telegramToken>
FREQTRADE__EXCHANGE__KEY=<yourExchangeKey>
FREQTRADE__EXCHANGE__SECRET=<yourExchangeSecret>
```

JSON 列表会以 JSON 方式解析，因此可以像下面这样设置交易对列表：

``` bash
export FREQTRADE__EXCHANGE__PAIR_WHITELIST='["BTC/USDT", "ETH/USDT"]'
```

!!! Note
    检测到的环境变量会在启动时写入日志。如果你发现某个值与预期不符，请确认是否被环境变量覆盖。

!!! Tip "验证合并结果"
    可以使用 [show-config 子命令](utils.md#show-config) 查看最终合并后的配置。

??? Warning "加载顺序"
    环境变量在初始配置文件加载之后才会被应用，因此无法通过环境变量提供配置文件路径。若需指定配置文件，请使用 `--config path/to/config.json`。  
    对 `user_dir` 也部分适用此规则。尽管可以通过环境变量设置用户目录，但配置文件不会自动从该位置加载。

### 多个配置文件

机器人可以指定多个配置文件，也可以从标准输入读取配置。

你可以在 `add_config_files` 字段中列出额外的配置文件。这些文件会按照列出的顺序加载，并与初始配置合并。路径相对于最初加载的配置文件解析。  
这与同时传递多个 `--config` 参数类似，但使用上更简单，因为无需在每个命令中重复所有文件。

!!! Tip "验证合并结果"
    可以使用 [show-config 子命令](utils.md#show-config) 查看最终合并后的配置。

!!! Tip "通过多个配置文件保护私密信息"
    你可以把敏感信息放在第二个配置文件中。这样既能共享“主”配置文件，又能保护自己的 API Key。  
    第二个文件只需包含希望覆盖的字段。  
    如果同一个键在多个文件中出现，则“最后指定的配置文件”具有最高优先级（上述示例中即 `config-private.json`）。

    对于一次性命令，你也可以使用下述语法，通过多个 `--config` 参数传入同样的文件：

    ``` bash
    freqtrade trade --config user_data/config1.json --config user_data/config-private.json <...>
    ```

    如果 `add_config_files` 中包含多个文件，它们会被视为处于同级，后出现者会覆盖先前的配置（除非更高层级已经定义该键）。

## 编辑器自动完成与校验

如果你的编辑器支持 JSON Schema，可以在配置文件顶部添加下列语句来启用 Freqtrade 提供的 schema，从而获得自动补全与校验功能：

``` json
{
    "$schema": "https://schema.freqtrade.io/schema.json",
}
```

??? Note "开发版 Schema"
    开发分支对应的 schema 位于 `https://schema.freqtrade.io/schema_dev.json`。不过为获得更稳定的体验，推荐使用稳定版 schema。

## 配置参数

下表列出了当前可用的所有配置参数。

许多选项也可以通过命令行（CLI）参数设置。可使用各命令的 `--help` 查看详情。

### 配置项优先级

各选项的生效优先级如下（自上而下）：

* CLI 参数覆盖所有其他设置
* [环境变量](#environment-variables)
* 配置文件按照加载顺序依次覆盖（后加载者优先），并覆盖策略中的同名设置
* 策略中定义的参数仅在配置文件和命令行未设置时生效。下表中带有 [Strategy Override](#parameters-in-the-strategy) 标记的选项可在策略内设置。

### 参数表

必填参数以 **Required** 标识，表示必须通过某种方式设定。

|  参数 | 说明 |
|------------|-------------|
| `max_open_trades` | **Required.** 允许同时持有的最大仓位数量。每个交易对最多只能开一单，因此交易对白名单长度也会限制可用仓位数。若设为 -1，则忽略该限制（理论上可开无限仓位，仍受交易对列表限制）。[更多说明](#configuring-amount-per-trade)。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 正整数或 -1 |
| `stake_currency` | **Required.** 交易所使用的计价货币。<br> **Datatype:** 字符串 |
| `stake_amount` | **Required.** 每笔交易投入的计价货币数量。设置为 `"unlimited"` 可使用全部可用余额。[更多说明](#configuring-amount-per-trade)。<br> **Datatype:** 正浮点数或 `"unlimited"` |
| `tradable_balance_ratio` | 机器人可用于交易的账户余额比例。[更多说明](#configuring-amount-per-trade)。<br>*默认 `0.99`（99%）。*<br> **Datatype:** 介于 `0.1` 与 `1.0` 的正浮点数 |
| `available_capital` | 机器人可用的初始资金。适用于在同一交易所账户上运行多个机器人。[更多说明](#configuring-amount-per-trade)。<br> **Datatype:** 正浮点数 |
| `amend_last_stake_amount` | 若有需要，允许最后一笔仓位使用减少后的下单金额。[更多说明](#configuring-amount-per-trade)。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `last_stake_amount_min_ratio` | 定义调整后最后一笔下单金额的下限。当 `amend_last_stake_amount` 为 `true` 时生效。[更多说明](#configuring-amount-per-trade)。<br>*默认 `0.5`。*<br> **Datatype:** 浮点数（比例） |
| `amount_reserve_percent` | 计算最小下单金额时预留的额外比例。机器人会在最小下单额基础上额外预留 `amount_reserve_percent` 与止损金额，避免订单被拒。<br>*默认 `0.05`（5%）。*<br> **Datatype:** 正浮点数（比例） |
| `timeframe` | 使用的时间周期（例如 `1m`、`5m`、`15m`、`30m`、`1h` 等）。通常不在配置文件中设置，而是在策略中声明。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 字符串 |
| `fiat_display_currency` | 用于显示盈亏的法币。[更多说明](#what-values-can-be-used-for-fiat_display_currency)。<br> **Datatype:** 字符串 |
| `dry_run` | **Required.** 指定机器人是否运行在 Dry-run（模拟）模式。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| `dry_run_wallet` | Dry-run 模式下模拟钱包的初始计价货币余额。[更多说明](#dry-run-wallet)。<br>*默认 `1000`。*<br> **Datatype:** 浮点数或字典 |
| `cancel_open_orders_on_exit` | 当收到 `/stop` 命令、按下 `Ctrl+C` 或机器人意外退出时自动取消未完成订单（不影响已开的仓位）。在市场剧烈波动时，可以借助 `/stop` 取消未成交及部分成交订单以规避风险。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `process_only_new_candles` | 仅在出现新蜡烛时处理指标。如果设为 `false`，每次循环都会重新计算指标，即便是同一根蜡烛，这虽然增加系统负载，但当策略依赖于更细粒度的行情变化时可能有用。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| `minimal_roi` | **Required.** 设置机器人平仓所需的最低收益阈值（比例）。[更多说明](#understand-minimal_roi)。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 字典 |
| `stoploss` | **Required.** 止损线（比例）。详见[止损文档](stoploss.md)。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 浮点数（比例） |
| `trailing_stop` | 启用追踪止损（以配置或策略中的 `stoploss` 为基础）。详见[止损文档](stoploss.md#trailing-stop-loss)。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 布尔值 |
| `trailing_stop_positive` | 在达到一定收益后调整止损。详见[止损文档](stoploss.md#trailing-stop-loss-different-positive-loss)。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 浮点数 |
| `trailing_stop_positive_offset` | 应用 `trailing_stop_positive` 的收益偏移阈值，应设为正数。详见[止损文档](stoploss.md#trailing-stop-loss-only-once-the-trade-has-reached-a-certain-offset)。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `0.0`（无偏移）。*<br> **Datatype:** 浮点数 |
| `trailing_only_offset_is_reached` | 仅当达到偏移阈值时才启用追踪止损。详见[止损文档](stoploss.md)。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `fee` | 回测、Dry-run 时使用的手续费。通常无需设置，缺省会使用交易所默认费率。手续费以比例表示（如 0.001 = 0.1%），买卖各计一次。<br> **Datatype:** 浮点数（比例） |
| `futures_funding_rate` | 当交易所无法提供历史资金费率时使用的备用费率。不会覆盖真实历史数据。除非明确需要测试某个币种并理解资金费率对频交易收益的影响，否则建议保持为 0。[详情](leverage.md#unavailable-funding-rates)。<br>*默认 `None`。*<br> **Datatype:** 浮点数 |
| `trading_mode` | 指定交易模式（现货、杠杆或衍生品）。详见[杠杆文档](leverage.md)。<br>*默认 `"spot"`。*<br> **Datatype:** 字符串 |
| `margin_mode` | 在杠杆交易中，定义保证金为全仓还是逐仓。详见[杠杆文档](leverage.md)。<br> **Datatype:** 字符串 |
| `liquidation_buffer` | 设置在强平价与止损价之间预留的安全缓冲比例，以避免触及强平。详见[杠杆文档](leverage.md)。<br>*默认 `0.05`。*<br> **Datatype:** 浮点数 |
| | **未成交订单超时** |
| `unfilledtimeout.entry` | **Required.** 未成交买单的超时时间（分钟或秒）。超时后取消订单。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 整数 |
| `unfilledtimeout.exit` | **Required.** 未成交卖单的超时时间（分钟或秒）。超时后取消订单，并在仍有信号时按最新价格重新下单。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 整数 |
| `unfilledtimeout.unit` | `unfilledtimeout` 的时间单位。注意：若设置为 `"seconds"`，则 `internals.process_throttle_secs` 必须小于或等于该值。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `"minutes"`。*<br> **Datatype:** 字符串 |
| `unfilledtimeout.exit_timeout_count` | 允许卖单超时的次数。达到该次数后触发紧急平仓。设为 0 表示无限次取消。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `0`。*<br> **Datatype:** 整数 |
| | **定价** |
| `entry_pricing.price_side` | 选择用于获取买入价格的报价方。[更多说明](#entry-price)。<br>*默认 `"same"`。*<br> **Datatype:** 字符串（`ask`、`bid`、`same` 或 `other`） |
| `entry_pricing.price_last_balance` | **Required.** 使用最新价与订单薄平衡值插值买入价格。[更多说明](#entry-price-without-orderbook-enabled)。 |
| `entry_pricing.use_order_book` | 启用基于订单薄的买入定价。[更多说明](#entry-price-with-orderbook-enabled)。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| `entry_pricing.order_book_top` | 买入时在订单薄 `price_side` 的前 N 档中择价。例如值为 2 表示可选择第二档报价。[更多说明](#entry-price-with-orderbook-enabled)。<br>*默认 `1`。*<br> **Datatype:** 正整数 |
| `entry_pricing. check_depth_of_market.enabled` | 若买单与卖单数量差距达到设定阈值，则拒绝开仓。[检查市场深度](#check-depth-of-market)。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `entry_pricing. check_depth_of_market.bids_to_ask_delta` | 买卖单数量差的比例。小于 1 表示卖单较多，大于 1 表示买单较多。[检查市场深度](#check-depth-of-market)。<br>*默认 `0`。*<br> **Datatype:** 浮点数（比例） |
| `exit_pricing.price_side` | 选择用于获取卖出价格的报价方。[更多说明](#exit-price-side)。<br>*默认 `"same"`。*<br> **Datatype:** 字符串（`ask`、`bid`、`same` 或 `other`） |
| `exit_pricing.price_last_balance` | 使用最新价与订单薄平衡值插值卖出价格。[更多说明](#exit-price-without-orderbook-enabled)。 |
| `exit_pricing.use_order_book` | 启用基于订单薄的卖出定价。[更多说明](#exit-price-with-orderbook-enabled)。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| `exit_pricing.order_book_top` | 卖出时在订单薄 `price_side` 的前 N 档中择价。例如值为 2 表示可选第二档卖价。[更多说明](#exit-price-with-orderbook-enabled)。<br>*默认 `1`。*<br> **Datatype:** 正整数 |
| `custom_price_max_distance_ratio` | 限制自定义价格与当前价格的最大偏离比例。<br>*默认 `0.02`（2%）。*<br> **Datatype:** 正浮点数 |
| | **订单/信号处理** |
| `use_exit_signal` | 结合策略产生的离场信号与 `minimal_roi` 一同判断卖出。若设为 `false`，则禁用 `"exit_long"` 与 `"exit_short"` 列。对其他离场方式（止损、ROI、回调）无影响。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| `exit_profit_only` | 在达到 `exit_profit_offset` 之前不执行离场信号。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `exit_profit_offset` | 当 `exit_profit_only=True` 时，仅在收益超过该值才允许离场。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `0.0`。*<br> **Datatype:** 浮点数（比例） |
| `ignore_roi_if_entry_signal` | 如果买入信号仍然有效，则不依据 ROI 退出。该设置优先于 `minimal_roi` 与 `use_exit_signal`。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `ignore_buying_expired_candle_after` | 指定买入信号失效前允许的秒数。<br> **Datatype:** 整数 |
| `order_types` | 根据不同操作（`"entry"`、`"exit"`、`"stoploss"`、`"stoploss_on_exchange"` 等）配置订单类型。[更多说明](#understand-order_types)。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 字典 |
| `order_time_in_force` | 配置买入、卖出订单的有效期策略。详见[相关章节](#understand-order_time_in_force)。[Strategy Override](#parameters-in-the-strategy)。<br> **Datatype:** 字典 |
| `position_adjustment_enable` | 启用策略的仓位调整能力（追加买入或卖出）。[更多说明](strategy-callbacks.md#adjust-trade-position)。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `max_entry_position_adjustment` | 单笔交易允许追加的最大订单数，设为 `-1` 表示无限制。[更多说明](strategy-callbacks.md#adjust-trade-position)。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `-1`。*<br> **Datatype:** 正整数或 -1 |
| | **交易所** |
| `exchange.name` | **Required.** 使用的交易所名称。<br> **Datatype:** 字符串 |
| `exchange.key` | 交易所 API Key，仅在实盘模式需要。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `exchange.secret` | 交易所 API Secret，仅在实盘模式需要。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `exchange.password` | 部分交易所要求的 API 密码，仅在实盘模式需要。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `exchange.uid` | 部分交易所要求的 UID，仅在实盘模式需要。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `exchange.pair_whitelist` | 交易及回测时使用的交易对列表。支持 `.*/BTC` 形式的正则表达式。VolumePairList 不使用此项。[更多说明](plugins.md#pairlists-and-pairlist-handlers)。<br> **Datatype:** 列表 |
| `exchange.pair_blacklist` | 必须排除的交易对列表。[更多说明](plugins.md#pairlists-and-pairlist-handlers)。<br> **Datatype:** 列表 |
| `exchange.ccxt_config` | 传递给同步与异步 ccxt 实例的附加参数。通常在此处添加额外配置。参数会因交易所而异，详见 [ccxt 文档](https://docs.ccxt.com/#/README?id=overriding-exchange-properties-upon-instantiation)。请勿在此处放置密钥，否则可能写入日志。<br> **Datatype:** 字典 |
| `exchange.ccxt_sync_config` | 仅传递给同步 ccxt 实例的附加参数。详见 [ccxt 文档](https://docs.ccxt.com/#/README?id=overriding-exchange-properties-upon-instantiation)。<br> **Datatype:** 字典 |
| `exchange.ccxt_async_config` | 仅传递给异步 ccxt 实例的附加参数。详见 [ccxt 文档](https://docs.ccxt.com/#/README?id=overriding-exchange-properties-upon-instantiation)。<br> **Datatype:** 字典 |
| `exchange.enable_ws` | 启用交易所 Websocket。[更多说明](#consuming-exchange-websockets)。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| `exchange.markets_refresh_interval` | 重新加载市场数据的时间间隔（分钟）。<br>*默认 60 分钟。*<br> **Datatype:** 正整数 |
| `exchange.skip_open_order_update` | 若交易所存在问题，可在启动时跳过更新未成交订单，仅对实盘有效。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `exchange.unknown_fee_rate` | 计算手续费时的备用费率，适用于手续费以不可交易货币计价的情况。该值会乘以“手续费金额”。<br>*默认 `None`。*<br> **Datatype:** 浮点数 |
| `exchange.log_responses` | 记录交易所响应，仅建议在调试模式下使用。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `exchange.only_from_ccxt` | 禁止从 data.binance.vision 下载数据。保持默认可显著提升下载速度，但若该站点不可用可能产生问题。<br>*默认 `false`。*<br> **Datatype:** 布尔值 |
| `experimental.block_bad_exchanges` | 阻止已知与 freqtrade 不兼容的交易所。除非想测试某交易所是否已恢复支持，否则建议保持默认。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| | **插件** |
| `pairlists` | 定义一个或多个交易对列表。[更多说明](plugins.md#pairlists-and-pairlist-handlers)。<br>*默认 `StaticPairList`。*<br> **Datatype:** 字典列表 |
| | **Telegram** |
| `telegram.enabled` | 启用 Telegram 通知。<br> **Datatype:** 布尔值 |
| `telegram.token` | Telegram Bot Token。启用 Telegram 时必填。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `telegram.chat_id` | 你的 Telegram 个人账号 ID。启用 Telegram 时必填。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `telegram.balance_dust_level` | 余额粉尘阈值（以计价货币计），余额低于该值的资产不会在 `/balance` 中显示。<br> **Datatype:** 浮点数 |
| `telegram.reload` | 允许在 Telegram 消息中显示“刷新”按钮。<br>*默认 `true`。*<br> **Datatype:** 布尔值 |
| `telegram.notification_settings.*` | 详细的通知设置。详见 [Telegram 文档](telegram-usage.md)。<br> **Datatype:** 字典 |
| `telegram.allow_custom_messages` | 允许策略通过 `dataprovider.send_msg()` 发送自定义 Telegram 消息。<br> **Datatype:** 布尔值 |
| | **Webhook** |
| `webhook.enabled` | 启用 Webhook 通知。<br> **Datatype:** 布尔值 |
| `webhook.url` | Webhook 的 URL。启用 Webhook 时必填，详情见 [Webhook 文档](webhook-config.md)。<br> **Datatype:** 字符串 |
| `webhook.entry` | 买入通知的 payload。启用 Webhook 时必填。详见 [Webhook 文档](webhook-config.md)。<br> **Datatype:** 字符串 |
| `webhook.entry_cancel` | 买单取消通知的 payload。启用 Webhook 时必填。<br> **Datatype:** 字符串 |
| `webhook.entry_fill` | 买单成交通知的 payload。启用 Webhook 时必填。<br> **Datatype:** 字符串 |
| `webhook.exit` | 卖出通知的 payload。启用 Webhook 时必填。<br> **Datatype:** 字符串 |
| `webhook.exit_cancel` | 卖单取消通知的 payload。启用 Webhook 时必填。<br> **Datatype:** 字符串 |
| `webhook.exit_fill` | 卖单成交通知的 payload。启用 Webhook 时必填。<br> **Datatype:** 字符串 |
| `webhook.status` | 状态查询通知的 payload。启用 Webhook 时必填。<br> **Datatype:** 字符串 |
| `webhook.allow_custom_messages` | 允许策略通过 `dataprovider.send_msg()` 发送自定义 Webhook 消息。<br> **Datatype:** 布尔值 |
| | **Rest API / FreqUI / 生产者-消费者模式** |
| `api_server.enabled` | 启用 API 服务器。详见 [API Server 文档](rest-api.md)。<br> **Datatype:** 布尔值 |
| `api_server.listen_ip_address` | API 服务器绑定的 IP 地址。详见 [API Server 文档](rest-api.md)。<br> **Datatype:** IPv4 |
| `api_server.listen_port` | API 服务器绑定的端口。详见 [API Server 文档](rest-api.md)。<br> **Datatype:** 1024-65535 的整数 |
| `api_server.verbosity` | 日志详细程度。`info` 会打印所有 RPC 调用，`error` 仅显示错误。默认 `info`。<br> **Datatype:** `info` 或 `error` |
| `api_server.username` | API 服务器用户名。详见 [API Server 文档](rest-api.md)。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `api_server.password` | API 服务器密码。详见 [API Server 文档](rest-api.md)。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `api_server.ws_token` | 消息 WebSocket 的 API Token。详见 [API Server 文档](rest-api.md)。**请妥善保管，不要泄露。**<br> **Datatype:** 字符串 |
| `bot_name` | 机器人名称，会通过 API 传递至客户端，便于区分。<br>*默认 `freqtrade`。*<br> **Datatype:** 字符串 |
| `external_message_consumer` | 启用[生产者/消费者模式](producer-consumer.md)。<br> **Datatype:** 字典 |
| | **其他** |
| `initial_state` | 初始运行状态。若设为 `stopped`，则需通过 `/start` 命令显式启动。<br>*默认 `stopped`。*<br> **Datatype:** `running`、`paused` 或 `stopped` |
| `force_entry_enable` | 启用强制开仓的 RPC 命令。详见下文。<br> **Datatype:** 布尔值 |
| `disable_dataframe_checks` | 禁用对策略返回的 OHLCV DataFrame 的有效性检查。仅在你明确修改 DataFrame 且了解后果时使用。[Strategy Override](#parameters-in-the-strategy)。<br>*默认 `False`。*<br> **Datatype:** 布尔值 |
| `internals.process_throttle_secs` | 设置主循环的最小执行间隔（秒）。<br>*默认 5 秒。*<br> **Datatype:** 正整数 |
| `internals.heartbeat_interval` | 心跳日志的输出间隔。设为 0 可禁用心跳消息。<br>*默认 60 秒。*<br> **Datatype:** 正整数或 0 |
| `internals.sd_notify` | 启用 sd_notify 协议，以便向 systemd 汇报状态并发送保活心跳。详见[系统服务配置](advanced-setup.md#configure-the-bot-running-as-a-systemd-service)。<br> **Datatype:** 布尔值 |
| `strategy` | **Required.** 指定使用的策略类。推荐通过 `--strategy NAME` 设置。<br> **Datatype:** 类名 |
| `strategy_path` | 增加额外的策略搜索目录（必须为文件夹）。<br> **Datatype:** 字符串 |
| `recursive_strategy_search` | 设为 `true` 可在 `user_data/strategies` 下递归搜索子目录。<br> **Datatype:** 布尔值 |
| `user_data_dir` | 用户数据目录。<br>*默认 `./user_data/`。*<br> **Datatype:** 字符串 |
| `db_url` | 数据库连接字符串。注意：当 `dry_run=true` 时默认使用 `sqlite:///tradesv3.dryrun.sqlite`，实盘时默认 `sqlite:///tradesv3.sqlite`。<br> **Datatype:** 字符串（SQLAlchemy 连接串） |
| `logfile` | 指定日志文件名称。采用滚动策略：最多 10 个文件，每个文件 1MB。<br> **Datatype:** 字符串 |
| `add_config_files` | 额外配置文件列表，会与当前配置合并。路径相对于首个配置文件。<br>*默认 `[]`。*<br> **Datatype:** 字符串列表 |
| `dataformat_ohlcv` | 历史 K 线（OHLCV）数据的存储格式。<br>*默认 `feather`。*<br> **Datatype:** 字符串 |
| `dataformat_trades` | 历史成交数据的存储格式。<br>*默认 `feather`。*<br> **Datatype:** 字符串 |
| `reduce_df_footprint` | 将数值列转换为 float32/int32，以减少内存/磁盘占用，并缩短回测、Hyperopt 与 FreqAI 的训练/推理时间。<br> **Datatype:** 布尔值（默认 `False`） |
| `log_config` | Python logging 的配置字典。详见[高级日志配置](advanced-setup.md#advanced-logging)。<br> **Datatype:** 字典（默认 `FtRichHandler`） |

### 策略内的参数 {#parameters-in-the-strategy}

以下参数既可在配置文件中设置，也可在策略中定义。若配置文件中提供了值，则会覆盖策略中的设置。

* `minimal_roi`
* `timeframe`
* `stoploss`
* `max_open_trades`
* `trailing_stop`
* `trailing_stop_positive`
* `trailing_stop_positive_offset`
* `trailing_only_offset_is_reached`
* `use_custom_stoploss`
* `process_only_new_candles`
* `order_types`
* `order_time_in_force`
* `unfilledtimeout`
* `disable_dataframe_checks`
* `use_exit_signal`
* `exit_profit_only`
* `exit_profit_offset`
* `ignore_roi_if_entry_signal`
* `ignore_buying_expired_candle_after`
* `position_adjustment_enable`
* `max_entry_position_adjustment`

### 配置每笔交易金额 {#configuring-amount-per-trade}

有多种方式可以控制机器人在开仓时投入的计价货币数量。以下所有方法都会遵循[可用余额设置](#tradable-balance)。

#### 最小下单金额

最小下单金额取决于交易所和交易对，通常可以在交易所帮助页面找到。

!!! Warning
    由于交易所的下单限制通常变化不大，有些交易对可能会因为价格上涨而显示很高的最小下单额。Freqtrade 会自动将下单金额调整到该值，除非该金额比预期值高出 30% 以上，此时会拒绝下单。

#### Dry-run 模拟钱包 {#dry-run-wallet}

Dry-run 模式下，机器人会使用模拟钱包进行交易。钱包的初始余额由 `dry_run_wallet` 定义（默认 1000）。对于复杂场景，也可以为每种货币设置初始余额：

```json
"dry_run_wallet": {
    "BTC": 0.01,
    "ETH": 2,
    "USDT": 1000
}
```

命令行参数 `--dry-run-wallet` 可以覆盖配置中的浮点值，但无法覆盖字典形式。若需使用字典，请直接修改配置文件。

!!! Note
    非计价货币的余额不会用于交易，但会显示在钱包余额中。  
    在全仓杠杆交易所，钱包余额也可能用于计算可用保证金。

#### 可交易余额 {#tradable-balance}

默认情况下，机器人会假设可用余额为 `全部余额 - 1%`。启用[动态下单金额](#dynamic-stake-amount) 时，它会将余额平均分配到 `max_open_trades` 个槽位。  
为了应对下单费用，Freqtrade 默认保留 1% 的资金，不会动用这部分余额。

可通过 `tradable_balance_ratio` 设置保留比例。

例如，若钱包中有 10 ETH，且 `tradable_balance_ratio=0.5`（即 50%），则机器人最多只会使用 5 ETH 进行交易，剩余余额保持不动。

!!! Danger
    当同一账户运行多个机器人时，**不要**使用该设置。请改用[为机器人分配初始资金](#assign-available-capital)。

!!! Warning
    `tradable_balance_ratio` 作用于当前总余额（可用余额 + 持仓金额）。例如起始余额 1000，配置 `tradable_balance_ratio=0.99` 并不能保证交易所永远保留 10 单位货币。如果总余额降至 500（例如回撤或提现），可用余额可能仅剩 5。

#### 为机器人分配初始资金 {#assign-available-capital}

若在同一交易所运行多个机器人并希望独立复利，可通过 `available_capital` 为每个机器人划定起始资金。

假设账户中有 10000 USDT，你计划运行 2 套策略，则可将 `available_capital` 设为 5000，为每个机器人提供 5000 USDT 的初始资金。机器人会将该金额平均分配到 `max_open_trades` 个槽位。盈利会提高该机器人的下单金额，而不会影响另一个机器人。

调整 `available_capital` 后需重新加载配置才能生效。增加或减少该值时，机器人会在原值与新值之间补差。减少可用资金并不会立刻平掉已有仓位，差额会在仓位关闭后返还钱包，收益则取决于调整时点后价格的变化。

!!! Warning "`tradable_balance_ratio` 不兼容"
    一旦设置 `available_capital`，`tradable_balance_ratio` 会被忽略。

#### 调整最后一笔下单金额 {#amend-last-stake-amount}

假设可交易余额为 1000 USDT，`stake_amount=400`，`max_open_trades=3`。机器人会开出 2 笔 400 USDT 的仓位后，第三个槽位剩余 200 USDT 无法下单。

启用 `amend_last_stake_amount`（设为 `True`）后，机器人会将最后一笔订单的金额下调至剩余余额，从而填满最后一个交易槽位。

上述例子中每笔下单金额为：

* 第 1 笔：400 USDT
* 第 2 笔：400 USDT
* 第 3 笔：200 USDT

!!! Note
    该选项仅适用于[固定下单金额](#static-stake-amount)。[动态下单金额](#dynamic-stake-amount) 会自动平均分配余额。

!!! Note
    `last_stake_amount_min_ratio` 控制最后一单的最小金额，默认 0.5（50%），即最小金额为 `stake_amount * 0.5`。这样可以避免金额过小导致交易所拒单。

#### 固定下单金额 {#static-stake-amount}

`stake_amount` 配置可为每笔交易设置固定的下单金额。

最小值为 0.0001，但请务必确认交易所对该计价货币的最小下单限制。

该设置与 `max_open_trades` 共同决定最大持仓规模：`stake_amount * max_open_trades`。例如 `max_open_trades=3` 且 `stake_amount=0.05`，最多会投入 0.15 BTC。

!!! Note
    此设置会遵循[可交易余额](#tradable-balance)。

#### 动态下单金额 {#dynamic-stake-amount}

另一种方式是使用动态下单金额，即将交易所可用余额按 `max_open_trades` 平均分配。

配置方法是将 `stake_amount` 设为 `"unlimited"`。建议同时设置 `tradable_balance_ratio=0.99`（99%），以保留手续费所需资金。

此时每笔交易的金额计算为：

```python
currency_balance / (max_open_trades - current_open_trades)
```

若希望机器人使用账户中所有计价货币（减去 `tradable_balance_ratio`），可以这样设置：

```json
"stake_amount": "unlimited",
"tradable_balance_ratio": 0.99,
```

!!! Tip "复利效果"
    该配置会根据机器人表现动态增减下单金额：回撤时减少，盈利时增加，实现复利。

!!! Note "Dry-run 模式注意事项"
    当 `"stake_amount": "unlimited"` 与 Dry-run/回测/Hyperopt 配合使用时，余额会从 `dry_run_wallet` 开始模拟并动态变化。因此务必为 `dry_run_wallet` 设置合理值（例如 BTC 0.05 或 0.01、USDT 1000 或 100），否则可能模拟出一次交易 100 BTC 或 0.05 USDT 的极端情况。

#### 动态下单金额与仓位调整 {#dynamic-stake-amount-with-position-adjustment}

若希望在无限下单金额模式下使用仓位调整，则必须实现 `custom_stake_amount`，根据策略返回合适的金额。

常见做法是返回建议金额的 25%-50%，为后续仓位调整预留空间。具体比例取决于策略。例如计划追加 2 次相同金额的买入，则应预留 66.67% 的余额；若计划只追加 1 次、金额为原始下单的 3 倍，则 `custom_stake_amount` 应返回原建议金额的 25%，将剩余 75% 作为缓冲。

--8<-- "includes/pricing.md"

## 更多配置细节

### 理解 minimal_roi {#understand-minimal_roi}

`minimal_roi` 是一个 JSON 对象，键为分钟数，值为对应的最小收益率。示例：

```json
"minimal_roi": {
    "40": 0.0,    # 若 40 分钟后收益不为负，则离场
    "30": 0.01,   # 若 30 分钟后收益 ≥ 1%，则离场
    "20": 0.02,   # 若 20 分钟后收益 ≥ 2%，则离场
    "0":  0.04    # 若收益 ≥ 4%，立即离场
},
```

大多数策略文件已经包含了推荐的 `minimal_roi`。该参数可在策略或配置中设置；若配置文件中提供了值，会覆盖策略中的设置。  
如果两处都未设置，则默认 `{"0": 10}`（1000%），即除非收益达 1000%，否则不会因为 ROI 达标而平仓。

!!! Note "按固定时间强制平仓"
    如果将 ROI 设为 `"<N>": -1`，机器人会在 N 分钟后强制平仓，无论盈亏，例如 `{"60": -1}` 表示持仓 60 分钟后必定出场。

### 理解 force_entry_enable

`force_entry_enable` 允许通过 Telegram 与 REST API 使用 `/forcelong`、`/forceshort` 命令强制开仓。出于安全考虑，该功能默认关闭，启用时机器人会在启动日志中给出警告。

例如发送 `/forceenter ETH/BTC`，机器人会直接买入该交易对，并持有至常规退出信号（ROI、止损或 `/forceexit`）出现。

该功能对于某些策略可能风险较大，请谨慎使用。详细用法参见 [Telegram 文档](telegram-usage.md)。

### 忽略过期蜡烛

在使用较大周期（例如 1h）且 `max_open_trades` 较低时，一旦释放出新仓位，策略可能立即处理当前蜡烛。如果策略依赖交叉等条件，过晚使用某根蜡烛的买入信号可能并不合适。

此时可以通过 `ignore_buying_expired_candle_after` 指定一段秒数，超过该时间后买入信号即视为过期。

例如策略使用 1h 周期，希望仅在新蜡烛的前 5 分钟内买入，可以在策略中添加：

``` json
{
    // ...
    "ignore_buying_expired_candle_after": 300,
    // ...
}
```

!!! Note
    该设置会在每根新蜡烛时重置，无法阻止信号在第二或第三根蜡烛继续触发。建议在策略中使用只在单根蜡烛有效的触发条件。

### 理解 order_types {#understand-order_types}

`order_types` 用于将各类操作（`entry`、`exit`、`stoploss`、`emergency_exit`、`force_exit`、`force_entry`）映射到具体的订单类型（`market`、`limit` 等），并可配置是否在交易所直接挂出止损单、以及止损更新间隔。

这使得我们可以使用限价单开仓、限价单平仓、止损则用市价单执行。也可以开启“交易所止损”，即在买单成交后立即于交易所挂出止损单。

配置文件中的 `order_types` 会整体覆盖策略里的设置，因此需要在同一个位置完整定义整个字典。

该字典至少需要包含 `entry`、`exit`、`stoploss`、`stoploss_on_exchange` 四个键，否则机器人无法启动。

`emergency_exit`、`force_exit`、`force_entry`、`stoploss_on_exchange`、`stoploss_on_exchange_interval`、`stoploss_on_exchange_limit_ratio` 等选项的说明请参见[止损文档](stoploss.md)。

策略中使用示例：

```python
order_types = {
    "entry": "limit",
    "exit": "limit",
    "emergency_exit": "market",
    "force_entry": "market",
    "force_exit": "market",
    "stoploss": "market",
    "stoploss_on_exchange": False,
    "stoploss_on_exchange_interval": 60,
    "stoploss_on_exchange_limit_ratio": 0.99,
}
```

配置文件示例：

```json
"order_types": {
    "entry": "limit",
    "exit": "limit",
    "emergency_exit": "market",
    "force_entry": "market",
    "force_exit": "market",
    "stoploss": "market",
    "stoploss_on_exchange": false,
    "stoploss_on_exchange_interval": 60
}
```

!!! Note "交易所是否支持市价单"
    并非所有交易所都支持市价单。如若不支持，机器人会提示 `"Exchange <yourexchange> does not support market orders."` 并拒绝启动。

!!! Warning "使用市价单"
    若使用市价单，请仔细阅读[市价单定价](#market-order-pricing) 部分。

!!! Note "交易所止损"
    `order_types.stoploss_on_exchange_interval` 并非必填。如不确定其效果，请保持默认值。  
    若启用 `order_types.stoploss_on_exchange`，但你在交易所手动取消了止损单，机器人会重新挂出止损。

!!! Warning "`order_types.stoploss_on_exchange` 失败时的处理"
    若交易所止损下单失败，机器人会触发“紧急平仓”（默认以市价单退出）。虽然可以通过 `order_types` 中的 `emergency_exit` 调整订单类型，但并不建议这么做。

### 理解 order_time_in_force {#understand-order_time_in_force}

`order_time_in_force` 定义交易所执行订单的策略。常见取值包括：

**GTC（Good Till Canceled）**：默认选项。订单会在交易所持续挂单，直到被完全或部分成交，或被用户取消。部分成交后，剩余部分仍会保留在订单簿上。

**FOK（Fill Or Kill）**：若订单不能立即并完全成交，则会被交易所取消。

**IOC（Immediate Or Canceled）**：与 FOK 类似，但允许部分成交，未成交部分立即取消。

> 注意：IOC 可能导致成交量低于交易所允许的最小金额，请谨慎使用。

**PO（Post only）**：仅以挂单（Maker）形式提交订单，否则直接取消。意味着订单必须至少在订单簿上停留一段时间。

请参阅[交易所文档](exchanges.md)了解你的交易所支持哪些 Time in Force。

#### time_in_force 配置

`order_time_in_force` 是包含买入、卖出策略的字典，可在配置文件或策略中设置。配置文件中的值会遵循[优先级规则](#configuration-option-prevalence) 覆盖策略中的设置。

可选值包括：`GTC`（默认）、`FOK`、`IOC`。

``` python
"order_time_in_force": {
    "entry": "GTC",
    "exit": "GTC"
},
```

!!! Warning
    除非完全了解影响，否则不要修改默认值，并务必查阅交易所的相关说明。

### 法币换算

Freqtrade 使用 Coingecko API 将资产折算为法币，并在 Telegram 报告中展示。你可以通过 `fiat_display_currency` 设置显示的法币。

若从配置中删除 `fiat_display_currency`，机器人将不会初始化 Coingecko，也不会显示法币换算。这不会影响机器人的正常运行。

#### `fiat_display_currency` 可用取值 {#what-values-can-be-used-for-fiat_display_currency}

`fiat_display_currency` 设置 Telegram 报告中显示的法币单位。

支持的法币包括：

```json
"AUD", "BRL", "CAD", "CHF", "CLP", "CNY", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF", "IDR", "ILS", "INR", "JPY", "KRW", "MXN", "MYR", "NOK", "NZD", "PHP", "PKR", "PLN", "RUB", "SEK", "SGD", "THB", "TRY", "TWD", "ZAR", "USD"
```

此外还支持部分加密货币：

```json
"BTC", "ETH", "XRP", "LTC", "BCH", "BNB"
```

#### Coingecko 频率限制

部分 IP 可能会遭遇 Coingecko 的严格限流。这种情况下，可以在配置中添加 Coingecko API Key：

``` json
{
    "fiat_display_currency": "USD",
    "coingecko": {
        "api_key": "your-api",
        "is_demo": true
    }
}
```

Freqtrade 同时支持 Coingecko 的 Demo 与 Pro API Key。

Coingecko API Key 并非必需，仅用于 Telegram 报告中的法币换算。大多数情况下，即便没有 API Key 也能正常工作。

## 使用交易所 Websocket {#consuming-exchange-websockets}

Freqtrade 通过 ccxt.pro 消费交易所 Websocket。

Freqtrade 目标是在任何时候都能获取到数据。如果 Websocket 连接失败（或被禁用），机器人会自动回退到 REST API。

若你怀疑 Websocket 引发问题，可通过 `exchange.enable_ws` 设置禁用（默认 `true`）。

```jsonc
"exchange": {
    // ...
    "enable_ws": false,
    // ...
}
```

若需要使用代理，请参考[代理章节](#using-a-proxy-with-freqtrade)。

!!! Info "逐步发布"
    Websocket 支持正在循序渐进地推出，以确保稳定。目前仅用于 OHLCV 数据，并只支持部分交易所，未来会持续扩展。

## 使用 Dry-run 模式 {#using-dry-run-mode}

推荐先在 Dry-run 模式下运行机器人，观察策略表现。Dry-run 模式不会动用真实资金，而是模拟实时交易。

1. 编辑 `config.json`。
2. 将 `dry_run` 设为 `true`，并指定用于持久化的 `db_url`：

```json
"dry_run": true,
"db_url": "sqlite:///tradesv3.dryrun.sqlite",
```

3. 删除交易所 API Key 与 Secret（可以留空或写入假值）：

```json
"exchange": {
    "name": "binance",
    "key": "key",
    "secret": "secret",
    ...
}
```

当你对 Dry-run 模式的表现满意后，可切换至实盘模式。

!!! Note
    Dry-run 模式会提供一个模拟钱包，初始资金为 `dry_run_wallet`（默认 1000）。

### Dry-run 注意事项

* API Key 可选。Dry-run 模式仅使用不会改变账户状态的只读请求。
* `/balance` 会基于 `dry_run_wallet` 模拟。
* 订单为模拟订单，不会发送至交易所。
* 市价单会参考下单时的委托量，最多滑点 5%。
* 限价单在价格触及时成交，或根据 `unfilledtimeout` 超时。
* 若价格偏离限价超过 1%，限价单会被视为市价单并立即成交。
* 若结合 `stoploss_on_exchange` 使用，止损价视为已成交。
* 未成交订单（非交易记录）在机器人重启后仍保持开放，假设离线期间未成交。

## 切换至实盘模式 {#switch-to-production-mode}

实盘模式会动用真实资金，错误的策略可能导致亏损。请确保完全理解策略风险。

切换至实盘时，务必使用全新或干净的数据库，以免 Dry-run 记录影响统计。

### 设置交易所账户

需要在交易所后台创建 API Key（通常包括 `key` 与 `secret`，某些交易所还需要 `password`），并填入配置文件或 `freqtrade new-config` 命令。API Key 仅在实盘（真实交易）需要，Dry-run 模式可留空。

### 切换为实盘模式

1. **编辑 `config.json`。**
2. **将 `dry_run` 设为 `false`，如有自定义数据库请同步调整：**

```json
"dry_run": false,
```

3. **填写交易所 API Key（以下示例为假值）：**

```json
{
    "exchange": {
        "name": "binance",
        "key": "af8ddd35195e9dc500b9a6f799f6f5c93d89193b",
        "secret": "08a9dc6db3d7b53e1acebd9275677f4b0a04f1a5",
        //"password": "", // 部分交易所需要，示例留空
        // ...
    }
    // ...
}
```

同样请阅读文档中的[交易所](exchanges.md)章节，了解具体交易所的配置细节。

!!! Hint "保护好密钥"
    建议使用第二个配置文件存放 API Key，例如 `config-private.json`，并保持该文件私密。  
    启动命令示例：`freqtrade trade --config user_data/config.json --config user_data/config-private.json <...>`。

    **绝对不要**与他人共享包含密钥的配置文件！

## 在 Freqtrade 中使用代理 {#using-a-proxy-with-freqtrade}

若需使用代理，可在环境变量中设置 `"HTTP_PROXY"` 与 `"HTTPS_PROXY"`，这些设置会作用于 Telegram、Coingecko 等组件，但**不包括**交易所请求：

``` bash
export HTTP_PROXY="http://addr:port"
export HTTPS_PROXY="http://addr:port"
freqtrade
```

### 代理交易所请求 {#proxy-exchange-requests}

要为交易所连接配置代理，需要在 ccxt 配置中指定：

``` json
{
  "exchange": {
    "ccxt_config": {
      "httpsProxy": "http://addr:port",
      "wsProxy": "http://addr:port"
    }
  }
}
```

更多可用代理类型请参考 [ccxt 代理文档](https://docs.ccxt.com/#/README?id=proxy)。

## 下一步

完成 `config.json` 的配置后，下一步可以[启动机器人](bot-usage.md)。
