# 高级回测分析

## 分析买入/入场与卖出/出场标签

了解一个策略在不同买入标签下的行为方式非常有帮助，这样可以比默认回测输出提供的结果查看更多关于每个买卖条件的复杂统计信息。你也可能希望确认触发交易开仓时信号蜡烛上的指标数值。

!!! Note
    下述买入原因分析仅适用于回测，*不适用于 hyperopt*。

我们需要在回测时将 `--export` 选项设置为 `signals`，以便导出信号**以及**交易：

``` bash
freqtrade backtesting -c <config.json> --timeframe <tf> --strategy <strategy_name> --timerange=<timerange> --export=signals
```

这会告诉 freqtrade 输出一个包含策略、交易对，以及触发入场和出场信号的蜡烛 DataFrame 的 pickle 字典。
根据策略的入场次数，文件可能会非常大，因此请定期检查 `user_data/backtest_results` 目录并删除旧的导出文件。

在运行下一次回测前，请确保删除旧的回测结果，或者在回测时使用 `--cache none` 选项，以避免使用缓存结果。

如果一切顺利，你现在应该可以在 `user_data/backtest_results` 目录中看到 `backtest-result-{timestamp}_signals.pkl` 和 `backtest-result-{timestamp}_exited.pkl` 文件。

要分析入场/出场标签，我们需要使用 `freqtrade backtesting-analysis` 命令，并配合以空格分隔参数的 `--analysis-groups` 选项：

``` bash
freqtrade backtesting-analysis -c <config.json> --analysis-groups 0 1 2 3 4 5
```

该命令会读取最近一次回测的结果。`--analysis-groups` 选项用来指定各类表格输出，显示每个分组或交易的收益，范围从最简单的（0）到按交易对、买入标签、卖出标签详细划分（4）：

* 0：按 enter_tag 汇总的整体胜率与收益
* 1：按 enter_tag 汇总的收益
* 2：按 enter_tag 与 exit_tag 汇总的收益
* 3：按交易对与 enter_tag 汇总的收益
* 4：按交易对、enter_tag 与 exit_tag 汇总的收益（可能非常庞大）
* 5：按 exit_tag 汇总的收益

使用 `-h` 选项可以查看更多参数。

### 使用 backtest-filename

默认情况下，`backtesting-analysis` 会处理 `user_data/backtest_results` 目录中最近的回测结果。
如果你想分析更早的回测结果，可以使用 `--backtest-filename` 指定目标文件。这样只需提供相关回测结果的文件名，就能随时重新查看和分析历史回测输出：

``` bash
freqtrade backtesting-analysis -c <config.json> --timeframe <tf> --strategy <strategy_name> --timerange <timerange> --export signals --backtest-filename backtest-result-2025-03-05_20-38-34.zip
```

你应该会在日志中看到类似下面的输出，其中包含导出的带时间戳的文件名：

```
2022-06-14 16:28:32,698 - freqtrade.misc - INFO - dumping json to "mystrat_backtest-2022-06-14_16-28-32.json"
```

随后你就可以在 `backtesting-analysis` 中使用该文件名：

```
freqtrade backtesting-analysis -c <config.json> --backtest-filename=mystrat_backtest-2022-06-14_16-28-32.json
```

如果结果文件位于其他目录，可以使用 `--backtest-directory` 指定目录：

``` bash
freqtrade backtesting-analysis -c <config.json> --backtest-directory custom_results/ --backtest-filename mystrat_backtest-2022-06-14_16-28-32.json
```

### 调整要显示的买入/卖出标签

若只想展示特定的买入和卖出标签，可使用以下两个参数：

```
--enter-reason-list : 需要分析的买入信号（以空格分隔）。默认值："all"
--exit-reason-list : 需要分析的卖出信号（以空格分隔）。默认值："all"
```

例如：

```bash
freqtrade backtesting-analysis -c <config.json> --analysis-groups 0 2 --enter-reason-list enter_tag_a enter_tag_b --exit-reason-list roi custom_exit_tag_a stop_loss
```

### 输出信号蜡烛上的指标数值

`freqtrade backtesting-analysis` 的真正强大之处，在于它能够打印信号蜡烛上的指标值，从而对买入信号指标进行细粒度的观察和调优。要打印某组指标的列，可以使用 `--indicator-list` 选项：

```bash
freqtrade backtesting-analysis -c <config.json> --analysis-groups 0 2 --enter-reason-list enter_tag_a enter_tag_b --exit-reason-list roi custom_exit_tag_a stop_loss --indicator-list rsi rsi_1h bb_lowerband ema_9 macd macdsignal
```

这些指标必须已经存在于策略的主 DataFrame 中（无论是主时间框架还是信息时间框架），否则脚本会忽略这些指标列。

当仅在终端输出时，表格的可读性可能不佳，因此推荐配合 `--analysis-to-csv` 等选项导出为 CSV 文件，在电子表格软件中查看。

默认会输出使用分析组设置的指标，不过你也可以手动指定指标列表。例如：

```
freqtrade backtesting-analysis -c user_data/config.json --analysis-groups 0 --indicator-list chikou_span tenkan_sen
```

在这个例子中，我们希望在交易的入场和出场点显示 `chikou_span` 与 `tenkan_sen` 指标值。

指标输出示例如下：

| pair      | open_date                 | enter_reason | exit_reason | chikou_span (entry) | tenkan_sen (entry) | chikou_span (exit) | tenkan_sen (exit) |
|-----------|---------------------------|--------------|-------------|---------------------|--------------------|--------------------|-------------------|
| DOGE/USDT | 2024-07-06 00:35:00+00:00 |              | exit_signal | 0.105               | 0.106              | 0.105              | 0.107             |
| BTC/USDT  | 2024-08-05 14:20:00+00:00 |              | roi         | 54643.440           | 51696.400          | 54386.000          | 52072.010         |

如表格所示，`chikou_span (entry)` 表示交易入场时的指标值，而 `chikou_span (exit)` 表示出场时的指标值。这类指标视图能够显著提升分析效果。

为了区分交易的入场和出场点，指标名称会添加 `(entry)` 与 `(exit)` 后缀。

!!! Note "Trade-wide Indicators"
    某些横跨整个交易的指标没有 `(entry)` 或 `(exit)` 后缀。这些指标包括：`pair`、`stake_amount`、`max_stake_amount`、`amount`、`open_date`、`close_date`、`open_rate`、`close_rate`、`fee_open`、`fee_close`、`trade_duration`、`profit_ratio`、`profit_abs`、`exit_reason`、`initial_stop_loss_abs`、`initial_stop_loss_ratio`、`stop_loss_abs`、`stop_loss_ratio`、`min_rate`、`max_rate`、`is_open`、`enter_tag`、`leverage`、`is_short`、`open_timestamp`、`close_timestamp` 以及 `orders`

#### 基于入场或出场信号过滤指标

默认情况下，`--indicator-list` 会同时展示入场和出场信号的指标值。若只想显示入场信号，请使用 `--entry-only`；若只想显示出场信号，请使用 `--exit-only`。

只显示入场信号指标的示例：

```bash
freqtrade backtesting-analysis -c user_data/config.json --analysis-groups 0 --indicator-list chikou_span tenkan_sen --entry-only
```

只显示出场信号指标的示例：

```bash
freqtrade backtesting-analysis -c user_data/config.json --analysis-groups 0 --indicator-list chikou_span tenkan_sen --exit-only
```

!!! note 
    使用这些过滤器时，指标名称不会添加 `(entry)` 或 `(exit)` 后缀。

### 按日期过滤交易输出

若想仅展示回测时间范围内特定日期区间的交易，可使用常规的 `timerange` 参数，格式为 `YYYYMMDD-[YYYYMMDD]`：

```
--timerange : 用于过滤交易输出的时间范围，起始日期包含，结束日期不包含。例如 20220101-20221231
```

例如，如果你的回测区间是 `20220101-20221231`，但只想输出 1 月份的交易：

```bash
freqtrade backtesting-analysis -c <config.json> --timerange 20220101-20220201
```

### 打印被拒绝的信号

使用 `--rejected-signals` 选项可以打印被拒绝的信号。

```bash
freqtrade backtesting-analysis -c <config.json> --rejected-signals
```

### 将表格写入 CSV

由于部分表格输出可能很大，直接打印到终端并不理想。
使用 `--analysis-to-csv` 选项可以禁用标准输出的表格内容，并改为写入 CSV 文件。

```bash
freqtrade backtesting-analysis -c <config.json> --analysis-to-csv
```

默认情况下，脚本会为 `backtesting-analysis` 命令中指定的每个输出表格生成一个文件，例如：

```bash
freqtrade backtesting-analysis -c <config.json> --analysis-to-csv --rejected-signals --analysis-groups 0 1
```

这会在 `user_data/backtest_results` 目录中写入：

* rejected_signals.csv
* group_0.csv
* group_1.csv

若要自定义文件的输出位置，可额外指定 `--analysis-csv-path` 参数。

```bash
freqtrade backtesting-analysis -c <config.json> --analysis-to-csv --analysis-csv-path another/data/path/
```
