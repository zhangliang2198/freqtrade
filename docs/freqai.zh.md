![freqai-logo](assets/freqai_doc_logo.svg)

# FreqAI

## 简介

FreqAI 旨在自动化构建预测型机器学习模型所需的各项工作，通过输入信号生成市场预测。整体而言，FreqAI 致力于提供一个沙盒环境，便于在实时数据上部署稳健的机器学习库（详见[在开源机器学习生态中的定位](#freqai-在开源机器学习生态中的定位)）。

!!! Note
    FreqAI 是一个非盈利、开源项目。它没有任何加密货币、不会出售信号，也没有除[官方文档站点](https://www.freqtrade.io/en/latest/freqai/)以外的域名。

主要特性：

* **自适应再训练**：在 [实时部署](freqai-running.md#live-deployments) 中自动再训练模型，随市场变化自我调整。
* **快速特征工程**：基于用户自定义策略构建丰富的[特征集合](freqai-feature-engineering.md#feature-engineering)，可轻松达到万级特征数量。
* **高性能**：采用多线程或 GPU（若可用）将模型再训练与推理分离，最新模型与数据保存在内存中实现快速预测。
* **现实的回测模拟**：通过[回测模块](freqai-running.md#backtesting)在历史数据上模拟自适应再训练流程。
* **高度扩展性**：通用架构可整合任意 Python 机器学习库/方法，目前已提供 8 种示例，包括分类器、回归器与卷积神经网络。详见[模型配置](freqai-configuration.md#using-different-prediction-models)。
* **智能异常值清理**：提供多种[异常值检测](freqai-feature-engineering.md#outlier-detection)手段清理训练与预测数据。
* **崩溃恢复能力**：将训练好的模型持久化存储，快速从崩溃中恢复，并可[清理旧模型文件](freqai-running.md#purging-old-model-data)，便于长时间 Dry/Live 运行。
* **自动归一化**：提供[智能、安全的归一化](freqai-feature-engineering.md#building-the-data-pipeline)流程。
* **自动下载数据**：计算所需时间区间，下载或更新历史数据（在实时部署场景中）。
* **清洗输入数据**：在训练和推理前安全地处理 NaN。
* **降维能力**：可使用[主成分分析（PCA）](freqai-feature-engineering.md#data-dimensionality-reduction-with-principal-component-analysis)降低训练数据维度。
* **多实例部署**：可设置一个机器人训练模型，再由[消费者](producer-consumer.md)集群共享这些信号。

## 快速上手

最简单的试用方式是在 Dry-run 模式下运行：

```bash
freqtrade trade --config config_examples/config_freqai.example.json --strategy FreqaiExampleStrategy --freqaimodel LightGBMRegressor --strategy-path freqtrade/templates
```

启动过程中会自动下载数据，并同时进行训练与交易。

!!! danger "勿用于生产"
    示例策略面向功能展示与测试，同时考虑到在低性能设备上运行，因此与生产环境需求相差甚远，仅供参考。

你可以在以下位置找到起步所需的策略、模型与配置：

* `freqtrade/templates/FreqaiExampleStrategy.py`
* `freqtrade/freqai/prediction_models/LightGBMRegressor.py`
* `config_examples/config_freqai.example.json`

## 总体思路

与常规 Freqtrade 策略类似，你需要为 FreqAI 提供基础指标（Base Indicators）与目标值（Labels）。FreqAI 会针对白名单中的每个交易对，训练模型来预测这些目标值，并按设定频率持续再训练以适应市场变化。可通过回测模拟周期性再训练，也可在 Dry/Live 运行时于后台线程常态化再训练，以保持模型更新。

下图概述了 FreqAI 的数据处理管线与模型使用流程：

![freqai-algo](assets/freqai_algo.jpg)

### 重要术语

* **特征（Features）**：模型训练所依赖的历史数据字段，每根蜡烛的特征组成一个向量。你可以在策略中构建任意特征集合。
* **标签（Labels）**：模型需要预测的目标值，每个特征向量对应一个标签。
* **DataFrame**：在 Freqtrade 中通常指 Pandas DataFrame，用于盛放历史数据并附加特征/标签。
* **数据字典（Data Dictionary）**：将训练/验证集拆分为 NumPy 数组的结构，方便模型读取。

FreqAI 使用这些概念串联数据处理流程，并在后台使用多线程（或 GPU）完成训练、归一化与预测，尽可能降低交易线程的负担。

## FreqAI 在开源机器学习生态中的定位

| 项目类型 | 代表库 | 与 FreqAI 的区别 |
|----------|--------|------------------|
| 传统机器学习 | scikit-learn | 针对单一模型训练，缺少自动化数据处理、在线再训练能力 |
| 深度学习框架 | TensorFlow、PyTorch | 提供训练基础，但需自行管理数据、模型、推理与部署流程 |
| 量化平台 | Zipline、Backtrader | 偏重回测框架，对实时机器学习支持有限 |
| FreqAI | - | 集成自动特征工程、归一化、再训练、模型管理与实时推理，能够快速部署多模型到实时行情 |

FreqAI 不试图替代这些库，而是作为上层封装，以便用户将模型应用于高频、实时的交易场景。

## 工作流程概览

1. **策略定义特征与标签**：在 `feature_engineering_*` 与 `set_freqai_targets` 中构造特征与目标。
2. **数据准备**：FreqAI 自动下载、清洗并归一化数据，构建训练/测试集字典。
3. **模型训练与存储**：调用预设或自定义模型进行训练，并将结果序列化，便于崩溃后快速恢复。
4. **预测与下单**：在交易线程中使用最新模型进行推理，输出信号供策略决策。
5. **周期性再训练**：按配置在后台线程中持续再训练（可设置时间或蜡烛数量触发），保持模型更新。
6. **清理旧模型**：周期性删除过期模型文件，防止磁盘空间被占满。

更多细节请参阅：

* [配置](freqai-configuration.md)
* [特征工程](freqai-feature-engineering.md)
* [运行模式（回测、Dry-run、Live）](freqai-running.md)
* [开发者指南](freqai-developers.md)

## 组织结构与社区

FreqAI 由社区志愿者推动，以下为当前主要贡献者：

* 理论设计与数据分析：Elin Törnquist（@th0rntwig）
* 代码审查与架构讨论：@xmatthias
* 软件开发：Wagner Costa（@wagnercosta）、Emre Suzen（@aemr3）、Timothy Pogue（@wizrds）
* 测试与反馈：Stefan Gehring（@bloodhunter4rc）、@longyu、Andrew Lawless（@paranoidandy）、Pascal Schmidt（@smidelis）、Ryan McMullan（@smarmau）、Juha Nykänen（@suikula）、Johan van der Vlugt（@jooopiert）、Richárd Józsa（@richardjosza）

如想参与贡献，请参考[开发者文档](freqai-developers.md)或在 Discord 中联系社区。
