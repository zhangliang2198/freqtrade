# 运行 FreqAI

有两种方法来训练和部署自适应机器学习模型 - 实时部署和历史回测。在这两种情况下，FreqAI 都会运行/模拟定期重新训练模型，如下图所示：

![freqai-window](assets/freqai_moving-window.jpg)

## 实时部署

FreqAI 可以使用以下命令进行干运行/实时运行：

```bash
freqtrade trade --strategy FreqaiExampleStrategy --config config_freqai.example.json --freqaimodel LightGBMRegressor
```

启动时，FreqAI 将根据配置设置开始训练一个新模型，使用一个新的 `identifier`。训练完成后，该模型将用于对传入的蜡烛进行预测，直到有新模型可用。新模型通常尽可能频繁地生成，FreqAI 管理币对的内部队列，以尝试保持所有模型同样更新。FreqAI 将始终使用最近训练的模型对传入的实时数据进行预测。如果您不希望 FreqAI 尽可能频繁地重新训练新模型，您可以设置 `live_retrain_hours` 来告诉 FreqAI 在训练新模型之前至少等待那么多小时。此外，您可以设置 `expired_hours` 来告诉 FreqAI 避免对超过那么多小时的模型进行预测。

默认情况下，训练的模型会保存到磁盘，以允许在回测期间或崩溃后重用。您可以通过在配置中设置 `"purge_old_models": true` 来选择[清除旧模型](#purging-old-model-data)以节省磁盘空间。

要从保存的回测模型（或从之前崩溃的干运行/实时会话）启动干运行/实时运行，您只需指定特定模型的 `identifier`：

```json
    "freqai": {
        "identifier": "example",
        "live_retrain_hours": 0.5
    }
```

在这种情况下，虽然 FreqAI 将使用预训练的模型启动，但它仍将检查自模型训练以来经过了多少时间。如果自加载模型结束以来已经过了完整的 `live_retrain_hours`，FreqAI 将开始训练新模型。

### 自动数据下载

FreqAI 自动下载所需的适当数据量，以确保通过定义的 `train_period_days` 和 `startup_candle_count` 训练模型（有关这些参数的详细描述，请参见[参数表](freqai-parameter-table.md)）。

### 保存预测数据

在特定 `identifier` 模型的生命周期内进行的所有预测都存储在 `historic_predictions.pkl` 中，以允许在崩溃或配置更改后重新加载。

### 清除旧模型数据

FreqAI 在每次成功训练后存储新的模型文件。随着新模型的生成以适应新的市场条件，这些文件会变得过时。如果您计划让 FreqAI 以高频率重新训练长时间运行，您应该在配置中启用 `purge_old_models`：

```json
    "freqai": {
        "purge_old_models": 4,
    }
```

这将自动清除所有超过四个最近训练的模型以节省磁盘空间。输入"0"将永远不会清除任何模型。

## 回测

FreqAI 回测模块可以使用以下命令执行：

```bash
freqtrade backtesting --strategy FreqaiExampleStrategy --strategy-path freqtrade/templates --config config_examples/config_freqai.example.json --freqaimodel LightGBMRegressor --timerange 20210501-20210701
```

如果此命令从未使用现有配置文件执行过，FreqAI 将在扩展的 `--timerange` 内为每个配对、每个回测窗口训练一个新模型。

回测模式需要在部署之前[下载必要的数据](#downloading-data-to-cover-the-full-backtest-period)（不像干运行/实时模式，FreqAI 会自动处理数据下载）。您应该小心考虑下载数据的时间范围大于回测时间范围。这是因为 FreqAI 需要在所需的回测时间范围之前的数据，以便训练模型以准备对设置的回测时间范围的第一根蜡烛进行预测。有关如何计算要下载的数据的更多详细信息可以在[这里](#deciding-the-size-of-the-sliding-training-window-and-backtesting-duration)找到。

!!! Note "模型重用"
    一旦训练完成，您可以使用相同的配置文件再次执行回测，FreqAI 将找到训练的模型并加载它们，而不是花费时间进行训练。如果您想调整（甚至超参数优化）策略内的买入和卖出标准，这很有用。如果您*想*使用相同的配置文件重新训练新模型，您应该简单地更改 `identifier`。这样，您可以通过简单地指定 `identifier` 来返回使用您希望的任何模型。

!!! Note
    回测对每个回测窗口调用 `set_freqai_targets()` 一次（窗口数量是完整回测时间范围除以 `backtest_period_days` 参数）。这样做意味着目标模拟干运行/实时行为，没有前瞻偏差。但是，`feature_engineering_*()` 中特征的定义在整个训练时间范围上执行一次。这意味着您应该确保特征不会前瞻到未来。
    有关前瞻偏差的更多详细信息可以在[常见错误](strategy-customization.md#common-mistakes-when-developing-strategies)中找到。

---

### 保存回测预测数据

为了允许调整您的策略（**不是**特征！），FreqAI 将自动在回测期间保存预测，以便它们可以重用于使用相同 `identifier` 模型的未来回测和实时运行。这提供了针对**高级超参数优化**进入/退出标准的性能增强。

将在 `unique-id` 文件夹中创建一个名为 `backtesting_predictions` 的附加目录，其中包含以 `feather` 格式存储的所有预测。

要更改您的**特征**，您**必须**在配置中设置新的 `identifier`，以向 FreqAI 发出训练新模型的信号。

要保存在特定回测期间生成的模型，以便您可以从其中之一启动实时部署而不是训练新模型，您必须在配置中将 `save_backtest_models` 设置为 `True`。

!!! Note
    为了确保模型可以重用，freqAI 将使用长度为 1 的数据框调用您的策略。
    如果您的策略需要更多数据才能生成相同的特征，则无法重用回测预测进行实时部署，需要为每个新的回测更新您的 `identifier`。

### 回测实时收集的预测

FreqAI 允许您通过回测参数 `--freqai-backtest-live-models` 重用实时历史预测。当您想重用在干运行/实时运行中生成的预测进行比较或其他研究时，这可能很有用。

不得通知 `--timerange` 参数，因为它将通过历史预测文件中的数据自动计算。

### 下载数据以涵盖完整的回测期间

对于实时/干运行部署，FreqAI 将自动下载必要的数据。但是，要使用回测功能，您需要使用 `download-data` 下载必要的数据（详细信息[在这里](data-download.md#data-downloading)）。您需要仔细注意理解需要下载多少*额外*数据，以确保在回测时间范围开始*之前*有足够的训练数据。额外数据的数量可以通过从所需回测时间范围的开始向后移动 `train_period_days` 和 `startup_candle_count`（有关这些参数的详细描述，请参见[参数表](freqai-parameter-table.md)）来粗略估计。

例如，要使用设置 `train_period_days` 为 30 的[示例配置](freqai-configuration.md#setting-up-the-configuration-file)回测 `--timerange 20210501-20210701`，以及最大 `include_timeframes` 为 1h 的 `startup_candle_count: 40`，下载数据的开始日期需要为 `20210501` - 30 天 - 40 * 1h / 24 小时 = 20210330（比所需训练时间范围的开始早 31.7 天）。

### 决定滑动训练窗口和回测持续时间的大小

回测时间范围使用配置文件中的典型 `--timerange` 参数定义。滑动训练窗口的持续时间由 `train_period_days` 设置，而 `backtest_period_days` 是滑动回测窗口，两者都以天数表示（`backtest_period_days` 可以是浮点数，以指示干运行/实时模式下的亚日重新训练）。在所示的[示例配置](freqai-configuration.md#setting-up-the-configuration-file)（在 `config_examples/config_freqai.example.json` 中找到）中，用户要求 FreqAI 使用 30 天的训练期并在随后的 7 天上回测。在模型训练之后，FreqAI 将回测随后的 7 天。然后"滑动窗口"向前移动一周（模拟 FreqAI 在实时模式下每周重新训练一次），新模型使用之前的 30 天（包括之前模型用于回测的 7 天）进行训练。这会重复直到 `--timerange` 结束。这意味着如果您设置 `--timerange 20210501-20210701`，FreqAI 将在 `--timerange` 结束时训练了 8 个单独的模型（因为完整范围包括 8 周）。

!!! Note
    虽然允许小数 `backtest_period_days`，但您应该意识到 `--timerange` 被此值除以以确定 FreqAI 需要训练多少个模型才能完成完整范围的回测。例如，通过设置 `--timerange` 为 10 天，`backtest_period_days` 为 0.1，FreqAI 将需要训练每对 100 个模型来完成完整的回测。因此，FreqAI 自适应训练的真正回测将需要*非常*长的时间。完全测试模型的最佳方法是运行它进行干运行并让它不断训练。在这种情况下，回测将花费与干运行完全相同的时间。

## 定义模型过期

在干运行/实时模式期间，FreqAI 按顺序训练每个币对（在与主 Freqtrade 机器人分离的线程/GPU 上）。这意味着模型之间总是存在年龄差异。如果您正在训练 50 对，每对需要 5 分钟来训练，最旧的模型将超过 4 小时。如果策略的特征时间尺度（交易持续时间目标）小于 4 小时，这可能是不可取的。您可以决定仅在模型小于一定小时数时才进行交易条目，方法是在配置文件中设置 `expiration_hours`：

```json
    "freqai": {
        "expiration_hours": 0.5,
    }
```

在所示的示例配置中，用户只允许对小于 1/2 小时的模型进行预测。

## 控制模型学习过程

模型训练参数对于所选的机器学习库是唯一的。FreqAI 允许您使用配置中的 `model_training_parameters` 字典为任何库设置任何参数。示例配置（在 `config_examples/config_freqai.example.json` 中找到）显示了与 `Catboost` 和 `LightGBM` 相关的一些示例参数，但您可以添加这些库中可用的任何参数或您选择实现的任何其他机器学习库。

数据拆分参数在 `data_split_parameters` 中定义，它可以是与 scikit-learn 的 `train_test_split()` 函数相关的任何参数。`train_test_split()` 有一个名为 `shuffle` 的参数，允许洗牌数据或保持其未洗牌。这对于避免用时间自相关数据偏置训练特别有用。有关这些参数的更多详细信息可以在 [scikit-learn 网站](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.train_test_split.html)（外部网站）上找到。

FreqAI 特定参数 `label_period_candles` 定义用于 `labels` 的偏移量（蜡烛数量到未来）。在所示的[示例配置](freqai-configuration.md#setting-up-the-configuration-file)中，用户要求未来 24 根蜡烛的 `labels`。

## 持续学习

您可以通过在配置中设置 `"continual_learning": true` 来选择采用持续学习方案。通过启用 `continual_learning`，在从头开始训练初始模型之后，后续训练将从前一次训练的最终模型状态开始。这为新模型提供了先前状态的"记忆"。默认情况下，这设置为 `False`，这意味着所有新模型都从头开始训练，没有来自先前模型的输入。

???+ danger "持续学习强制执行恒定的参数空间"
    由于 `continual_learning` 意味着模型参数空间*不能*在训练之间改变，当启用 `continual_learning` 时，`principal_component_analysis` 会自动禁用。提示：PCA 改变参数空间和特征数量，在[这里](freqai-feature-engineering.md#data-dimensionality-reduction-with-principal-component-analysis)了解更多关于 PCA 的信息。

???+ danger "实验性功能"
    请注意，这目前是一种幼稚的增量学习方法，它有很高的过拟合/陷入局部最小值的可能性，而市场会远离您的模型。我们在 FreqAI 中提供这些机制主要是为了实验目的，以便为像加密货币市场这样的混沌系统中更成熟的持续学习方法做好准备。

## 超参数优化

您可以使用与[典型 Freqtrade 超参数优化](hyperopt.md)相同的命令进行超参数优化：

```bash
freqtrade hyperopt --hyperopt-loss SharpeHyperOptLoss --strategy FreqaiExampleStrategy --freqaimodel LightGBMRegressor --strategy-path freqtrade/templates --config config_examples/config_freqai.example.json --timerange 20220428-20220507
```

`hyperopt` 要求您以与进行[回测](#backtesting)相同的方式预先下载数据。此外，在尝试超参数优化 FreqAI 策略时，您必须考虑一些限制：

- `--analyze-per-epoch` 超参数优化参数与 FreqAI 不兼容。
- 无法在 `feature_engineering_*()` 和 `set_freqai_targets()` 函数中超参数优化指标。这意味着您不能使用超参数优化模型参数。除了这个例外，可以优化所有其他[空间](hyperopt.md#running-hyperopt-with-smaller-search-space)。
- 回测说明也适用于超参数优化。

结合超参数优化和 FreqAI 的最佳方法是专注于超参数优化进入/退出阈值/标准。您需要专注于超参数优化您的特征中未使用的参数。例如，您不应尝试在特征创建中超参数优化滚动窗口长度，或 FreqAI 配置中任何改变预测的部分。为了有效地超参数优化 FreqAI 策略，FreqAI 将预测存储为数据框并重用它们。因此，仅超参数优化进入/退出阈值/标准的要求。

FreqAI 中超参数可优化参数的一个好例子是[相异性指数（DI）](freqai-feature-engineering.md#identifying-outliers-with-the-dissimilarity-index-di) `DI_values` 的阈值，超过该阈值我们认为数据点是异常值：

```python
di_max = IntParameter(low=1, high=20, default=10, space='buy', optimize=True, load=True)
dataframe['outlier'] = np.where(dataframe['DI_values'] > self.di_max.value/10, 1, 0)
```

这个特定的超参数优化将帮助您了解特定参数空间的适当 `DI_values`。

## 使用 Tensorboard

!!! note "可用性"
    FreqAI 为各种模型包括 tensorboard，包括 XGBoost、所有 PyTorch 模型、强化学习和 Catboost。如果您希望看到 Tensorboard 集成到另一个模型类型中，请在 [Freqtrade GitHub](https://github.com/freqtrade/freqtrade/issues) 上开一个问题

!!! danger "要求"
    Tensorboard 日志记录需要 FreqAI torch 安装/docker 镜像。


使用 tensorboard 的最简单方法是确保在您的配置文件中将 `freqai.activate_tensorboard` 设置为 `True`（默认设置），运行 FreqAI，然后打开一个单独的 shell 并运行：

```bash
cd freqtrade
tensorboard --logdir user_data/models/unique-id
```

其中 `unique-id` 是 `freqai` 配置文件中设置的 `identifier`。如果您希望在浏览器中查看输出，此命令必须在单独的 shell 中运行，地址为 127.0.0.1:6060（6060 是 Tensorboard 使用的默认端口）。

![tensorboard](assets/tensorboard.jpg)


!!! note "停用以提高性能"
    Tensorboard 日志记录可能会减慢训练速度，应该在生产使用时停用。
