# Telegram 使用指南

## 创建 Telegram 机器人

以下步骤将指导你创建机器人并获取 `chat_id`。

### 1. 创建机器人

1. 与 [BotFather](https://telegram.me/BotFather) 开始对话。
2. 发送 `/newbot`，根据提示输入机器人名称与用户名（必须以 `bot` 结尾，如 `MyFreqtradeBot`）。
3. BotFather 会返回访问令牌 `token`，例如 `22222222:APITOKEN`，请保存到配置文件。
4. 点击 `/START` 与新建机器人开启对话。

### 2. 获取用户 ID 或群组 ID

- 私聊：[UserInfoBot](https://telegram.me/userinfobot) 并记录返回的 `Id` 作为 `chat_id`。
- 群聊：将机器人加入群组后启动 Freqtrade，使用 `/tg_info` 查看群组 ID（若启用了话题，还会同时返回 `topic_id`）。

配置示例：

```json
{
    "enabled": true,
    "token": "********",
    "chat_id": "-1001332619709",
    "topic_id": "122"
}
```

!!! Warning "群组使用风险"
    群内所有成员都能操作机器人。请确保群成员可信，或使用 `authorized_users` 限制指令权限。

### 3. 限制允许操作的用户

```json
{
    "chat_id": "-1001332619709",
    "topic_id": "3",
    "authorized_users": ["1234567"]
}
```

## 通知控制

可在配置中指定各类消息的通知级别（`on` | `silent` | `off`）：

```json
"telegram": {
    "enabled": true,
    "token": "...",
    "chat_id": "...",
    "allow_custom_messages": true,
    "notification_settings": {
        "status": "silent",
        "warning": "on",
        "startup": "off",
        "entry": "silent",
        "entry_fill": "on",
        "exit": {
            "roi": "silent",
            "stop_loss": "on"
        },
        "status_table": {
            "performance": "silent"
        }
    }
}
```

## 自定义消息

策略可通过 `self.dp.send_msg()` 向 Telegram 发送自定义内容，需启用 `allow_custom_messages`。示例：

```json
"telegram": {
    "enabled": true,
    "token": "...",
    "chat_id": "...",
    "allow_custom_messages": true
}
```

## 可用命令

### `/help`

显示所有可用命令。

### `/start`, `/stop`, `/panic`, `/reload_config`

分别用于启动、停止、紧急平仓与重新加载配置。

### `/status [table]`

查看持仓状态，`/status table` 会以表格输出。

### `/count`, `/profit`, `/balance`

分别返回当前持仓数量、收益统计与账户余额。

### `/forcesell <trade_id>`

强制平仓指定交易（`all` 代表全部）。

### `/forcesell <pair> [rate]`（空头 `/forceshort`，多头 `/forcelong`）

以指定价格立即建仓（使用 `/forceentry` 同义）。启用该命令需在配置中设置 `force_entry_enable: true`。

### `/performance`

返回各交易对的累计收益。

### `/daily [n]`, `/weekly [n]`, `/monthly [n]`

统计最近 n 天 / 周 / 月的收益（默认 7/8/6）。

### `/whitelist`, `/blacklist [pair]`

显示当前白名单/黑名单；在 `/blacklist` 中附带交易对可临时加入黑名单。

### `/version`

显示当前 Freqtrade 版本。

### `/marketdir [direction]`

更新或查看自定义市场方向（用于策略内的 `self.market_direction`）。

!!! Warning "重启后重置"
    市场方向不会持久化，机器人重启后需重新设置。

### `/help [command]` / `/commands`

查看指令说明或列出全部命令。

## 机器人管理员命令

管理员（默认为配置中的 `chat_id`）可执行更多操作：

* `/status table`：持仓表格
* `/entry_reason`、`/exit_reason`：查看最近交易原因
* `/open_orders`：显示未完成订单
* `/time`：当前时间
* `/ping`：连通性检测

## 推送模板

可自定义通知格式（支持 `{trade_id}`、`{pair}` 等占位符）。例：

```json
"notification_settings": {
    "entry_fill": "on",
    "templates": {
        "entry_fill": "🎯 {pair} @ {open_rate}"
    }
}
```

## 安全建议

* 不要在公开群组使用机器人，避免敏感信息外泄。
* 若使用群组，请搭配 `authorized_users` 限制可操作用户。
* 不要在网络环境不安全的设备上保存 `token`。
