# 实用子命令

除直播、Dry-run、回测与 Hyperopt 外，Freqtrade 还提供若干辅助子命令，以下为常用工具说明。

## create-userdir

创建用户目录结构，并生成示例策略、Hyperopt、Notebook 等文件。可多次执行；若使用 `--reset`，示例文件会恢复为默认状态。

--8<-- "commands/create-userdir.md"

!!! Warning
    `--reset` 会覆盖示例文件，请确认是否有重要修改。

## new-config

通过交互提问生成配置文件。仅覆盖基础选项，更多参数请参考[配置文档](configuration.md#configuration-parameters)。

--8<-- "commands/new-config.md"

示例（简略）：

```
freqtrade new-config --config user_data/config_binance.json
```

## show-config

展示合并后的完整配置（默认隐藏敏感信息）。对于多配置文件或依赖环境变量的场景，便于确认最终生效的设置。

--8<-- "commands/show-config.md"

!!! Warning
    输出将尝试隐藏敏感字段，但仍应自行确认避免泄露。

## new-strategy

基于模板创建新策略文件，命名与类名一致，位置位于 `user_data/strategies/`。

--8<-- "commands/new-strategy.md"

示例：

```bash
freqtrade new-strategy --strategy AwesomeStrategy --template advanced
```

## list-strategies

列出策略目录下的所有策略。若模块加载失败会标红（LOAD FAILED），同名策略会标黄（DUPLICATE NAME）。

--8<-- "commands/list-strategies.md"

!!! Warning
    命令会尝试导入目录里的所有 Python 文件，请确保目录中不存在不可信文件。

## plot-dataframe / plot-profit

详见[绘图文档](plotting.zh.md)。可绘制价格、指标与收益图（功能已不再积极维护，建议使用 FreqUI）。

## download-data

下载回测与 Hyperopt 所需的数据。详细说明见[数据下载](data-download.zh.md)。

--8<-- "commands/download-data.md"

## convert-trade-data / trades-to-ohlcv / convert-data

分别用于不同数据格式转换，详见对应命令说明。

--8<-- "commands/convert-trade-data.md"
--8<-- "commands/trades-to-ohlcv.md"
--8<-- "commands/convert-data.md"

## webserver

实验性功能，可开启 Webserver 以配合 FreqUI 进行回测、策略调试等，并缓存数据避免重复加载。

--8<-- "commands/webserver.md"

!!! Tip
    以 Docker 方式运行时，可在 compose 中调整命令为 `webserver`，随后使用 `docker compose up` 启动。需要时请记得切回交易命令。

## backtesting-show / backtesting-analysis

* `backtesting-show`：展示历史回测结果，可附加 `--show-pair-list` 导出表现良好的交易对。
* `backtesting-analysis`：高级分析工具，详见[回测分析](advanced-backtesting.zh.md)。

--8<-- "commands/backtesting-show.md"
--8<-- "commands/backtesting-analysis.md"

!!! Warning "策略过拟合"
    回测中只保留盈利交易对可能导致过拟合，实盘前务必进行 Dry-run。

## hyperopt-list / hyperopt-show

* `hyperopt-list`：列出历史 Hyperopt 结果。
* `hyperopt-show`：查看指定 epoch 的详细信息。

--8<-- "commands/hyperopt-list.md"
--8<-- "commands/hyperopt-show.md"

## show-trades

从数据库中打印交易记录，支持筛选、导出等功能。

--8<-- "commands/show-trades.md"

## strategy-updater

将策略更新为 v3 兼容格式，并将旧文件备份到 `user_data/strategies_orig_updater/`。

--8<-- "commands/strategy-updater.md"

!!! Warning
    转换结果并非 100% 准确，请务必审查并使用格式化工具（如 `black`）整理代码。
