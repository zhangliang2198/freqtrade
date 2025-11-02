# 数据库连接池与多线程配置

## 概述

从 v1.0.3 版本开始，Freqtrade 优化版支持**数据库连接池配置**和**多线程策略分析**，显著提升了在使用 PostgreSQL/MySQL 等数据库时的并发性能。

## 数据库连接池配置

### 为什么需要连接池？

在多线程环境下（如启用 `strategy_threading`），多个线程会同时访问数据库。如果没有连接池：
- 每次数据库操作都需要创建新连接，开销巨大
- 连接数可能超过数据库服务器限制
- 性能严重下降，甚至导致连接失败

**连接池**通过复用数据库连接，解决了这些问题。

### 支持的数据库

| 数据库类型 | 连接池支持 | 说明 |
|-----------|----------|------|
| **SQLite** | ❌ 不支持 | 文件级锁定，使用 `StaticPool` |
| **PostgreSQL** | ✅ 支持 | 推荐用于生产环境 |
| **MySQL** | ✅ 支持 | 支持连接池配置 |
| **MariaDB** | ✅ 支持 | 支持连接池配置 |

### 配置参数

在 `config.json` 中添加以下配置：

```json
{
  "db_url": "postgresql+psycopg://user:password@localhost:5432/freqtrade",
  "db_pool_size": 20,
  "db_max_overflow": 40
}
```

#### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|-----|------|--------|------|
| `db_pool_size` | int | 20 | 连接池基础大小（常驻连接数） |
| `db_max_overflow` | int | 40 | 最大溢出连接数（临时连接） |

**总最大连接数** = `db_pool_size` + `db_max_overflow` = 60

### 如何选择合适的值？

#### 1. 基于线程数计算

如果启用了多线程策略分析：

```
推荐 pool_size = strategy_thread_workers + 10
推荐 max_overflow = strategy_thread_workers * 2
```

**示例**：
```json
{
  "strategy_threading": true,
  "strategy_thread_workers": 32,
  "db_pool_size": 42,
  "db_max_overflow": 64
}
```

#### 2. 基于使用场景

| 场景 | pool_size | max_overflow | 说明 |
|-----|-----------|--------------|------|
| **单线程运行** | 5 | 10 | 最小配置 |
| **中等并发** | 20 | 40 | 默认配置，适合大多数场景 |
| **高并发** | 50 | 100 | 多线程 + API 服务器 |
| **极限性能** | 100 | 200 | 大量交易对 + 高频策略 |

#### 3. 数据库服务器限制

确保不超过数据库服务器的最大连接数限制：

**PostgreSQL**：
```sql
-- 查看最大连接数
SHOW max_connections;

-- 查看当前连接数
SELECT count(*) FROM pg_stat_activity;
```

**MySQL**：
```sql
-- 查看最大连接数
SHOW VARIABLES LIKE 'max_connections';

-- 查看当前连接数
SHOW STATUS LIKE 'Threads_connected';
```

### 连接池工作原理

```
┌─────────────────────────────────────────────────┐
│           Freqtrade 应用程序                     │
│                                                 │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐       │
│  │线程1 │  │线程2 │  │线程3 │  │线程N │       │
│  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘       │
│     │         │         │         │            │
│     └─────────┴─────────┴─────────┘            │
│                 │                               │
│     ┌───────────▼───────────────┐               │
│     │    SQLAlchemy 连接池      │               │
│     │                           │               │
│     │  [连接1] [连接2] ... [连接N] │  ← pool_size
│     │  [临时1] [临时2] ... [临时M] │  ← max_overflow
│     └───────────┬───────────────┘               │
└─────────────────┼───────────────────────────────┘
                  │
         ┌────────▼────────┐
         │  数据库服务器    │
         │  (PostgreSQL/   │
         │   MySQL/etc)    │
         └─────────────────┘
```

### 连接池监控

启动时会看到类似日志：

```
2025-11-02 10:30:15 - freqtrade.persistence.models - INFO - PostgreSQL 连接池已配置: pool_size=20, max_overflow=40, total_max=60
```

## 多线程与数据库的协同工作

### 线程安全机制

Freqtrade 使用 **scoped_session** 确保线程安全：

```python
# 每个线程获得独立的 session
Trade.session = scoped_session(
    sessionmaker(bind=engine, autoflush=False), 
    scopefunc=get_request_or_thread_id  # 基于线程 ID 或请求 ID
)
```

**工作原理**：
1. 每个线程首次访问数据库时，从连接池获取一个连接
2. 该连接绑定到当前线程，后续操作复用此连接
3. 线程结束时，连接归还到连接池供其他线程使用

### 最佳实践

#### ✅ 推荐配置

```json
{
  "db_url": "postgresql+psycopg://user:password@localhost:5432/freqtrade",
  "db_pool_size": 50,
  "db_max_overflow": 100,
  "strategy_threading": true,
  "strategy_thread_workers": 32
}
```

#### ❌ 不推荐配置

```json
{
  // ❌ SQLite 不支持高并发
  "db_url": "sqlite:///tradesv3.sqlite",
  "strategy_threading": true,
  "strategy_thread_workers": 32
}
```

**问题**：SQLite 是文件级锁定，多线程写入会导致 `database is locked` 错误。

### 性能对比

| 配置 | 100 个交易对分析耗时 | 说明 |
|-----|-------------------|------|
| SQLite + 单线程 | ~30 秒 | 基准 |
| SQLite + 32 线程 | ~25 秒 | 提升有限，可能出错 |
| PostgreSQL + 单线程 | ~28 秒 | 网络开销 |
| **PostgreSQL + 32 线程 + 连接池** | **~5 秒** | 🚀 性能提升 6 倍 |

## 数据库迁移

### 从 SQLite 迁移到 PostgreSQL

#### 1. 安装 PostgreSQL 驱动

```bash
pip install "psycopg[binary]"
```

#### 2. 创建数据库

```sql
CREATE DATABASE freqtrade;
CREATE USER freqtrade_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE freqtrade TO freqtrade_user;
```

#### 3. 迁移数据

```bash
freqtrade convert-db \
  --db-url postgresql+psycopg://freqtrade_user:your_password@localhost:5432/freqtrade \
  --db-url-from sqlite:///tradesv3.sqlite
```

#### 4. 更新配置

```json
{
  "db_url": "postgresql+psycopg://freqtrade_user:your_password@localhost:5432/freqtrade",
  "db_pool_size": 50,
  "db_max_overflow": 100
}
```

### 从 SQLite 迁移到 MySQL

#### 1. 安装 MySQL 驱动

```bash
pip install pymysql
```

#### 2. 创建数据库

```sql
CREATE DATABASE freqtrade CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'freqtrade_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON freqtrade.* TO 'freqtrade_user'@'localhost';
FLUSH PRIVILEGES;
```

#### 3. 迁移数据

```bash
freqtrade convert-db \
  --db-url mysql+pymysql://freqtrade_user:your_password@localhost:3306/freqtrade \
  --db-url-from sqlite:///tradesv3.sqlite
```

#### 4. 更新配置

```json
{
  "db_url": "mysql+pymysql://freqtrade_user:your_password@localhost:3306/freqtrade",
  "db_pool_size": 50,
  "db_max_overflow": 100
}
```

## 故障排查

### 问题 1：连接池耗尽

**症状**：
```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 20 overflow 40 reached
```

**解决方案**：
1. 增加 `db_pool_size` 和 `db_max_overflow`
2. 检查是否有连接泄漏（未正确关闭的 session）
3. 减少 `strategy_thread_workers`

### 问题 2：数据库连接数过多

**症状**：
```
FATAL: sorry, too many clients already
```

**解决方案**：
1. 降低 `db_pool_size` 和 `db_max_overflow`
2. 增加数据库服务器的 `max_connections`
3. 使用连接池中间件（如 PgBouncer）

### 问题 3：SQLite 锁定错误

**症状**：
```
sqlite3.OperationalError: database is locked
```

**解决方案**：
- **迁移到 PostgreSQL 或 MySQL**（推荐）
- 或禁用多线程：`"strategy_threading": false`

### 问题 4：连接超时

**症状**：
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**解决方案**：
1. 检查数据库服务器是否运行
2. 检查防火墙和网络配置
3. 验证连接字符串是否正确
4. 启用 `pool_pre_ping` 自动重连（已默认启用）

## 配置示例

### 小型部署（单机器人）

```json
{
  "db_url": "sqlite:///tradesv3.sqlite",
  "strategy_threading": false
}
```

### 中型部署（多线程 + SQLite）

```json
{
  "db_url": "sqlite:///tradesv3.sqlite",
  "strategy_threading": true,
  "strategy_thread_workers": 8
}
```

**注意**：SQLite 在多线程下性能有限，建议交易对数量 < 50。

### 大型部署（多线程 + PostgreSQL）

```json
{
  "db_url": "postgresql+psycopg://user:password@localhost:5432/freqtrade",
  "db_pool_size": 50,
  "db_max_overflow": 100,
  "strategy_threading": true,
  "strategy_thread_workers": 32
}
```

### 生产环境（高可用 + 监控）

```json
{
  "db_url": "postgresql+psycopg://user:password@db-server:5432/freqtrade?connect_timeout=10",
  "db_pool_size": 100,
  "db_max_overflow": 200,
  "strategy_threading": true,
  "strategy_thread_workers": 64,
  "api_server": {
    "enabled": true,
    "listen_ip_address": "0.0.0.0",
    "listen_port": 8080
  }
}
```

## 相关文档

- [多线程策略分析配置](bot-basics.zh.md#多线程配置)
- [数据库配置](configuration.zh.md#数据库)
- [高级设置](advanced-setup.zh.md#数据库)

## 总结

- ✅ **SQLite**：适合单线程、小规模部署（< 50 交易对）
- ✅ **PostgreSQL/MySQL + 连接池**：适合多线程、大规模部署（> 50 交易对）
- ✅ **合理配置连接池**：避免连接耗尽或数据库过载
- ✅ **监控连接使用**：定期检查数据库连接数和性能指标

