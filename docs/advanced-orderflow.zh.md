# Orderflow 数据

本指南将引导您了解如何在 Freqtrade 中利用公共交易数据进行高级订单流分析。

!!! Warning "实验性功能"
    订单流功能目前处于测试阶段，可能会在未来版本中发生变化。请在 [Freqtrade GitHub 仓库](https://github.com/freqtrade/freqtrade/issues)上报告任何问题或反馈。
    目前该功能尚未与 freqAI 一起测试 - 将这两个功能结合使用目前被认为超出范围。

!!! Warning "性能提示"
    Orderflow 需要原始交易数据。这些数据相当大，可能会导致初始启动缓慢，因为 freqtrade 需要下载最近 X 根蜡烛的交易数据。此外，启用此功能将导致内存使用量增加。请确保有足够的资源可用。

## 入门指南

### 启用公共交易数据

在您的 `config.json` 文件中，在 `exchange` 部分将 `use_public_trades` 选项设置为 true。

```json
"exchange": {
   ...
   "use_public_trades": true,
}
```

### 配置 Orderflow 处理

在 config.json 的 orderflow 部分定义您所需的订单流处理设置。在这里，您可以调整以下因素：

- `cache_size`: 将多少个先前的订单流蜡烛保存到缓存中，而不是每根新蜡烛都重新计算
- `max_candles`: 过滤您想要获取交易数据的蜡烛数量。
- `scale`: 控制足迹图的价格区间大小。
- `stacked_imbalance_range`: 定义需要考虑的最小连续不平衡价格水平数量。
- `imbalance_volume`: 过滤掉低于此阈值的不平衡量。
- `imbalance_ratio`: 过滤掉比率（买卖量之间的差异）低于此值的不平衡。

```json
"orderflow": {
    "cache_size": 1000, 
    "max_candles": 1500, 
    "scale": 0.5, 
    "stacked_imbalance_range": 3, //  需要至少这么多个不平衡彼此相邻
    "imbalance_volume": 1, //  过滤掉低于此值的
    "imbalance_ratio": 3 //  过滤掉比率低于此值的
  },
```

## 下载用于回测的交易数据

要下载用于回测的历史交易数据，请在 freqtrade download-data 命令中使用 --dl-trades 标志。

```bash
freqtrade download-data -p BTC/USDT:USDT --timerange 20230101- --trading-mode futures --timeframes 5m --dl-trades
```

!!! Warning "数据可用性"
    并非所有交易所都提供公共交易数据。对于支持的交易所，如果您使用 `--dl-trades` 标志开始下载数据时公共交易数据不可用，freqtrade 会发出警告。

## 访问 Orderflow 数据

一旦激活，您的 dataframe 中将提供多个新列：

``` python

dataframe["trades"] # 包含每笔单独交易的信息。
dataframe["orderflow"] # 表示足迹图字典（见下文）
dataframe["imbalances"] # 包含订单流中不平衡的信息。
dataframe["bid"] # 总买入量
dataframe["ask"] # 总卖出量
dataframe["delta"] # 买卖量之间的差异。
dataframe["min_delta"] # 蜡烛内的最小 delta
dataframe["max_delta"] # 蜡烛内的最大 delta
dataframe["total_trades"] # 总交易数量
dataframe["stacked_imbalances_bid"] # 堆叠买入不平衡范围开始的价格水平列表
dataframe["stacked_imbalances_ask"] # 堆叠卖出不平衡范围开始的价格水平列表
```

您可以在策略代码中访问这些列以进行进一步分析。以下是一个示例：

``` python
def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    # 计算累积 delta
    dataframe["cum_delta"] = cumulative_delta(dataframe["delta"])
    # 访问总交易数
    total_trades = dataframe["total_trades"]
    ...

def cumulative_delta(delta: Series):
    cumdelta = delta.cumsum()
    return cumdelta

```

### 足迹图 (`dataframe["orderflow"]`)

此列提供了不同价格水平的买卖订单的详细分类，为订单流动态提供了宝贵的见解。配置中的 `scale` 参数决定了此表示的价格区间大小。

`orderflow` 列包含一个具有以下结构的字典：

``` output
{
    "price": {
        "bid_amount": 0.0,
        "ask_amount": 0.0,
        "bid": 0,
        "ask": 0,
        "delta": 0.0,
        "total_volume": 0.0,
        "total_trades": 0
    }
}
```

#### Orderflow 列说明

- key: 价格区间 - 以 `scale` 间隔分箱
- `bid_amount`: 每个价格水平买入的总量。
- `ask_amount`: 每个价格水平卖出的总量。
- `bid`: 每个价格水平的买入订单数量。
- `ask`: 每个价格水平的卖出订单数量。
- `delta`: 每个价格水平买卖量之间的差异。
- `total_volume`: 每个价格水平的总量（卖出量 + 买入量）。
- `total_trades`: 每个价格水平的总交易数量（卖出 + 买入）。

通过利用这些功能，您可以获得对市场情绪的宝贵见解，并基于订单流分析识别潜在的交易机会。

### 原始交易数据 (`dataframe["trades"]`)

包含蜡烛期间发生的单独交易的列表。此数据可用于更精细的订单流动态分析。

每个单独的条目包含一个具有以下键的字典：

- `timestamp`: 交易的时间戳。
- `date`: 交易的日期。
- `price`: 交易的价格。
- `amount`: 交易的量。
- `side`: 买入或卖出。
- `id`: 交易的唯一标识符。
- `cost`: 交易的总成本（价格 * 数量）。

### 不平衡 (`dataframe["imbalances"]`)

此列提供了一个包含订单流中不平衡信息的字典。当给定价格水平的买卖量之间存在显著差异时，就会发生不平衡。

每行如下所示 - 以价格作为索引，以及相应的买入和卖出不平衡值作为列：

``` output
{
    "price": {
        "bid_imbalance": False,
        "ask_imbalance": False
    }
}
```
