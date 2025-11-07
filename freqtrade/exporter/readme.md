## 目录说明

- `freqtrade_exporter.py`：Prometheus Exporter 入口，负责加载所有指标采集器并输出 `/metrics`。
- `metrics/`：按功能拆分的采集器子模块。
  - `system.py`：系统运行状态（健康检查、CPU/RAM）。
  - `balances.py`：账户资金与币种分布。
  - `trades.py`：未平仓交易详情、仓位占用情况。
- `profitability.py`：`/profit` 汇总的收益、回撤、胜率等统计。
- `performance.py`：`/performance` 按交易对的收益表现。
- `locks.py`：`/locks` 中的交易对锁定信息。
- `stats.py`：`/stats` 计算胜负持仓时长与退出原因分布。
- `tags.py`：`/entries`、`/exits`、`/mix_tags` 汇总买入/卖出标签表现。
- `timeprofits.py`：`/daily`、`/weekly`、`/monthly` 维度的收益时间序列。
- `pairlists.py`：`/whitelist`、`/blacklist` 维护的交易对列表。
- `grafana/freqtrade_dashboard.json`：综合概览仪表盘（保留，适合快速查看）。
- `grafana/freqtrade_system_dashboard.json`：系统与 Exporter 运行状态监控。
- `grafana/freqtrade_balances_dashboard.json`：资金与资产分布分析。
- `grafana/freqtrade_trading_dashboard.json`：未平仓持仓、交易对表现等交易相关指标。
- `grafana/freqtrade_strategy_dashboard.json`：策略收益、标签与时间序列表现。

所有采集器都会通过 `metrics/__init__.py` 中的 `COLLECTORS` 自动注册，`build_metrics()` 会逐个执行并将结果统一渲染成 Prometheus 文本协议。

## 环境依赖

```bash
pip install fastapi uvicorn requests
```

如果同时监控 PostgreSQL，请按需安装：

```bash
pip install "psycopg[binary]"
```

## 运行流程

在 Freqtrade 配置文件中添加 `prometheus_exporter` 配置，Exporter 会随机器人自动启动：

```json
{
  "api_server": {
    "enabled": true,
    "listen_ip_address": "0.0.0.0",
    "listen_port": 10800,
    "username": "admin",
    "password": "admin123",
    "verbosity": "error",
    "enable_openapi": true
  },
  "prometheus_exporter": {
    "enabled": true,
    "listen_ip_address": "0.0.0.0",
    "listen_port": 8000
  }
}
```

**配置说明：**
- `prometheus_exporter.enabled`: 是否启用 Prometheus Exporter（必需）
- `prometheus_exporter.listen_ip_address`: Exporter 监听地址（默认 127.0.0.1）
- `prometheus_exporter.listen_port`: Exporter 监听端口（默认 8000）
- **Exporter 会自动从 `api_server` 配置中读取：**
  - `username` / `password`: API 认证信息
  - `listen_ip_address` / `listen_port`: 自动构建 Freqtrade API 地址

在运行交易命令时也可以临时附加 `--start-exporter`，Freqtrade 会在同一进程内后台拉起 Exporter：

```bash
freqtrade trade --config user_data/config.json --start-exporter
```

如需单独启动 Exporter，可在另一终端执行：

```bash
freqtrade exporter --config user_data/config.json
```

启动后进程会常驻，按 `Ctrl+C` 可停止。Exporter 读取同一份配置文件，因此可与交易进程分离部署。

**工作原理：**
1. Freqtrade 启动时会读取整个配置对象
2. 如果 `prometheus_exporter.enabled = true`，自动在后台线程启动 FastAPI 服务
3. Exporter 从 `api_server` 配置提取认证信息和 API URL，无需重复配置
4. 访问 `http://<exporter_host>:<exporter_port>/metrics` 查看 Prometheus 指标

启动 Freqtrade 后，你会在日志中看到：
```
Prometheus Exporter 配置: host=0.0.0.0, port=8000, freqtrade_api=http://0.0.0.0:10800/api/v1, user=admin
启动 Prometheus Exporter FastAPI 服务于 http://0.0.0.0:8000/metrics
Prometheus Exporter 已在后台线程启动
```

## 配置 Prometheus 和 Grafana

### 启动 Prometheus

```bash
C:\applications\prometheus-3.7.3.windows-amd64\prometheus.exe --config.file=C:\applications\prometheus-3.7.3.windows-amd64\prometheus.yml
```

打开 `http://127.0.0.1:9090/targets`，确认 `freqtrade_exporter` 状态为 `UP`。

### 配置 Grafana

- 访问 `http://127.0.0.1:3000`，默认账号密码 `admin/admin`
- 添加 Prometheus 数据源，URL 填 `http://127.0.0.1:9090`
- 新建或导入 Dashboard，使用以下示例指标：
  - `freqtrade_balance_total_stake`：账户总权益
  - `freqtrade_open_trades_total`：未平仓数量
  - `freqtrade_profit_all_percent`：总体收益率
  - `freqtrade_trade_stake_amount{pair="BTC/USDT"}`：指定交易对的建仓规模

## 常见指标速览

| 指标名 | 含义 |
| --- | --- |
| `freqtrade_exporter_up` | Exporter 自身可用性 |
| `freqtrade_exporter_scrape_duration_seconds` | 单次抓取耗时 |
| `freqtrade_balance_total_bot` | 机器人实际占用资金（仓位货币） |
| `freqtrade_trade_slots_used` / `freqtrade_trade_slots_max` | 当前占用的仓位槽位 / 最大允许槽位 |
| `freqtrade_profit_max_drawdown` | 历史最大回撤（相对值） |
| `freqtrade_pair_profit_abs{pair="XXX/USDT"}` | 单个交易对累计收益 |
| `freqtrade_trade_duration_seconds_avg{outcome="wins"}` | 胜/平/负的平均持仓时长 |
| `freqtrade_enter_tag_trades_total{enter_tag="dca"}` | 各买入标签的成交次数 |
| `freqtrade_timeunit_profit_abs{timeunit="daily",date="2024-07-01"}` | 日/周/月维度收益 |
| `freqtrade_whitelist_total` / `freqtrade_blacklist_total` | 白名单/黑名单交易对数量 |
| `freqtrade_locks_total` | 当前锁定的交易对数量 |

## Grafana 查询示例

```promql
// 查看各交易对的未平仓收益
freqtrade_trade_profit_abs > 0

// 统计不同策略的资金占用
sum by (strategy) (freqtrade_trade_stake_amount)

// 监控 Exporter 是否健康
freqtrade_exporter_up
```

## Prometheus `job` 变量说明

- `job` 是 Prometheus 在抓取目标时自动附加的标签，通常对应 `scrape_configs` 中的 `job_name`。
- 仪表盘变量 `Prometheus job` 使用 `label_values(freqtrade_exporter_up, job)` 动态获取可用实例。
- 当部署了多个 Freqtrade Exporter 时，可通过下拉框选择特定实例，或选择 `All` 聚合查看整体表现。

## 其它说明

- Prometheus 默认间隔抓取，Exporter 会在单次抓取内缓存 API 响应，避免重复请求。
- 采集器默认使用线程池并发抓取多个 REST 接口，可根据网络状况显著缩短单轮响应时间。
- 所有日志信息、注释与 README 已统一改为中文，方便日常维护。
- 如果需要连接 PostgreSQL，请保证连接串追加 `?client_encoding=utf8&options=-c%20timezone%3DUTC`，避免时区错乱。

## Grafana Dashboard 导入步骤

1. 打开 Grafana → `Dashboards` → `Import`。
2. 分别选择上述 JSON 文件之一导入；也可以逐个导入全部分类仪表盘。
3. 为每个仪表盘选择 Prometheus 数据源（对应 `DS_PROMETHEUS`），确认导入。
4. 需要切换实例时，可使用面板内的 `Prometheus job` 变量进行筛选或对比。
