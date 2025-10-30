# SQL 助手

本页面包含一些帮助，如果你想查询 sqlite 数据库。

!!! Tip "其他数据库系统"
    要使用其他数据库系统，如 PostgreSQL 或 MariaDB，你可以使用相同的查询，但你需要使用数据库系统的相应客户端。[点击这里](advanced-setup.md#使用不同的数据库系统)了解如何使用 freqtrade 设置不同的数据库系统。

!!! Warning
    如果你不熟悉 SQL，在数据库上运行查询时应该非常小心。
    在运行任何查询之前，始终确保备份你的数据库。

## 安装 sqlite3

Sqlite3 是一个基于终端的 sqlite 应用程序。
如果你觉得更舒服，可以随意使用可视化数据库编辑器，如 SqliteBrowser。

### Ubuntu/Debian 安装

```bash
sudo apt-get install sqlite3
```

### 通过 docker 使用 sqlite3

freqtrade docker 镜像包含 sqlite3，因此你可以在不在主机系统上安装任何东西的情况下编辑数据库。

``` bash
docker compose exec freqtrade /bin/bash
sqlite3 <database-file>.sqlite
```

## 打开数据库

```bash
sqlite3
.open <filepath>
```

## 表结构

### 列出表

```bash
.tables
```

### 显示表结构

```bash
.schema <table_name>
```

### 获取表中的所有交易

```sql
SELECT * FROM trades;
```

## 破坏性查询

写入数据库的查询。
这些查询通常不应该是必需的，因为 freqtrade 尝试自己处理所有数据库操作 - 或通过 API 或 telegram 命令公开它们。

!!! Warning
    在运行以下任何查询之前，请确保你有数据库的备份。

!!! Danger
    当机器人连接到数据库时，你也**永远不应该**运行任何写入查询（`update`、`insert`、`delete`）。
    这可能会并将导致数据损坏 - 很可能无法恢复。

### 修复交易所手动退出后交易仍然开启的问题

!!! Warning
    在交易所手动出售交易对不会被机器人检测到，它仍会尝试出售。只要可能，应使用 /forceexit <tradeid> 来完成相同的事情。
    强烈建议在进行任何手动更改之前备份你的数据库文件。

!!! Note
    在 /forceexit 之后，这应该不是必需的，因为强制退出订单在下一次迭代时由机器人自动关闭。

```sql
UPDATE trades
SET is_open=0,
  close_date=<close_date>,
  close_rate=<close_rate>,
  close_profit = close_rate / open_rate - 1,
  close_profit_abs = (amount * <close_rate> * (1 - fee_close) - (amount * (open_rate * (1 - fee_open)))),
  exit_reason=<exit_reason>
WHERE id=<trade_ID_to_update>;
```

#### 示例

```sql
UPDATE trades
SET is_open=0,
  close_date='2020-06-20 03:08:45.103418',
  close_rate=0.19638016,
  close_profit=0.0496,
  close_profit_abs = (amount * 0.19638016 * (1 - fee_close) - (amount * (open_rate * (1 - fee_open)))),
  exit_reason='force_exit'
WHERE id=31;
```

### 从数据库中删除交易

!!! Tip "使用 RPC 方法删除交易"
    考虑通过 telegram 或 rest API 使用 `/delete <tradeid>`。这是删除交易的推荐方法。

如果你仍想直接从数据库中删除交易，你可以使用以下查询。

!!! Danger
    一些系统（Ubuntu）在其 sqlite3 打包中禁用外键。使用 sqlite 时 - 请确保在上述查询之前运行 `PRAGMA foreign_keys = ON` 以启用外键。

```sql
DELETE FROM trades WHERE id = <tradeid>;

DELETE FROM trades WHERE id = 31;
```

!!! Warning
    这将从数据库中删除此交易。请确保你获得了正确的 id，并且**永远不要**在没有 `where` 子句的情况下运行此查询。
