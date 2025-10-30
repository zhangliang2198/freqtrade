# 强化学习

!!! Note "安装大小"
    强化学习依赖项包括大型包，如 `torch`，应在 `./setup.sh -i` 期间通过回答"是"来明确请求问题"您是否还想要 freqai-rl 的依赖项（约需要 700mb 额外空间）[y/N]？"。
    偏好使用 docker 的用户应确保他们使用附加了 `_freqairl` 的 docker 镜像。

## 背景和术语

### 什么是 RL，为什么 FreqAI 需要它？

强化学习涉及两个重要组成部分，*代理*和训练*环境*。在代理训练期间，代理逐个蜡烛地移动通过历史数据，始终进行一组动作中的 1 个：做多入场、做多退出、做空入场、做空退出、中性）。在此训练过程中，环境跟踪这些动作的表现，并根据自定义用户制作的 `calculate_reward()` 奖励代理（这里我们提供一个默认奖励供用户根据需要构建[详细信息在这里](#creating-a-custom-reward-function)）。奖励用于训练神经网络中的权重。

FreqAI RL 实现的第二个重要组成部分是使用*状态*信息。状态信息在每一步都馈送到网络中，包括当前利润、当前位置和当前交易持续时间。这些用于在训练环境中训练代理，并在干运行/实时运行中强化代理（此功能在回测中不可用）。*FreqAI + Freqtrade 是这种强化机制的完美匹配，因为这些信息在实时部署中很容易获得。*

强化学习是 FreqAI 的自然进展，因为它增加了分类器和回归器无法匹配的新的适应性和市场反应性层。然而，分类器和回归器具有 RL 所不具备的优势，例如稳健的预测。训练不当的 RL 代理可能会找到"作弊"和"技巧"来最大化奖励而实际上没有赢得任何交易。因此，RL 更复杂，需要比典型的分类器和回归器更高的理解水平。

### RL 接口

使用当前框架，我们旨在通过通用的"预测模型"文件公开训练环境，该文件是用户继承的 `BaseReinforcementLearner` 对象（例如 `freqai/prediction_models/ReinforcementLearner`）。在此用户类中，RL 环境可通过 `MyRLEnv` 获得并自定义，如[下文所示](#creating-a-custom-reward-function)。

我们设想大多数用户将他们的精力集中在 `calculate_reward()` 函数[详细信息在这里](#creating-a-custom-reward-function)的创造性设计上，同时保持环境的其余部分不变。其他用户可能根本不触及环境，他们只会使用配置设置和 FreqAI 中已经存在的强大特征工程。同时，我们使高级用户能够完全创建自己的模型类。

该框架建立在 stable_baselines3（torch）和 OpenAI gym 之上，用于基础环境类。但一般来说，模型类是很好地隔离的。因此，竞争库的添加可以轻松集成到现有框架中。对于环境，它继承自 `gym.Env`，这意味着为了切换到不同的库，需要编写一个全新的环境。

### 重要考虑事项

如上所述，代理在人工交易"环境"中"训练"。在我们的情况下，该环境可能看起来与真实的 Freqtrade 回测环境非常相似，但它*不是*。事实上，RL 训练环境要简化得多。它不包含任何复杂的策略逻辑，例如回调，如 `custom_exit`、`custom_stoploss`、杠杆控制等。相反，RL 环境是真实市场的一个非常"原始"的表示，代理可以自由学习由 `calculate_reward()` 强制执行的策略（读取：止损、止盈等）。因此，重要的是要考虑代理训练环境与现实世界不同。

## 运行强化学习

设置和运行强化学习模型与运行回归器或分类器相同。必须在命令行上定义相同的两个标志 `--freqaimodel` 和 `--strategy`：

```bash
freqtrade trade --freqaimodel ReinforcementLearner --strategy MyRLStrategy --config config.json
```

其中 `ReinforcementLearner` 将使用来自 `freqai/prediction_models/ReinforcementLearner` 的模板 `ReinforcementLearner`（或位于 `user_data/freqaimodels` 中的自定义用户定义的）。另一方面，策略遵循与典型回归器相同的基础[特征工程](freqai-feature-engineering.md)，使用 `feature_engineering_*`。不同之处在于目标的创建，强化学习不需要它们。但是，FreqAI 需要在动作列中设置一个默认（中性）值：

```python
    def set_freqai_targets(self, dataframe, **kwargs) -> DataFrame:
        """
        *仅适用于启用 FreqAI 的策略*
        设置模型目标的必需函数。
        所有目标必须以 `&` 为前缀才能被 FreqAI 内部识别。

        有关特征工程的更多详细信息，请访问：

        https://www.freqtrade.io/en/latest/freqai-feature-engineering

        :param df: 将接收目标的策略数据框
        用法示例：dataframe["&-target"] = dataframe["close"].shift(-1) / dataframe["close"]
        """
        # 对于 RL，没有直接的目标要设置。这是填充物（中性）
        # 直到代理发送一个动作。
        dataframe["&-action"] = 0
        return dataframe
```

大部分函数与典型回归器保持相同，但是，下面的函数显示了策略必须如何将原始价格数据传递给代理，以便它可以在训练环境中访问原始 OHLCV：

```python
    def feature_engineering_standard(self, dataframe: DataFrame, **kwargs) -> DataFrame:
        # RL 模型需要以下特征
        dataframe[f"%-raw_close"] = dataframe["close"]
        dataframe[f"%-raw_open"] = dataframe["open"]
        dataframe[f"%-raw_high"] = dataframe["high"]
        dataframe[f"%-raw_low"] = dataframe["low"]
    return dataframe
```

最后，没有明确的"标签"要制作 - 相反，需要分配 `&-action` 列，该列将在 `populate_entry/exit_trends()` 中访问时包含代理的动作。在本例中，中性动作为 0。此值应与使用的环境一致。FreqAI 提供两种环境，两者都使用 0 作为中性动作。

在用户意识到没有标签要设置后，他们很快就会明白代理正在做出自己的"进入"和"退出"决策。这使得策略构建相当简单。进入和退出信号来自代理，以整数形式 - 直接用于决定策略中的进入和退出：

```python
    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:

        enter_long_conditions = [df["do_predict"] == 1, df["&-action"] == 1]

        if enter_long_conditions:
            df.loc[
                reduce(lambda x, y: x & y, enter_long_conditions), ["enter_long", "enter_tag"]
            ] = (1, "long")

        enter_short_conditions = [df["do_predict"] == 1, df["&-action"] == 3]

        if enter_short_conditions:
            df.loc[
                reduce(lambda x, y: x & y, enter_short_conditions), ["enter_short", "enter_tag"]
            ] = (1, "short")

        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        exit_long_conditions = [df["do_predict"] == 1, df["&-action"] == 2]
        if exit_long_conditions:
            df.loc[reduce(lambda x, y: x & y, exit_long_conditions), "exit_long"] = 1

        exit_short_conditions = [df["do_predict"] == 1, df["&-action"] == 4]
        if exit_short_conditions:
            df.loc[reduce(lambda x, y: x & y, exit_short_conditions), "exit_short"] = 1

        return df
```

重要的是要考虑 `&-action` 取决于他们选择使用的环境。上面的示例显示了 5 个动作，其中 0 是中性，1 是做多入场，2 是做多退出，3 是做空入场，4 是做空退出。

## 配置强化学习器

为了配置 `Reinforcement Learner`，`freqai` 配置中必须存在以下字典：

```json
        "rl_config": {
            "train_cycles": 25,
            "add_state_info": true,
            "max_trade_duration_candles": 300,
            "max_training_drawdown_pct": 0.02,
            "cpu_count": 8,
            "model_type": "PPO",
            "policy_type": "MlpPolicy",
            "model_reward_parameters": {
                "rr": 1,
                "profit_aim": 0.025
            }
        }
```

参数详细信息可以在[这里](freqai-parameter-table.md)找到，但一般来说，`train_cycles` 决定代理应在其人工环境中循环通过蜡烛数据多少次来训练模型中的权重。`model_type` 是一个字符串，它选择 [stable_baselines](https://stable-baselines3.readthedocs.io/en/master/)（外部链接）中可用的模型之一。

!!! Note
    如果您想尝试 `continual_learning`，那么您应该在主 `freqai` 配置字典中将该值设置为 `true`。这将告诉强化学习库继续从先前模型的最终状态训练新模型，而不是每次发起重新训练时从头开始重新训练新模型。

!!! Note
    请记住，通用 `model_training_parameters` 字典应包含特定 `model_type` 的所有模型超参数自定义。例如，`PPO` 参数可以在[这里](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)找到。

## 创建自定义奖励函数

!!! danger "不适用于生产"
    警告！
    Freqtrade 源代码提供的奖励函数是功能展示，旨在展示/测试尽可能多的环境控制功能。它也设计为在小型计算机上快速运行。这是一个基准，它*不*用于实时生产。请注意，您需要创建自己的 custom_reward() 函数或使用 Freqtrade 源代码之外的其他用户构建的模板。

当您开始修改策略和预测模型时，您很快就会意识到强化学习器与回归器/分类器之间的一些重要区别。首先，策略不设置目标值（没有标签！）。相反，您在 `MyRLEnv` 类内设置 `calculate_reward()` 函数（见下文）。默认的 `calculate_reward()` 在 `prediction_models/ReinforcementLearner.py` 中提供，以演示创建奖励的必要构建块，但这*不*是为生产设计的。用户*必须*创建自己的自定义强化学习模型类或使用 Freqtrade 源代码之外的预构建模型并将其保存到 `user_data/freqaimodels`。在 `calculate_reward()` 中可以表达关于市场的创造性理论。例如，您可以在代理进行获胜交易时奖励它，并在代理进行失败交易时惩罚它。或者，您可能希望奖励代理进入交易，并惩罚代理在交易中停留太长时间。下面我们展示如何计算所有这些奖励的示例：

!!! note "提示"
    最好的奖励函数是连续可微的且缩放良好的。换句话说，向罕见事件添加单个大的负面惩罚不是一个好主意，神经网络将无法学习该函数。相反，最好向常见事件添加一个小的负面惩罚。这将帮助代理学习得更快。不仅如此，您还可以通过根据某些线性/指数函数使它们随严重程度缩放来帮助提高奖励/惩罚的连续性。换句话说，您会随着交易持续时间的增加而缓慢地缩放惩罚。这比在单个时间点出现单个大惩罚要好。

```python
from freqtrade.freqai.prediction_models.ReinforcementLearner import ReinforcementLearner
from freqtrade.freqai.RL.Base5ActionRLEnv import Actions, Base5ActionRLEnv, Positions


class MyCoolRLModel(ReinforcementLearner):
    """
    用户创建的 RL 预测模型。

    将此文件保存到 `freqtrade/user_data/freqaimodels`

    然后使用它：

    freqtrade trade --freqaimodel MyCoolRLModel --config config.json --strategy SomeCoolStrat

    这里用户可以覆盖 `IFreqaiModel` 继承树中可用的任何函数。
    对于 RL 来说，最重要的是，这是用户覆盖 `MyRLEnv`（见下文）的地方，
    以定义自定义 `calculate_reward()` 函数，或覆盖环境的任何其他部分。

    此类还允许用户覆盖 IFreqaiModel 树的任何其他部分。
    例如，用户可以覆盖 `def fit()` 或 `def train()` 或 `def predict()`
    以对这些过程进行精细控制。

    另一个常见的覆盖可能是 `def data_cleaning_predict()`，用户可以在其中
    对数据处理管道进行精细控制。
    """
    class MyRLEnv(Base5ActionRLEnv):
        """
        用户制作的自定义环境。此类继承自 BaseEnvironment 和 gym.Env。
        用户可以覆盖这些父类的任何函数。这是一个示例
        用户自定义的 `calculate_reward()` 函数。

        警告！
        此函数是功能展示，旨在展示尽可能多的
        环境控制功能。它也设计为在小型计算机上快速运行。
        这是一个基准，它*不*用于实时生产。
        """
        def calculate_reward(self, action: int) -> float:
            # 首先，如果动作无效则惩罚
            if not self._is_valid(action):
                return -2
            pnl = self.get_unrealized_profit()

            factor = 100

            pair = self.pair.replace(':', '')

            # 您可以使用数据框中的特征值
            # 假设在策略中生成了移位的 RSI 指标。
            rsi_now = self.raw_features[f"%-rsi-period_10_shift-1_{pair}_"
                            f"{self.config['timeframe']}"].iloc[self._current_tick]

            # 奖励代理进入交易
            if (action in (Actions.Long_enter.value, Actions.Short_enter.value)
                    and self._position == Positions.Neutral):
                if rsi_now < 40:
                    factor = 40 / rsi_now
                else:
                    factor = 1
                return 25 * factor

            # 不鼓励代理不进入交易
            if action == Actions.Neutral.value and self._position == Positions.Neutral:
                return -1
            max_trade_duration = self.rl_config.get('max_trade_duration_candles', 300)
            trade_duration = self._current_tick - self._last_trade_tick
            if trade_duration <= max_trade_duration:
                factor *= 1.5
            elif trade_duration > max_trade_duration:
                factor *= 0.5
            # 不鼓励停留在持仓中
            if self._position in (Positions.Short, Positions.Long) and \
            action == Actions.Neutral.value:
                return -1 * trade_duration / max_trade_duration
            # 平多
            if action == Actions.Long_exit.value and self._position == Positions.Long:
                if pnl > self.profit_aim * self.rr:
                    factor *= self.rl_config['model_reward_parameters'].get('win_reward_factor', 2)
                return float(pnl * factor)
            # 平空
            if action == Actions.Short_exit.value and self._position == Positions.Short:
                if pnl > self.profit_aim * self.rr:
                    factor *= self.rl_config['model_reward_parameters'].get('win_reward_factor', 2)
                return float(pnl * factor)
            return 0.
```

## 使用 Tensorboard

强化学习模型受益于跟踪训练指标。FreqAI 集成了 Tensorboard，允许用户跟踪所有币种和所有重新训练的训练和评估性能。Tensorboard 通过以下命令激活：

```bash
tensorboard --logdir user_data/models/unique-id
```

其中 `unique-id` 是 `freqai` 配置文件中设置的 `identifier`。此命令必须在单独的 shell 中运行，以在浏览器中查看输出，地址为 127.0.0.1:6006（6006 是 Tensorboard 使用的默认端口）。

![tensorboard](assets/tensorboard.jpg)

## 自定义日志记录

FreqAI 还提供了一个内置的情节摘要记录器，称为 `self.tensorboard_log`，用于向 Tensorboard 日志添加自定义信息。默认情况下，此函数已在环境内的每一步中调用一次以记录代理动作。为单个情节中的所有步骤累积的所有值都在每个情节结束时报告，然后完全重置所有指标为 0，为后续情节做准备。

`self.tensorboard_log` 也可以在环境内的任何地方使用，例如，它可以添加到 `calculate_reward` 函数中，以收集有关奖励各部分被调用频率的更详细信息：

```python
    class MyRLEnv(Base5ActionRLEnv):
        """
        用户制作的自定义环境。此类继承自 BaseEnvironment 和 gym.Env。
        用户可以覆盖这些父类的任何函数。这是一个示例
        用户自定义的 `calculate_reward()` 函数。
        """
        def calculate_reward(self, action: int) -> float:
            if not self._is_valid(action):
                self.tensorboard_log("invalid")
                return -2

```

!!! Note
    `self.tensorboard_log()` 函数设计用于仅跟踪递增对象，即训练环境内的事件、动作。如果感兴趣的事件是浮点数，则浮点数可以作为第二个参数传递，例如 `self.tensorboard_log("float_metric1", 0.23)`。在这种情况下，指标值不会递增。

## 选择基础环境

FreqAI 提供三种基础环境，`Base3ActionRLEnvironment`、`Base4ActionEnvironment` 和 `Base5ActionEnvironment`。顾名思义，环境是为可以从 3、4 或 5 个动作中选择的代理定制的。`Base3ActionEnvironment` 是最简单的，代理可以从持有、做多或做空中选择。此环境也可用于仅做多的机器人（它自动遵循策略中的 `can_short` 标志），其中做多是进入条件，做空是退出条件。同时，在 `Base4ActionEnvironment` 中，代理可以做多入场、做空入场、保持中性或退出持仓。最后，在 `Base5ActionEnvironment` 中，代理具有与 Base4 相同的动作，但它不是单个退出动作，而是分离退出做多和退出做空。环境选择引起的主要变化包括：

* `calculate_reward` 中可用的动作
* 用户策略消耗的动作

所有 FreqAI 提供的环境都继承自一个动作/位置不可知的环境对象，称为 `BaseEnvironment`，它包含所有共享逻辑。该架构设计为易于自定义。最简单的自定义是 `calculate_reward()`（详细信息请参见[这里](#creating-a-custom-reward-function)）。但是，自定义可以进一步扩展到环境内的任何函数。您可以通过简单地在预测模型文件中的 `MyRLEnv` 内覆盖这些函数来做到这一点。或者对于更高级的自定义，鼓励创建一个从 `BaseEnvironment` 继承的全新环境。

!!! Note
    只有 `Base3ActionRLEnv` 可以进行仅做多训练/交易（设置用户策略属性 `can_short = False`）。
