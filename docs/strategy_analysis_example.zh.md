# 策略分析示例

调试策略往往耗时费力。Freqtrade 提供了一套 Notebook 示例，帮助你可视化原始数据。本教程基于 SampleStrategy、Binance 5 分钟数据（已下载到默认目录）。

## 环境准备

### 切换到项目根目录

```python
import os
from pathlib import Path

project_root = "somedir/freqtrade"
i = 0
try:
    os.chdir(project_root)
    if not Path("LICENSE").is_file():
        while i < 4 and (not Path("LICENSE").is_file()):
            os.chdir(Path(Path.cwd(), "../"))
            i += 1
        project_root = Path.cwd()
except FileNotFoundError:
    print("请正确设置项目根目录")
print(Path.cwd())
```

### 配置 Freqtrade 环境

```python
from freqtrade.configuration import Configuration

config = Configuration.from_files([])
# 或使用已有配置：
# config = Configuration.from_files(["user_data/config.json"])
config["timeframe"] = "5m"
config["strategy"] = "SampleStrategy"
data_location = config["datadir"]
pair = "BTC/USDT"
```

### 加载历史数据

```python
from freqtrade.data.history import load_pair_history
from freqtrade.enums import CandleType

candles = load_pair_history(
    datadir=data_location,
    timeframe=config["timeframe"],
    pair=pair,
    data_format="json",
    candle_type=CandleType.SPOT,
)
print(f"Loaded {len(candles)} rows for {pair}")
candles.head()
```

## 加载策略并生成信号

```python
from freqtrade.data.dataprovider import DataProvider
from freqtrade.resolvers import StrategyResolver

strategy = StrategyResolver.load_strategy(config)
strategy.dp = DataProvider(config, None, None)
strategy.ft_bot_start()
df = strategy.analyze_ticker(candles, {"pair": pair})
df.tail()
```

### 查看 DataFrame

```python
print(f"Generated {df['enter_long'].sum()} entry signals")
data = df.set_index("date")
data.tail()
```

常见诊断项：

- 指标列末尾是否存在 NaN
- `crossed_*` 使用的列单位是否一致
- 信号次数多，并不代表实际交易次数；回测会受 `max_open_trades`、订单是否成交等因素影响

## 载入历史回测结果

若已使用命令行完成回测，可读取结果进行深入分析。

```python
from freqtrade.data.btanalysis import load_backtest_data, load_backtest_stats
from freqtrade.configuration import Configuration

# config = Configuration.from_files(["user_data/config.json"])
backtest_dir = config["user_data_dir"] / "backtest_results"
strategy = config["strategy"]
stats = load_backtest_stats(backtest_dir)
```

### 统计指标

```python
strategy_stats = stats["strategy"][strategy]
print(strategy_stats["max_drawdown"])
print(strategy_stats["daily_profit"])
```

### 加载交易记录

```python
trades = load_backtest_data(backtest_dir)
trades.groupby("pair")["exit_reason"].value_counts()
```

## 绘制权益曲线

```python
import pandas as pd
import plotly.express as px

df = pd.DataFrame(strategy_stats["daily_profit"], columns=["dates", "equity"])
df["equity_daily"] = df["equity"].cumsum()
fig = px.line(df, x="dates", y="equity_daily")
fig.show()
```

## 分析实时交易数据

```python
from freqtrade.data.btanalysis import load_trades_from_db
trades_live = load_trades_from_db("sqlite:///tradesv3.sqlite")
trades_live.groupby("pair")["exit_reason"].value_counts()
```

## 并行交易分析

了解并行仓位数量有助于调整 `max_open_trades`。

```python
from freqtrade.data.btanalysis import analyze_trade_parallelism

parallel = analyze_trade_parallelism(trades, "5m")
parallel.plot()
```

## 可视化信号与交易

Freqtrade 提供基于 Plotly 的交互式图表。

```python
from freqtrade.plot.plotting import generate_candlestick_graph

trades_pair = trades.loc[trades["pair"] == pair]
data_slice = data["2019-06-01":"2019-06-10"]
graph = generate_candlestick_graph(
    pair=pair,
    data=data_slice,
    trades=trades_pair,
    indicators1=["sma20", "ema50", "ema55"],
    indicators2=["rsi", "macd", "macdsignal", "macdhist"],
)
graph.show()        # inline
# graph.show(renderer="browser")  # 在浏览器中打开
```

## 收益分布图

```python
import plotly.figure_factory as ff

hist_data = [trades.profit_ratio]
fig = ff.create_distplot(hist_data, ["profit_ratio"], bin_size=0.01)
fig.show()
```

## 结语

通过上述 Notebook 示例，可快速诊断策略问题、分析回测与实盘数据，并可视化信号与收益。如果你有更好的分析方法，欢迎提交 Issue 或 Pull Request 与社区共享。
