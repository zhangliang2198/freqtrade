# 数据下载

## 获取回测与 Hyperopt 所需数据

要下载回测与超参优化所需的蜡烛（OHLCV）数据，可使用 `freqtrade download-data` 命令。

如果未提供额外参数，freqtrade 会默认下载最近 30 天的 `"1m"` 与 `"5m"` 数据。交易所与交易对取自 `config.json`（通过 `-c/--config` 指定）。若未提供配置文件，则必须使用 `--exchange`。

可以使用相对时间范围（例如 `--days 20`）或绝对起点（例如 `--timerange 20200101-`）。增量下载建议使用相对时间范围。

!!! Tip "更新已有数据"
    如果数据目录中已经存在回测数据，且想更新至当前日期，freqtrade 会自动计算缺失的时间范围，从最新数据点继续下载，无需传入 `--days` 或 `--timerange`。已有数据会保留，freqtrade 只会补齐缺失部分。  
    如果新增了此前未下载过的交易对，请使用 `--new-pairs-days xx`。旧交易对仍只补缺失部分，新交易对会按指定天数下载。

### 基本用法

--8<-- "commands/download-data.md"

!!! Tip "下载某个计价货币的全部交易对"
    如果想下载某个计价货币的全部交易对，可以使用正则简写：  
    `freqtrade download-data --exchange binance --pairs ".*/USDT" <...>`  
    该字符串会展开为交易所上所有活跃交易对。若需包含已下架交易对，可加上 `--include-inactive-pairs`。

!!! Note "启动周期"
    `download-data` 与策略无关，适合一次性下载大批量数据，再按需追加。  
    因此该命令不会考虑策略中的 startup-period。如果你希望回测从更早时间开始，需要自行下载足够的历史数据。

### 开始下载

假设已提供 `config.json`，可运行：

```bash
freqtrade download-data --exchange binance
```

这会为配置中所有交易对下载历史 OHLCV 数据。

也可以直接指定交易对：

```bash
freqtrade download-data --exchange binance --pairs ETH/USDT XRP/USDT BTC/USDT
```

或者使用正则（如下示例表示下载所有活跃的 USDT 交易对）：

```bash
freqtrade download-data --exchange binance --pairs ".*/USDT"
```

### 其他注意事项

* 如果想将数据存储到非默认目录，可使用 `--datadir user_data/data/some_directory`。
* 若需更换下载数据的交易所，可通过 `--exchange <exchange>` 或使用不同的配置文件。
* 若需使用其他目录的 `pairs.json`，可以传入 `--pairs-file some_other_dir/pairs.json`。
* 下载指定天数的数据可使用 `--days 10`（默认 30 天）。
* 使用 `--timerange 20200101-` 可从 2020-01-01 起下载全部数据。
* 如果已存在该时间范围的数据，freqtrade 会忽略起始时间，仅补齐缺失部分直至当前。
* `--timeframes` 控制需要的周期，默认 `1m 5m`。
* 使用 `-c/--config` 时，会遵循配置文件中定义的交易所、时间框架与交易对（无需 `pairs.json`）。可以与大部分其他选项组合使用。

??? Note "权限错误"
    如果你的 `user_data` 目录由 docker 创建，可能会遇到：

    ```
    cp: cannot create regular file 'user_data/data/binance/pairs.json': Permission denied
    ```

    可以通过以下命令修复权限：

    ```bash
    sudo chown -R $UID:$GID user_data
    ```

### 在现有时间范围前追加数据

假设你之前使用 `--timerange 20220101-` 下载了 2022 年的全部数据，现在希望再向前补充 2021 年的数据，可以使用 `--prepend` 并结合 `--timerange` 指定结束日期：

``` bash
freqtrade download-data --exchange binance --pairs ETH/USDT XRP/USDT BTC/USDT --prepend --timerange 20210101-20220101
```

!!! Note
    在此模式下，如果目标时间范围末尾已有数据，freqtrade 会自动调整结束时间到现有数据开始的位置。

### 数据格式

Freqtrade 当前支持多种数据格式（详见文档后续章节）。默认会选择适合的格式存储数据。有关格式转换请见下方子命令说明。

### 时间范围详细说明

`--timerange` 选项支持多种写法。例如：

* `YYYYMMDD-YYYYMMDD`：从开始日期（含）到结束日期（不含）
* `YYYYMMDD-`：从指定日期至今
* `-YYYYMMDD`：从最早可用数据到指定日期
* `YYYYMMDDTHHMM`：可指定具体时间

当结合 `--days` 使用时，`--timerange` 会被忽略。

### 下载自定义交易对列表

使用 `--pairs-file` 可以加载自定义的 `pairs.json` 文件。该文件需包含键 `blacklist` 与 `whitelist`。举例：

```bash
freqtrade download-data --exchange binance --pairs-file mypairs.json --timeframes 1m 5m --timerange 20220101- --erase
```

`--erase` 会在下载前清理现有数据。

## 子命令 convert-data

--8<-- "commands/convert-data.md"

### 转换数据示例

``` bash
freqtrade convert-data --format-from feather --format-to hdf5 --datadir user_data/data/binance -t 1m --erase
```

注：`--erase` 会删除原始数据，请谨慎使用。

## 子命令 convert-trade-data

--8<-- "commands/convert-trade-data.md"

### 转换成交数据示例

以下命令会将 `~/.freqtrade/data/kraken` 中所有交易数据从 `jsongz` 转换为 `json`，并删除原始文件。

``` bash
freqtrade convert-trade-data --format-from jsongz --format-to json --datadir ~/.freqtrade/data/kraken --erase
```

## 子命令 trades-to-ohlcv

当你需要使用 `--dl-trades`（目前仅 Kraken 支持）下载成交数据时，最后一步是将成交数据转换为 OHLCV。该命令可以在不重新下载的情况下，为额外的时间框架执行转换。

--8<-- "commands/trades-to-ohlcv.md"

### 成交转蜡烛示例

``` bash
freqtrade trades-to-ohlcv --exchange kraken -t 5m 1h 1d --pairs BTC/EUR ETH/EUR
```

## 子命令 list-data

使用 `list-data` 可以列出当前本地的数据。

--8<-- "commands/list-data.md"

### 列出数据示例

```bash
freqtrade list-data --userdir ~/.freqtrade/user_data/
```

示例输出：

```
              Found 33 pair / timeframe combinations.
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┓
┃          Pair ┃                                 Timeframe ┃ Type ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━┩
│       ADA/BTC │     5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d │ spot │
│       ADA/ETH │     5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d │ spot │
│       ETH/BTC │     5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d │ spot │
│      ETH/USDT │                  5m, 15m, 30m, 1h, 2h, 4h │ spot │
└───────────────┴───────────────────────────────────────────┴──────┘
```

展示全部成交数据与时间范围：

``` bash
freqtrade list-data --show --trades
```

示例输出：

```
                     Found trades data for 1 pair.                     
┏━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃    Pair ┃ Type ┃                From ┃                  To ┃ Trades ┃
┡━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│ XRP/ETH │ spot │ 2019-10-11 00:00:11 │ 2019-10-13 11:19:28 │  12477 │
└─────────┴──────┴─────────────────────┴─────────────────────┴────────┘
```

## 成交（tick）数据

默认情况下，`download-data` 会下载蜡烛数据。大多数交易所也提供历史成交数据，在需要多个时间框架时，这种方式非常高效：只需下载一次成交数据，即可在本地重采样。

由于成交数据体积较大，默认使用 feather 格式存储，文件名以 `<pair>-trades.feather` 命名（例如 `ETH_BTC-trades.feather`）。与蜡烛数据相同，也支持增量更新，例如每周运行 `--days 8` 以维护数据。

要启用该模式，只需添加 `--dl-trades`。若同时提供 `--convert`，则会自动执行重采样，并覆盖已有的 OHLCV 数据。

!!! Warning "谨慎使用"
    除非你是 Kraken 用户（因为 Kraken 不提供历史 OHLCV 数据），否则不建议使用此模式。对大多数交易所来说，直接下载多个时间框架的蜡烛数据更快。

!!! Note "Kraken 用户"
    Kraken 用户在下载数据前应先阅读[相关章节](exchanges.md#historic-kraken-data)。

示例：

```bash
freqtrade download-data --exchange kraken --pairs XRP/EUR ETH/EUR --days 20 --dl-trades
```

!!! Note
    尽管使用了异步请求，该模式仍然较慢，因为每次调用都依赖上一次结果以生成下一次请求。

## 下一步

数据下载完成后，可以开始[回测](backtesting.md)你的策略啦。
