# 已废弃功能

本页列出了已声明为 **DEPRECATED** 并且不再受支持的命令行参数、配置项以及机器人功能。请避免在配置中继续使用它们。

## 已移除的功能

### `--refresh-pairs-cached` 命令行参数

该参数曾用于在回测、Hyperopt、Edge 模式下刷新蜡烛数据。由于易引发混淆且会拖慢回测，该功能已被拆分为独立子命令 `freqtrade download-data`。  
此参数在 2019.7-dev（develop 分支）中弃用，并于 2019.9 移除。

### `--dynamic-whitelist` 命令行参数

该参数于 2018 年弃用，并在 freqtrade 2019.6-dev 与 2019.7 中被移除。请改用 [pairlists](plugins.md#pairlists-and-pairlist-handlers)。

### `--live` 命令行参数

`--live` 用于回测时下载最新的 K 线数据，仅能获取 500 根，效果有限。  
该选项在 2019.7-dev 以及 2019.8 中移除。

### `ticker_interval`（现为 `timeframe`）

从 2020.6 开始推荐使用 `timeframe`，兼容代码在 2022.3 中移除。

### 顺序运行多个 pairlist

旧版配置使用 `"pairlist"` 字段，现已改为 `"pairlists"` 列表，以便顺序指定多个 pairlist。  
`"pairlist"` 于 2019.11 弃用，并在 2020.4 移除。

### volume-pairlist 中的 bidVolume / askVolume

由于只有 `quoteVolume` 具备可比性，`bidVolume` 与 `askVolume` 在 2020.4 弃用，并于 2020.9 移除。

### 退出价使用订单簿阶梯

曾经可配置 `order_book_min` 与 `order_book_max` 来沿订单簿寻找更高 ROI 的卖出价。此功能风险较高且收益有限，为维护性考虑已在 2021.7 移除。

### 旧版 Hyperopt 模式

独立 Hyperopt 文件的写法于 2021.4 弃用，并在 2021.9 移除。请改用[参数化策略](hyperopt.md)的新接口。

## V2 与 V3 策略变化

2022.4 引入了逐仓合约/做空功能，涉及配置与策略接口的大幅调整。

我们尽力保持与现有策略的兼容性——若仅在现货市场使用，通常无需改动。若未来决定移除旧接口，我们会另行通知并提供过渡期。

如需使用新功能，请参考[策略迁移指南](strategy_migration.md)。

### 2022.4 起的 webhook 变更

#### `buy_tag` 重命名为 `enter_tag`

仅影响策略与可能涉及的 webhook。我们会在 1-2 个版本内保留兼容层（`buy_tag` 与 `enter_tag` 均有效），之后将彻底移除旧字段。

#### 命名变更

Webhook 术语由 “buy/sell” 转为 “entry/exit”，并去掉前缀 “webhook”。变化如下：

* `webhookbuy`, `webhookentry` -> `entry`
* `webhookbuyfill`, `webhookentryfill` -> `entry_fill`
* `webhookbuycancel`, `webhookentrycancel` -> `entry_cancel`
* `webhooksell`, `webhookexit` -> `exit`
* `webhooksellfill`, `webhookexitfill` -> `exit_fill`
* `webhooksellcancel`, `webhookexitcancel` -> `exit_cancel`

## 移除 `populate_any_indicators`

2023.3 版本移除了 `populate_any_indicators`，改为分别用于特征工程与目标的独立方法。详情请参考[迁移文档](strategy_migration.md#freqai-strategy)。

## 配置中移除 `protections`

通过配置文件设置 `"protections": []` 的方式在 2024.10 移除，此前已连续 3 年发出弃用警告。

## hdf5 数据存储

使用 hdf5 存储数据在 2024.12 弃用，并在 2025.1 移除。建议切换至 feather 等受支持格式。  
更新前请使用 [`convert-data` 子命令](data-download.md#sub-command-convert-data)转换既有数据。

## 通过配置设置高级日志

通过 `--logfile systemd` 与 `--logfile journald` 配置 syslog/journald 在 2025.3 弃用。请改用配置化的[高级日志方案](advanced-setup.md#advanced-logging)。

## 移除 edge 模块

edge 模块在 2023.9 弃用，并于 2025.6 移除。相关功能全部删除，若仍在配置中启用 edge 会导致错误。
