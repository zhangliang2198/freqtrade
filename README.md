# 这是一个freqtrade的优化版本，可以用于实盘

fork自源仓库，每月同步一次源框架稳定代码。不断优化和添加功能。

## 交流讨论，版本发行说明，更多量化实盘技巧和策略，请入`qq`群：

<img src="小森林量化logo.png" alt="小森林量化QQ群" width="300">

## v1.0.2 新增策略资金快照和账户分离功能

添加 `BaseStrategyWithSnapshot` 策略基类，提供**资金快照记录**、**Long/Short 账户分离**、**严格资金限制**等功能。

**新增文件**：
- 核心：[`freqtrade/strategy/BaseStrategyWithSnapshot.py`](freqtrade/strategy/BaseStrategyWithSnapshot.py) - 策略基类
- 数据库：[`freqtrade/persistence/strategy_snapshot.py`](freqtrade/persistence/strategy_snapshot.py) - 快照模型
- 示例：[`user_data/strategies/ExampleStrategyWithAccountLimit.py`](user_data/strategies/ExampleStrategyWithAccountLimit.py) - 使用示例
- 配置：[`config_examples/strategy_account_config.example.json`](config_examples/strategy_account_config.example.json) - 配置示例

**文档**：
- 使用文档：[`docs/BaseStrategyWithSnapshot.zh.md`](docs/BaseStrategyWithSnapshot.zh.md)

## v1.0.1

1. 将原串行分析交易对变成并行提升每轮K线处理速度；
   - 配置项:
   ```json  
   "strategy_threading": true,    
   "strategy_thread_workers": 32,
   ```
2. 添加几个策略，供参考，策略均在实盘运行；
3. 文档全部中文化，参考 `/docs` 目录中的 `xx.zh.md` 文档，建议通读一遍；
4. 增加mysql支持，请执行；`pip install pymysql`(额外包需求已放在 `requirements-add.txt` 中)，在配置中设置：`"db_url": "mysql+pymysql://<user>:<password>@localhost:3306/<dbname>"`；
5. 梳理配置文件，参考 `config.json` 中配置；
6. 添加优选山寨币对，参考 `pairlist_static.json`；
7. 添加常用指令说明，参考 `/user_data/COMMANDS_CHEATSHEET.md`。
   
## 原始框架bug修复

1. 使用 `mysql` 当作数据库时， `custom_data` 先查后写触发并发写会冲突，导致接下来任何查询/提交都会报错，文件：`custom_data.py`。
  - `get_custom_data()` 加一个“若会话挂起则先 `rollback` 再查询”的容错，以杜绝因先前失败造成的后续读异常。
  - 把 `set_custom_data()` 改为原子 `upsert（PG 的 ON CONFLICT DO UPDATE / MySQL 的 ON DUPLICATE KEY UPDATE）`。这样并发对同一键的写会被数据库合并为插入或更新，不再走“先查后插”的竞态路径。

# 下面是原版说明：

# ![freqtrade](https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/assets/freqtrade_poweredby.svg)

[![Freqtrade CI](https://github.com/freqtrade/freqtrade/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/freqtrade/freqtrade/actions/)
[![DOI](https://joss.theoj.org/papers/10.21105/joss.04864/status.svg)](https://doi.org/10.21105/joss.04864)
[![Coverage Status](https://coveralls.io/repos/github/freqtrade/freqtrade/badge.svg?branch=develop&service=github)](https://coveralls.io/github/freqtrade/freqtrade?branch=develop)
[![Documentation](https://readthedocs.org/projects/freqtrade/badge/)](https://www.freqtrade.io)

Freqtrade 是一个用 Python 编写的免费开源加密货币交易机器人。它被设计为支持所有主要交易所，并可通过 Telegram 或 Web UI 进行控制。它包含回测、绘图和资金管理工具，以及通过机器学习进行策略优化。

![freqtrade](https://raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/assets/freqtrade-screenshot.png)

## 免责声明

本软件仅用于教育目的。请勿拿您不敢损失的资金去冒险。使用本软件风险自担。作者和所有关联方对您的交易结果不承担任何责任。

在您了解机器人的工作原理以及您应该期望的盈利/亏损之前，请务必从运行干跑交易机器人开始，不要投入真金白银。

我们强烈建议您具备编程和 Python 知识。请不要犹豫阅读源代码并了解此机器人的机制。

## 支持的交易所市场

请阅读[交易所特定说明](docs/exchanges.md)以了解每个交易所可能需要的特殊配置。

- [X] [Binance](https://www.binance.com/)
- [X] [BingX](https://bingx.com/invite/0EM9RX)
- [X] [Bitget](https://www.bitget.com/)
- [X] [Bitmart](https://bitmart.com/)
- [X] [Bybit](https://bybit.com/)
- [X] [Gate.io](https://www.gate.io/ref/6266643)
- [X] [HTX](https://www.htx.com/)
- [X] [Hyperliquid](https://hyperliquid.xyz/) (A decentralized exchange, or DEX)
- [X] [Kraken](https://kraken.com/)
- [X] [OKX](https://okx.com/)
- [X] [MyOKX](https://okx.com/) (OKX EEA)
- [ ] [potentially many others](https://github.com/ccxt/ccxt/). _(We cannot guarantee they will work)_

### 支持的期货交易所（实验性）

- [X] [Binance](https://www.binance.com/)
- [X] [Bitget](https://www.bitget.com/)
- [X] [Gate.io](https://www.gate.io/ref/6266643)
- [X] [Hyperliquid](https://hyperliquid.xyz/) (去中心化交易所，即 DEX)
- [X] [OKX](https://okx.com/)
- [X] [Bybit](https://bybit.com/)

在深入了解之前，请务必阅读[交易所特定说明](docs/exchanges.md)以及[杠杆交易](docs/leverage.md)文档。

### 社区测试

经社区确认可以工作的交易所：

- [X] [Bitvavo](https://bitvavo.com/)
- [X] [Kucoin](https://www.kucoin.com/)

## 文档

我们邀请您阅读机器人文档，以确保您了解机器人的工作原理。

请在[freqtrade 网站](https://www.freqtrade.io)上查看完整文档。

## 功能特性

- [x] **基于 Python 3.11+**：可在任何操作系统上运行机器人 - Windows、macOS 和 Linux。
- [x] **持久化**：通过 sqlite 实现持久化。
- [x] **干跑**：在不花费真金白银的情况下运行机器人。
- [x] **回测**：模拟您的买卖策略。
- [x] **通过机器学习进行策略优化**：使用机器学习和真实交易所数据优化您的买卖策略参数。
- [X] **自适应预测建模**：使用 FreqAI 构建智能策略，通过自适应机器学习方法自主训练适应市场。[了解更多](https://www.freqtrade.io/en/stable/freqai/)
- [x] **加密货币白名单**：选择您想要交易的加密货币或使用动态白名单。
- [x] **加密货币黑名单**：选择您想要避免的加密货币。
- [x] **内置 WebUI**：内置 web UI 来管理您的机器人。
- [x] **通过 Telegram 管理**：通过 Telegram 管理机器人。
- [x] **以法币显示盈亏**：以法币显示您的盈利/亏损。
- [x] **性能状态报告**：提供当前交易的性能状态。

## 快速开始

请参考[Docker 快速开始文档](https://www.freqtrade.io/en/stable/docker_quickstart/)了解如何快速开始。

有关进一步的（原生）安装方法，请参考[安装文档页面](https://www.freqtrade.io/en/stable/installation/)。

## 基本用法

### 机器人命令

```
用法: freqtrade [-h] [-V]
                 {trade,create-userdir,new-config,show-config,new-strategy,download-data,convert-data,convert-trade-data,trades-to-ohlcv,list-data,backtesting,backtesting-show,backtesting-analysis,edge,hyperopt,hyperopt-list,hyperopt-show,list-exchanges,list-markets,list-pairs,list-strategies,list-hyperoptloss,list-freqaimodels,list-timeframes,show-trades,test-pairlist,convert-db,install-ui,plot-dataframe,plot-profit,webserver,strategy-updater,lookahead-analysis,recursive-analysis}
                 ...

免费、开源的加密货币交易机器人

位置参数:
  {trade,create-userdir,new-config,show-config,new-strategy,download-data,convert-data,convert-trade-data,trades-to-ohlcv,list-data,backtesting,backtesting-show,backtesting-analysis,edge,hyperopt,hyperopt-list,hyperopt-show,list-exchanges,list-markets,list-pairs,list-strategies,list-hyperoptloss,list-freqaimodels,list-timeframes,show-trades,test-pairlist,convert-db,install-ui,plot-dataframe,plot-profit,webserver,strategy-updater,lookahead-analysis,recursive-analysis}
    trade               交易模块。
    create-userdir      创建用户数据目录。
    new-config          创建新配置
    show-config         显示已解析的配置
    new-strategy        创建新策略
    download-data       下载回测数据。
    convert-data        将K线（OHLCV）数据从一种格式转换为另一种格式。
    convert-trade-data  将交易数据从一种格式转换为另一种格式。
    trades-to-ohlcv     将交易数据转换为OHLCV数据。
    list-data           列出已下载的数据。
    backtesting         回测模块。
    backtesting-show    显示过去的回测结果
    backtesting-analysis
                        回测分析模块。
    hyperopt            超参数优化模块。
    hyperopt-list       列出超参数优化结果
    hyperopt-show       显示超参数优化结果详情
    list-exchanges      打印可用的交易所。
    list-markets        打印交易所上的市场。
    list-pairs          打印交易所上的交易对。
    list-strategies     打印可用的策略。
    list-hyperoptloss   打印可用的超参数优化损失函数。
    list-freqaimodels   打印可用的freqAI模型。
    list-timeframes     打印交易所的可用时间周期。
    show-trades         显示交易。
    test-pairlist       测试您的交易对列表配置。
    convert-db          将数据库迁移到不同系统
    install-ui          安装FreqUI
    plot-dataframe      绘制带指标的K线图。
    plot-profit         生成显示利润的图表。
    webserver           Web服务器模块。
    strategy-updater    将过时的策略文件更新到当前版本
    lookahead-analysis  检查潜在的前瞻偏差。
    recursive-analysis  检查潜在的递归公式问题。

选项:
  -h, --help            显示此帮助信息并退出
  -V, --version         显示程序版本号并退出
```

### Telegram RPC 命令

Telegram 不是必需的。但是，这是控制您的机器人的好方法。更多详细信息和完整命令列表请参见[文档](https://www.freqtrade.io/en/latest/telegram-usage/)

- `/start`: 启动交易者。
- `/stop`: 停止交易者。
- `/stopentry`: 停止进入新交易。
- `/status <trade_id>|[table]`: 列出所有或特定的未平仓交易。
- `/profit [<n>]`: 列出过去n天内所有已完成交易的累计利润。
- `/profit_long [<n>]`: 列出过去n天内所有已完成多头交易的累计利润。
- `/profit_short [<n>]`: 列出过去n天内所有已完成空头交易的累计利润。
- `/forceexit <trade_id>|all`: 立即退出指定交易（忽略`minimum_roi`）。
- `/fx <trade_id>|all`: `/forceexit`的别名
- `/performance`: 显示按交易对分组的每个已完成交易的表现
- `/balance`: 显示每种货币的账户余额。
- `/daily <n>`: 显示过去n天内每日的盈利或亏损。
- `/help`: 显示帮助信息。
- `/version`: 显示版本。


## 支持

### 帮助 / Discord

对于文档未涵盖的任何问题或有关机器人的更多信息，或者只是与志同道合的人交流，我们鼓励您加入 Freqtrade [discord 服务器](https://discord.gg/p7nuUNVfP7)。

### [错误 / 问题](https://github.com/freqtrade/freqtrade/issues?q=is%3Aissue)

如果您在机器人中发现错误，请先[搜索问题跟踪器](https://github.com/freqtrade/freqtrade/issues?q=is%3Aissue)。如果尚未报告，请[创建新问题](https://github.com/freqtrade/freqtrade/issues/new/choose)并确保您遵循模板指南，以便团队能够尽快为您提供帮助。

对于创建的每个[问题](https://github.com/freqtrade/freqtrade/issues/new/choose)，请跟进并在达到平衡点时标记满意度或提醒关闭问题。

--维护 github 的[社区政策](https://docs.github.com/en/site-policy/github-terms/github-community-code-of-conduct)--

### [功能请求](https://github.com/freqtrade/freqtrade/labels/enhancement)

您有改进机器人的好主意想要分享吗？请先搜索此功能是否[已经讨论过](https://github.com/freqtrade/freqtrade/labels/enhancement)。如果尚未请求，请[创建新请求](https://github.com/freqtrade/freqtrade/issues/new/choose)并确保您遵循模板指南，以免在错误报告中丢失。

### [拉取请求](https://github.com/freqtrade/freqtrade/pulls)

觉得机器人缺少某个功能？我们欢迎您的拉取请求！

请阅读[贡献文档](https://github.com/freqtrade/freqtrade/blob/develop/CONTRIBUTING.md)以在发送拉取请求之前了解要求。

贡献不一定需要编程 - 也许可以从改进文档开始？
标记为[好的第一个问题](https://github.com/freqtrade/freqtrade/labels/good%20first%20issue)的问题可以是很好的第一次贡献，并将帮助您熟悉代码库。

__注意__在开始任何主要的新功能工作之前，_请打开一个描述您计划做什么的问题_或在[discord](https://discord.gg/p7nuUNVfP7)上与我们交谈（请为此使用 #dev 频道）。这将确保相关方可以就该功能提供有价值的反馈，并让其他人知道您正在处理它。

__重要：__始终针对`develop`分支创建您的 PR，而不是`stable`。

## 要求

### 时钟需要保持最新

时钟必须准确，经常与 NTP 服务器同步，以避免与交易所通信时出现问题。

### 最低硬件要求

要运行此机器人，我们建议您使用最低配置的云实例：

- 最低（建议）系统要求：2GB RAM，1GB 磁盘空间，2vCPU

### 软件要求

- [Python >= 3.11](http://docs.python-guide.org/en/latest/starting/installation/)
- [pip](https://pip.pypa.io/en/stable/installing/)
- [git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)
- [TA-Lib](https://ta-lib.github.io/ta-lib-python/)
- [virtualenv](https://virtualenv.pypa.io/en/stable/installation.html) (推荐)
- [Docker](https://www.docker.com/products/docker) (推荐)
