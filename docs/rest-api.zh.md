# REST API

## FreqUI

FreqUI 现在有自己的专用[文档部分](freq-ui.md) - 请参考该部分获取有关 FreqUI 的所有信息。

## 配置

通过在配置中添加 api_server 部分并将 `api_server.enabled` 设置为 `true` 来启用 rest API。

示例配置：

``` json
    "api_server": {
        "enabled": true,
        "listen_ip_address": "127.0.0.1",
        "listen_port": 8080,
        "verbosity": "error",
        "enable_openapi": false,
        "jwt_secret_key": "somethingrandom",
        "CORS_origins": [],
        "username": "Freqtrader",
        "password": "SuperSecret1!",
        "ws_token": "sercet_Ws_t0ken"
    },
```

!!! Danger "安全警告"
    默认情况下，配置仅监听本地主机（因此无法从其他系统访问）。我们强烈建议不要将此 API 暴露到互联网，并选择一个强大、唯一的密码，因为其他人可能能够控制你的机器人。

??? Note "远程服务器上的 API/UI 访问"
    如果你在 VPS 上运行，你应该考虑使用 ssh 隧道，或设置 VPN（openVPN、wireguard）连接到你的机器人。
    这将确保 freqUI 不会直接暴露到互联网，出于安全原因不建议这样做（freqUI 不支持开箱即用的 https）。
    这些工具的设置不是本教程的一部分，但是可以在互联网上找到许多好的教程。

然后，你可以通过在浏览器中访问 `http://127.0.0.1:8080/api/v1/ping` 来检查 API 是否正常运行。
这应该返回响应：

``` output
{"status":"pong"}
```

所有其他端点返回敏感信息，需要身份验证，因此无法通过 Web 浏览器访问。

### 安全

要生成安全密码，最好使用密码管理器，或使用以下代码。

``` python
import secrets
secrets.token_hex()
```

!!! Hint "JWT 令牌"
    使用相同的方法生成 JWT 密钥（`jwt_secret_key`）。

!!! Danger "密码选择"
    请确保选择一个非常强大、唯一的密码来保护你的机器人免受未经授权的访问。
    还要将 `jwt_secret_key` 更改为随机的内容（无需记住这个，但它将用于加密你的会话，所以最好是唯一的！）。

### 使用 docker 配置

如果你使用 docker 运行机器人，你需要让机器人监听传入连接。然后由 docker 处理安全性。

``` json
    "api_server": {
        "enabled": true,
        "listen_ip_address": "0.0.0.0",
        "listen_port": 8080,
        "username": "Freqtrader",
        "password": "SuperSecret1!",
        //...
    },
```

确保你的 docker-compose 文件中有以下 2 行：

```yml
    ports:
      - "127.0.0.1:8080:8080"
```

!!! Danger "安全警告"
    通过在 docker 端口映射中使用 `"8080:8080"`（或 `"0.0.0.0:8080:8080"`），API 将可供连接到服务器的每个人在正确的端口下访问，因此其他人可能能够控制你的机器人。
    如果你在安全环境中运行机器人（如你的家庭网络），这**可能**是安全的，但不建议将 API 暴露到互联网。

## Rest API

### 使用 API

我们建议使用受支持的 `freqtrade-client` 包（也可作为 `scripts/rest_client.py` 使用）来使用 API。

此命令可以通过使用 `pip install freqtrade-client` 独立于任何运行的 freqtrade 机器人安装。

此模块设计为轻量级，仅依赖于 `requests` 和 `python-rapidjson` 模块，跳过 freqtrade 否则需要的所有重型依赖。

``` bash
freqtrade-client <command> [optional parameters]
```

默认情况下，脚本假定使用 `127.0.0.1`（localhost）和端口 `8080`，但是你可以指定配置文件来覆盖此行为。

#### 最小客户端配置

``` json
{
    "api_server": {
        "enabled": true,
        "listen_ip_address": "0.0.0.0",
        "listen_port": 8080,
        "username": "Freqtrader",
        "password": "SuperSecret1!",
        //...
    }
}
```

``` bash
freqtrade-client --config rest_config.json <command> [optional parameters]
```

具有许多参数的命令可能需要关键字参数（为了清晰起见）- 可以按如下方式提供：

``` bash
freqtrade-client --config rest_config.json forceenter BTC/USDT long enter_tag=GutFeeling
```

此方法适用于所有参数 - 检查"show"命令以获取可用参数列表。

??? Note "编程使用"
    `freqtrade-client` 包（可独立于 freqtrade 安装）可以在你自己的脚本中使用以与 freqtrade API 交互。
    要这样做，请使用以下内容：

    ``` python
    from freqtrade_client import FtRestClient


    client = FtRestClient(server_url, username, password)

    # 获取机器人的状态
    ping = client.ping()
    print(ping)

    # 将交易对添加到黑名单
    client.blacklist("BTC/USDT", "ETH/USDT")
    # 通过提供列表将交易对添加到黑名单
    client.blacklist(*listPairs)
    # ...
    ```

    有关可用命令的完整列表，请参考下面的列表。

可以使用 `help` 命令从 rest-client 脚本列出可能的命令。

``` bash
freqtrade-client help
```

``` output
Possible commands:

available_pairs
    Return available pair (backtest data) based on timeframe / stake_currency selection

        :param timeframe: Only pairs with this timeframe available.
        :param stake_currency: Only pairs that include this timeframe

balance
    Get the account balance.

blacklist
    Show the current blacklist.

        :param add: List of coins to add (example: "BNB/BTC")

cancel_open_order
    Cancel open order for trade.

        :param trade_id: Cancels open orders for this trade.

count
    Return the amount of open trades.

daily
    Return the profits for each day, and amount of trades.

delete_lock
    Delete (disable) lock from the database.

        :param lock_id: ID for the lock to delete

delete_trade
    Delete trade from the database.
        Tries to close open orders. Requires manual handling of this asset on the exchange.

        :param trade_id: Deletes the trade with this ID from the database.

forcebuy
    Buy an asset.

        :param pair: Pair to buy (ETH/BTC)
        :param price: Optional - price to buy

forceenter
    Force entering a trade

        :param pair: Pair to buy (ETH/BTC)
        :param side: 'long' or 'short'
        :param price: Optional - price to buy

forceexit
    Force-exit a trade.

        :param tradeid: Id of the trade (can be received via status command)
        :param ordertype: Order type to use (must be market or limit)
        :param amount: Amount to sell. Full sell if not given

health
    Provides a quick health check of the running bot.

lock_add
    Manually lock a specific pair

        :param pair: Pair to lock
        :param until: Lock until this date (format "2024-03-30 16:00:00Z")
        :param side: Side to lock (long, short, *)
        :param reason: Reason for the lock

locks
    Return current locks

logs
    Show latest logs.

        :param limit: Limits log messages to the last <limit> logs. No limit to get the entire log.

pair_candles
    Return live dataframe for <pair><timeframe>.

        :param pair: Pair to get data for
        :param timeframe: Only pairs with this timeframe available.
        :param limit: Limit result to the last n candles.

pair_history
    Return historic, analyzed dataframe

        :param pair: Pair to get data for
        :param timeframe: Only pairs with this timeframe available.
        :param strategy: Strategy to analyze and get values for
        :param timerange: Timerange to get data for (same format than --timerange endpoints)

performance
    Return the performance of the different coins.

ping
    simple ping

plot_config
    Return plot configuration if the strategy defines one.

profit
    Return the profit summary.

reload_config
    Reload configuration.

show_config
    Returns part of the configuration, relevant for trading operations.

start
    Start the bot if it's in the stopped state.

pause
    Pause the bot if it's in the running state. If triggered on stopped state will handle open positions.

stats
    Return the stats report (durations, sell-reasons).

status
    Get the status of open trades.

stop
    Stop the bot. Use `start` to restart.

stopbuy
    Stop buying (but handle sells gracefully). Use `reload_config` to reset.

strategies
    Lists available strategies

strategy
    Get strategy details

        :param strategy: Strategy class name

sysinfo
    Provides system information (CPU, RAM usage)

trade
    Return specific trade

        :param trade_id: Specify which trade to get.

trades
    Return trades history, sorted by id

        :param limit: Limits trades to the X last trades. Max 500 trades.
        :param offset: Offset by this amount of trades.

list_open_trades_custom_data
    Return a dict containing open trades custom-datas

        :param key: str, optional - Key of the custom-data
        :param limit: Limits trades to X trades.
        :param offset: Offset by this amount of trades.

list_custom_data
    Return a dict containing custom-datas of a specified trade

        :param trade_id: int - ID of the trade
        :param key: str, optional - Key of the custom-data

version
    Return the version of the bot.

whitelist
    Show the current whitelist.


```

### 可用端点

如果你希望通过另一个路由手动调用 REST API，例如直接通过 `curl`，下表显示了相关的 URL 端点和参数。
下表中的所有端点都需要以 API 的基本 URL 为前缀，例如 `http://127.0.0.1:8080/api/v1/` - 因此命令变为 `http://127.0.0.1:8080/api/v1/<command>`。

|  端点 | 方法 | 描述 / 参数 |
|-----------|--------|-----------------------------|
| `/ping` | GET | 简单命令测试 API 就绪性 - 不需要身份验证。
| `/start` | POST | 启动交易者。
| `/pause` | POST | 暂停交易者。根据规则优雅地处理未平仓交易。不进入新头寸。
| `/stop` | POST | 停止交易者。
| `/stopbuy` | POST | 阻止交易者开启新交易。根据规则优雅地关闭未平仓交易。
| `/reload_config` | POST | 重新加载配置文件。
| `/trades` | GET | 列出最后的交易。每次调用限制为 500 笔交易。
| `/trade/<tradeid>` | GET | 获取特定交易。<br/>*参数：*<br/>- `tradeid` (`int`)
| `/trades/<tradeid>` | DELETE | 从数据库中删除交易。尝试关闭未平仓订单。需要在交易所手动处理此交易。<br/>*参数：*<br/>- `tradeid` (`int`)
| `/trades/<tradeid>/open-order` | DELETE | 取消此交易的未平仓订单。<br/>*参数：*<br/>- `tradeid` (`int`)
| `/trades/<tradeid>/reload` | POST | 从交易所重新加载交易。仅适用于实盘，可能有助于恢复在交易所上手动出售的交易。<br/>*参数：*<br/>- `tradeid` (`int`)
| `/show_config` | GET | 显示当前配置的一部分，包含与操作相关的相关设置。
| `/logs` | GET | 显示最近的日志消息。
| `/status` | GET | 列出所有未平仓交易。
| `/count` | GET | 显示已使用和可用的交易数量。
| `/entries` | GET | 显示给定交易对（如果未给出交易对则为所有交易对）的每个入场标签的利润统计。交易对是可选的。<br/>*参数：*<br/>- `pair` (`str`)
| `/exits` | GET | 显示给定交易对（如果未给出交易对则为所有交易对）的每个出场原因的利润统计。交易对是可选的。<br/>*参数：*<br/>- `pair` (`str`)
| `/mix_tags` | GET | 显示给定交易对（如果未给出交易对则为所有交易对）的入场标签 + 出场原因的每个组合的利润统计。交易对是可选的。<br/>*参数：*<br/>- `pair` (`str`)
| `/locks` | GET | 显示当前锁定的交易对。
| `/locks` | POST | 锁定交易对直到"until"。（Until 将向上舍入到最近的时间框架）。Side 是可选的，是 `long` 或 `short`（默认是 `long`）。Reason 是可选的。<br/>*参数：*<br/>- `<pair>` (`str`)<br/>- `<until>` (`datetime`)<br/>- `[side]` (`str`)<br/>- `[reason]` (`str`)
| `/locks/<lockid>` | DELETE | 通过 id 删除（禁用）锁。<br/>*参数：*<br/>- `lockid` (`int`)
| `/profit` | GET | 显示你的平仓交易的利润/损失摘要以及有关你的表现的一些统计数据。
| `/forceexit` | POST | 立即退出给定的交易（忽略 `minimum_roi`），使用给定的订单类型（"market"或"limit"，如果未指定则使用你的配置设置），以及选择的金额（如果未指定则完全出售）。如果提供 `all` 作为 `tradeid`，则所有当前未平仓交易将被强制退出。<br/>*参数：*<br/>- `<tradeid>` (`int` 或 `str`)<br/>- `<ordertype>` (`str`)<br/>- `[amount]` (`float`)
| `/forceenter` | POST | 立即进入给定的交易对。Side 是可选的，是 `long` 或 `short`（默认是 `long`）。Rate 是可选的。（`force_entry_enable` 必须设置为 True）<br/>*参数：*<br/>- `<pair>` (`str`)<br/>- `<side>` (`str`)<br/>- `[rate]` (`float`)
| `/performance` | GET | 显示按交易对分组的每笔已完成交易的表现。
| `/balance` | GET | 显示每种货币的账户余额。
| `/daily` | GET | 显示过去 n 天的每日利润或损失（n 默认为 7）。<br/>*参数：*<br/>- `timescale` (`int`)
| `/weekly` | GET | 显示过去 n 周的每周利润或损失（n 默认为 4）。<br/>*参数：*<br/>- `timescale` (`int`)
| `/monthly` | GET | 显示过去 n 月的每月利润或损失（n 默认为 3）。<br/>*参数：*<br/>- `timescale` (`int`)
| `/stats` | GET | 显示利润/损失原因的摘要以及平均持仓时间。
| `/whitelist` | GET | 显示当前白名单。
| `/blacklist` | GET | 显示当前黑名单。
| `/blacklist` | POST | 将指定的交易对添加到黑名单。<br/>*参数：*<br/>- `blacklist` (`str`)
| `/blacklist` | DELETE | 从黑名单中删除指定的交易对列表。<br/>*参数：*<br/>- `[pair,pair]` (`list[str]`)
| `/pair_candles` | GET | 在机器人运行时返回交易对/时间框架组合的数据帧。**Alpha**
| `/pair_candles` | POST | 在机器人运行时返回交易对/时间框架组合的数据帧，由提供的要返回的列列表过滤。**Alpha**<br/>*参数：*<br/>- `<column_list>` (`list[str]`)
| `/pair_history` | GET | 返回给定时间范围的已分析数据帧，由给定策略分析。**Alpha**
| `/pair_history` | POST | 返回给定时间范围的已分析数据帧，由给定策略分析，由提供的要返回的列列表过滤。**Alpha**<br/>*参数：*<br/>- `<column_list>` (`list[str]`)
| `/plot_config` | GET | 从策略获取绘图配置（如果未配置则为空）。**Alpha**
| `/strategies` | GET | 列出策略目录中的策略。**Alpha**
| `/strategy/<strategy>` | GET | 通过策略类名获取特定策略内容。**Alpha**<br/>*参数：*<br/>- `<strategy>` (`str`)
| `/available_pairs` | GET | 列出可用的回测数据。**Alpha**
| `/version` | GET | 显示版本。
| `/sysinfo` | GET | 显示有关系统负载的信息。
| `/health` | GET | 显示机器人健康状况（上次机器人循环）。

!!! Warning "Alpha 状态"
    上面标记为 *Alpha 状态* 的端点可能随时更改，恕不另行通知。

### 消息 WebSocket

API 服务器包括一个 websocket 端点，用于订阅来自 freqtrade Bot 的 RPC 消息。
这可用于从你的机器人消费实时数据，例如入场/出场填充消息、白名单更改、交易对的填充指标等。

这也用于在 Freqtrade 中设置[生产者/消费者模式](producer-consumer.md)。

假设你的 rest API 设置为 `127.0.0.1`，端口为 `8080`，端点可在 `http://localhost:8080/api/v1/message/ws` 访问。

要访问 websocket 端点，需要在端点 URL 中将 `ws_token` 作为查询参数。

要生成安全的 `ws_token`，你可以运行以下代码：

``` python
>>> import secrets
>>> secrets.token_urlsafe(25)
'hZ-y58LXyX_HZ8O1cJzVyN6ePWrLpNQv4Q'
```

然后，你将在 `api_server` 配置中的 `ws_token` 下添加该令牌。如下所示：

``` json
"api_server": {
    "enabled": true,
    "listen_ip_address": "127.0.0.1",
    "listen_port": 8080,
    "verbosity": "error",
    "enable_openapi": false,
    "jwt_secret_key": "somethingrandom",
    "CORS_origins": [],
    "username": "Freqtrader",
    "password": "SuperSecret1!",
    "ws_token": "hZ-y58LXyX_HZ8O1cJzVyN6ePWrLpNQv4Q" // <-----
},
```

你现在可以连接到端点 `http://localhost:8080/api/v1/message/ws?token=hZ-y58LXyX_HZ8O1cJzVyN6ePWrLpNQv4Q`。

!!! Danger "重用示例令牌"
    请不要使用上面的示例令牌。为确保你的安全，请生成一个全新的令牌。

#### 使用 WebSocket

连接到 WebSocket 后，机器人将向订阅它们的任何人广播 RPC 消息。要订阅消息列表，你必须通过 WebSocket 发送如下所示的 JSON 请求。`data` 键必须是消息类型字符串列表。

``` json
{
  "type": "subscribe",
  "data": ["whitelist", "analyzed_df"] // 字符串消息类型列表
}
```

有关消息类型列表，请参考 `freqtrade/enums/rpcmessagetype.py` 中的 RPCMessageType 枚举

现在，只要在机器人中发送这些类型的 RPC 消息，只要连接处于活动状态，你就会通过 WebSocket 接收它们。它们通常采用与请求相同的形式：

``` json
{
  "type": "analyzed_df",
  "data": {
      "key": ["NEO/BTC", "5m", "spot"],
      "df": {}, // 数据帧
      "la": "2022-09-08 22:14:41.457786+00:00"
  }
}
```

#### 反向代理设置

使用 [Nginx](https://nginx.org/en/docs/) 时，WebSocket 需要以下配置才能工作（请注意，此配置不完整，缺少一些信息，不能按原样使用）：

请确保将 `<freqtrade_listen_ip>`（和后续端口）替换为与你的配置/设置匹配的 IP 和端口。

```
http {
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    #...

    server {
        #...

        location / {
            proxy_http_version 1.1;
            proxy_pass http://<freqtrade_listen_ip>:8080;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Host $host;
        }
    }
}
```

要正确配置反向代理（安全地），请查阅其有关代理 websocket 的文档。

- **Traefik**：Traefik 开箱即用地支持 websockets，请参阅[文档](https://doc.traefik.io/traefik/)
- **Caddy**：Caddy v2 开箱即用地支持 websockets，请参阅[文档](https://caddyserver.com/docs/v2-upgrade#proxy)

!!! Tip "SSL 证书"
    你可以使用 certbot 等工具设置 ssl 证书，通过使用上述任何反向代理通过加密连接访问机器人的 UI。
    虽然这将保护你的传输数据，但我们不建议在你的专用网络（VPN、SSH 隧道）之外运行 freqtrade API。

### OpenAPI 接口

要启用内置的 openAPI 接口（Swagger UI），请在 api_server 配置中指定 `"enable_openapi": true`。
这将在 `/docs` 端点启用 Swagger UI。默认情况下，它在 <http://localhost:8080/docs> 运行 - 但这取决于你的设置。

### 使用 JWT 令牌的高级 API 使用

!!! Note
    以下应该在应用程序中完成（Freqtrade REST API 客户端，通过 API 获取信息），不打算定期使用。

Freqtrade 的 REST API 还提供 JWT（JSON Web Tokens）。
你可以使用以下命令登录，然后使用生成的 access_token。

``` bash
> curl -X POST --user Freqtrader http://localhost:8080/api/v1/token/login
{"access_token":"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE1ODkxMTk2ODEsIm5iZiI6MTU4OTExOTY4MSwianRpIjoiMmEwYmY0NWUtMjhmOS00YTUzLTlmNzItMmM5ZWVlYThkNzc2IiwiZXhwIjoxNTg5MTIwNTgxLCJpZGVudGl0eSI6eyJ1IjoiRnJlcXRyYWRlciJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.qt6MAXYIa-l556OM7arBvYJ0SDI9J8bIk3_glDujF5g","refresh_token":"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE1ODkxMTk2ODEsIm5iZiI6MTU4OTExOTY4MSwianRpIjoiZWQ1ZWI3YjAtYjMwMy00YzAyLTg2N2MtNWViMjIxNWQ2YTMxIiwiZXhwIjoxNTkxNzExNjgxLCJpZGVudGl0eSI6eyJ1IjoiRnJlcXRyYWRlciJ9LCJ0eXBlIjoicmVmcmVzaCJ9.d1AT_jYICyTAjD0fiQAr52rkRqtxCjUGEMwlNuuzgNQ"}

> access_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE1ODkxMTk2ODEsIm5iZiI6MTU4OTExOTY4MSwianRpIjoiMmEwYmY0NWUtMjhmOS00YTUzLTlmNzItMmM5ZWVlYThkNzc2IiwiZXhwIjoxNTg5MTIwNTgxLCJpZGVudGl0eSI6eyJ1IjoiRnJlcXRyYWRlciJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.qt6MAXYIa-l556OM7arBvYJ0SDI9J8bIk3_glDujF5g"
# 使用 access_token 进行身份验证
> curl -X GET --header "Authorization: Bearer ${access_token}" http://localhost:8080/api/v1/count

```

由于访问令牌有一个短超时时间（15 分钟）- 应定期使用 `token/refresh` 请求来获取新的访问令牌：

``` bash
> curl -X POST --header "Authorization: Bearer ${refresh_token}"http://localhost:8080/api/v1/token/refresh
{"access_token":"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpYXQiOjE1ODkxMTk5NzQsIm5iZiI6MTU4OTExOTk3NCwianRpIjoiMDBjNTlhMWUtMjBmYS00ZTk0LTliZjAtNWQwNTg2MTdiZDIyIiwiZXhwIjoxNTg5MTIwODc0LCJpZGVudGl0eSI6eyJ1IjoiRnJlcXRyYWRlciJ9LCJmcmVzaCI6ZmFsc2UsInR5cGUiOiJhY2Nlc3MifQ.1seHlII3WprjjclY6DpRhen0rqdF4j6jbvxIhUFaSbs"}
```

--8<-- "includes/cors.md"
