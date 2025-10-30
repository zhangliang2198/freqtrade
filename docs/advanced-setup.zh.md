# 高级安装后任务

本页面解释了一些可以在机器人安装后执行的高级任务和配置选项，这些可能在某些环境中很有用。

如果您不知道这里提到的内容是什么意思，您可能不需要它。

## 运行多个 Freqtrade 实例

本节将向您展示如何在同一台机器上同时运行多个机器人。

### 需要考虑的事项

* 使用不同的数据库文件。
* 使用不同的 Telegram 机器人（需要多个不同的配置文件；仅在启用 Telegram 时适用）。
* 使用不同的端口（仅在启用 Freqtrade REST API 网络服务器时适用）。

### 不同的数据库文件

为了跟踪您的交易、利润等，freqtrade 使用 SQLite 数据库存储各种类型的信息，例如您过去执行的交易以及您在任何时候持有的当前仓位。这使您能够跟踪您的利润，但最重要的是，如果机器人进程重新启动或意外终止，也能跟踪正在进行的活动。

默认情况下，Freqtrade 将为模拟运行和实盘机器人使用单独的数据库文件（假设配置中或通过命令行参数未给出 database-url）。
对于实盘交易模式，默认数据库将是 `tradesv3.sqlite`，对于模拟运行，将是 `tradesv3.dryrun.sqlite`。

用于指定这些文件路径的 trade 命令的可选参数是 `--db-url`，它需要一个有效的 SQLAlchemy url。
因此，当您在模拟运行模式下仅使用配置和策略参数启动机器人时，以下 2 个命令将具有相同的结果。

``` bash
freqtrade trade -c MyConfig.json -s MyStrategy
# 等同于
freqtrade trade -c MyConfig.json -s MyStrategy --db-url sqlite:///tradesv3.dryrun.sqlite
```

这意味着，如果您在两个不同的终端中运行 trade 命令，例如，为了测试您的策略在 USDT 中的交易和在另一个实例中在 BTC 中的交易，您将必须使用不同的数据库运行它们。

如果您指定一个不存在的数据库的 URL，freqtrade 将创建一个具有您指定名称的数据库。因此，要使用 BTC 和 USDT 质押货币测试您的自定义策略，您可以使用以下命令（在 2 个单独的终端中）：

``` bash
# 终端 1:
freqtrade trade -c MyConfigBTC.json -s MyCustomStrategy --db-url sqlite:///user_data/tradesBTC.dryrun.sqlite
# 终端 2:
freqtrade trade -c MyConfigUSDT.json -s MyCustomStrategy --db-url sqlite:///user_data/tradesUSDT.dryrun.sqlite
```

相反，如果您希望在生产模式下执行相同的操作，您还必须创建至少一个新数据库（除了默认数据库之外），并指定"实盘"数据库的路径，例如：

``` bash
# 终端 1:
freqtrade trade -c MyConfigBTC.json -s MyCustomStrategy --db-url sqlite:///user_data/tradesBTC.live.sqlite
# 终端 2:
freqtrade trade -c MyConfigUSDT.json -s MyCustomStrategy --db-url sqlite:///user_data/tradesUSDT.live.sqlite
```

有关使用 sqlite 数据库的更多信息，例如手动输入或删除交易，请参阅 [SQL 速查表](sql_cheatsheet.md)。

### 使用 docker 的多个实例

要使用 docker 运行多个 freqtrade 实例，您需要编辑 docker-compose.yml 文件，并将所有想要的实例作为单独的服务添加。请记住，您可以将配置分成多个文件，因此最好考虑使它们模块化，这样如果您需要编辑所有机器人通用的内容，您可以在单个配置文件中完成。
``` yml
---
version: '3'
services:
  freqtrade1:
    image: freqtradeorg/freqtrade:stable
    # image: freqtradeorg/freqtrade:develop
    # 使用绘图镜像
    # image: freqtradeorg/freqtrade:develop_plot
    # 构建步骤 - 仅在需要其他依赖项时需要
    # build:
    #   context: .
    #   dockerfile: "./docker/Dockerfile.custom"
    restart: always
    container_name: freqtrade1
    volumes:
      - "./user_data:/freqtrade/user_data"
    # 在端口 8080 上公开 api（仅本地主机）
    # 请在启用之前阅读 https://www.freqtrade.io/en/latest/rest-api/ 文档
     ports:
     - "127.0.0.1:8080:8080"
    # 运行 `docker compose up` 时使用的默认命令
    command: >
      trade
      --logfile /freqtrade/user_data/logs/freqtrade1.log
      --db-url sqlite:////freqtrade/user_data/tradesv3_freqtrade1.sqlite
      --config /freqtrade/user_data/config.json
      --config /freqtrade/user_data/config.freqtrade1.json
      --strategy SampleStrategy
  
  freqtrade2:
    image: freqtradeorg/freqtrade:stable
    # image: freqtradeorg/freqtrade:develop
    # 使用绘图镜像
    # image: freqtradeorg/freqtrade:develop_plot
    # 构建步骤 - 仅在需要其他依赖项时需要
    # build:
    #   context: .
    #   dockerfile: "./docker/Dockerfile.custom"
    restart: always
    container_name: freqtrade2
    volumes:
      - "./user_data:/freqtrade/user_data"
    # 在端口 8080 上公开 api（仅本地主机）
    # 请在启用之前阅读 https://www.freqtrade.io/en/latest/rest-api/ 文档
    ports:
      - "127.0.0.1:8081:8080"
    # 运行 `docker compose up` 时使用的默认命令
    command: >
      trade
      --logfile /freqtrade/user_data/logs/freqtrade2.log
      --db-url sqlite:////freqtrade/user_data/tradesv3_freqtrade2.sqlite
      --config /freqtrade/user_data/config.json
      --config /freqtrade/user_data/config.freqtrade2.json
      --strategy SampleStrategy

```

您可以使用任何您想要的命名约定，freqtrade1 和 2 是任意的。请注意，您需要为每个实例使用不同的数据库文件、端口映射和 telegram 配置，如上所述。

## 使用不同的数据库系统

Freqtrade 使用 SQLAlchemy，它支持多种不同的数据库系统。因此，应该支持多种数据库系统。
Freqtrade 不依赖或安装任何其他数据库驱动程序。有关各个数据库系统的安装说明，请参阅 [SQLAlchemy 文档](https://docs.sqlalchemy.org/en/14/core/engines.html#database-urls)。

以下系统已经过测试，已知可与 freqtrade 一起使用：

* sqlite（默认）
* PostgreSQL
* MariaDB

!!! Warning "警告"
    通过使用以下数据库系统之一，您承认您知道如何管理此类系统。freqtrade 团队不会为以下数据库系统的设置或维护（或备份）提供任何支持。

### PostgreSQL

安装：
`pip install "psycopg[binary]"`

使用：
`... --db-url postgresql+psycopg://<username>:<password>@localhost:5432/<database>`

Freqtrade 将在启动时自动创建必要的表。

如果您正在运行不同的 Freqtrade 实例，则必须为每个实例设置一个数据库，或者为您的连接使用不同的用户/模式。

### MariaDB / MySQL

Freqtrade 通过使用 SQLAlchemy 支持 MariaDB，SQLAlchemy 支持多种不同的数据库系统。

安装：
`pip install pymysql`

使用：
`... --db-url mysql+pymysql://<username>:<password>@localhost:3306/<database>`



## 将机器人配置为 systemd 服务运行

将 `freqtrade.service` 文件复制到您的 systemd 用户目录（通常是 `~/.config/systemd/user`），并更新 `WorkingDirectory` 和 `ExecStart` 以匹配您的设置。

!!! Note "注意"
    某些系统（如 Raspbian）不会从用户目录加载服务单元文件。在这种情况下，将 `freqtrade.service` 复制到 `/etc/systemd/user/`（需要超级用户权限）。

之后，您可以使用以下命令启动守护进程：

```bash
systemctl --user start freqtrade
```

为了使其持久（用户注销时运行），您需要为您的 freqtrade 用户启用 `linger`。

```bash
sudo loginctl enable-linger "$USER"
```

如果您将机器人作为服务运行，您可以使用 systemd 服务管理器作为软件看门狗来监控 freqtrade 机器人状态，并在失败的情况下重新启动它。如果配置中的 `internals.sd_notify` 参数设置为 true，或使用 `--sd-notify` 命令行选项，机器人将使用 sd_notify（systemd 通知）协议向 systemd 发送保活 ping 消息，并在更改时告诉 systemd 其当前状态（运行、暂停或停止）。

`freqtrade.service.watchdog` 文件包含使用 systemd 作为看门狗的服务单元配置文件的示例。

!!! Note "注意"
    如果机器人在 Docker 容器中运行，机器人和 systemd 服务管理器之间的 sd_notify 通信将不起作用。

## 高级日志记录

Freqtrade 使用 python 提供的默认日志模块。
Python 在这方面允许进行广泛的[日志配置](https://docs.python.org/3/library/logging.config.html#logging.config.dictConfig) - 这里可以涵盖的内容远远超过了这些。

如果您的 freqtrade 配置中未提供 `log_config`，则默认设置默认日志格式（彩色终端输出）。
使用 `--logfile logfile.log` 将启用 RotatingFileHandler。

如果您对日志格式或为 RotatingFileHandler 提供的默认设置不满意，您可以通过将 `log_config` 配置添加到您的 freqtrade 配置文件中来自定义日志记录。

默认配置大致如下，提供了文件处理程序，但未启用，因为 `filename` 被注释掉了。
取消注释此行并提供有效的路径/文件名以启用它。

``` json hl_lines="5-7 13-16 27"
{
  "log_config": {
      "version": 1,
      "formatters": {
          "basic": {
              "format": "%(message)s"
          },
          "standard": {
              "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
          }
      },
      "handlers": {
          "console": {
              "class": "freqtrade.loggers.ft_rich_handler.FtRichHandler",
              "formatter": "basic"
          },
          "file": {
              "class": "logging.handlers.RotatingFileHandler",
              "formatter": "standard",
              // "filename": "someRandomLogFile.log",
              "maxBytes": 10485760,
              "backupCount": 10
          }
      },
      "root": {
          "handlers": [
              "console",
              // "file"
          ],
          "level": "INFO",
      }
  }
}
```

!!! Note "突出显示的行"
    上面代码块中突出显示的行定义了 Rich 处理程序并属于一起。
    格式化程序"standard"和"file"将属于 FileHandler。

每个处理程序必须使用定义的格式化程序之一（按名称），其类必须可用，并且必须是有效的日志类。
要实际使用处理程序，它必须位于"root"段内的"handlers"部分中。
如果省略此部分，freqtrade 将不提供输出（在未配置的处理程序中，无论如何）。

!!! Tip "显式日志配置"
    我们建议从主要的 freqtrade 配置文件中提取日志配置，并通过[多个配置文件](configuration.md#multiple-configuration-files)功能将其提供给您的机器人。这将避免不必要的代码重复。

---

在许多 Linux 系统上，可以将机器人配置为将其日志消息发送到 `syslog` 或 `journald` 系统服务。在 Windows 上也可以记录到远程 `syslog` 服务器。可以使用 `--logfile` 命令行选项的特殊值来实现此目的。

### 记录到 syslog

要将 Freqtrade 日志消息发送到本地或远程 `syslog` 服务，请使用 `"log_config"` 设置选项来配置日志记录。

``` json
{
  // ...
  "log_config": {
    "version": 1,
    "formatters": {
      "syslog_fmt": {
        "format": "%(name)s - %(levelname)s - %(message)s"
      }
    },
    "handlers": {
      // 其他处理程序？
      "syslog": {
         "class": "logging.handlers.SysLogHandler",
          "formatter": "syslog_fmt",
          // 使用上面的其他选项之一作为地址？
          "address": "/dev/log"
      }
    },
    "root": {
      "handlers": [
        // 其他处理程序
        "syslog",
        
      ]
    }

  }
}
```

可能需要配置[其他日志处理程序](#advanced-logging)，例如，还要在控制台中输出日志。

#### Syslog 使用

日志消息使用 `user` 设施发送到 `syslog`。因此，您可以使用以下命令查看它们：

* `tail -f /var/log/user`，或
* 安装一个全面的图形查看器（例如，Ubuntu 的"日志文件查看器"）。

在许多系统上，`syslog`（`rsyslog`）从 `journald` 获取数据（反之亦然），因此可以使用 syslog 或 journald，并且可以使用 `journalctl` 和 syslog 查看器实用程序查看消息。您可以以任何适合您的方式组合它们。

对于 `rsyslog`，来自机器人的消息可以重定向到单独的专用日志文件中。要实现此目的，请添加

```
if $programname startswith "freqtrade" then -/var/log/freqtrade.log
```

到 rsyslog 配置文件之一，例如在 `/etc/rsyslog.d/50-default.conf` 的末尾。

对于 `syslog`（`rsyslog`），可以打开减少模式。这将减少重复消息的数量。例如，当机器人没有发生其他事情时，多个机器人心跳消息将减少到单个消息。要实现此目的，在 `/etc/rsyslog.conf` 中设置：

```
# 过滤重复的消息
$RepeatedMsgReduction on
```

#### Syslog 寻址

syslog 地址可以是 Unix 域套接字（套接字文件名）或 UDP 套接字规范，由 IP 地址和 UDP 端口组成，用 `:` 字符分隔。

因此，以下是可能地址的示例：

* `"address": "/dev/log"` -- 使用 `/dev/log` 套接字记录到 syslog（rsyslog），适用于大多数系统。
* `"address": "/var/run/syslog"` -- 使用 `/var/run/syslog` 套接字记录到 syslog（rsyslog）。在 MacOS 上使用此选项。
* `"address": "localhost:514"` -- 如果本地 syslog 在端口 514 上监听，则使用 UDP 套接字记录到本地 syslog。
* `"address": "<ip>:514"` -- 记录到 IP 地址和端口 514 的远程 syslog。这可能在 Windows 上用于远程记录到外部 syslog 服务器。

??? Info "已弃用 - 通过命令行配置 syslog"
    `--logfile syslog:<syslog_address>` -- 使用 `<syslog_address>` 作为 syslog 地址将日志消息发送到 `syslog` 服务。

    syslog 地址可以是 Unix 域套接字（套接字文件名）或 UDP 套接字规范，由 IP 地址和 UDP 端口组成，用 `:` 字符分隔。

    因此，以下是可能用法的示例：

    * `--logfile syslog:/dev/log` -- 使用 `/dev/log` 套接字记录到 syslog（rsyslog），适用于大多数系统。
    * `--logfile syslog` -- 与上面相同，`/dev/log` 的快捷方式。
    * `--logfile syslog:/var/run/syslog` -- 使用 `/var/run/syslog` 套接字记录到 syslog（rsyslog）。在 MacOS 上使用此选项。
    * `--logfile syslog:localhost:514` -- 如果本地 syslog 在端口 514 上监听，则使用 UDP 套接字记录到本地 syslog。
    * `--logfile syslog:<ip>:514` -- 记录到 IP 地址和端口 514 的远程 syslog。这可能在 Windows 上用于远程记录到外部 syslog 服务器。

### 记录到 journald

这需要安装 `cysystemd` python 包作为依赖项（`pip install cysystemd`），它在 Windows 上不可用。因此，整个 journald 日志功能不适用于在 Windows 上运行的机器人。

要将 Freqtrade 日志消息发送到 `journald` 系统服务，请将以下配置片段添加到您的配置中。

``` json
{
  // ...
  "log_config": {
    "version": 1,
    "formatters": {
      "journald_fmt": {
        "format": "%(name)s - %(levelname)s - %(message)s"
      }
    },
    "handlers": {
      // 其他处理程序？
      "journald": {
         "class": "cysystemd.journal.JournaldLogHandler",
          "formatter": "journald_fmt",
      }
    },
    "root": {
      "handlers": [
        // .. 
        "journald",
        
      ]
    }

  }
}
```

可能需要配置[其他日志处理程序](#advanced-logging)，例如，还要在控制台中输出日志。

日志消息使用 `user` 设施发送到 `journald`。因此，您可以使用以下命令查看它们：

* `journalctl -f` -- 显示发送到 `journald` 的 Freqtrade 日志消息以及 `journald` 获取的其他日志消息。
* `journalctl -f -u freqtrade.service` -- 当机器人作为 `systemd` 服务运行时，可以使用此命令。

`journalctl` 实用程序中有许多其他选项可以过滤消息，请参阅此实用程序的手册页。

在许多系统上，`syslog`（`rsyslog`）从 `journald` 获取数据（反之亦然），因此可以使用 `--logfile syslog` 或 `--logfile journald`，并且可以使用 `journalctl` 和 syslog 查看器实用程序查看消息。您可以以任何适合您的方式组合它们。

??? Info "已弃用 - 通过命令行配置 journald"
    要将 Freqtrade 日志消息发送到 `journald` 系统服务，请使用格式如下的 `--logfile` 命令行选项：

    `--logfile journald` -- 将日志消息发送到 `journald`。

### 日志格式为 JSON

您还可以将默认输出流配置为使用 JSON 格式。
"fmt_dict" 属性定义 json 输出的键 - 以及 [python 日志 LogRecord 属性](https://docs.python.org/3/library/logging.html#logrecord-attributes)。

以下配置将更改默认输出为 JSON。但是，相同的格式化程序也可以与 `RotatingFileHandler` 结合使用。
我们建议保留一种人类可读的格式。

``` json
{
  // ...
  "log_config": {
    "version": 1,
    "formatters": {
       "json": {
          "()": "freqtrade.loggers.json_formatter.JsonFormatter",
          "fmt_dict": {
              "timestamp": "asctime",
              "level": "levelname",
              "logger": "name",
              "message": "message"
          }
      }
    },
    "handlers": {
      // 其他处理程序？
      "jsonStream": {
          "class": "logging.StreamHandler",
          "formatter": "json"
      }
    },
    "root": {
      "handlers": [
        // .. 
        "jsonStream",
        
      ]
    }

  }
}
```
