# 绘图

本页介绍如何绘制价格、指标与收益图表。

!!! Warning "已弃用"
    本页涉及的 `plot-dataframe`、`plot-profit` 命令已处于维护模式，存在性能限制（即便中等规模的图表也可能较慢），而且“生成文件后再手动打开浏览器”也不够直观。虽然暂无立即移除计划，但若后续维护成本过高，可能会在短期内下线。日常建议使用 [FreqUI](freq-ui.md) 查看图表。

## 安装与配置

绘图模块依赖 Plotly，可通过以下命令安装或更新：

```bash
pip install -U -r requirements-plot.txt
```

## 绘制价格与指标

`freqtrade plot-dataframe` 会生成交互式图表，包含：

* 主图：K 线及跟随价格的指标（如 SMA/EMA）
* 成交量柱状图
* 额外指标（通过 `--indicators2` 指定）

![plot-dataframe](assets/plot-dataframe.png)

可选参数：

--8<-- "commands/plot-dataframe.md"

示例：

```bash
freqtrade plot-dataframe -p BTC/ETH --strategy AwesomeStrategy
```

`-p/--pairs` 用于指定需要绘制的交易对。每个交易对会单独生成一个文件。

自定义指标：

```bash
freqtrade plot-dataframe --strategy AwesomeStrategy -p BTC/ETH --indicators1 sma ema --indicators2 macd
```

### 更多用法示例

多交易对：

```bash
freqtrade plot-dataframe --strategy AwesomeStrategy -p BTC/ETH XRP/ETH
```

限定时间范围：

```bash
freqtrade plot-dataframe --strategy AwesomeStrategy -p BTC/ETH --timerange=20180801-20180805
```

使用数据库中的交易记录：

```bash
freqtrade plot-dataframe --strategy AwesomeStrategy --db-url sqlite:///tradesv3.dry_run.sqlite -p BTC/ETH --trade-source DB
```

使用回测导出的交易：

```bash
freqtrade plot-dataframe --strategy AwesomeStrategy --export-filename user_data/backtest_results/backtest-result.json -p BTC/ETH
```

### 图表元素说明

![plot-dataframe2](assets/plot-dataframe2.png)

`plot-dataframe` 需要回测数据、策略，以及包含对应交易记录的导出文件或数据库。生成的图表元素包括：

* 绿色三角：策略买入信号（并非所有信号都会真实下单）
* 红色三角：策略卖出信号
* 青色圆点：实际交易的入场点
* 红色方块：亏损或 0% 盈亏的平仓点
* 绿色方块：盈利平仓点
* 与价格同量纲的指标（`--indicators1`）
* 成交量柱状图
* 与价格量纲不同的指标（`--indicators2`）

!!! Note "布林带"
    如果 DataFrame 中存在 `bb_lowerband`、`bb_upperband`，会自动绘制成淡蓝色区域。

#### 高级绘图配置

可在策略的 `plot_config` 中配置高级样式，如自定义颜色、添加子图与填充区域等。

`type` 支持 `scatter`（默认，对应 `plotly.graph_objects.Scatter`）与 `bar`（`plotly.graph_objects.Bar`）；额外的 plotly 关键字参数可放在 `plotly` 字段中。

示例（摘录）：

```python
@property
def plot_config(self):
    plot_config = {"main_plot": {}, "subplots": {}}
    plot_config["main_plot"] = {
        "ema_10": {"color": "red"},
        "ema_50": {"color": "#CCCCCC"},
        "senkou_a": {
            "color": "green",
            "fill_to": "senkou_b",
            "fill_label": "Ichimoku Cloud",
            "fill_color": "rgba(255,76,46,0.2)",
        },
        "senkou_b": {},
    }
    plot_config["subplots"] = {
        "MACD": {
            "macd": {"color": "blue", "fill_to": "macdhist"},
            "macdsignal": {"color": "orange"},
            "macdhist": {"type": "bar", "plotly": {"opacity": 0.9}},
        },
        "RSI": {"rsi": {"color": "red"}},
    }
    return plot_config
```

??? Note "属性写法（旧方式）"
    也可通过类属性赋值，不过无法访问策略参数，灵活性较差：

    ```python
    plot_config = {
        "main_plot": {
            "ema10": {"color": "red"},
            "ema50": {"color": "#CCCCCC"},
            "senkou_a": {
                "color": "green",
                "fill_to": "senkou_b",
                "fill_label": "Ichimoku Cloud",
                "fill_color": "rgba(255,76,46,0.2)",
            },
            "senkou_b": {},
        },
        "subplots": {
            "MACD": {
                "macd": {"color": "blue", "fill_to": "macdhist"},
                "macdsignal": {"color": "orange"},
                "macdhist": {"type": "bar", "plotly": {"opacity": 0.9}},
            },
            "RSI": {"rsi": {"color": "red"}},
        },
    }
    ```

!!! Note
    配置中引用的指标列（如 `ema10`、`macd`、`rsi` 等）必须存在于策略生成的 DataFrame 中。

!!! Warning
    `plotly` 参数仅在 Plotly 中生效，与 FreqUI 无关。

!!! Note "仓位调整"
    如果启用了 `position_adjustment_enable` / `adjust_trade_position()`，多次加仓会导致平均开仓价偏移，平仓点可能不在蜡烛范围内。

## 绘制收益

![plot-profit](assets/plot-profit.png)

`plot-profit` 会展示：

* 所有交易对的平均收盘价
* 回测累计收益（估算值，非真实收益）
* 单个交易对的收益记录
* 并行交易情况（是否用满 `max_open_trades`）
* 回撤（Underwater 图）

该工具可帮助你判断策略是在小幅稳定盈利，还是偶尔大涨大跌，也能分析回撤与并行交易情况。

常用参数：

--8<-- "commands/plot-profit.md"

示例：

自定义回测文件：

```bash
freqtrade plot-profit -p LTC/BTC --export-filename user_data/backtest_results/backtest-result.json
```

使用数据库：

```bash
freqtrade plot-profit -p LTC/BTC --db-url sqlite:///tradesv3.sqlite --trade-source DB
```

或指定数据目录：

```bash
freqtrade --datadir user_data/data/binance_save/ plot-profit -p LTC/BTC
```

`plot-profit` 同样会为指定的交易对生成图表，便于分析收益曲线、回撤区间与交易频度等指标。
