# Webhook 使用指南

## 配置

在配置文件中添加 `webhook` 段并将 `webhook.enabled` 设为 `true` 即可启用。以下示例基于 IFTTT：

```json
"webhook": {
    "enabled": true,
    "url": "https://maker.ifttt.com/trigger/<YOUREVENT>/with/key/<YOURKEY>/",
    "entry": {
        "value1": "Buying {pair}",
        "value2": "limit {limit:8f}",
        "value3": "{stake_amount:8f} {stake_currency}"
    },
    "entry_cancel": {
        "value1": "Cancelling Open Buy Order for {pair}",
        "value2": "limit {limit:8f}",
        "value3": "{stake_amount:8f} {stake_currency}"
    },
    "entry_fill": {
        "value1": "Buy Order for {pair} filled",
        "value2": "at {open_rate:8f}",
        "value3": ""
    },
    "exit": {
        "value1": "Exiting {pair}",
        "value2": "limit {limit:8f}",
        "value3": "profit: {profit_amount:8f} {stake_currency} ({profit_ratio})"
    },
    "exit_cancel": {
        "value1": "Cancelling Open Exit Order for {pair}",
        "value2": "limit {limit:8f}",
        "value3": "profit: {profit_amount:8f} {stake_currency} ({profit_ratio})"
    },
    "exit_fill": {
        "value1": "Exit Order for {pair} filled",
        "value2": "at {close_rate:8f}",
        "value3": ""
    },
    "status": {
        "value1": "Status: {status}",
        "value2": "",
        "value3": ""
    }
}
```

`webhook.url` 应为目标服务的接收地址。若使用 [IFTTT](https://ifttt.com)，请将事件名和 key 填入上述 URL。

### 请求格式

* 表单编码（默认）：`"format": "form"`
* JSON 编码：`"format": "json"`
* 原始文本：`"format": "raw"`

例如 Mattermost Cloud（JSON）：

```json
"webhook": {
    "enabled": true,
    "url": "https://<YOURSUBDOMAIN>.cloud.mattermost.com/hooks/<YOURHOOK>",
    "format": "json",
    "status": {
        "text": "Status: {status}"
    }
}
```

上述配置会发送 `{"text":"Status: running"}`，并附带 `Content-Type: application/json`。

* 若使用表单或 JSON，可在 payload 中自定义任意键值。
* 若使用 `raw`，只能指定名为 `"data"` 的单个字段，并且该字段仅提交值本身。例如：

```json
"webhook": {
    "enabled": true,
    "url": "https://<YOURHOOKURL>",
    "format": "raw",
    "webhookstatus": {
        "data": "Status: {status}"
    }
}
```

结果会发送 `Status: running`，并附带 `Content-Type: text/plain`。

### 嵌套结构

部分服务需要嵌套 JSON，可通过字典或列表构造内容（仅支持 `format: json`）：

```json
"webhook": {
    "enabled": true,
    "url": "https://<yourhookurl>",
    "format": "json",
    "status": {
        "msgtype": "text",
        "text": {
            "content": "Status update: {status}"
        }
    }
}
```

## 重试与超时

* `webhook.retries`：遇到非 200 响应的最大重试次数，默认 `0`（禁用）。
* `webhook.retry_delay`：两次重试之间的延迟（秒），默认 `0.1`。
* `webhook.timeout`：请求超时时间（秒），默认 10。

示例：

```json
"webhook": {
    "enabled": true,
    "url": "https://<YOURHOOKURL>",
    "timeout": 10,
    "retries": 3,
    "retry_delay": 0.2,
    "status": {
        "status": "Status: {status}"
    }
}
```

策略可通过 `self.dp.send_msg()` 自定义发送消息，需在配置中启用：

```json
"webhook": {
    "enabled": true,
    "url": "...",
    "allow_custom_messages": true
}
```

## 可用事件字段

| 事件 | 填充值说明 |
|------|------------|
| `entry`、`entry_fill` | 下单/成交时触发 |
| `entry_cancel` | 取消买单时触发 |
| `exit`、`exit_fill` | 平仓下单/成交时触发 |
| `exit_cancel` | 取消卖单时触发 |
| `status` | 状态变更（启动、停止等） |

字段内容通过 `str.format` 格式化。常见参数包括：

* `trade_id`、`exchange`、`pair`、`direction`、`leverage`
* `open_rate`、`close_rate`、`current_rate`
* `amount`、`stake_currency`、`base_currency`、`quote_currency`、`fiat_currency`
* `profit_amount`、`profit_ratio`、`gain`
* `order_type`、`enter_tag`、`exit_reason`
* `open_date`、`close_date`
* `sub_trade`、`is_final_exit`

## Discord Webhook

可单独配置 `discord` 节点（默认模板如下）：

```json
"discord": {
    "enabled": true,
    "webhook_url": "https://discord.com/api/webhooks/<...>",
    "exit_fill": [
        {"Trade ID": "{trade_id}"},
        {"Exchange": "{exchange}"},
        {"Pair": "{pair}"},
        {"Direction": "{direction}"},
        {"Open rate": "{open_rate}"},
        {"Close rate": "{close_rate}"},
        {"Amount": "{amount}"},
        {"Open date": "{open_date:%Y-%m-%d %H:%M:%S}"},
        {"Close date": "{close_date:%Y-%m-%d %H:%M:%S}"},
        {"Profit": "{profit_amount} {stake_currency}"},
        {"Profitability": "{profit_ratio:.2%}"},
        {"Enter tag": "{enter_tag}"},
        {"Exit Reason": "{exit_reason}"},
        {"Strategy": "{strategy}"},
        {"Timeframe": "{timeframe}"}
    ],
    "entry_fill": [
        {"Trade ID": "{trade_id}"},
        {"Exchange": "{exchange}"},
        {"Pair": "{pair}"},
        {"Direction": "{direction}"},
        {"Open rate": "{open_rate}"},
        {"Amount": "{amount}"},
        {"Open date": "{open_date:%Y-%m-%d %H:%M:%S}"},
        {"Enter tag": "{enter_tag}"},
        {"Strategy": "{strategy} {timeframe}"}
    ]
}
```

* 可通过赋值空数组（如 `exit_fill: []`）关闭默认模板。
* 支持 `allow_custom_messages` 配合策略调用 `send_msg()` 发送自定义通知。
* 展示示例：

![discord-notification](assets/discord_notification.png)
