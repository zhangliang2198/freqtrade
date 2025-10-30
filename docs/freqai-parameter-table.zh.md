# 参数表

下表将列出 FreqAI 可用的所有配置参数。一些参数在 `config_examples/config_freqai.example.json` 中示例化。

强制参数标记为**必需**，必须以建议的方式之一设置。

### 通用配置参数

|  参数 | 描述 |
|------------|-------------|
|  |  **`config.freqai` 树中的通用配置参数**
| `freqai` | **必需**。<br> 包含控制 FreqAI 的所有参数的父字典。<br> **数据类型：** 字典。
| `train_period_days` | **必需**。<br> 用于训练数据的天数（滑动窗口的宽度）。<br> **数据类型：** 正整数。
| `backtest_period_days` | **必需**。<br> 在回测期间，在滑动上面定义的 `train_period_days` 窗口并重新训练模型之前，从训练模型推理的天数（更多信息[在这里](freqai-running.md#backtesting)）。这可以是小数天，但请注意，提供的 `timerange` 将被此数字除以，以得出完成回测所需的训练数量。<br> **数据类型：** 浮点数。
| `identifier` | **必需**。<br> 当前模型的唯一 ID。如果模型保存到磁盘，`identifier` 允许重新加载特定的预训练模型/数据。<br> **数据类型：** 字符串。
| `live_retrain_hours` | 干运行/实时运行期间的重新训练频率。<br> **数据类型：** 浮点数 > 0。<br> 默认值：`0`（模型尽可能频繁地重新训练）。
| `expiration_hours` | 如果模型超过 `expiration_hours` 小时，则避免进行预测。<br> **数据类型：** 正整数。<br> 默认值：`0`（模型永不过期）。
| `purge_old_models` | 磁盘上保留的模型数量（与回测无关）。默认值为 2，这意味着干运行/实时运行将在磁盘上保留最新的 2 个模型。设置为 0 保留所有模型。此参数也接受布尔值以保持向后兼容性。<br> **数据类型：** 整数。<br> 默认值：`2`。
| `save_backtest_models` | 运行回测时将模型保存到磁盘。回测通过保存预测数据并直接重用它们用于后续运行（当您希望调整进入/退出参数时）来最高效地运行。将回测模型保存到磁盘还允许使用相同的模型 `identifier` 启动干运行/实时实例时使用相同的模型文件。<br> **数据类型：** 布尔值。<br> 默认值：`False`（不保存模型）。
| `fit_live_predictions_candles` | 用于从预测数据而不是训练数据集计算目标（标签）统计信息的历史蜡烛数量（更多信息可以在[这里](freqai-configuration.md#creating-a-dynamic-target-threshold)找到）。<br> **数据类型：** 正整数。
| `continual_learning` | 使用最近训练的模型的最终状态作为新模型的起点，允许增量学习（更多信息可以在[这里](freqai-running.md#continual-learning)找到）。请注意，这目前是一种幼稚的增量学习方法，它有很高的过拟合/陷入局部最小值的可能性，而市场会远离您的模型。我们在这里提供这些连接主要是为了实验目的，以便为像加密货币市场这样的混沌系统中更成熟的持续学习方法做好准备。<br> **数据类型：** 布尔值。<br> 默认值：`False`。
| `write_metrics_to_disk` | 在 json 文件中收集训练时间、推理时间和 CPU 使用情况。<br> **数据类型：** 布尔值。<br> 默认值：`False`
| `data_kitchen_thread_count` | <br> 指定您想要用于数据处理（异常值方法、归一化等）的线程数。这不会影响用于训练的线程数。如果用户未设置它（默认），FreqAI 将使用最大线程数 - 2（为 Freqtrade 机器人和 FreqUI 留下 1 个物理核心）<br> **数据类型：** 正整数。
| `activate_tensorboard` | <br> 指示是否为启用 tensorboard 的模块（当前为强化学习、XGBoost、Catboost 和 PyTorch）激活 tensorboard。Tensorboard 需要安装 Torch，这意味着您需要 torch/RL docker 镜像，或者您需要对是否希望安装 Torch 的安装问题回答"是"。<br> **数据类型：** 布尔值。<br> 默认值：`True`。
| `wait_for_training_iteration_on_reload` | <br> 使用 /reload 或 ctrl-c 时，等待当前训练迭代完成后再完成优雅关闭。如果设置为 `False`，FreqAI 将中断当前训练迭代，允许您更快地优雅关闭，但您将失去当前训练迭代。<br> **数据类型：** 布尔值。<br> 默认值：`True`。

### 特征参数

|  参数 | 描述 |
|------------|-------------|
|  |  **`freqai.feature_parameters` 子字典中的特征参数**
| `feature_parameters` | 包含用于工程特征集的参数的字典。详细信息和示例显示[在这里](freqai-feature-engineering.md)。<br> **数据类型：** 字典。
| `include_timeframes` | `feature_engineering_expand_*()` 中的所有指标将为其创建的时间框架列表。该列表作为特征添加到基础指标数据集。<br> **数据类型：** 时间框架列表（字符串）。
| `include_corr_pairlist` | FreqAI 将作为附加特征添加到所有 `pair_whitelist` 币的相关币列表。在特征工程期间（详细信息请参见[这里](freqai-feature-engineering.md)），将为每个相关币创建在 `feature_engineering_expand_*()` 中设置的所有指标。相关币特征添加到基础指标数据集。<br> **数据类型：** 资产列表（字符串）。
| `label_period_candles` | 为其创建标签的未来蜡烛数量。这可以在 `set_freqai_targets()` 中使用（有关详细用法，请参见 `templates/FreqaiExampleStrategy.py`）。此参数不一定是必需的，您可以创建自定义标签并选择是否使用此参数。请参见 `templates/FreqaiExampleStrategy.py` 以查看示例用法。<br> **数据类型：** 正整数。
| `include_shifted_candles` | 从先前的蜡烛向后续蜡烛添加特征，目的是添加历史信息。如果使用，FreqAI 将复制并移动来自 `include_shifted_candles` 先前蜡烛的所有特征，以便信息可用于后续蜡烛。<br> **数据类型：** 正整数。
| `weight_factor` | 根据训练数据点的时效性对其进行加权（详细信息请参见[这里](freqai-feature-engineering.md#weighting-features-for-temporal-importance)）。<br> **数据类型：** 正浮点数（通常 < 1）。
| `indicator_max_period_candles` | **不再使用（#7325）**。被 `startup_candle_count` 替换，后者在[策略](freqai-configuration.md#building-a-freqai-strategy)中设置。`startup_candle_count` 与时间框架无关，定义在 `feature_engineering_*()` 中用于指标创建的最大*周期*。FreqAI 将此参数与 `include_time_frames` 中的最大时间框架一起使用来计算要下载多少数据点，以便第一个数据点不包含 NaN。<br> **数据类型：** 正整数。
| `indicator_periods_candles` | 计算指标的时间周期。指标添加到基础指标数据集。<br> **数据类型：** 正整数列表。
| `principal_component_analysis` | 使用主成分分析自动减少数据集的维度。有关其工作原理的详细信息，请参见[这里](freqai-feature-engineering.md#data-dimensionality-reduction-with-principal-component-analysis)<br> **数据类型：** 布尔值。<br> 默认值：`False`。
| `plot_feature_importances` | 为每个模型的前/后 `plot_feature_importances` 个特征创建特征重要性图。图存储在 `user_data/models/<identifier>/sub-train-<COIN>_<timestamp>.html` 中。<br> **数据类型：** 整数。<br> 默认值：`0`。
| `DI_threshold` | 当设置为 > 0 时，激活使用相异性指数进行异常值检测。有关其工作原理的详细信息，请参见[这里](freqai-feature-engineering.md#identifying-outliers-with-the-dissimilarity-index-di)。<br> **数据类型：** 正浮点数（通常 < 1）。
| `use_SVM_to_remove_outliers` | 训练支持向量机以从训练数据集以及传入数据点中检测和删除异常值。有关其工作原理的详细信息，请参见[这里](freqai-feature-engineering.md#identifying-outliers-using-a-support-vector-machine-svm)。<br> **数据类型：** 布尔值。
| `svm_params` | Sklearn 的 `SGDOneClassSVM()` 中可用的所有参数。有关某些选定参数的详细信息，请参见[这里](freqai-feature-engineering.md#identifying-outliers-using-a-support-vector-machine-svm)。<br> **数据类型：** 字典。
| `use_DBSCAN_to_remove_outliers` | 使用 DBSCAN 算法对数据进行聚类，以识别和删除训练和预测数据中的异常值。有关其工作原理的详细信息，请参见[这里](freqai-feature-engineering.md#identifying-outliers-with-dbscan)。<br> **数据类型：** 布尔值。
| `noise_standard_deviation` | 如果设置，FreqAI 会向训练特征添加噪声，目的是防止过拟合。FreqAI 从标准偏差为 `noise_standard_deviation` 的高斯分布生成随机偏差并将它们添加到所有数据点。`noise_standard_deviation` 应相对于归一化空间保持，即在 -1 和 1 之间。换句话说，由于 FreqAI 中的数据始终归一化为 -1 和 1 之间，`noise_standard_deviation: 0.05` 将导致 32% 的数据被随机增加/减少超过 2.5%（即落在第一个标准偏差内的数据百分比）。<br> **数据类型：** 整数。<br> 默认值：`0`。
| `outlier_protection_percentage` | 启用以防止异常值检测方法丢弃太多数据。如果 SVM 或 DBSCAN 检测到超过 `outlier_protection_percentage` % 的点是异常值，FreqAI 将记录警告消息并忽略异常值检测，即原始数据集将保持完整。如果触发异常值保护，则不会基于训练数据集进行预测。<br> **数据类型：** 浮点数。<br> 默认值：`30`。
| `reverse_train_test_order` | 拆分特征数据集（见下文）并使用最新的数据拆分进行训练，并在数据的历史拆分上进行测试。这允许模型训练到最新的数据点，同时避免过拟合。但是，在使用此参数之前，您应该小心理解其非正统的性质。<br> **数据类型：** 布尔值。<br> 默认值：`False`（无反转）。
| `shuffle_after_split` | 将数据拆分为训练集和测试集，然后分别对两个集合进行洗牌。<br> **数据类型：** 布尔值。<br> 默认值：`False`。
| `buffer_train_data_candles` | 在指标填充*后*从训练数据的开头和结尾切掉 `buffer_train_data_candles`。主要示例用途是在预测最大值和最小值时，argrelextrema 函数无法知道时间范围边缘的最大值/最小值。为了提高模型准确性，最好在整个时间范围上计算 argrelextrema，然后使用此函数按内核切掉边缘（缓冲区）。在另一种情况下，如果目标设置为移位的价格变动，则此缓冲区是不必要的，因为时间范围末尾的移位蜡烛将是 NaN，FreqAI 将自动将它们从训练数据集中切掉。<br> **数据类型：** 整数。<br> 默认值：`0`。

### 数据拆分参数

|  参数 | 描述 |
|------------|-------------|
|  |  **`freqai.data_split_parameters` 子字典中的数据拆分参数**
| `data_split_parameters` | 包含 scikit-learn `test_train_split()` 可用的任何其他参数，这些参数显示[在这里](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.train_test_split.html)（外部网站）。<br> **数据类型：** 字典。
| `test_size` | 应用于测试而不是训练的数据比例。<br> **数据类型：** 正浮点数 < 1。
| `shuffle` | 在训练期间洗牌训练数据点。通常，为了不删除时间序列预测中数据的时间顺序，这设置为 `False`。<br> **数据类型：** 布尔值。<br> 默认值：`False`。

### 模型训练参数

|  参数 | 描述 |
|------------|-------------|
|  |  **`freqai.model_training_parameters` 子字典中的模型训练参数**
| `model_training_parameters` | 一个灵活的字典，包括所选模型库可用的所有参数。例如，如果您使用 `LightGBMRegressor`，此字典可以包含 `LightGBMRegressor` 可用的任何参数[在这里](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRegressor.html)（外部网站）。如果您选择不同的模型，此字典可以包含该模型的任何参数。当前可用模型的列表可以在[这里](freqai-configuration.md#using-different-prediction-models)找到。<br> **数据类型：** 字典。
| `n_estimators` | 在模型训练中拟合的提升树数量。<br> **数据类型：** 整数。
| `learning_rate` | 在模型训练期间提升学习率。<br> **数据类型：** 浮点数。
| `n_jobs`、`thread_count`、`task_type` | 设置并行处理的线程数和 `task_type`（`gpu` 或 `cpu`）。不同的模型库使用不同的参数名称。<br> **数据类型：** 浮点数。

### 强化学习参数

|  参数 | 描述 |
|------------|-------------|
|  |  **`freqai.rl_config` 子字典中的强化学习参数**
| `rl_config` | 包含强化学习模型的控制参数的字典。<br> **数据类型：** 字典。
| `train_cycles` | 训练时间步长将基于 `train_cycles * 训练数据点数量` 设置。<br> **数据类型：** 整数。
| `max_trade_duration_candles`| 指导代理训练将交易保持在所需长度以下。示例用法显示在 `prediction_models/ReinforcementLearner.py` 中的可自定义 `calculate_reward()` 函数内。<br> **数据类型：** 整数。
| `model_type` | stable_baselines3 或 SBcontrib 的模型字符串。可用字符串包括：`'TRPO'、'ARS'、'RecurrentPPO'、'MaskablePPO'、'PPO'、'A2C'、'DQN'`。用户应通过访问其文档确保 `model_training_parameters` 与相应的 stable_baselines3 模型可用的参数匹配。[PPO 文档](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)（外部网站）<br> **数据类型：** 字符串。
| `policy_type` | stable_baselines3 可用的策略类型之一<br> **数据类型：** 字符串。
| `max_training_drawdown_pct` | 代理在训练期间允许经历的最大回撤。<br> **数据类型：** 浮点数。<br> 默认值：0.8
| `cpu_count` | 专用于强化学习训练过程的线程/CPU 数量（取决于是否选择 `ReinforcementLearner_multiproc`）。建议不要触及此项，默认情况下，此值设置为物理核心总数减 1。<br> **数据类型：** 整数。
| `model_reward_parameters` | 在 `ReinforcementLearner.py` 中可自定义 `calculate_reward()` 函数内使用的参数<br> **数据类型：** 整数。
| `add_state_info` | 告诉 FreqAI 在用于训练和推理的特征集中包含状态信息。当前状态变量包括交易持续时间、当前利润、交易位置。这仅在干运行/实时运行中可用，并自动切换为 false 进行回测。<br> **数据类型：** 布尔值。<br> 默认值：`False`。
| `net_arch` | 网络架构，在 [`stable_baselines3` 文档](https://stable-baselines3.readthedocs.io/en/master/guide/custom_policy.html#examples)中有很好的描述。总结：`[<共享层>, dict(vf=[<非共享值网络层>], pi=[<非共享策略网络层>])]`。默认情况下，这设置为 `[128, 128]`，它定义了 2 个共享隐藏层，每个层有 128 个单元。
| `randomize_starting_position` | 随机化每个情节的起始点以避免过拟合。<br> **数据类型：** 布尔值。<br> 默认值：`False`。
| `drop_ohlc_from_features` | 在训练期间传递给代理的特征集中不包括归一化的 ohlc 数据（在所有情况下，ohlc 仍将用于驱动环境）<br> **数据类型：** 布尔值。<br> **默认值：** `False`
| `progress_bar` | 显示带有当前进度、经过时间和估计剩余时间的进度条。<br> **数据类型：** 布尔值。<br> 默认值：`False`。

### PyTorch 参数

#### 通用

|  参数 | 描述 |
|------------|-------------|
|  |  **`freqai.model_training_parameters` 子字典中的模型训练参数**
| `learning_rate` | 要传递给优化器的学习率。<br> **数据类型：** 浮点数。<br> 默认值：`3e-4`。
| `model_kwargs` | 要传递给模型类的参数。<br> **数据类型：** 字典。<br> 默认值：`{}`。
| `trainer_kwargs` | 要传递给训练器类的参数。<br> **数据类型：** 字典。<br> 默认值：`{}`。

#### trainer_kwargs

| 参数    | 描述 |
|--------------|-------------|
|              |  **`freqai.model_training_parameters.model_kwargs` 子字典中的模型训练参数**
| `n_epochs`   | `n_epochs` 参数是 PyTorch 训练循环中的关键设置，它决定了整个训练数据集将被用于更新模型参数的次数。一个 epoch 代表对整个训练数据集的一次完整遍历。覆盖 `n_steps`。必须设置 `n_epochs` 或 `n_steps` 之一。<br><br> **数据类型：** 整数。可选。<br> 默认值：`10`。
| `n_steps`    | 设置 `n_epochs` 的另一种方法 - 要运行的训练迭代次数。这里的迭代是指我们调用 `optimizer.step()` 的次数。如果设置了 `n_epochs`，则忽略。函数的简化版本：<br><br> n_epochs = n_steps / (n_obs / batch_size) <br><br> 这里的动机是 `n_steps` 更容易优化并在不同 n_obs - 数据点数量之间保持稳定。<br> <br> **数据类型：** 整数。可选。<br> 默认值：`None`。
| `batch_size` | 训练期间使用的批次大小。<br><br> **数据类型：** 整数。<br> 默认值：`64`。


### 附加参数

|  参数 | 描述 |
|------------|-------------|
|  |  **额外参数**
| `freqai.keras` | 如果所选模型使用 Keras（对于基于 TensorFlow 的预测模型是典型的），则需要激活此标志，以便模型保存/加载遵循 Keras 标准。<br> **数据类型：** 布尔值。<br> 默认值：`False`。
| `freqai.conv_width` | 神经网络输入张量的宽度。这通过将历史数据点作为张量的第二维来替代移位蜡烛（`include_shifted_candles`）的需要。从技术上讲，此参数也可用于回归器，但它只会增加计算开销，不会改变模型训练/预测。<br> **数据类型：** 整数。<br> 默认值：`2`。
| `freqai.reduce_df_footprint` | 将所有数值列重新转换为 float32/int32，目的是减少 RAM/磁盘使用并减少训练/推理时间。此参数在 Freqtrade 配置文件的主级别设置（不在 FreqAI 内部）。<br> **数据类型：** 布尔值。<br> 默认值：`False`。
