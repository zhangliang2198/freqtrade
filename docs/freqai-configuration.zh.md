# 配置

FreqAI 的配置与普通 Freqtrade 一致：使用标准的[配置文件](configuration.md)和[策略](strategy-customization.md)。示例见 `config_examples/config_freqai.example.json` 与 `freqtrade/templates/FreqaiExampleStrategy.py`。

## 配置文件

虽然可选参数很多（详见 [参数表](freqai-parameter-table.md#parameter-table)），但最基本的配置需包含以下内容（仅示例值）：

```json
"freqai": {
    "enabled": true,
    "purge_old_models": 2,
    "train_period_days": 30,
    "backtest_period_days": 7,
    "identifier": "unique-id",
    "feature_parameters": {
        "include_timeframes": ["5m", "15m", "4h"],
        "include_corr_pairlist": [
            "ETH/USD",
            "LINK/USD",
            "BNB/USD"
        ],
        "label_period_candles": 24,
        "include_shifted_candles": 2,
        "indicator_periods_candles": [10, 20]
    },
    "data_split_parameters": {
        "test_size": 0.25
    }
}
```

完整示例可参考 `config_examples/config_freqai.example.json`。

!!! Note
    `identifier` 往往被忽略，但它能提供崩溃恢复与快速回测的能力。只要配置不变，请保持 `identifier` 不变（或保留 `user_data/models/<identifier>` 目录）；当你想尝试全新方案（如不同特征或模型）时，再修改该值或清理对应目录。详情见[参数表](freqai-parameter-table.md#feature-parameters)。

## 构建 FreqAI 策略

在常规策略中需要加入以下代码片段：

```python
startup_candle_count: int = 20  # 需要的最多历史蜡烛数

def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
    dataframe = self.freqai.start(dataframe, metadata, self)
    return dataframe
```

此外还需要实现 `feature_engineering_expand_all()` 与 `feature_engineering_expand_basic()` 来定义特征，并以 `%` 前缀标记供 FreqAI 内部识别。`expand_all` 会自动基于 `indicator_periods_candles`、`include_timeframes`、`include_shifted_candles`、`include_corr_pairs` 扩展特征；`expand_basic` 仅应用后面三项扩展。

### 设置标签与目标

在策略中实现 `set_freqai_targets()`，用于生成训练标签。例如：

```python
def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
    dataframe['&target'] = dataframe['close'].shift(-24)
    return dataframe
```

`freqai.start()` 会返回所有标签、是否接受预测、标签在各训练周期的均值/标准差等信息。

## 数据管理

FreqAI 使用 `FreqaiDataKitchen` 组织数据。它会根据配置自动加载、缓存、切分训练/验证数据，并处理特征工程管线。常用参数包括：

* `train_period_days`：训练样本长度
* `backtest_period_days`：验证样本长度
* `purge_old_models`：保留模型数量
* `include_timeframes`/`include_corr_pairlist`：多周期与相关交易对
* `include_shifted_candles`：平移蜡烛数
* `label_period_candles`：目标偏移

## 模型与训练

模型需继承 `IFreqaiModel` 并实现 `train`、`fit`、`predict`。Freqtrade 内置多种模型基类（sklearn、LightGBM、XGBoost、CatBoost、PyTorch 等）。以 PyTorch 为例：

1. `BasePyTorchModel`：实现通用训练逻辑（含数据标准化、设备选择、调用 `fit`）。
2. `BasePyTorchRegressor` / `BasePyTorchClassifier`：实现预测流程。
3. 具体模型类（如 `PyTorchMLPRegressor`）仅需实现 `fit`，定义模型结构、损失函数、优化器等，并调用 `PyTorchModelTrainer` 完成训练。

示例：

```python
class PyTorchMLPRegressor(BasePyTorchRegressor):
    def fit(self, data_dictionary: dict, dk: FreqaiDataKitchen, **kwargs) -> Any:
        n_features = data_dictionary["train_features"].shape[-1]
        model = PyTorchMLPModel(input_dim=n_features, output_dim=1, **self.model_kwargs)
        model.to(self.device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=self.learning_rate)
        criterion = torch.nn.MSELoss()
        init_model = self.get_init_model(dk.pair)
        trainer = PyTorchModelTrainer(
            model=model,
            optimizer=optimizer,
            criterion=criterion,
            device=self.device,
            init_model=init_model,
            target_tensor_type=torch.float,
            **self.trainer_kwargs,
        )
        trainer.fit(data_dictionary)
        return trainer
```

??? Note "分类器的标签名称"
    若使用分类模型，需要在 `set_freqai_targets` 中设置 `self.freqai.class_names`，例如：  
    ```python
    self.freqai.class_names = ["down", "up"]
    ```

### 提升性能

PyTorch 2.0 提供 `torch.compile()` 可针对特定 GPU 优化训练速度，只需在创建模型后包裹一次：

```python
model = torch.compile(model)
```

注意：启用后会禁用 eager 模式，调试信息会减少。

## 运行与回测

* `train_period_days` 与 `backtest_period_days` 会决定模型训练和验证区间。  
* `identifier` 用于区分不同实验，方便复用模型缓存。  
* 可以在回测命令中使用 `--freqai-train-periods` 等参数覆盖配置。  
* 模型与相关数据默认存放在 `user_data/models/<identifier>`。

## 常见问题

* **模型过大或过多**：可通过 `purge_old_models` 控制保留数量。  
* **训练耗时长**：减少特征、降低时间范围、缩短训练区间或使用更高性能硬件。  
* **预测偏差大**：检查标签定义、特征工程、数据预处理与模型超参。  
* **分类模型精度低**：请确保 `class_names` 顺序与标签一致，并尝试平衡数据或调整阈值。
