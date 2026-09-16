# 2026-09-16 review 核实与修复

本次依据当前源码、安装的 CCXT 4.5.78、离线复现和现有监控记录核实。未启动或重启实盘，未调用下单/撤单接口。外部 review 的行号及 491 个测试统计对应旧版本。

| 条目 | 核实结论 | 处理 |
| --- | --- | --- |
| buy_pending 目标不存在 | 下单拒绝且无成交的情况此前已加双次空仓核对；目标成交后已平仓的情况仍会保留暂停 | 本次补充已平仓目标核对：唯一匹配本次 rotation 标签的已关闭 Trade、提交后的开仓时间、无未完成本地订单、历史成交订单 ID/数量逐一匹配、本地及交易所无目标持仓且无普通/条件挂单。连续两次通过才取消计划，保留旧仓并重新计冷却；不回退 buy 盲重试 |
| 交易锁误报数据异常 | 成立 | 正常交易锁继续阻止买入并显示原因，但不再触发“数据不可用”警告 |
| 强平流脏消息/单次超时 | 成立 | 跳过无法解析的消息和无效订单字段；单次接收超时不直接重连，以已有 stream_max_age 时限判断有效消息是否断流。真实断流仍重连、重新预热，避免把缺失样本当成完整窗口 |
| 待成交评分快照残留 | 成立，但按 pair 覆盖，并非每次拒单新增一条 | 每轮清理无对应开放 Trade 且超过 data_grace_seconds 的记录；保留仍有开放 Trade 的记录，避免长期挂单成交后丢失开仓分数 |
| 第二个基础仓位被 50 分拒绝 | 所述确定性时序不成立 | freqtradebot.execute_entry 先调用 confirm_trade_entry，再 create_order，再创建 Trade。第二笔确认前已有一仓，仍使用 40 分；已有两仓、包括外部仓位时提高为 50 分符合现有设计，不减去已确认仓位绕过门槛 |
| UTC 与北京时间 08:00 不符 | 不成立 | UTC 00:00 就是北京时间 08:00；代码和文档一致 |
| _seconds 缺少类型检查 | 当前版本不成立 | 已拒绝非 int/float、bool、非有限值、非正数；已有强平近期/总窗口、轮换恢复时限等关系校验。不能要求所有网络超时/同步间隔大于 15 分钟；external_stop_check 与 position_stale 也不是同一计时含义，不添加无依据的约束 |
| 同轮重复计算/双份表格渲染 | 存在重复开销，但未复现 review 所报的精确耗时/锁竞争数字 | 增加一次日志输出内的 K 线、趋势与热度计算缓存，输出结束即失效，不缓存实盘下单/退出复核；删除选币质量检查后的重复 candle_metrics 计算。纯文本表格按文件/API handler 的需求延迟渲染并复用，Rich handler 直接使用独立标题 |
| 钱包 BOTH / 负合约数量 | 对当前 CCXT 标准化结果不成立 | binance.parse_position_risk 将 contracts 取绝对值，并按 notional 正负设置 long/short；原始 info.positionSide=BOTH 不等于标准化 side。保留现有按 contracts 判断仓位的修复，不把负仓位简单忽略 |
| 钱包 0 仓位警告 | 监控文件记录的是旧 collateral=0 过滤问题 | 现有监控记录明确 12:15 修复、12:16 后恢复；不能用此前累计警告数量证明当前仍存在同一个问题。本次未修改钱包核心 |

恢复的限制：部分成交仍未平仓、成交记录对不上、查询截断、时间不可信、接口失败、超过配置自动恢复年龄，均不自动解除。`rotation_recovery_max_age_seconds` 当前为 24 小时，连续确认次数为 2，检查间隔至少 30 秒，提交后宽限 120 秒。审计事件沿用 recovery_check/recovery_blocked/recovered，核对结果增加 closed_target_reconciled。

本次不改评分、入场门槛、杠杆、趋势退出或持仓容量，不增加新策略参数。上述“核对后已平仓可恢复”替代旧文档中“任何历史成交一律暂停”的限制；未核实的成交仍然暂停。

资料：

- [CCXT 标准仓位结构](https://github.com/ccxt/ccxt/wiki/manual#position-structure)：side 为 long/short，raw info 与标准化字段分开。
- [websockets 同步客户端 recv 文档](https://websockets.readthedocs.io/en/stable/reference/sync/client.html)：接收超时抛 TimeoutError，关闭连接使用 ConnectionClosed；单次超时本身不证明连接已经断开。
