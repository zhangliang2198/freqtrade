# 超参数优化 (Hyperopt)

本页面解释如何通过寻找最优参数来调整你的策略，这个过程称为超参数优化。机器人使用 `optuna` 包中包含的算法来完成此任务。
搜索过程会占用你所有的 CPU 核心，让你的笔记本电脑听起来像战斗机，但仍然需要很长时间。

一般来说，搜索最佳参数从一些随机组合开始（更多细节请参见[下文](#可重现的结果)），然后使用 optuna 的采样器算法之一（目前是 NSGAIIISampler）在搜索超空间中快速找到最小化[损失函数](#损失函数)值的参数组合。

Hyperopt 需要历史数据才能运行，就像回测一样（hyperopt 使用不同的参数多次运行回测）。
要了解如何获取你感兴趣的交易对和交易所的数据，请前往文档的[数据下载](data-download.md)部分。

!!! Bug
    在[Issue #1133](https://github.com/freqtrade/freqtrade/issues/1133)中发现，当只使用 1 个 CPU 核心时，Hyperopt 可能会崩溃

!!! Note
    从 2021.4 版本开始，你不再需要编写单独的 hyperopt 类，而是可以直接在策略中配置参数。
    旧方法支持到 2021.8 版本，并在 2021.9 版本中被移除。

## 安装 hyperopt 依赖

由于 Hyperopt 依赖不是运行机器人所必需的，且体积较大，在某些平台（如树莓派）上无法轻松构建，因此默认不安装。在运行 Hyperopt 之前，你需要安装相应的依赖，如下面的部分所述。

!!! Note
    由于 Hyperopt 是一个资源密集型过程，不推荐也不支持在树莓派上运行。

### Docker

Docker 镜像包含 hyperopt 依赖，无需进一步操作。

### 简易安装脚本 (setup.sh) / 手动安装

```bash
source .venv/bin/activate
pip install -r requirements-hyperopt.txt
```

## Hyperopt 命令参考

--8<-- "commands/hyperopt.md"

### Hyperopt 检查清单

Hyperopt 中所有任务/可能性的检查清单

根据你想要优化的空间，只需要下面的部分内容：

* 使用 `space='buy'` 定义参数 - 用于入场信号优化
* 使用 `space='sell'` 定义参数 - 用于出场信号优化

!!! Note
    `populate_indicators` 需要创建任何空间可能使用的所有指标，否则 hyperopt 将无法工作。

在极少数情况下，你可能还需要创建一个名为 `HyperOpt` 的[嵌套类](advanced-hyperopt.md#覆盖预定义空间)并实现

* `roi_space` - 用于自定义 ROI 优化（如果你需要优化超空间中 ROI 参数的范围与默认值不同）
* `generate_roi_table` - 用于自定义 ROI 优化（如果你需要 ROI 表中值的范围与默认值不同，或者 ROI 表中的条目数（步骤）与默认的 4 步不同）
* `stoploss_space` - 用于自定义止损优化（如果你需要优化超空间中止损参数的范围与默认值不同）
* `trailing_space` - 用于自定义追踪止损优化（如果你需要优化超空间中追踪止损参数的范围与默认值不同）
* `max_open_trades_space` - 用于自定义 max_open_trades 优化（如果你需要优化超空间中 max_open_trades 参数的范围与默认值不同）

!!! Tip "快速优化 ROI、止损和追踪止损"
    你可以快速优化 `roi`、`stoploss` 和 `trailing` 空间，无需更改策略中的任何内容。

    ``` bash
    # 准备好一个工作策略。
    freqtrade hyperopt --hyperopt-loss SharpeHyperOptLossDaily --spaces roi stoploss trailing --strategy MyWorkingStrategy --config config.json -e 100
    ```

### Hyperopt 执行逻辑

Hyperopt 首先将你的数据加载到内存中，然后对每个交易对运行一次 `populate_indicators()`以生成所有指标，除非指定了 `--analyze-per-epoch`。

然后 Hyperopt 会分叉成不同的进程（处理器数量，或 `-j <n>`），并一遍又一遍地运行回测，更改属于 `--spaces` 定义的参数。

对于每组新参数，freqtrade 将首先运行 `populate_entry_trend()`，然后是 `populate_exit_trend()`，然后运行常规回测过程来模拟交易。

回测后，结果被传递到[损失函数](#损失函数)中，该函数将评估此结果是否比以前的结果更好或更差。
基于损失函数的结果，hyperopt 将确定下一轮回测中要尝试的下一组参数。

### 配置你的守卫和触发器

在策略文件中有两个地方需要更改以添加新的买入 hyperopt 进行测试：

* 在类级别定义 hyperopt 应优化的参数。
* 在 `populate_entry_trend()` 中 - 使用定义的参数值而不是原始常量。

你有两种不同类型的指标：1. `守卫` 和 2. `触发器`。

1. 守卫是类似"如果 ADX < 10 则永不买入"或"如果当前价格高于 EMA10 则永不买入"的条件。
2. 触发器是在特定时刻实际触发买入的条件，例如"当 EMA5 与 EMA10 交叉时买入"或"当收盘价触及布林带下轨时买入"。

!!! Hint "守卫和触发器"
    从技术上讲，守卫和触发器之间没有区别。
    但是，本指南将做出这种区分，以明确信号不应该"粘连"。
    粘连信号是指在多个蜡烛图上都处于活动状态的信号。这可能导致信号进入较晚（就在信号消失之前 - 这意味着成功的机会比刚开始时要低得多）。

超参数优化将在每个轮次中选择一个触发器和可能多个守卫。

#### 出场信号优化

与上面的入场信号类似，出场信号也可以优化。
将相应的设置放入以下方法中

* 在类级别定义 hyperopt 应优化的参数，要么命名为 `sell_*`，要么通过显式定义 `space='sell'`。
* 在 `populate_exit_trend()` 中 - 使用定义的参数值而不是原始常量。

配置和规则与买入信号相同。

## 解决一个谜题

假设你很好奇：你应该使用 MACD 交叉还是布林带下轨来触发你的多头入场。
你还想知道应该使用 RSI 还是 ADX 来帮助做出这些决定。
如果你决定使用 RSI 或 ADX，我应该为它们使用什么值？

所以让我们使用超参数优化来解决这个谜题。

### 定义要使用的指标

我们从计算策略将要使用的指标开始。

``` python
class MyAwesomeStrategy(IStrategy):

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """
        生成策略使用的所有指标
        """
        dataframe['adx'] = ta.ADX(dataframe)
        dataframe['rsi'] = ta.RSI(dataframe)
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        bollinger = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe['bb_lowerband'] = bollinger['lowerband']
        dataframe['bb_middleband'] = bollinger['middleband']
        dataframe['bb_upperband'] = bollinger['upperband']
        return dataframe
```

### 可超参数优化的参数

我们继续定义可超参数优化的参数：

```python
class MyAwesomeStrategy(IStrategy):
    buy_adx = DecimalParameter(20, 40, decimals=1, default=30.1, space="buy")
    buy_rsi = IntParameter(20, 40, default=30, space="buy")
    buy_adx_enabled = BooleanParameter(default=True, space="buy")
    buy_rsi_enabled = CategoricalParameter([True, False], default=False, space="buy")
    buy_trigger = CategoricalParameter(["bb_lower", "macd_cross_signal"], default="bb_lower", space="buy")
```

上述定义说：我有五个参数，我想随机组合以找到最佳组合。
`buy_rsi` 是一个整数参数，将在 20 到 40 之间测试。这个空间的大小为 20。
`buy_adx` 是一个十进制参数，将在 20 到 40 之间评估，保留 1 位小数（因此值为 20.1、20.2、...）。这个空间的大小为 200。
然后我们有三个类别变量。前两个是 `True` 或 `False`。
我们使用这些来启用或禁用 ADX 和 RSI 守卫。
最后一个我们称为 `trigger`，用它来决定我们想要使用哪个买入触发器。

!!! Note "参数空间分配"
    参数必须分配给名为 `buy_*` 或 `sell_*` 的变量 - 或包含 `space='buy'` | `space='sell'` 才能正确分配到空间。
    如果某个空间没有可用的参数，在运行 hyperopt 时会收到未找到空间的错误。
    空间不明确的参数（例如 `adx_period = IntParameter(4, 24, default=14)` - 既没有显式也没有隐式空间）将不会被检测到，因此将被忽略。

所以让我们使用这些值编写买入策略：

```python
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        # 守卫和趋势
        if self.buy_adx_enabled.value:
            conditions.append(dataframe['adx'] > self.buy_adx.value)
        if self.buy_rsi_enabled.value:
            conditions.append(dataframe['rsi'] < self.buy_rsi.value)

        # 触发器
        if self.buy_trigger.value == 'bb_lower':
            conditions.append(dataframe['close'] < dataframe['bb_lowerband'])
        if self.buy_trigger.value == 'macd_cross_signal':
            conditions.append(qtpylib.crossed_above(
                dataframe['macd'], dataframe['macdsignal']
            ))

        # 检查成交量不为 0
        conditions.append(dataframe['volume'] > 0)

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, conditions),
                'enter_long'] = 1

        return dataframe
```

Hyperopt 现在将使用不同的值组合多次调用 `populate_entry_trend()`（`epochs`）。
它将使用给定的历史数据，并根据上述函数生成的买入信号模拟买入。
基于结果，hyperopt 将告诉你哪个参数组合产生了最佳结果（基于配置的[损失函数](#损失函数)）。

!!! Note
    上述设置期望在填充的指标中找到 ADX、RSI 和布林带。
    当你想测试机器人当前未使用的指标时，请记住
    将其添加到策略或 hyperopt 文件中的 `populate_indicators()` 方法。

## 参数类型

有四种参数类型，每种都适合不同的目的。

* `IntParameter` - 定义具有搜索空间上下边界的整数参数。
* `DecimalParameter` - 定义具有有限小数位数（默认 3）的浮点参数。在大多数情况下应优先于 `RealParameter`。
* `RealParameter` - 定义具有上下边界且无精度限制的浮点参数。很少使用，因为它创建了一个具有几乎无限可能性的空间。
* `CategoricalParameter` - 定义具有预定数量选择的参数。
* `BooleanParameter` - `CategoricalParameter([True, False])` 的简写 - 非常适合"启用"参数。

### 参数选项

有两个参数选项可以帮助你快速测试各种想法：

* `optimize` - 当设置为 `False` 时，该参数将不会包含在优化过程中。（默认值：True）
* `load` - 当设置为 `False` 时，先前 hyperopt 运行的结果（在策略中的 `buy_params` 和 `sell_params` 或 JSON 输出文件中）将不会用作后续 hyperopt 的起始值。将使用参数中指定的默认值。（默认值：True）

!!! Tip "`load=False` 对回测的影响"
    请注意，将 `load` 选项设置为 `False` 意味着回测也将使用参数中指定的默认值，而*不是*通过超参数优化找到的值。

!!! Warning
    可超参数优化的参数不能在 `populate_indicators` 中使用 - 因为 hyperopt 不会为每个 epoch 重新计算指标，因此在这种情况下将使用起始值。

## 优化指标参数

假设你有一个简单的策略 - EMA 交叉策略（2 个移动平均线交叉）- 并且你想找到此策略的理想参数。
默认情况下，我们假设止损为 5% - 止盈（`minimal_roi`）为 10% - 这意味着一旦达到 10% 的利润，freqtrade 将卖出交易。

``` python
from pandas import DataFrame
from functools import reduce

import talib.abstract as ta

from freqtrade.strategy import (BooleanParameter, CategoricalParameter, DecimalParameter,
                                IStrategy, IntParameter)
import freqtrade.vendor.qtpylib.indicators as qtpylib

class MyAwesomeStrategy(IStrategy):
    stoploss = -0.05
    timeframe = '15m'
    minimal_roi = {
        "0":  0.10
    }
    # 定义参数空间
    buy_ema_short = IntParameter(3, 50, default=5)
    buy_ema_long = IntParameter(15, 200, default=50)


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """生成策略使用的所有指标"""

        # 计算所有 ema_short 值
        for val in self.buy_ema_short.range:
            dataframe[f'ema_short_{val}'] = ta.EMA(dataframe, timeperiod=val)

        # 计算所有 ema_long 值
        for val in self.buy_ema_long.range:
            dataframe[f'ema_long_{val}'] = ta.EMA(dataframe, timeperiod=val)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        conditions.append(qtpylib.crossed_above(
                dataframe[f'ema_short_{self.buy_ema_short.value}'], dataframe[f'ema_long_{self.buy_ema_long.value}']
            ))

        # 检查成交量不为 0
        conditions.append(dataframe['volume'] > 0)

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, conditions),
                'enter_long'] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []
        conditions.append(qtpylib.crossed_above(
                dataframe[f'ema_long_{self.buy_ema_long.value}'], dataframe[f'ema_short_{self.buy_ema_short.value}']
            ))

        # 检查成交量不为 0
        conditions.append(dataframe['volume'] > 0)

        if conditions:
            dataframe.loc[
                reduce(lambda x, y: x & y, conditions),
                'exit_long'] = 1
        return dataframe
```

分解说明：

使用 `self.buy_ema_short.range` 将返回一个包含参数低值和高值之间所有条目的范围对象。
在这种情况下（`IntParameter(3, 50, default=5)`），循环将运行 3 到 50 之间的所有数字（`[3, 4, 5, ... 49, 50]`）。
通过在循环中使用这个，hyperopt 将生成 48 个新列（`['buy_ema_3', 'buy_ema_4', ... , 'buy_ema_50']`）。

Hyperopt 本身将使用选定的值来创建买入和卖出信号。

虽然这个策略很可能过于简单而无法提供持续的利润，但它应该作为如何优化指标参数的示例。

!!! Note
    `self.buy_ema_short.range` 在 hyperopt 和其他模式之间的行为会有所不同。对于 hyperopt，上述示例可能会生成 48 个新列，但是对于所有其他模式（回测、dry/live），它只会生成所选值的列。因此，你应该避免使用显式值（除 `self.buy_ema_short.value` 之外的值）使用结果列。

!!! Note
    `range` 属性也可以与 `DecimalParameter` 和 `CategoricalParameter` 一起使用。`RealParameter` 由于无限的搜索空间而不提供此属性。

??? Hint "性能提示"
    在正常的 hyperopt 过程中，指标计算一次并提供给每个 epoch，随着核心数量的增加，RAM 使用量线性增加。由于这也会影响性能，因此有两种替代方案可以减少 RAM 使用

    * 将 `ema_short` 和 `ema_long` 计算从 `populate_indicators()` 移动到 `populate_entry_trend()`。由于 `populate_entry_trend()` 将在每个 epoch 计算，你不需要使用 `.range` 功能。
    * hyperopt 提供 `--analyze-per-epoch`，它将 `populate_indicators()` 的执行移动到 epoch 进程，每个 epoch 每个参数计算一个值，而不是使用 `.range` 功能。在这种情况下，`.range` 功能将仅返回实际使用的值。

    这些替代方案将减少 RAM 使用，但会增加 CPU 使用。但是，你的 hyperopt 运行不太可能因内存不足（OOM）问题而失败。

    无论你是使用 `.range` 功能还是上述替代方案，你都应该尝试使用尽可能小的空间范围，因为这将改善 CPU/RAM 使用。

## 优化保护

Freqtrade 也可以优化保护。如何优化保护取决于你，以下内容应仅视为示例。

策略只需将"protections"条目定义为返回保护配置列表的属性。

``` python
from pandas import DataFrame
from functools import reduce

import talib.abstract as ta

from freqtrade.strategy import (BooleanParameter, CategoricalParameter, DecimalParameter,
                                IStrategy, IntParameter)
import freqtrade.vendor.qtpylib.indicators as qtpylib

class MyAwesomeStrategy(IStrategy):
    stoploss = -0.05
    timeframe = '15m'
    # 定义参数空间
    cooldown_lookback = IntParameter(2, 48, default=5, space="protection", optimize=True)
    stop_duration = IntParameter(12, 200, default=5, space="protection", optimize=True)
    use_stop_protection = BooleanParameter(default=True, space="protection", optimize=True)


    @property
    def protections(self):
        prot = []

        prot.append({
            "method": "CooldownPeriod",
            "stop_duration_candles": self.cooldown_lookback.value
        })
        if self.use_stop_protection.value:
            prot.append({
                "method": "StoplossGuard",
                "lookback_period_candles": 24 * 3,
                "trade_limit": 4,
                "stop_duration_candles": self.stop_duration.value,
                "only_per_pair": False
            })

        return prot

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ...

```

然后你可以如下运行 hyperopt：
`freqtrade hyperopt --hyperopt-loss SharpeHyperOptLossDaily --strategy MyAwesomeStrategy --spaces protection`

!!! Note
    保护空间不是默认空间的一部分，仅在参数 Hyperopt 接口中可用，在旧的 hyperopt 接口（需要单独的 hyperopt 文件）中不可用。
    如果选择保护空间，Freqtrade 还将自动更改"--enable-protections"标志。

!!! Warning
    如果将保护定义为属性，配置中的条目将被忽略。
    因此建议不要在配置中定义保护。

### 从先前的属性设置迁移

从先前设置的迁移非常简单，可以通过将保护条目转换为属性来完成。
简单来说，以下配置将转换为下面的内容。

``` python
class MyAwesomeStrategy(IStrategy):
    protections = [
        {
            "method": "CooldownPeriod",
            "stop_duration_candles": 4
        }
    ]
```

结果

``` python
class MyAwesomeStrategy(IStrategy):

    @property
    def protections(self):
        return [
            {
                "method": "CooldownPeriod",
                "stop_duration_candles": 4
            }
        ]
```

然后，你显然还会将潜在的有趣条目更改为参数以允许超参数优化。

### 优化 `max_entry_position_adjustment`

虽然 `max_entry_position_adjustment` 不是单独的空间，但仍可以通过使用上面显示的属性方法在 hyperopt 中使用。

``` python
from pandas import DataFrame
from functools import reduce

import talib.abstract as ta

from freqtrade.strategy import (BooleanParameter, CategoricalParameter, DecimalParameter,
                                IStrategy, IntParameter)
import freqtrade.vendor.qtpylib.indicators as qtpylib

class MyAwesomeStrategy(IStrategy):
    stoploss = -0.05
    timeframe = '15m'

    # 定义参数空间
    max_epa = CategoricalParameter([-1, 0, 1, 3, 5, 10], default=1, space="buy", optimize=True)

    @property
    def max_entry_position_adjustment(self):
        return self.max_epa.value


    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ...
```

??? Tip "使用 `IntParameter`"
    你也可以使用 `IntParameter` 进行此优化，但你必须显式返回一个整数：
    ``` python
    max_epa = IntParameter(-1, 10, default=1, space="buy", optimize=True)

    @property
    def max_entry_position_adjustment(self):
        return int(self.max_epa.value)
    ```

## 损失函数

每个超参数调整都需要一个目标。这通常定义为损失函数（有时也称为目标函数），对于更理想的结果应该减少，对于糟糕的结果应该增加。

必须通过 `--hyperopt-loss <Class-name>` 参数（或可选地通过配置中的 `"hyperopt_loss"` 键）指定损失函数。
此类应位于 `user_data/hyperopts/` 目录中的自己的文件中。

目前，以下损失函数是内置的：

* `ShortTradeDurHyperOptLoss` - (默认的旧版 Freqtrade 超参数优化损失函数) - 主要用于短交易持续时间和避免损失。
* `OnlyProfitHyperOptLoss` - 仅考虑利润金额。
* `SharpeHyperOptLoss` - 优化根据交易回报相对于标准差计算的夏普比率。
* `SharpeHyperOptLossDaily` - 优化根据**每日**交易回报相对于标准差计算的夏普比率。
* `SortinoHyperOptLoss` - 优化根据交易回报相对于**下行**标准差计算的索提诺比率。
* `SortinoHyperOptLossDaily` - 优化根据**每日**交易回报相对于**下行**标准差计算的索提诺比率。
* `MaxDrawDownHyperOptLoss` - 优化最大绝对回撤。
* `MaxDrawDownRelativeHyperOptLoss` - 优化最大绝对回撤，同时调整最大相对回撤。
* `MaxDrawDownPerPairHyperOptLoss` - 计算每对的利润/回撤比率，并返回最差的结果作为目标，强制 hyperopt 优化交易对列表中所有交易对的参数。这样，我们可以防止一个或多个结果良好的交易对使指标膨胀，而结果不佳的交易对未被代表，因此未被优化。
* `CalmarHyperOptLoss` - 优化根据交易回报相对于最大回撤计算的卡尔玛比率。
* `ProfitDrawDownHyperOptLoss` - 通过最大利润和最小回撤目标优化。可以调整 hyperoptloss 文件中的 `DRAWDOWN_MULT` 变量，以在回撤目的上更严格或更灵活。
* `MultiMetricHyperOptLoss` - 通过几个关键指标优化以实现平衡性能。主要关注最大化利润和最小化回撤，同时还考虑其他指标，如利润因子、期望比率和胜率。此外，它对交易数量少的 epoch 应用惩罚，鼓励具有足够交易频率的策略。

自定义损失函数的创建在文档的[高级 Hyperopt](advanced-hyperopt.md)部分中介绍。

## 执行 Hyperopt

一旦你更新了 hyperopt 配置，你就可以运行它。
因为 hyperopt 尝试了很多组合来找到最佳参数，所以需要时间才能得到好的结果。

我们强烈建议使用 `screen` 或 `tmux` 来防止任何连接丢失。

```bash
freqtrade hyperopt --config config.json --hyperopt-loss <hyperoptlossname> --strategy <strategyname> -e 500 --spaces all
```

`-e` 选项将设置 hyperopt 将执行多少次评估。由于 hyperopt 使用贝叶斯搜索，一次运行太多 epoch 可能不会产生更好的结果。经验表明，在 500-1000 个 epoch 之后，最佳结果通常不会有太大改善。
`--early-stop` 选项将设置在没有改进的多少个 epoch 后 hyperopt 将停止。一个好的值是总 epoch 的 20-30%。任何大于 0 且小于 20 的值都将被 20 替换。早期停止默认禁用（`--early-stop=0`）

进行多次运行（执行），每次运行几千个 epoch 并使用不同的随机状态，很可能会产生不同的结果。

`--spaces all` 选项确定应优化所有可能的参数。可能性如下所示。

!!! Note
    Hyperopt 将使用 hyperopt 开始时间的时间戳存储 hyperopt 结果。
    读取命令（`hyperopt-list`、`hyperopt-show`）可以使用 `--hyperopt-filename <filename>` 来读取和显示较旧的 hyperopt 结果。
    你可以使用 `ls -l user_data/hyperopt_results/` 找到文件名列表。

### 使用不同的历史数据源执行 Hyperopt

如果你想使用磁盘上的备用历史数据集来优化参数，请使用 `--datadir PATH` 选项。默认情况下，hyperopt 使用目录 `user_data/data` 中的数据。

### 使用较小的测试集运行 Hyperopt

使用 `--timerange` 参数更改你想使用的测试集的多少。
例如，要使用一个月的数据，请将 `--timerange 20210101-20210201`（从 2021 年 1 月 - 2021 年 2 月）传递给 hyperopt 调用。

完整命令：

```bash
freqtrade hyperopt --strategy <strategyname> --timerange 20210101-20210201
```

### 使用较小的搜索空间运行 Hyperopt

使用 `--spaces` 选项限制 hyperopt 使用的搜索空间。
让 Hyperopt 优化所有内容是一个巨大的搜索空间。
通常，仅搜索初始买入算法可能更有意义。
或者你可能只想为你的出色新买入策略优化止损或 roi 表。

合法值为：

* `all`：优化所有内容
* `buy`：仅搜索新的买入策略
* `sell`：仅搜索新的卖出策略
* `roi`：仅优化策略的最小利润表
* `stoploss`：搜索最佳止损值
* `trailing`：搜索最佳追踪止损值
* `trades`：搜索最佳最大开仓交易值
* `protection`：搜索最佳保护参数（阅读[保护部分](#优化保护)了解如何正确定义这些）
* `default`：除 `trailing`、`trades` 和 `protection` 之外的 `all`
* 上述任何值的空格分隔列表，例如 `--spaces roi stoploss`

当未指定 `--space` 命令行选项时使用的默认 Hyperopt 搜索空间不包括 `trailing` 超空间。我们建议你在找到、验证并粘贴其他超空间的最佳参数到自定义策略后，单独运行 `trailing` 超空间的优化。

## 了解 Hyperopt 结果

一旦 Hyperopt 完成，你可以使用结果来更新你的策略。
给定 hyperopt 的以下结果：

```
Best result:

    44/100:    135 trades. Avg profit  0.57%. Total profit  0.03871918 BTC (0.7722%). Avg duration 180.4 mins. Objective: 1.94367

    # Buy hyperspace params:
    buy_params = {
        'buy_adx': 44,
        'buy_rsi': 29,
        'buy_adx_enabled': False,
        'buy_rsi_enabled': True,
        'buy_trigger': 'bb_lower'
    }
```

你应该这样理解这个结果：

* 效果最好的买入触发器是 `bb_lower`。
* 你不应该使用 ADX，因为 `'buy_adx_enabled': False`。
* 你应该**考虑**使用 RSI 指标（`'buy_rsi_enabled': True`），最佳值是 `29.0`（`'buy_rsi': 29.0`）

### 自动将参数应用于策略

使用可超参数优化的参数时，你的 hyperopt 运行的结果将写入策略旁边的 json 文件（因此对于 `MyAwesomeStrategy.py`，文件将是 `MyAwesomeStrategy.json`）。
当使用 `hyperopt-show` 子命令时，此文件也会更新，除非向这两个命令中的任何一个提供了 `--disable-param-export`。


你的策略类还可以明确包含这些结果。只需复制 hyperopt 结果块并将它们粘贴到类级别，替换旧参数（如果有）。下次执行策略时，新参数将自动加载。

将整个 hyperopt 结果传输到你的策略将如下所示：

```python
class MyAwesomeStrategy(IStrategy):
    # Buy hyperspace params:
    buy_params = {
        'buy_adx': 44,
        'buy_rsi': 29,
        'buy_adx_enabled': False,
        'buy_rsi_enabled': True,
        'buy_trigger': 'bb_lower'
    }
```

!!! Note
    配置文件中的值将覆盖参数文件级别的参数 - 两者都将覆盖策略中的参数。
    因此优先级为：config > 参数文件 > 策略 `*_params` > 参数默认值

### 了解 Hyperopt ROI 结果

如果你正在优化 ROI（即优化搜索空间包含 'all'、'default' 或 'roi'），你的结果将如下所示并包含一个 ROI 表：

```
Best result:

    44/100:    135 trades. Avg profit  0.57%. Total profit  0.03871918 BTC (0.7722%). Avg duration 180.4 mins. Objective: 1.94367

    # ROI table:
    minimal_roi = {
        0: 0.10674,
        21: 0.09158,
        78: 0.03634,
        118: 0
    }
```

为了在回测和实时交易/模拟运行中使用 Hyperopt 找到的最佳 ROI 表，请将其复制粘贴作为自定义策略的 `minimal_roi` 属性的值：

```
    # 为策略设计的最小 ROI。
    # 如果配置文件包含"minimal_roi"，此属性将被覆盖
    minimal_roi = {
        0: 0.10674,
        21: 0.09158,
        78: 0.03634,
        118: 0
    }
```

如注释中所述，你还可以将其用作配置文件中 `minimal_roi` 设置的值。

#### 默认 ROI 搜索空间

如果你正在优化 ROI，Freqtrade 会为你创建 'roi' 优化超空间 - 它是 ROI 表组件的超空间。默认情况下，Freqtrade 生成的每个 ROI 表由 4 行（步骤）组成。Hyperopt 为 ROI 表实现自适应范围，ROI 步骤中的值范围取决于使用的时间框架。默认情况下，值在以下范围内变化（对于一些最常用的时间框架，值四舍五入到小数点后 3 位）：

| # step | 1m     |               | 5m       |             | 1h         |               | 1d           |               |
| ------ | ------ | ------------- | -------- | ----------- | ---------- | ------------- | ------------ | ------------- |
| 1      | 0      | 0.011...0.119 | 0        | 0.03...0.31 | 0          | 0.068...0.711 | 0            | 0.121...1.258 |
| 2      | 2...8  | 0.007...0.042 | 10...40  | 0.02...0.11 | 120...480  | 0.045...0.252 | 2880...11520 | 0.081...0.446 |
| 3      | 4...20 | 0.003...0.015 | 20...100 | 0.01...0.04 | 240...1200 | 0.022...0.091 | 5760...28800 | 0.040...0.162 |
| 4      | 6...44 | 0.0           | 30...220 | 0.0         | 360...2640 | 0.0           | 8640...63360 | 0.0           |

在大多数情况下，这些范围应该足够。步骤中的分钟（ROI 字典键）根据使用的时间框架线性缩放。步骤中的 ROI 值（ROI 字典值）根据使用的时间框架对数缩放。

如果你的自定义 hyperopt 中有 `generate_roi_table()` 和 `roi_space()` 方法，请删除它们，以便利用这些自适应 ROI 表和 Freqtrade 默认生成的 ROI 超参数优化空间。

如果你需要 ROI 表的组件在其他范围内变化，请覆盖 `roi_space()` 方法。如果你需要不同结构的 ROI 表或其他数量的行（步骤），请覆盖 `generate_roi_table()` 和 `roi_space()` 方法并实现你自己的自定义方法来生成超参数优化期间的 ROI 表。

这些方法的示例可以在[覆盖预定义空间部分](advanced-hyperopt.md#覆盖预定义空间)中找到。

!!! Note "减少的搜索空间"
    为了进一步限制搜索空间，小数限制为 3 位小数（精度为 0.001）。这通常是足够的，任何比这更精确的值通常会导致过拟合结果。但是，你可以[覆盖预定义空间](advanced-hyperopt.md#覆盖预定义空间)以根据你的需要更改此设置。

### 了解 Hyperopt 止损结果

如果你正在优化止损值（即优化搜索空间包含 'all'、'default' 或 'stoploss'），你的结果将如下所示并包含止损：

```
Best result:

    44/100:    135 trades. Avg profit  0.57%. Total profit  0.03871918 BTC (0.7722%). Avg duration 180.4 mins. Objective: 1.94367

    # Buy hyperspace params:
    buy_params = {
        'buy_adx': 44,
        'buy_rsi': 29,
        'buy_adx_enabled': False,
        'buy_rsi_enabled': True,
        'buy_trigger': 'bb_lower'
    }

    stoploss: -0.27996
```

为了在回测和实时交易/模拟运行中使用 Hyperopt 找到的最佳止损值，请将其复制粘贴作为自定义策略的 `stoploss` 属性的值：

``` python
    # 为策略设计的最佳止损
    # 如果配置文件包含"stoploss"，此属性将被覆盖
    stoploss = -0.27996
```

如注释中所述，你还可以将其用作配置文件中 `stoploss` 设置的值。

#### 默认止损搜索空间

如果你正在优化止损值，Freqtrade 会为你创建 'stoploss' 优化超空间。默认情况下，该超空间中的止损值在 -0.35...-0.02 范围内变化，这在大多数情况下是足够的。

如果你的自定义 hyperopt 文件中有 `stoploss_space()` 方法，请删除它以利用 Freqtrade 默认生成的止损超参数优化空间。

如果你需要止损值在超参数优化期间在其他范围内变化，请覆盖 `stoploss_space()` 方法并在其中定义所需范围。此方法的示例可以在[覆盖预定义空间部分](advanced-hyperopt.md#覆盖预定义空间)中找到。

!!! Note "减少的搜索空间"
    为了进一步限制搜索空间，小数限制为 3 位小数（精度为 0.001）。这通常是足够的，任何比这更精确的值通常会导致过拟合结果。但是，你可以[覆盖预定义空间](advanced-hyperopt.md#覆盖预定义空间)以根据你的需要更改此设置。

### 了解 Hyperopt 追踪止损结果

如果你正在优化追踪止损值（即优化搜索空间包含 'all' 或 'trailing'），你的结果将如下所示并包含追踪止损参数：

```
Best result:

    45/100:    606 trades. Avg profit  1.04%. Total profit  0.31555614 BTC ( 630.48%). Avg duration 150.3 mins. Objective: -1.10161

    # Trailing stop:
    trailing_stop = True
    trailing_stop_positive = 0.02001
    trailing_stop_positive_offset = 0.06038
    trailing_only_offset_is_reached = True
```

为了在回测和实时交易/模拟运行中使用 Hyperopt 找到的这些最佳追踪止损参数，请将它们复制粘贴作为自定义策略的相应属性的值：

``` python
    # 追踪止损
    # 如果配置文件包含相应的值，这些属性将被覆盖。
    trailing_stop = True
    trailing_stop_positive = 0.02001
    trailing_stop_positive_offset = 0.06038
    trailing_only_offset_is_reached = True
```

如注释中所述，你还可以将其用作配置文件中相应设置的值。

#### 默认追踪止损搜索空间

如果你正在优化追踪止损值，Freqtrade 会为你创建 'trailing' 优化超空间。默认情况下，该超空间中的 `trailing_stop` 参数始终设置为 True，`trailing_only_offset_is_reached` 的值在 True 和 False 之间变化，`trailing_stop_positive` 和 `trailing_stop_positive_offset` 参数的值分别在 0.02...0.35 和 0.01...0.1 范围内变化，这在大多数情况下是足够的。

如果你需要追踪止损参数的值在超参数优化期间在其他范围内变化，请覆盖 `trailing_space()` 方法并在其中定义所需范围。此方法的示例可以在[覆盖预定义空间部分](advanced-hyperopt.md#覆盖预定义空间)中找到。

!!! Note "减少的搜索空间"
    为了进一步限制搜索空间，小数限制为 3 位小数（精度为 0.001）。这通常是足够的，任何比这更精确的值通常会导致过拟合结果。但是，你可以[覆盖预定义空间](advanced-hyperopt.md#覆盖预定义空间)以根据你的需要更改此设置。

### 可重现的结果

搜索最佳参数从参数超空间中的一些（当前为 30 个）随机组合开始，即随机 Hyperopt epoch。这些随机 epoch 在 Hyperopt 输出的第一列中用星号字符（`*`）标记。

生成这些随机值的初始状态（随机状态）由 `--random-state` 命令行选项的值控制。你可以将其设置为你选择的某个任意值以获得可重现的结果。

如果你没有在命令行选项中显式设置此值，Hyperopt 会为你使用一些随机值为随机状态设定种子。每次 Hyperopt 运行的随机状态值都会显示在日志中，因此你可以将其复制并粘贴到 `--random-state` 命令行选项中以重复使用的初始随机 epoch 集。

如果你没有更改命令行选项、配置、时间范围、策略和 Hyperopt 类、历史数据和损失函数中的任何内容 - 你应该使用相同的随机状态值获得相同的超参数优化结果。

## 输出格式

默认情况下，hyperopt 打印彩色结果 - 具有正利润的 epoch 以绿色打印。这种突出显示可帮助你找到可能对以后的分析有趣的 epoch。具有零总利润或负利润（损失）的 epoch 以正常颜色打印。如果你不需要结果的彩色显示（例如，当你将 hyperopt 输出重定向到文件时），你可以通过在命令行中指定 `--no-color` 选项来关闭彩色显示。

如果你想在 hyperopt 输出中看到所有结果，而不仅仅是最好的结果，你可以使用 `--print-all` 命令行选项。当使用 `--print-all` 时，当前最佳结果也默认以彩色显示 - 它们以粗体（明亮）样式打印。这也可以使用 `--no-color` 命令行选项关闭。

!!! Note "Windows 和颜色输出"
    Windows 本身不支持颜色输出，因此它会自动禁用。要在 Windows 下运行的 hyperopt 有颜色输出，请考虑使用 WSL。

## 持仓堆叠和禁用最大市场持仓

在某些情况下，你可能需要使用 `--eps`/`--enable-position-stacking` 参数运行 Hyperopt（和回测），或者你可能需要将 `max_open_trades` 设置为非常高的数字以禁用对开仓交易数量的限制。

默认情况下，hyperopt 模拟 Freqtrade 实时运行/模拟运行的行为，每个交易对只允许一个开仓交易。所有交易对的开仓交易总数也受 `max_open_trades` 设置的限制。在 Hyperopt/回测期间，这可能导致潜在的交易被已经开仓的交易隐藏（或掩盖）。

`--eps`/`--enable-position-stacking` 参数允许模拟多次购买同一交易对。
使用 `--max-open-trades` 并设置非常高的数字将禁用对开仓交易数量的限制。

!!! Note
    模拟/实时运行**不会**使用持仓堆叠 - 因此验证没有这个的策略也是有意义的，因为它更接近现实。

你还可以通过在配置文件中显式设置 `"position_stacking"=true` 来启用持仓堆叠。

## 内存不足错误

由于 hyperopt 消耗大量内存（每个并行回测进程需要将完整数据放入内存一次），你很可能会遇到"内存不足"错误。
为了解决这些问题，你有多种选择：

* 减少交易对数量。
* 减少使用的时间范围（`--timerange <timerange>`）。
* 避免使用 `--timeframe-detail`（这会将大量额外数据加载到内存中）。
* 减少并行进程数（`-j <n>`）。
* 增加机器的内存。
* 如果你使用带有 `.range` 功能的大量参数，请使用 `--analyze-per-epoch`。


## 目标已在此点之前被评估。

如果你看到 `The objective has been evaluated at this point before.` - 那么这表明你的空间已经耗尽，或者接近耗尽。
基本上你的空间中的所有点都已被命中（或已命中局部最小值）- hyperopt 不再在它尚未尝试的多维空间中找到点。
Freqtrade 尝试通过在这种情况下使用新的随机化点来对抗"局部最小值"问题。

示例：

``` python
buy_ema_short = IntParameter(5, 20, default=10, space="buy", optimize=True)
# 这是买入空间中的唯一参数
```

`buy_ema_short` 空间有 15 个可能的值（`5, 6, ... 19, 20`）。如果你现在为买入空间运行 hyperopt，hyperopt 在用完选项之前只有 15 个值可以尝试。
因此，你的 epoch 应该与可能的值对齐 - 或者如果你注意到很多 `The objective has been evaluated at this point before.` 警告，你应该准备好中断运行。

## 显示 Hyperopt 结果的详细信息

在你为所需数量的 epoch 运行 Hyperopt 后，你稍后可以列出所有结果进行分析，仅选择最佳或有利可图的结果，并显示任何先前评估的 epoch 的详细信息。这可以使用 `hyperopt-list` 和 `hyperopt-show` 子命令完成。这些子命令的使用在[工具](utils.md#列出-hyperopt-结果)章节中描述。

## 从策略输出调试消息

如果你想从策略输出调试消息，你可以使用 `logging` 模块。默认情况下，Freqtrade 将输出所有级别为 `INFO` 或更高的消息。


``` python
import logging


logger = logging.getLogger(__name__)


class MyAwesomeStrategy(IStrategy):
    ...

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        logger.info("This is a debug message")
        ...

```

!!! Note "使用 print"
    除非禁用并行性（`-j 1`），否则通过 `print()` 打印的消息不会显示在 hyperopt 输出中。
    建议改用 `logging` 模块。

## 验证回测结果

一旦优化的策略已实现到你的策略中，你应该回测此策略以确保一切按预期工作。

要获得与 Hyperopt 期间相同的结果（交易数量、持续时间、利润等），请使用与 Hyperopt 相同的配置和参数（时间范围、时间框架等）进行回测。

### 为什么我的回测结果与我的 hyperopt 结果不匹配？

如果结果不匹配，请检查以下因素：

* 你可能已在 `populate_indicators()` 中向 hyperopt 添加了参数，其中它们将仅为**所有 epoch** 计算一次。例如，如果你尝试优化多个 SMA 时间周期值，可超参数优化的时间周期参数应放在 `populate_entry_trend()` 中，该参数在每个 epoch 计算。请参阅[优化指标参数](https://www.freqtrade.io/en/stable/hyperopt/#优化指标参数)。
* 如果你已禁用将 hyperopt 参数自动导出到 JSON 参数文件，请仔细检查以确保你已正确地将所有超参数优化的值传输到策略中。
* 检查日志以验证正在设置哪些参数以及正在使用哪些值。
* 特别注意止损、max_open_trades 和追踪止损参数，因为这些通常在配置文件中设置，这会覆盖对策略的更改。检查回测日志以确保没有任何参数被配置无意中设置（如 `stoploss`、`max_open_trades` 或 `trailing_stop`）。
* 验证你没有意外的参数 JSON 文件覆盖参数或策略中的默认 hyperopt 设置。
* 验证在回测中启用的任何保护在超参数优化时也启用，反之亦然。当使用 `--space protection` 时，保护会自动为超参数优化启用。
