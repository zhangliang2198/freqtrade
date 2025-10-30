# 回测

本页介绍如何使用回测来验证策略表现。

回测需要事先准备好历史数据。关于如何获取目标交易所和交易对的数据，请参阅文档中的[数据下载](data-download.md)章节。

回测同样可以通过[Web 服务模式](freq-ui.md#backtesting)运行，借助 Web 界面发起回测。

## 回测命令参考

--8<-- "commands/backtesting.md"

## 使用回测测试你的策略

当你已经拥有良好的买入与卖出逻辑以及一些历史数据时，就可以把它们套用到真实数据上测试，这就是所谓的[回测](https://en.wikipedia.org/wiki/Backtesting)。

回测会使用配置文件中的交易对，并默认从 `user_data/data/<exchange>` 加载历史 K 线（OHLCV）数据。如果某个交易所/交易对/时间框架组合没有数据，回测会提示你先执行 `freqtrade download-data` 下载。有关数据下载的细节请参阅[数据下载](data-download.md)章节。

回测结果能帮助你判断机器人在盈利和亏损之间哪种情况更占优势。

所有利润计算都包含手续费；Freqtrade 会采用交易所的默认费率来计算。

!!! Warning "在回测中使用动态交易对列表"
    可以使用动态交易对列表（并非所有 Handler 都允许在回测模式下使用），但它依赖当前的市场状况，无法反映历史上的交易对列表。
    而且，只要使用了非 `StaticPairlist` 的列表，回测结果都无法保证可复现。
    想了解更多信息，请阅读[交易对列表文档](plugins.md#pairlists)。

    如需获得可复现的结果，最好先通过 [`test-pairlist`](utils.md#test-pairlist) 命令生成固定的交易对列表，并以此作为静态列表。

!!! Note
    默认情况下，Freqtrade 会把回测结果导出到 `user_data/backtest_results`。
    导出的交易数据可用于[进一步分析](#更多回测结果分析)或通过脚本目录中的[绘图子命令](plotting.md#plot-price-and-indicators)（`freqtrade plot-dataframe`）生成图表。

### 初始资金

回测需要一个初始资金，可以通过命令行参数 `--dry-run-wallet <金额>` 或 `--starting-balance <金额>` 提供，也可以在配置文件中设置 `dry_run_wallet`。该数值必须大于 `stake_amount`，否则无法模拟交易。

### 动态下单金额

回测支持[动态下单金额](configuration.md#dynamic-stake-amount)。当 `stake_amount` 设置为 `"unlimited"` 时，初始资金会被平均分配到 `max_open_trades` 个槽位。较早成交的盈利会提升后续下单金额，使收益在回测期间自动复利。

### 回测命令示例

使用默认的 5 分钟 K 线：

```bash
freqtrade backtesting --strategy AwesomeStrategy
```

其中 `--strategy AwesomeStrategy` / `-s AwesomeStrategy` 指策略对应的类名，该类位于 `user_data/strategies` 目录下的某个 Python 文件中。

---

使用 1 分钟 K 线：

```bash
freqtrade backtesting --strategy AwesomeStrategy --timeframe 1m
```

---

将初始资金设置为 1000（以计价货币计）：

```bash
freqtrade backtesting --strategy AwesomeStrategy --dry-run-wallet 1000
```

---

使用自定义历史数据目录：

假设你从 Binance 下载的数据存放在 `user_data/data/binance-20180101`，可以这样调用：

```bash
freqtrade backtesting --strategy AwesomeStrategy --datadir user_data/data/binance-20180101
```

---

对比多个策略：

```bash
freqtrade backtesting --strategy-list SampleStrategy1 AwesomeStrategy --timeframe 5m
```

这里 `SampleStrategy1` 和 `AwesomeStrategy` 指策略类名。

---

阻止导出交易数据：

```bash
freqtrade backtesting --strategy backtesting --export none --config config.json
```

只有当确定不会进一步分析或绘图时才建议这么做。

---

导出交易数据并指定自定义目录：

```bash
freqtrade backtesting --strategy backtesting --export trades --backtest-directory=user_data/custom-backtest-results
```

---

建议同时阅读[策略启动期（startup period）](strategy-customization.md#strategy-startup-period)。

---

自定义手续费：

某些账户可能享有手续费减免（例如账户规模或月交易量达到某个档位），这些优惠不一定能通过 ccxt 获知。为了让回测考虑这部分配置，可以使用 `--fee` 命令行参数，将手续费（以比例表示）传入回测。该值会在开仓与平仓各应用一次。

例如交易所每笔订单的手续费为 0.1%（即 0.001），可执行：

```bash
freqtrade backtesting --fee 0.001
```

!!! Note
    仅在需要尝试不同费率时指定此参数（或对应的配置字段）。默认情况下，回测会从交易所的市场信息中获取费率。

---

通过 `--timerange` 指定测试区间

使用 `--timerange` 可以筛选出需要测试的时间段。例如 `--timerange=20190501-` 表示使用 2019 年 5 月 1 日之后的所有可用数据：

```bash
freqtrade backtesting --timerange=20190501-
```

还可以使用更多形式：

* `--timerange=-20180131`：数据截止到 2018/01/31
* `--timerange=20180131-`：数据自 2018/01/31 起
* `--timerange=20180131-20180301`：数据在 2018/01/31 至 2018/03/01 之间
* `--timerange=1527595200-1527618600`：使用给定的 POSIX 时间戳范围

## 理解回测结果

理解回测输出比结果本身更重要。典型输出如下：

```
                                                 BACKTESTING REPORT
┏━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┓
┃          Pair ┃ Trades ┃ Avg Profit % ┃ Tot Profit USDT ┃ Tot Profit % ┃    Avg Duration ┃  Win  Draw  Loss  Win% ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ...（省略） │
└───────────────┴────────┴──────────────┴─────────────────┴──────────────┴─────────────────┴────────────────────────┘
```

首个表格列出了所有已完成的交易及“留存的未平仓单”。最后一行 `TOTAL` 表示策略整体表现：

```
│         TOTAL │     77 │         0.22 │          54.774 │         5.48 │        22:12:00 │   67     0    10  87.0 │
```

这意味着策略共执行 77 笔交易，平均持仓 22 小时，收益率 5.48%，在起始资金 1000 USDT 的前提下取得 54.774 USDT 的盈利。  
`Avg Profit %` 表示所有交易的平均收益，`Tot Profit %` 则是相对于初始资金的累计收益（上例中 `(54.774 / 1000) * 100 ≈ 5.48%`）。

策略表现受买入逻辑、卖出逻辑、`minimal_roi` 与 `stop_loss` 等配置共同影响。例如：

```json
"minimal_roi": {
    "0": 0.01
},
```

意味着收益达到 1% 就会平仓，不可能期望单笔超过 1% 的利润；而若将 `minimal_roi` 设置得极高（如 `"0": 0.55`），大多数交易可能都无法达标。

!!! Note
    请务必配合 `minimal_roi` 和 `stop_loss` 等参数进行策略优化。

### 报表解读

表格中的关键列说明：

* `Pair`：交易对
* `Trades`：总交易数量
* `Avg Profit %`：平均收益率
* `Tot Profit`：累计收益（计价货币）
* `Tot Profit %`：累计收益率（相对初始资金）
* `Avg Duration`：平均持仓时间
* `Win/Draw/Loss/Win%`：胜/平/负的交易数与胜率

回测还会输出“未平仓单”统计及多项概要指标（最佳/最差交易、每日表现、连续胜负等），帮助你衡量策略的稳定性。

除此之外，还会给出整体摘要，例如：

```
Backtested 2025-07-01 00:00:00 -> 2025-08-01 00:00:00 | Max open trades : 3
                                                            STRATEGY SUMMARY
┏━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃       Strategy ┃ Trades ┃ Avg Profit % ┃ Tot Profit USDT ┃ Tot Profit % ┃ Avg Duration ┃  Win  Draw  Loss  Win% ┃           Drawdown ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│    SampleStrategy ...                                                                            │ 94.647 USDT  8.23% │
└────────────────┴────────┴──────────────┴─────────────────┴──────────────┴──────────────┴────────────────────────┴────────────────────┘
```

摘要中包含回测区间、交易模式、最大持仓数量、日均交易次数、起始/终止余额、收益指标（总收益、CAGR、Sortino、Sharpe、Calmar、SQN、盈亏比、期望值、日均收益）、平均下单金额、成交量以及多种回撤数据（最小/最大余额、最大回撤、持续时间、回撤起止时间、同期市场表现等）。

### 其他统计

* **未平仓单报表**：列出回测结束时仍持仓的交易。
* **按退出原因分类**：展示 `exit_reason` 的收益统计。
* **ROI 表**：按持仓时长汇总收益/胜率，便于分析「持仓多久更合适」。
* **成交量与时间分布**：帮助评估策略是否倾向在特定时段或成交量条件下交易。
* **订单表现**：统计 `enter_tag`、`exit_tag`、持仓方向等字段下的收益表现。
* **原始交易列表**：详列每单的开仓/平仓时间、价格、收益、订单类型、超时信息等。

### 特殊指标

报告末尾会列出历史最大回撤（Absolute drawdown）、回撤持续时间、回撤期间的利润变化等关键指标。熟悉这些数据有助于评估策略的风险承受能力，而不仅是收益能力。

## 回测中的假设

回测在模拟交易行为时做出了一些假设，理解这些假设能帮助你评估策略是否现实可行。常见假设包括：

1. **买单以开盘价成交**：默认在信号蜡烛的开盘价买入（静态交易对列表时，可能在训练日之前的蜡烛开盘就能触发）。
2. **卖单以最低/最高价成交**：默认使用 `exit_pricing` 指定的方式；若使用 `stop_loss` 等，也会根据配置模拟成交。
3. **仓位限制**：遵循 `max_open_trades`、`max_entry_position_adjustment` 等设置；若交易名额已满，则忽略新信号。
4. **订单超时**：遵循 `unfilledtimeout` 配置，超时后取消并按策略逻辑处理。
5. **手续费**：默认按照交易所给定的费率计算，可通过 `--fee` 覆盖。

更多假设及其影响请参阅本节后续内容。

## 提升回测精度

为了缓解“蜡烛内部走势未知”的问题，可以使用更快的时间框架来补充模拟。通过在回测命令中添加 `--timeframe-detail 5m`，即可在主时间框架（例如 1h）基础上引入 5 分钟的细节数据：

```bash
freqtrade backtesting --strategy AwesomeStrategy --timeframe 1h --timeframe-detail 5m
```

策略仍以 1 小时周期分析，但在有交易活动的蜡烛上，会使用 5 分钟数据模拟细节。这能更准确地还原真实走势（例如提前平仓后释放仓位）。

!!! Tip
    建议在策略定稿前使用 `--timeframe-detail` 做最后验证，确保策略并非依赖回测假设才能盈利。若此模式下表现仍稳定，则更有希望在 Dry-run/实盘中取得相似成绩。

!!! Warning
    细致时间框架会占用更多内存与时间，且需要预先下载好数据。

## 对比多个策略

回测支持同时比较多套策略：

```bash
freqtrade backtesting --timerange 20180401-20180410 --timeframe 5m --strategy-list Strategy001 Strategy002 --export trades
```

结果会保存在 `user_data/backtest_results/backtest-result-<datetime>.json` 中，并附带各策略的对比表。输出顺序为策略汇总（含胜率、收益、回撤等指标）以及每个策略的详细报表。

## 下一步

如果策略回测表现良好，接下来可以尝试使用 [Hyperopt](hyperopt.md) 为策略参数寻找更优解。
