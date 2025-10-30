## 交易对列表和交易对列表处理器

交易对列表处理器定义机器人应交易的交易对列表（交易对列表）。它们在配置设置的 `pairlists` 部分中配置。

在配置中，你可以使用静态交易对列表（由 [`StaticPairList`](#静态交易对列表) 交易对列表处理器定义）和动态交易对列表（由 [`VolumePairList`](#成交量交易对列表) 和 [`PercentChangePairList`](#百分比变化交易对列表) 交易对列表处理器定义）。

此外，[`AgeFilter`](#agefilter)、[`DelistFilter`](#delistfilter)、[`PrecisionFilter`](#precisionfilter)、[`PriceFilter`](#pricefilter)、[`ShuffleFilter`](#shufflefilter)、[`SpreadFilter`](#spreadfilter) 和 [`VolatilityFilter`](#volatilityfilter) 充当交易对列表过滤器，删除某些交易对和/或移动它们在交易对列表中的位置。

如果使用多个交易对列表处理器，它们会被链接，所有交易对列表处理器的组合形成机器人用于交易和回测的结果交易对列表。交易对列表处理器按照它们配置的顺序执行。你可以将 `StaticPairList`、`VolumePairList`、`ProducerPairList`、`RemotePairList`、`MarketCapPairList` 或 `PercentChangePairList` 定义为起始交易对列表处理器。

不活跃的市场始终从结果交易对列表中删除。明确列入黑名单的交易对（`pair_blacklist` 配置设置中的交易对）也始终从结果交易对列表中删除。

### 交易对黑名单

交易对黑名单（通过配置中的 `exchange.pair_blacklist` 配置）禁止某些交易对进行交易。
这可以像排除 `DOGE/BTC` 一样简单 - 这将删除这个确切的交易对。

交易对黑名单还支持通配符（正则表达式样式） - 因此 `BNB/.*` 将排除所有以 BNB 开头的交易对。
你还可以使用类似 `.*DOWN/BTC` 或 `.*UP/BTC` 的内容来排除杠杆代币（查看你的交易所的交易对命名约定！）

### 可用的交易对列表处理器

* [`StaticPairList`](#静态交易对列表)（默认，如果未以其他方式配置）
* [`VolumePairList`](#成交量交易对列表)
* [`PercentChangePairList`](#百分比变化交易对列表)
* [`ProducerPairList`](#producerpairlist)
* [`RemotePairList`](#remotepairlist)
* [`MarketCapPairList`](#marketcappairlist)
* [`AgeFilter`](#agefilter)
* [`DelistFilter`](#delistfilter)
* [`FullTradesFilter`](#fulltradesfilter)
* [`OffsetFilter`](#offsetfilter)
* [`PerformanceFilter`](#performancefilter)
* [`PrecisionFilter`](#precisionfilter)
* [`PriceFilter`](#pricefilter)
* [`ShuffleFilter`](#shufflefilter)
* [`SpreadFilter`](#spreadfilter)
* [`RangeStabilityFilter`](#rangestabilityfilter)
* [`VolatilityFilter`](#volatilityfilter)

!!! Tip "测试交易对列表"
    交易对列表配置可能很难正确设置。最好在 [webserver 模式](freq-ui.md#webserver-模式) 下使用 freqUI 或 [`test-pairlist`](utils.md#test-pairlist) 实用程序子命令来快速测试你的交易对列表配置。

#### 静态交易对列表

默认情况下，使用 `StaticPairList` 方法，该方法使用配置中静态定义的交易对白名单。交易对列表还支持通配符（正则表达式样式） - 因此 `.*/BTC` 将包括所有以 BTC 作为计价货币的交易对。

它使用 `exchange.pair_whitelist` 和 `exchange.pair_blacklist` 的配置，在下面的示例中，将交易 BTC/USDT 和 ETH/USDT - 并将阻止 BNB/USDT 交易。

两个 `pair_*list` 参数都支持正则表达式 - 因此像 `.*/USDT` 这样的值将启用所有不在黑名单中的交易对的交易。

```json
"exchange": {
    "name": "...",
    // ...
    "pair_whitelist": [
        "BTC/USDT",
        "ETH/USDT",
        // ...
    ],
    "pair_blacklist": [
        "BNB/USDT",
        // ...
    ]
},
"pairlists": [
    {"method": "StaticPairList"}
],
```

默认情况下，仅允许当前启用的交易对。
要跳过针对活跃市场的交易对验证，请在 `StaticPairList` 配置中设置 `"allow_inactive": true`。
这对于回测过期的交易对（如季度现货市场）很有用。

当在"后续"位置使用时（例如在 VolumePairlist 之后），`'pair_whitelist'` 中的所有交易对将被添加到交易对列表的末尾。

#### 成交量交易对列表

`VolumePairList` 通过交易量对交易对进行排序/过滤。它根据 `sort_key`（只能是 `quoteVolume`）选择 `number_assets` 个顶级交易对进行排序。

当在交易对列表处理器链中的非领先位置使用时（在 StaticPairList 和其他交易对列表过滤器之后），`VolumePairList` 会考虑先前交易对列表处理器的输出，通过交易量添加其对交易对的排序/选择。

当在交易对列表处理器链的领先位置使用时，将忽略 `pair_whitelist` 配置设置。相反，`VolumePairList` 从交易所上所有具有匹配计价货币的可用市场中选择顶级资产。

`refresh_period` 设置允许定义交易对列表将刷新的周期（以秒为单位）。默认为 1800 秒（30 分钟）。
`VolumePairList` 上的交易对列表缓存（`refresh_period`）仅适用于生成交易对列表。
过滤实例（不在列表中的第一个位置）不会应用任何缓存（除了在高级模式下缓存蜡烛图持续时间的蜡烛图），并且将始终使用最新数据。

`VolumePairList` 默认基于交易所的行情数据，如 ccxt 库报告的：

* `quoteVolume` 是过去 24 小时内交易（买入或卖出）的计价（计价）货币数量。

```json
"pairlists": [
    {
        "method": "VolumePairList",
        "number_assets": 20,
        "sort_key": "quoteVolume",
        "min_value": 0,
        "max_value": 8000000,
        "refresh_period": 1800
    }
],
```

你可以使用 `min_value` 定义最小成交量 - 这将过滤掉成交量低于指定时间范围内指定值的交易对。
除此之外，你还可以使用 `max_value` 定义最大成交量 - 这将过滤掉成交量高于指定时间范围内指定值的交易对。

##### VolumePairList 高级模式

`VolumePairList` 还可以在高级模式下运行，以在指定蜡烛图大小的给定时间范围内构建成交量。它利用交易所历史蜡烛图数据，构建典型价格（通过 (open+high+low)/3 计算）并将典型价格乘以每根蜡烛图的成交量。总和是给定范围内的 `quoteVolume`。这允许不同的场景，当使用具有较大蜡烛图大小的较长范围时，可以获得更平滑的成交量，或者当使用具有小蜡烛图的短范围时，则相反。

为了方便起见，可以指定 `lookback_days`，这将意味着将使用 1d 蜡烛图进行回溯。在下面的示例中，交易对列表将基于过去 7 天创建：

```json
"pairlists": [
    {
        "method": "VolumePairList",
        "number_assets": 20,
        "sort_key": "quoteVolume",
        "min_value": 0,
        "refresh_period": 86400,
        "lookback_days": 7
    }
],
```

!!! Warning "范围回溯和刷新周期"
    当与 `lookback_days` 和 `lookback_timeframe` 一起使用时，`refresh_period` 不能小于蜡烛图大小（以秒为单位）。因为这将导致对交易所 API 的不必要请求。

!!! Warning "使用回溯范围时的性能影响"
    如果在与回溯结合使用时在第一位置使用，基于范围的成交量计算可能会消耗时间和资源，因为它会下载所有可交易交易对的蜡烛图。因此，强烈建议使用带有 `VolumeFilter` 的标准方法来缩小交易对列表，以便进一步进行范围成交量计算。

??? Tip "不支持的交易所"
    在某些交易所（如 Gemini）上，常规 VolumePairList 不起作用，因为 api 本身不提供 24 小时成交量。这可以通过使用蜡烛图数据构建成交量来解决。
    要粗略模拟 24 小时成交量，你可以使用以下配置。
    请注意，这些交易对列表每天只会刷新一次。

    ```json
    "pairlists": [
        {
            "method": "VolumePairList",
            "number_assets": 20,
            "sort_key": "quoteVolume",
            "min_value": 0,
            "refresh_period": 86400,
            "lookback_days": 1
        }
    ],
    ```

可以使用更复杂的方法，通过使用 `lookback_timeframe` 作为蜡烛图大小和 `lookback_period` 来指定蜡烛图数量。此示例将基于 3 天 1 小时蜡烛图的滚动周期构建成交量交易对：

```json
"pairlists": [
    {
        "method": "VolumePairList",
        "number_assets": 20,
        "sort_key": "quoteVolume",
        "min_value": 0,
        "refresh_period": 3600,
        "lookback_timeframe": "1h",
        "lookback_period": 72
    }
],
```

!!! Note
    `VolumePairList` 不支持回测模式。

#### 百分比变化交易对列表

`PercentChangePairList` 根据交易对在过去 24 小时或作为高级选项的一部分定义的任何时间框架内的价格百分比变化来过滤和排序交易对。这允许交易者专注于经历了显著价格变动（正向或负向）的资产。

**配置选项**

* `number_assets`：指定根据 24 小时百分比变化选择的顶级交易对数量。
* `min_value`：设置最小百分比变化阈值。百分比变化低于此值的交易对将被过滤掉。
* `max_value`：设置最大百分比变化阈值。百分比变化高于此值的交易对将被过滤掉。
* `sort_direction`：指定基于百分比变化对交易对进行排序的顺序。接受两个值：`asc` 表示升序，`desc` 表示降序。
* `refresh_period`：定义交易对列表将刷新的间隔（以秒为单位）。默认值为 1800 秒（30 分钟）。
* `lookback_days`：要回溯的天数。选择 `lookback_days` 时，`lookback_timeframe` 默认为 1 天。
* `lookback_timeframe`：用于回溯期的时间框架。
* `lookback_period`：要回溯的周期数。

当 PercentChangePairList 在其他交易对列表处理器之后使用时，它将对这些处理器的输出进行操作。如果它是领先的交易对列表处理器，它将从具有指定计价货币的所有可用市场中选择交易对。

`PercentChangePairList` 使用通过 ccxt 库提供的交易所的行情数据：
百分比变化计算为过去 24 小时内价格的变化。

??? Note "不支持的交易所"
    在某些交易所（如 HTX）上，常规 PercentChangePairList 不起作用，因为 api 本身不提供 24 小时价格百分比变化。这可以通过使用蜡烛图数据来计算百分比变化来解决。要粗略模拟 24 小时百分比变化，你可以使用以下配置。请注意，这些交易对列表每天只会刷新一次。
    ```json
    "pairlists": [
        {
            "method": "PercentChangePairList",
            "number_assets": 20,
            "min_value": 0,
            "refresh_period": 86400,
            "lookback_days": 1
        }
    ],
    ```

**从行情读取的示例配置**

```json
"pairlists": [
    {
        "method": "PercentChangePairList",
        "number_assets": 15,
        "min_value": -10,
        "max_value": 50
    }
],
```

在此配置中：

1. 根据过去 24 小时内价格的最高百分比变化选择前 15 个交易对。
2. 仅考虑百分比变化在 -10% 和 50% 之间的交易对。

**从蜡烛图读取的示例配置**

```json
"pairlists": [
    {
        "method": "PercentChangePairList",
        "number_assets": 15,
        "sort_key": "percentage",
        "min_value": 0,
        "refresh_period": 3600,
        "lookback_timeframe": "1h",
        "lookback_period": 72
    }
],
```

此示例通过使用 `lookback_timeframe` 作为蜡烛图大小和 `lookback_period` 来指定蜡烛图数量，基于 3 天 1 小时蜡烛图的滚动周期构建百分比变化交易对。

价格百分比变化使用以下公式计算，该公式表示当前蜡烛图的收盘价与前一个蜡烛图的收盘价之间的百分比差异，由指定的时间框架和回溯期定义：

$$ Percent Change = (\frac{Current Close - Previous Close}{Previous Close}) * 100 $$

!!! Warning "范围回溯和刷新周期"
    当与 `lookback_days` 和 `lookback_timeframe` 一起使用时，`refresh_period` 不能小于蜡烛图大小（以秒为单位）。因为这将导致对交易所 API 的不必要请求。

!!! Warning "使用回溯范围时的性能影响"
    如果在与回溯结合使用时在第一位置使用，基于范围的百分比变化计算可能会消耗时间和资源，因为它会下载所有可交易交易对的蜡烛图。因此，强烈建议使用带有 `PercentChangePairList` 的标准方法来缩小交易对列表，以便进一步进行百分比变化计算。

!!! Note "回测"
    `PercentChangePairList` 不支持回测模式。

#### ProducerPairList

使用 `ProducerPairList`，你可以重用来自 [Producer](producer-consumer.md) 的交易对列表，而无需在每个消费者上明确定义交易对列表。

此交易对列表需要 [Consumer 模式](producer-consumer.md) 才能工作。

交易对列表将对当前交易所配置进行活跃交易对检查，以避免尝试在无效市场上交易。

你可以使用可选参数 `number_assets` 限制交易对列表的长度。使用 `"number_assets"=0` 或省略此键将导致重用所有对当前设置有效的生产者交易对。

```json
"pairlists": [
    {
        "method": "ProducerPairList",
        "number_assets": 5,
        "producer_name": "default",
    }
],
```

!!! Tip "组合交易对列表"
    此交易对列表可以与所有其他交易对列表和过滤器结合使用，以进一步减少交易对列表，还可以作为"附加"交易对列表，在已定义的交易对之上。
    `ProducerPairList` 也可以在序列中多次使用，组合来自多个生产者的交易对。
    显然在复杂的配置中，生产者可能不为所有交易对提供数据，因此策略必须适合这种情况。

#### RemotePairList

它允许用户从远程服务器或 freqtrade 目录中本地存储的 json 文件获取交易对列表，从而实现交易交易对列表的动态更新和自定义。

RemotePairList 在配置设置的 pairlists 部分中定义。它使用以下配置选项：

```json
"pairlists": [
    {
        "method": "RemotePairList",
        "mode": "whitelist",
        "processing_mode": "filter",
        "pairlist_url": "https://example.com/pairlist",
        "number_assets": 10,
        "refresh_period": 1800,
        "keep_pairlist_on_failure": true,
        "read_timeout": 60,
        "bearer_token": "my-bearer-token",
        "save_to_file": "user_data/filename.json"
    }
]
```

可选的 `mode` 选项指定交易对列表应用作 `blacklist` 还是 `whitelist`。默认值为"whitelist"。

RemotePairList 配置中的可选 `processing_mode` 选项确定如何处理检索到的交易对列表。它可以有两个值："filter" 或 "append"。默认值为 "filter"。

在 "filter" 模式下，检索到的交易对列表用作过滤器。只有原始交易对列表和检索到的交易对列表中都存在的交易对才会包含在最终交易对列表中。其他交易对被过滤掉。

在 "append" 模式下，检索到的交易对列表将添加到原始交易对列表中。两个列表中的所有交易对都包含在最终交易对列表中，没有任何过滤。

`pairlist_url` 选项指定交易对列表所在的远程服务器的 URL，或本地文件的路径（如果前面加上 file:///）。这允许用户使用远程服务器或本地文件作为交易对列表的源。

`save_to_file` 选项，当提供有效的文件名时，将处理后的交易对列表以 JSON 格式保存到该文件中。此选项是可选的，默认情况下，交易对列表不会保存到文件中。

??? Example "使用共享交易对列表的多机器人示例"

    `save_to_file` 可用于使用 Bot1 将交易对列表保存到文件：

    ```json
    "pairlists": [
        {
            "method": "RemotePairList",
            "mode": "whitelist",
            "pairlist_url": "https://example.com/pairlist",
            "number_assets": 10,
            "refresh_period": 1800,
            "keep_pairlist_on_failure": true,
            "read_timeout": 60,
            "save_to_file": "user_data/filename.json"
        }
    ]
    ```

    Bot2 或任何其他机器人可以使用此配置加载此保存的交易对列表文件：

    ```json
    "pairlists": [
        {
            "method": "RemotePairList",
            "mode": "whitelist",
            "pairlist_url": "file:///user_data/filename.json",
            "number_assets": 10,
            "refresh_period": 10,
            "keep_pairlist_on_failure": true,
        }
    ]
    ```

用户负责提供返回具有以下结构的 JSON 对象的服务器或本地文件：

```json
{
    "pairs": ["XRP/USDT", "ETH/USDT", "LTC/USDT"],
    "refresh_period": 1800
}
```

`pairs` 属性应包含机器人要使用的交易对的字符串列表。`refresh_period` 属性是可选的，指定交易对列表在刷新之前应缓存的秒数。

可选的 `keep_pairlist_on_failure` 指定如果远程服务器无法访问或返回错误，是否应使用先前接收的交易对列表。默认值为 true。

可选的 `read_timeout` 指定等待远程源响应的最长时间（以秒为单位），默认值为 60。

可选的 `bearer_token` 将包含在请求的 Authorization Header 中。

!!! Note
    如果 `keep_pairlist_on_failure` 设置为 true，则在服务器错误的情况下，如果设置为 false，将保留最后接收的交易对列表，则返回空交易对列表。

#### MarketCapPairList

`MarketCapPairList` 根据 CoinGecko 的市值排名对交易对进行排序/过滤。返回的交易对列表将根据它们的市值排名进行排序。

```json
"pairlists": [
    {
        "method": "MarketCapPairList",
        "number_assets": 20,
        "max_rank": 50,
        "refresh_period": 86400,
        "categories": ["layer-1"]
    }
]
```

`number_assets` 定义交易对列表返回的最大交易对数量。`max_rank` 将确定用于创建/过滤交易对列表的最大排名。预计前 `max_rank` 市值中的某些币不会包含在结果交易对列表中，因为并非所有交易对都会在你首选的市场/计价/交易所组合中有活跃的交易对。
虽然支持使用大于 250 的 `max_rank`，但不推荐，因为它会导致对 CoinGecko 的多次 API 调用，这可能会导致速率限制问题。

`refresh_period` 设置定义市值排名数据将刷新的间隔（以秒为单位）。默认值为 86,400 秒（1 天）。交易对列表缓存（`refresh_period`）适用于生成交易对列表（当在列表中的第一个位置时）和过滤实例（当不在列表中的第一个位置时）。

`categories` 设置指定从中选择币的 [coingecko 类别](https://www.coingecko.com/en/categories)。默认值为空列表 `[]`，表示不应用类别过滤。
如果选择了不正确的类别字符串，插件将打印 CoinGecko 的可用类别并失败。类别应该是类别的 ID，例如，对于 `https://www.coingecko.com/en/categories/layer-1`，类别 ID 将是 `layer-1`。你可以传递多个类别，例如 `["layer-1", "meme-token"]` 以从多个类别中选择。

像 1000PEPE/USDT 或 KPEPE/USDT:USDT 这样的币会尽力检测，使用前缀 `1000` 和 `K` 来识别它们。

!!! Warning "许多类别"
    每个添加的类别对应于对 CoinGecko 的一次 API 调用。你添加的类别越多，交易对列表生成时间就越长，可能会导致速率限制问题。

!!! Danger "coingecko 中的重复符号"
    Coingecko 通常有重复的符号，其中同一符号用于不同的币。Freqtrade 将按原样使用该符号并尝试在交易所上搜索它。如果符号存在 - 它将被使用。但是，Freqtrade 不会检查_预期_符号是否是 coingecko 的意思。这有时会导致意外结果，尤其是在低成交量币或模因币类别上。

#### AgeFilter

删除在交易所上市时间少于 `min_days_listed` 天（默认为 `10`）或超过 `max_days_listed` 天（默认 `None` 表示无限）的交易对。

当交易对首次在交易所上市时，它们可能会在前几天经历巨大的价格下跌和波动，而交易对正在经历其价格发现期。机器人通常会在交易对完成价格下跌之前被套牢。

此过滤器允许 freqtrade 忽略交易对，直到它们至少上市 `min_days_listed` 天并在 `max_days_listed` 之前上市。

#### DelistFilter

删除将在交易所从现在开始最多 `max_days_from_now` 天退市的交易对（默认为 `0`，删除所有未来退市的交易对，无论距离多远）。目前此过滤器仅支持以下交易所：

!!! Note "可用交易所"
    Delist 过滤器仅在 Binance 上可用，其中 Binance Futures 将适用于模拟和实盘模式，而 Binance Spot 仅限于实盘模式（出于技术原因）。

!!! Warning "回测"
    `DelistFilter` 不支持回测模式。

#### FullTradesFilter

当交易槽满时（当配置中未将 `max_open_trades` 设置为 `-1` 时），将白名单缩小为仅包含交易中的交易对。

当交易槽满时，没有必要计算其余交易对的指标（除了信息性交易对），因为无法开新交易。通过将白名单缩小到仅交易中的交易对，你可以提高计算速度并降低 CPU 使用率。当交易槽空闲时（交易关闭或配置中的 `max_open_trades` 值增加），白名单将恢复到正常状态。

当使用多个交易对列表过滤器时，建议将此过滤器放在主交易对列表正下方的第二个位置，因此当交易槽满时，机器人不必为其余过滤器下载数据。

!!! Warning "回测"
    `FullTradesFilter` 不支持回测模式。

#### OffsetFilter

通过给定的 `offset` 值偏移传入的交易对列表。

例如，它可以与 `VolumeFilter` 结合使用以删除前 X 个成交量交易对。或者在两个机器人实例上拆分更大的交易对列表。

删除交易对列表中的前 10 个交易对并获取接下来的 20 个（获取初始列表的 10-30 项）的示例：

```json
"pairlists": [
    // ...
    {
        "method": "OffsetFilter",
        "offset": 10,
        "number_assets": 20
    }
],
```

!!! Warning
    当 `OffsetFilter` 与 `VolumeFilter` 结合使用以在多个机器人之间拆分更大的交易对列表时，由于 `VolumeFilter` 的刷新间隔略有不同，因此无法保证交易对不会重叠。

!!! Note
    大于传入交易对列表总长度的偏移量将导致空交易对列表。

#### PerformanceFilter

按过去的交易表现排序交易对，如下所示：

1. 正面表现。
2. 尚未关闭交易。
3. 负面表现。

交易计数用作决胜局。

你可以使用 `minutes` 参数仅考虑过去 X 分钟的表现（滚动窗口）。
未定义此参数（或将其设置为 0）将使用所有时间的表现。

可选的 `min_profit`（作为比率 -> 设置 `0.01` 对应于 1%）参数定义交易对必须具有的最小利润才能被考虑。
低于此级别的交易对将被过滤掉。
强烈不建议在没有 `minutes` 的情况下使用此参数，因为它可能会导致空交易对列表，无法恢复。

```json
"pairlists": [
    // ...
    {
        "method": "PerformanceFilter",
        "minutes": 1440,  // 滚动 24 小时
        "min_profit": 0.01  // 最小利润 1%
    }
],
```

由于此过滤器使用机器人的过去表现，它将有一些启动期 - 应仅在机器人在数据库中有几百笔交易后使用。

!!! Warning "回测"
    `PerformanceFilter` 不支持回测模式。

#### PrecisionFilter

过滤不允许设置止损的低价值币。

也就是说，如果交易所的精度舍入导致止损价格变化 1% 或更多，即 `rounded(stop_price) <= rounded(stop_price * 0.99)`，交易对将被列入黑名单。这个想法是避免价值非常接近其下限交易边界的币，不允许设置适当的止损。

!!! Tip "PrecisionFilter 对期货交易毫无意义"
    以上不适用于空头。对于多头，理论上交易将首先被清算。

!!! Warning "回测"
    `PrecisionFilter` 不支持使用多个策略的回测模式。

#### PriceFilter

`PriceFilter` 允许按价格过滤交易对。目前支持以下价格过滤器：

* `min_price`
* `max_price`
* `max_value`
* `low_price_ratio`

`min_price` 设置删除价格低于指定价格的交易对。如果你希望避免交易非常低价的交易对，这很有用。
此选项默认禁用，仅在设置为 > 0 时才会应用。

`max_price` 设置删除价格高于指定价格的交易对。如果你希望仅交易低价交易对，这很有用。
此选项默认禁用，仅在设置为 > 0 时才会应用。

`max_value` 设置删除最小价值变化高于指定值的交易对。
当交易所的限制不平衡时，这很有用。例如，如果 step-size = 1（所以你只能买 1、2 或 3，但不能买 1.1 个币） - 并且价格相当高（如 20\$），因为自上次限制调整以来，币已大幅上涨。
由于上述原因，你只能购买 20\\$、或 40\$ - 但不能购买 25\$。
在从接收货币中扣除费用的交易所（例如 binance）上 - 这可能会导致高价值币/金额无法出售，因为金额略低于限制。

`low_price_ratio` 设置删除提高 1 个价格单位（pip）高于 `low_price_ratio` 比率的交易对。
此选项默认禁用，仅在设置为 > 0 时才会应用。

对于 `PriceFilter`，必须应用其 `min_price`、`max_price` 或 `low_price_ratio` 设置中的至少一个。

计算示例：

SHITCOIN/BTC 的最小价格精度为 8 位小数。如果其价格为 0.00000011 - 上面的一个价格步长将是 0.00000012，这比前一个价格值高约 9%。你可以通过使用 `low_price_ratio` 设置为 0.09（9%）的 PriceFilter 过滤掉此交易对，或相应地将 `min_price` 设置为 0.00000011。

!!! Warning "低价交易对"
    具有高"1 pip 移动"的低价交易对很危险，因为它们通常流动性不足，并且可能无法放置所需的止损，这通常会导致高损失，因为价格需要四舍五入到下一个可交易价格 - 因此，不是有 -5% 的止损，你可能会因为价格四舍五入而最终得到 -9% 的止损。

#### ShuffleFilter

随机化（随机化）交易对列表中的交易对。当你希望所有交易对以相同的优先级处理时，它可用于防止机器人比其他交易对更频繁地交易某些交易对。

默认情况下，ShuffleFilter 将每根蜡烛图随机化一次交易对。
要在每次迭代时随机化，请将 `"shuffle_frequency"` 设置为 `"iteration"` 而不是默认的 `"candle"`。

``` json
    {
        "method": "ShuffleFilter",
        "shuffle_frequency": "candle",
        "seed": 42
    }

```

!!! Tip
    你可以为此交易对列表设置 `seed` 值以获得可重现的结果，这对于重复回测会话很有用。如果未设置 `seed`，交易对将以不可重复的随机顺序随机化。ShuffleFilter 将自动检测运行模式，并仅为回测模式应用 `seed` - 如果设置了 `seed` 值。

#### SpreadFilter

删除买价和卖价之间的差异高于指定比率 `max_spread_ratio`（默认为 `0.005`）的交易对。

示例：

如果 `DOGE/BTC` 最大买价为 0.00000026，最小卖价为 0.00000027，则比率计算为：`1 - bid/ask ~= 0.037`，即 `> 0.005`，此交易对将被过滤掉。

#### RangeStabilityFilter

删除过去 `lookback_days` 天内最低低点和最高高点之间的差异低于 `min_rate_of_change` 或高于 `max_rate_of_change` 的交易对。由于这是一个需要额外数据的过滤器，结果会缓存 `refresh_period`。

在下面的示例中：
如果过去 10 天的交易范围 <1% 或 >99%，则从白名单中删除交易对。

```json
"pairlists": [
    {
        "method": "RangeStabilityFilter",
        "lookback_days": 10,
        "min_rate_of_change": 0.01,
        "max_rate_of_change": 0.99,
        "refresh_period": 86400
    }
]
```

添加 `"sort_direction": "asc"` 或 `"sort_direction": "desc"` 为此交易对列表启用排序。

!!! Tip
    此过滤器可用于自动删除稳定币对，它们具有非常低的交易范围，因此很难盈利地交易。
    此外，它还可用于自动删除在给定时间内具有极端高/低方差的交易对。

#### VolatilityFilter

波动性是交易对随时间的历史变化程度，它由对数日收益率的标准偏差来衡量。假设收益率呈正态分布，尽管实际分布可能不同。在正态分布中，68% 的观察值落在一个标准偏差内，95% 的观察值落在两个标准偏差内。假设波动率为 0.05 意味着 30 天中的 20 天的预期回报预计将小于 5%（一个标准偏差）。波动率是预期回报偏差的正比率，可以大于 1.00。请参考 [`volatility`](https://en.wikipedia.org/wiki/Volatility_(finance)) 的维基百科定义。

如果过去 `lookback_days` 天的平均波动率低于 `min_volatility` 或高于 `max_volatility`，此过滤器将删除交易对。由于这是一个需要额外数据的过滤器，结果会缓存 `refresh_period`。

此过滤器可用于将交易对缩小到某个波动率或避免非常波动的交易对。

在下面的示例中：
如果过去 10 天的波动率不在 0.05-0.50 的范围内，则从白名单中删除交易对。该过滤器每 24 小时应用一次。

```json
"pairlists": [
    {
        "method": "VolatilityFilter",
        "lookback_days": 10,
        "min_volatility": 0.05,
        "max_volatility": 0.50,
        "refresh_period": 86400
    }
]
```

添加 `"sort_direction": "asc"` 或 `"sort_direction": "desc"` 为此交易对列表启用排序模式。

### 交易对列表处理器的完整示例

下面的示例将 `BNB/BTC` 列入黑名单，使用带有 `20` 个资产的 `VolumePairList`，按 `quoteVolume` 对交易对进行排序，然后使用 [`DelistFilter`](#delistfilter) 和 [`AgeFilter`](#agefilter) 过滤未来退市的交易对以删除上市少于 10 天前的交易对。之后应用 [`PrecisionFilter`](#precisionfilter) 和 [`PriceFilter`](#pricefilter)，过滤所有 1 个价格单位 > 1% 的资产。然后应用 [`SpreadFilter`](#spreadfilter) 和 [`VolatilityFilter`](#volatilityfilter)，最后使用随机种子设置为某个预定义值对交易对进行随机化。

```json
"exchange": {
    "pair_whitelist": [],
    "pair_blacklist": ["BNB/BTC"]
},
"pairlists": [
    {
        "method": "VolumePairList",
        "number_assets": 20,
        "sort_key": "quoteVolume"
    },
    {
        "method": "DelistFilter",
        "max_days_from_now": 0,
    },
    {"method": "AgeFilter", "min_days_listed": 10},
    {"method": "PrecisionFilter"},
    {"method": "PriceFilter", "low_price_ratio": 0.01},
    {"method": "SpreadFilter", "max_spread_ratio": 0.005},
    {
        "method": "RangeStabilityFilter",
        "lookback_days": 10,
        "min_rate_of_change": 0.01,
        "refresh_period": 86400
    },
    {
        "method": "VolatilityFilter",
        "lookback_days": 10,
        "min_volatility": 0.05,
        "max_volatility": 0.50,
        "refresh_period": 86400
    },
    {"method": "ShuffleFilter", "seed": 42}
],
```
