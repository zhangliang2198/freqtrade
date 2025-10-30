# 生产者 / 消费者模式

Freqtrade 支持让一个实例（“生产者”）通过消息 WebSocket 向其他实例（“消费者”）广播分析后的数据，例如 `analyzed_df`、`whitelist` 等。这样多个机器人可以共享指标与信号，无需重复计算。

请先参阅 [REST API 文档](rest-api.md#message-websocket) 中的“消息 WebSocket”章节，完成生产者端 `api_server` 配置。

!!! Note
    强烈建议将 `ws_token` 设置为仅自己知道的随机值，以防止他人连接到你的机器人。

## 配置

在消费者配置中添加 `external_message_consumer` 即可订阅生产者：

```json
{
    "external_message_consumer": {
        "enabled": true,
        "producers": [
            {
                "name": "default",
                "host": "127.0.0.1",
                "port": 8080,
                "secure": false,
                "ws_token": "sercet_Ws_t0ken"
            }
        ]
        // 可选项示例：
        // "wait_timeout": 300,
        // "ping_timeout": 10,
        // "sleep_time": 10,
        // "remove_entry_exit_signals": false,
        // "message_size_limit": 8
    }
}
```

| 参数 | 说明 |
|------|------|
| `enabled` | **必填**，开启消费者模式。`false` 时忽略其余配置。默认 `false`。 |
| `producers` | **必填**，生产者列表。 |
| `producers.name` | **必填**，生产者名称；调用 `get_producer_pairs()`、`get_producer_df()` 时使用。 |
| `producers.host` | **必填**，生产者主机名或 IP。 |
| `producers.port` | **必填**，端口，默认 `8080`。 |
| `producers.secure` | 是否使用 wss，默认 `false`。 |
| `producers.ws_token` | **必填**，生产者配置中的 `ws_token`。 |
| `wait_timeout` | 收不到消息时的等待时间（秒），默认 `300`。 |
| `ping_timeout` | Ping 超时时间（秒），默认 `10`。 |
| `sleep_time` | 连接失败后的重试间隔（秒），默认 `10`。 |
| `remove_entry_exit_signals` | 是否在收到 DataFrame 后把入场/出场列清零，默认 `false`。 |
| `initial_candle_limit` | 初次期望收到的蜡烛数量，默认 `1500`。 |
| `message_size_limit` | 单条消息的大小限制（MB），默认 `8`。 |

消费者无需在 `populate_indicators()` 中重复计算指标，而是通过 WebSocket 获取生产者分析过的 DataFrame（可来自多个生产者）。

## 示例

### 生产者策略

普通策略即可，无需特殊处理：

```python
class ProducerStrategy(IStrategy):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe)
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]
        dataframe["tema"] = ta.TEMA(dataframe, timeperiod=9)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["rsi"], self.buy_rsi.value)
                & (dataframe["tema"] <= dataframe["bb_middleband"])
                & (dataframe["tema"] > dataframe["tema"].shift(1))
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe
```

!!! Tip "FreqAI"
    可在高性能机器上运行 FreqAI 生产者，再让低性能设备（如树莓派）作为消费者共享信号。

### 消费者策略

消费者不再计算指标，而是直接从生产者获取：

```python
class ConsumerStrategy(IStrategy):
    process_only_new_candles = False  # 对消费者来说必须关闭
    _columns_to_expect = ["rsi_default", "tema_default", "bb_middleband_default"]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        producer_dataframe, _ = self.dp.get_producer_df(pair)
        if not producer_dataframe.empty:
            merged = merge_informative_pair(
                dataframe,
                producer_dataframe,
                self.timeframe,
                self.timeframe,
                append_timeframe=False,
                suffix="default",
            )
            return merged
        dataframe[self._columns_to_expect] = 0
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                qtpylib.crossed_above(dataframe["rsi_default"], self.buy_rsi.value)
                & (dataframe["tema_default"] <= dataframe["bb_middleband_default"])
                & (dataframe["tema_default"] > dataframe["tema_default"].shift(1))
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe
```

!!! Tip "使用上游信号"
    若在消费者配置中设置 `remove_entry_exit_signals=false`，可直接接收生产者的信号列（例如 `enter_long_default`），作为信号或附加指标。
