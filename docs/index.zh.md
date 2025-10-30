![freqtrade](assets/freqtrade_poweredby.svg)

[![Freqtrade CI](https://github.com/freqtrade/freqtrade/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/freqtrade/freqtrade/actions/)
[![DOI](https://joss.theoj.org/papers/10.21105/joss.04864/status.svg)](https://doi.org/10.21105/joss.04864)
[![Coverage Status](https://coveralls.io/repos/github/freqtrade/freqtrade/badge.svg?branch=develop&service=github)](https://coveralls.io/github/freqtrade/freqtrade?branch=develop)

<!-- GitHub action buttons -->
[:octicons-star-16: Star](https://github.com/freqtrade/freqtrade){ .md-button .md-button--sm }
[:octicons-repo-forked-16: Fork](https://github.com/freqtrade/freqtrade/fork){ .md-button .md-button--sm }
[:octicons-download-16: Download](https://github.com/freqtrade/freqtrade/archive/stable.zip){ .md-button .md-button--sm }

## 介绍

Freqtrade 是一个用 Python 编写的免费开源加密货币交易机器人。它旨在支持所有主要交易所，并可通过 Telegram 或 webUI 进行控制。它包含回测、绘图和资金管理工具，以及通过机器学习进行策略优化的功能。

!!! Danger "免责声明"
    本软件仅用于教育目的。不要冒险投入你害怕失去的资金。使用本软件风险自负。作者和所有关联方对你的交易结果不承担任何责任。

    始终通过在模拟模式（Dry-run）下运行交易机器人开始，在你了解它的工作原理以及你应该期望的利润/损失之前，不要投入真实资金。

    我们强烈建议你具备基本的编程技能和 Python 知识。请毫不犹豫地阅读源代码并了解此机器人的机制、算法和实现的技术。

![freqtrade screenshot](assets/freqtrade-screenshot.png)

## 功能特性

- 开发你的策略：使用 [pandas](https://pandas.pydata.org/) 用 Python 编写你的策略。[策略仓库](https://github.com/freqtrade/freqtrade-strategies)中提供了激发灵感的示例策略。
- 下载市场数据：下载你可能想要交易的交易所和市场的历史数据。
- 回测：在下载的历史数据上测试你的策略。
- 优化：使用采用机器学习方法的超参数优化找到策略的最佳参数。你可以优化策略的买入、卖出、止盈（ROI）、止损和追踪止损参数。
- 选择市场：创建你的静态列表或使用基于最高交易量和/或价格的自动列表（回测期间不可用）。你还可以明确将不想交易的市场加入黑名单。
- 运行：使用模拟资金（模拟模式）测试你的策略，或使用真实资金（实盘交易模式）部署它。
- 控制/监控：使用 Telegram 或 WebUI（启动/停止机器人、显示利润/损失、每日摘要、当前开仓交易结果等）。
- 分析：可以对回测数据或 Freqtrade 交易历史（SQL 数据库）进行进一步分析，包括自动标准图表，以及将数据加载到[交互式环境](data-analysis.md)的方法。

## 支持的交易所市场

请阅读[交易所特定说明](exchanges.md)以了解每个交易所可能需要的特殊配置。

- [X] [Binance](https://www.binance.com/)
- [X] [BingX](https://bingx.com/invite/0EM9RX)
- [X] [Bitget](https://www.bitget.com/)
- [X] [Bitmart](https://bitmart.com/)
- [X] [Bybit](https://bybit.com/)
- [X] [Gate.io](https://www.gate.io/ref/6266643)
- [X] [HTX](https://www.htx.com/)
- [X] [Hyperliquid](https://hyperliquid.xyz/)（去中心化交易所，即 DEX）
- [X] [Kraken](https://kraken.com/)
- [X] [OKX](https://okx.com/)
- [X] [MyOKX](https://okx.com/)（OKX EEA）
- [ ] [通过 <img alt="ccxt" width="30px" src="assets/ccxt-logo.svg" /> 可能支持许多其他交易所](https://github.com/ccxt/ccxt/)。_（我们不能保证它们会正常工作）_

### 支持的期货交易所（实验性）

- [X] [Binance](https://www.binance.com/)
- [X] [Bitget](https://www.bitget.com/)
- [X] [Bybit](https://bybit.com/)
- [X] [Gate.io](https://www.gate.io/ref/6266643)
- [X] [Hyperliquid](https://hyperliquid.xyz/)（去中心化交易所，即 DEX）
- [X] [OKX](https://okx.com/)

在深入研究之前，请务必阅读[交易所特定说明](exchanges.md)以及[杠杆交易](leverage.md)文档。

### 社区测试

社区确认可用的交易所：

- [X] [Bitvavo](https://bitvavo.com/)
- [X] [Kucoin](https://www.kucoin.com/)

## 社区展示

--8<-- "includes/showcase.md"

## 要求

### 硬件要求

要运行此机器人，我们建议你使用至少具有以下配置的 Linux 云实例：

- 2GB RAM
- 1GB 磁盘空间
- 2vCPU

### 软件要求

- Docker（推荐）

或者

- Python 3.11+
- pip（pip3）
- git
- TA-Lib
- virtualenv（推荐）

## 支持

### 帮助 / Discord

对于文档未涵盖的任何问题，或有关机器人的更多信息，或只是想与志同道合的人交流，我们鼓励你加入 Freqtrade 的 [discord 服务器](https://discord.gg/p7nuUNVfP7)。

## 准备好试试了吗？

从阅读[docker 安装指南](docker_quickstart.md)（推荐）或[非 docker 安装](installation.md)指南开始。
