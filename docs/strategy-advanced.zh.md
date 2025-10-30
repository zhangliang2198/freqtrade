# 高级策略技巧

本文介绍策略开发中的进阶用法。若你尚未熟悉基础概念，请先阅读 [Freqtrade 基础](bot-basics.md) 与 [策略自定义指南](strategy-customization.zh.md)。

!!! Note
    仅在确实需要时实现回调；多余代码会增加复杂度。

!!! Tip
    可使用 `freqtrade new-strategy --strategy MyAwesomeStrategy --template advanced` 生成包含全部回调的模板。

## 持久化自定义数据

Freqtrade 支持针对单个交易存储自定义信息。通过 `trade.set_custom_data(key, value)` 保存，`trade.get_custom_data(key)` 读取：

```python
trade.set_custom_data(key="entry_type", value="breakout")
entry_type = trade.get_custom_data(key="entry_type")
```

数据会以 JSON 序列化写入数据库。请尽量使用简单数据类型（`int`、`float`、`str`、`bool`），避免保存大量数据造成性能问题。

## 自定义绘图标签（FreqUI）

策略可使用以下方法向 FreqUI 绘图面板添加额外信息。

### `plot_config` 指标配置

在策略中定义 `plot_config` 决定指标的颜色、类型、子图等。例如：

```python
@property
def plot_config(self):
    return {
        "main_plot": {
            "ema_20": {"color": "red"},
            "ema_50": {"color": "green"},
            "senkou_a": {
                "color": "orange",
                "fill_to": "senkou_b",
                "fill_label": "Ichimoku Cloud"
            },
            "senkou_b": {}
        },
        "subplots": {
            "MACD": {
                "macd": {"color": "blue", "fill_to": "macdhist"},
                "macdsignal": {"color": "orange"},
                "macdhist": {"type": "bar"}
            },
            "RSI": {"rsi": {"color": "purple"}}
        }
    }
```

!!! Note
    配置中引用的指标必须存在于 DataFrame 中。

### `plot_entries()` / `plot_exits()`

自定义绘制额外入场/出场点，可返回包含 `value`、`label`、`color` 等字段的列表：

```python
def plot_entries(self, pair, current_time, dataframe, **kwargs):
    return [
        PlotType(
            value=dataframe.loc[dataframe["custom_signal"] == 1, "close"],
            label="custom_entry",
            color="green"
        )
    ]
```

!!! Warning
    回调返回的数据量过大会拖慢界面，仅绘制必要点位。

### `plot_annotations()`

可在图表上标注区域或线段，例如标记每日开盘时段：

```python
def plot_annotations(self, pair, start_date, end_date, dataframe, **kwargs):
    annotations = []
    dt = start_date
    while dt < end_date:
        dt += timedelta(hours=1)
        if dt.hour in (8, 15):
            annotations.append({
                "type": "area",
                "label": "session",
                "start": dt,
                "end": dt + timedelta(hours=1),
                "color": "rgba(133,133,133,0.4)"
            })
    return annotations
```

支持类型：

* `line`：指定 `start`/`end` 与 `y_start`/`y_end`
* `area`：可省略 `y` 值以绘制垂直高亮区域

!!! Warning
    过多注释会导致 UI 卡顿，请谨慎使用。

## 策略版本控制

可实现 `version()` 方法返回自定义版本号，配合 Git 等工具记录策略变更：

```python
def version(self) -> str:
    return "1.1"
```

## 继承策略

可通过继承避免代码重复。例如：

```python
class BaseStrategy(IStrategy):
    stoploss = -0.1

class AggressiveStrategy(BaseStrategy):
    stoploss = -0.05
    trailing_stop = True
```

建议将子类放在独立文件中，并通过 import 引用父策略，以免 Hyperopt 参数加载错误。

## 策略嵌入配置

可将策略文件 BASE64 编码后直接写入配置：

```python
from base64 import urlsafe_b64encode
with open("MyStrategy.py", "r") as f:
    encoded = urlsafe_b64encode(f.read().encode("utf-8"))
```

配置示例：

```json
"strategy": "MyStrategy:BASE64字符串"
```

!!! Warning
    请确保类名与配置中一致。

## 修复 Pandas 碎片化警告

若出现 `PerformanceWarning: DataFrame is highly fragmented`，建议改用 `pd.concat` 一次性拼接列，而非循环逐列赋值。例如：

```python
frames = [dataframe]
for period in self.buy_ema_short.range:
    frames.append(DataFrame({f"ema_short_{period}": ta.EMA(dataframe, timeperiod=period)}))
dataframe = pd.concat(frames, axis=1)
```

虽然 Freqtrade 会自动复制 DataFrame 缓解性能问题，但优化后可减少不必要的警告。

## 小结

本文介绍了策略开发中的高级工具，包括：

- 持久化自定义数据
- FreqUI 绘图增强
- 回调与注释扩展
- 策略继承与版本管理
- 策略嵌入配置

善用这些机制，可让策略更加灵活、可维护。如需进一步优化，请继续阅读 [策略回调](strategy-callbacks.zh.md) 与相关文档。
