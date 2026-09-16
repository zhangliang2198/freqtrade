# 龙头挤空参数试算与当前配置说明

本文记录当前策略和公开配置已经落地的参数、离线试算结果，以及仍需确认的评分语义。文中的数值都是当前实现使用的起点；它们没有经过收益回测，因此不能称为最佳值。

## 当前评分公式

当前评分总分为 100 × Σ（配置权重 × 归一化分），每个归一化分限制在 0 到 1。当前权重和尺度如下；表中数值是当前公开配置的试算起点。

| 项目 | 权重/满分贡献 | 当前公式和尺度 |
|---|---:|---|
| 空头拥挤 | 20 分 | clamp（（最终空头占比 − `short_score_start_share`）/（`short_score_full_share` − `short_score_start_share`））；当前 75% 达满分，硬门槛由 `short_share_filter_enabled` 控制，当前关闭；50% 及以下该分项为 0 |
| 动量 | 32 分 | `momentum_return_weight` × clamp（动量涨幅/`momentum_full_score`）+（1 − `momentum_return_weight`）×上涨连续性；当前为 80% / 3% |
| 放量 | 15 分 | 70% 持续活跃度（45m 均量/此前 7 天均量，3 倍满分）+ 30% 新增放量（45m 均量/此前 5h 均量，2 倍满分）；基准均排除最近 3 根 |
| 主动买 | 15 分 | clamp（（主动买卖比 − 1）/（`taker_score_full_ratio` − 1））；普通比值取最近三根已收盘 15m 的 ΣbuyVol / ΣsellVol，1.5 达满分 |
| 强平 | 5 分 | 预热期间使用 `liquidation_warmup_score=0.5`；完成预热后，最近 `liquidation_recent_seconds`（当前 15m）相对前置窗口基线达到 `liquidation_score_full_ratio=5.0` 倍时满分 |
| OI 挤空 | 10 分 | 只有价格上涨且 OI 下降时计分；使用 `oi_score_full_drop=0.03`，当前 OI 下降 3% 达满分 |
| 资金费率 | 3 分 | 负费率相对该币负下限归一化；正费率当前不加分 |

当前所有核心评分请求使用顶层 `timeframe`（15m）。完整 15m OHLC 是入场、轮换快速突破和多周期聚合的源数据；1h/4h 在本地按 UTC 桶聚合，不额外订阅高周期 K 线。动量窗口由 `momentum_lookback_candles=4`、连续性由 `trend_continuity_candles=3`、量比窗口由 `volume_window_candles=3` 、`volume_baseline_windows=20` 和 `volume_activity_baseline_candles=672` 控制；OI 使用 `oi_sample_count=4` 个样本，约覆盖 45 分钟。这些当前值来自公开配置，ADL 的 10% 权重已平均转入放量和主动买入；快速核心门槛由 40/52 调为 48/62，其余热度和轮换门槛保持不变。

## 多周期行为

多周期阈值是当前实现的待验证起点，不能称为最优盈利设置。入场评分仍在 15m 上按原权重计算；4h 只作为背景观察，既不加权，也不单独拦截。正常入场要求 1h 持仓数据可用；1h 处于早期走弱时，只有热度调整后的买入评分达到快速门槛 60 且满足现有 15m 快速突破条件，才允许 `earlyweak` 例外；确认的退出条件始终拒绝入场。

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| `holding_timeframe` | `1h` | 持仓趋势、普通/慢跌/历史破位退出及旧仓轮换资格使用的本地聚合周期 |
| `background_timeframe` | `4h` | 仅记录背景趋势观察，不进入评分、不拦截入场 |
| `trend_slope_candles` | 3 | 1h EMA 与 3 小时前 EMA 比较，并用于持仓走弱和背景上下文 |
| `reversal_intrabar_atr_buffer` | 1.0 | 15m 额外急跌相对信号前完整 1h 支撑的 ATR 缓冲 |
| `reversal_emergency_memory_candles` | 16 | 15m 额外急跌最多回溯 16 根已收盘源 K 线 |
| `replacement_weak_atr_drop` | 0.5 | 旧仓最近 3 根先前小时最高收盘价到最新 1h 收盘价的最低回撤（ATR1h 倍数） |

1h 普通结构退出仍使用最近 2 根 1h 收盘和 `reversal_atr_buffer=0.5 × ATR1h`，1h 急跌分支使用 `reversal_fast_atr_buffer=1.5 × ATR1h`；慢跌确认使用 5 根 1h，即 5 小时，EMA20 走弱和连续弱势段累计跌幅规则不变。历史破位从可用 1h 历史重算并要求未收复原支撑且仍低于原普通阈值。15m 额外急跌不等待当前 1h 收盘，只以信号开始前已经完整的 1h 支撑和 ATR 为基准，在 1.0 ATR 阈值下检查最新 15m 收盘，并可在 16 根 15m 内回溯；回溯信号之后必须未收复支撑且当前仍在普通缓冲以下。

旧仓轮换先通过 1h 资格：最新 1h close < EMA20，且（EMA 相对 3 小时前下降，或本根 high、low、close 均低于上根）；最新 1h high 不得超过此前 3 根 1h high 的最高值，最近 3 根先前小时最高收盘价到最新收盘价的回撤至少为 0.5 ATR1h。通过后才应用原双通道的分差、确认和冷却；持仓趋势退出不等待固定持仓天数，程序硬止损保留，普通市场转弱只暂停新开仓，严重普跌才触发市场紧急退出。

## 当前实现的离线试算

以下结果使用测试中的指标构造辅助函数，并调用当前实现的 LeaderSqueezeStrategy._apply_scores()。试算将强平分设为 0、资金费率分设为 0，没有网络请求，也没有读取私有配置。

| 情景 | 构造条件 | 当前原评分 |
|---|---|---:|
| 普通基准 | 空头 65%、1h 涨幅 1.5%、连续性 2/3、短期量比 1.5、持续量比 2.0、主动买 1.2、OI 下降 1% | **45.9000** |
| 较强 | 在基准上改为 1h 涨幅 2%、短期量比 1.8、持续量比 2.6、主动买 1.3 | **57.6667** |
| 核心强势 | 空头 65%、1h 涨幅 3%、连续性 3/3、短期量比 2.0、持续量比 3.0、主动买 1.5、OI 不下降 | **74.0000** |
| 核心强势加 OI | 上一行再加入 OI 下降 1.5% | **79.0000** |

分项核对：45.9 分由空头 12.0、动量 17.0667、放量 7.5、主动买 6.0、OI 3.3333 构成。57.6667 分由空头 12.0、动量 21.3333、放量 12.0、主动买 9.0、OI 3.3333 构成。74 分情景为 12+32+15+15；OI 下降 1.5% 时增加 10 ×（1.5%/3%）=5 分。

## 热度折扣对门槛的影响

买入评分为原评分 ×（1 − 热度惩罚）。下表取 0%、10% 和 20% 三个惩罚场景用于理解门槛；实际热度惩罚按公开配置和指标连续计算。

| 原评分 | 0% 折扣 | 10% 折扣 | 20% 折扣 |
|---:|---:|---:|---:|
| 45.9000 | 45.9000 | 41.3100 | 36.7200 |
| 57.6667 | 57.6667 | 51.9000 | 46.1333 |
| 74.0000 | 74.0000 | 66.6000 | 59.2000 |
| 79.0000 | 79.0000 | 71.1000 | 63.2000 |

若折扣后的买入评分要达到下列门槛，原评分至少需要达到：

| 买入门槛 | 0% 折扣 | 10% 折扣 | 20% 折扣 |
|---:|---:|---:|---:|
| 40 | 40.00 | 44.4444 | 50.00 |
| 45 | 45.00 | 50.00 | 56.25 |
| 50 | 50.00 | 55.5556 | 62.50 |
| 60 | 60.00 | 66.6667 | 75.00 |
| 70 | 70.00 | 77.7778 | 87.50 |

因此，当前 `additional_entry_score=45` 配合最高 20% 热度惩罚时，原评分低于 56.25 的币不可能通过 45 分买入门槛。原评分 64 的币在满热度惩罚后仍有 51.2 分；原评分 61 的币会降到 48.8 分。

## 已开放的评分和热度参数

以下参数已经写入公开配置，并由策略启动时校验和读取，状态为“已开放”。当前配置值如下：

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| base_entry_score | 40.0 | 初始仓位基础买入门槛 |
| additional_entry_score | 45.0 | 后续买入的评分门槛 |
| short_share_filter_enabled | false | 是否启用空头占比硬门槛；关闭不影响空头拥挤评分 |
| min_short_share | 0.50 | 开启占比硬门槛后，最终空头占比必须严格高于此值 |
| min_absolute_momentum | 0.0 | 1h 涨幅必须严格为正 |
| min_trend_continuity | 2/3 | 最近 3 次变化至少 2 次上涨 |
| momentum_full_score | 0.03 | 1h 涨幅达到 3% 时，动量价格部分满分 |
| short_score_start_share | 0.50 | 空头拥挤分的起点 |
| short_score_full_share | 0.75 | 空头拥挤分的满分占比 |
| momentum_return_weight | 0.80 | 动量分中价格涨幅的比例；连续性比例为 1 减此值 |
| volume_score_full_ratio | 2.0 | 短期量比达到此值时，新增放量部分满分 |
| volume_activity_weight | 0.7 | 持续活跃度占放量分的 70%，新增放量占 30% |
| volume_activity_full_ratio | 3.0 | 持续量比达到此值时，持续部分满分 |
| volume_activity_baseline_candles | 672 | 此前一周 15m K 线作为均量基准，排除最近 3 根 |
| taker_score_full_ratio | 1.5 | 主动买卖比达到此值时主动买分满分 |
| oi_score_full_drop | 0.03 | OI 下降 3% 时 OI 分满分 |
| liquidation_min_notional | 1000.0 | 强平基线的最低名义金额 |
| liquidation_score_full_ratio | 5.0 | 最近强平达到基线 5 倍时强平分满分 |
| liquidation_warmup_score | 0.5 | 强平流预热期间使用的归一化分 |

热度参数也已经开放：

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| entry_heat_max_penalty | 0.20 | 最大热度惩罚 20% |
| entry_heat_return_scale | 1.0 | 配置的热度历史涨幅达到 100% 时涨幅热度满量程 |
| entry_heat_extension_start_atr | 2.0 | 偏离 EMA 达 2 ATR 后开始增加惩罚 |
| entry_heat_extension_full_atr | 6.0 | 偏离 EMA 达 6 ATR 时偏离热度满量程 |
| entry_heat_ema_candles | 96 | 热度参考 EMA96，约 24 小时 |
| entry_heat_box_candles | 16 | 整理箱体 16 根，约 4 小时 |
| entry_heat_box_max_width_atr | 4.0 | 整理箱体宽度上限 |
| entry_heat_prebreak_extension_max_atr | 2.0 | 突破前收盘距 EMA 的偏离上限 |
| entry_heat_breakout_overshoot_atr | 1.0 | 突破后允许超过箱体高点的 ATR 倍数 |
| entry_heat_cooled_breakout_factor | 0.5 | 整理后突破的惩罚乘数 |
| entry_heat_base_fraction | 0.25 | 仅有 15 日涨幅时的基础惩罚比例；偏离比例为 1 减此值 |

热度历史由 `entry_heat_history_days` 控制，当前为 15 天；在顶层 `timeframe=15m` 且 `startup_candle_count=1441` 时，对应 1441 根已收盘 K 线。趋势和热度 ATR 周期由 `atr_period` 控制，当前为 Wilder ATR14。`startup_candle_count` 必须覆盖公开配置中的热度和指标窗口，策略启动校验会拒绝历史不足的组合；修改配置后需要重启进程。

## 已实现的双通道轮换参数

当前公开配置已经使用以下实际键名和数值。普通轮换和快速轮换均由先买后卖流程执行，目标完整成交后才允许退出旧仓。

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| replacement_entry_score | 50.0 | 普通轮换目标最低买入评分 |
| replacement_weak_score | 45.0 | 普通轮换旧仓原评分必须低于此值 |
| replacement_score_gap | 10.0 | 普通目标买入评分至少领先旧仓原评分 10 分 |
| replacement_confirmations | 2 | 普通通道需要 2 根连续不同的已收盘 15m K 线确认 |
| replacement_min_age_minutes | 30 | 普通旧仓最短持有 30 分钟 |
| replacement_cooldown_minutes | 30 | 普通轮换冷却 30 分钟 |
| replacement_no_new_high_candles | 4 | 旧仓最近 4 根 1h K 线中，最新高点不得超过此前 3 根高点 |
| replacement_candidate_hysteresis | 3.0 | 候选切换的评分滞后范围，减少候选来回切换 |
| replacement_reentry_cooldown_minutes | 30 | 轮换后同一交易对重新进入的冷却时间 |
| replacement_fast_enabled | true | 启用快速轮换 |
| replacement_fast_entry_score | 60.0 | 快速目标最低买入评分 |
| replacement_fast_score_gap | 15.0 | 快速目标至少领先旧仓原评分 15 分 |
| replacement_fast_confirmations | 1 | 快速通道需要 1 根已收盘 15m K 线确认 |
| replacement_fast_min_age_minutes | 15 | 快速旧仓最短持有 15 分钟 |
| replacement_fast_cooldown_minutes | 15 | 快速轮换冷却 15 分钟 |
| replacement_fast_core_score | 48.0 | 动量、放量、主动买三项核心分至少 48/62 |
| replacement_fast_breakout_candles | 8 | 突破前参考 8 根已收盘 K 线高点 |
| replacement_fast_volume_baseline_candles | 20 | 单根 15m 量比使用前 20 根均量 |
| replacement_fast_volume_ratio | 1.5 | 单根 15m 量比至少 1.5 |
| replacement_fast_taker_ratio | 1.2 | 最新单根主动买卖比至少 1.2，时间必须匹配突破 K 线 |
| replacement_fast_close_location | 0.65 | 收盘位于本根振幅的 65% 以上 |
| replacement_fast_max_breakout_atr | 1.0 | 突破前高后最多超出 1 ATR |

快速通道的核心分上限 62 来自动量 32 分、放量 15 分和主动买 15 分；replacement_fast_core_score=48 表示至少取得其中 48 分。快速通道不要求旧仓原评分低于 45，但仍要求旧仓先通过 1h 走弱、回撤和最近 3 根 1h 高点保护条件；目标还必须通过 15m 突破、量比、主动买和收盘位置检查。追加开仓现为 additional_entry_score=45；普通轮换仍取其与 replacement_entry_score=50 的较高值，即 50 分。

## 轮换审计记录

服务使用的 PostgreSQL 已创建 `leader_rotation_events` 表。轮换现场和结果会记录为 `evaluation`、`candidate_observed`、`plan_created`、`cancelled`、`entry_approved`、`entry_rejected`、`execution_status`、`target_filled`、`review_required`、`order_filled`、`exit_allowed`、`completed`、`blocked`、`startup`、`external_exit_submitted`、`external_exit_failed` 和 `state_save_failed` 等事件。

每条事件的 `snapshot` 是 JSONB，保存原评分及分项评分、热度、实际配置、指标、持仓/仓位、轮换门控、实际检查结果（包括旧仓是否创新高）和 `multi_timeframe.exit_reason`（`_trend_exit_details` 文本）；每个 `snapshot.pairs[pair]` 还保存 `multi_timeframe.holding`、`multi_timeframe.background`、`multi_timeframe.entry`、`multi_timeframe.rotation`、`multi_timeframe.emergency` 五类上下文。`reason` 保存观察、取消、阻断或失败原因。快照不包含凭据。对带一次性语义的事件，相同状态与快照指纹不会重复刷写；评分评估仍可保留每次新的现场快照。

审计写入使用独立事务，不加入交易订单事务。数据库不可用时先写入本地 outbox，服务启动或定时重试恢复写入；`event_id` 提供幂等保护。实盘和模拟盘使用不同的 spool 文件，路径由 `rotation_audit_spool_live` 与 `rotation_audit_spool_dry_run` 配置。当前进程需重启后才开始记录，历史轮换不会回填。查询示例见 [轮换审计查询](leader_squeeze_rotation_queries.sql)。

## 当前可配置的窗口与运行参数

此前写在文档中的固定窗口已经全部移到公开配置。当前 127 个 `leader_squeeze` 配置键均由启动时严格读取，代码不再补默认值；修改后必须重启，且启动校验会检查窗口关系、最少历史和时效范围。主周期与启动历史属于顶层框架配置，其他策略参数属于 `leader_squeeze`；策略同级职责文件当前共 8 个 helper：config、data、execution、reporting、storage、support、audit 和 trend：

| 配置项 | 当前值 | 作用 |
|---|---:|---|
| `timeframe` / `startup_candle_count` | `15m` / `1441` | 入场源周期和启动时预加载的历史数量 |
| `holding_timeframe` / `background_timeframe` | `1h` / `4h` | 持仓/退出/轮换周期和仅观察的背景周期 |
| `trend_slope_candles` | 3 | EMA 与 3 根更早的同周期收盘比较 |
| `entry_heat_history_days` | 15 | 入场热度涨幅历史天数 |
| `atr_period` / `trend_ema_candles` | 14 / 20 | Wilder ATR 周期和趋势 EMA 周期 |
| `eth_confirm_candles` / `reversal_pivot_side_candles` | 2 / 2 | ETH 过滤确认根数和结构支撑局部低点两侧窗口 |
| `momentum_lookback_candles` / `trend_continuity_candles` | 4 / 3 | 动量和收盘连续性窗口 |
| `volume_window_candles` / `volume_baseline_windows` | 3 / 20 | 近期均量窗口和此前短期基准根数 |
| `candle_min_history` / `oi_sample_count` | 21 / 4 | 评分 K 线最少历史和 OI 样本数 |
| `liquidation_window_seconds` / `liquidation_recent_seconds` | 3600 / 900 | 强平保留窗口和最近比较窗口 |
| `metric_request_timeout_seconds` / `funding_request_timeout_seconds` | 10 / 5 | 远端指标和资金费率请求超时 |
| `liquidation_open_timeout_seconds` / `liquidation_close_timeout_seconds` / `liquidation_receive_timeout_seconds` / `liquidation_reconnect_seconds` | 10 / 1 / 30 / 5 | 强平流连接、关闭、接收和重连时限 |
| `position_sync_seconds` / `position_stale_seconds` | 30 / 60 | 仓位同步和状态过旧阈值 |

反转分支的 `reversal_lookback_candles`、`reversal_confirm_candles`、`reversal_atr_buffer`、`reversal_fast_atr_buffer`、`reversal_slow_candles` 和 `reversal_slow_atr_drop`，以及新增的 `reversal_intrabar_atr_buffer=1.0`、`reversal_emergency_memory_candles=16`、`replacement_weak_atr_drop=0.5`、热度、轮换、评分、数据时效、网络、状态文件和审计 outbox 参数，也都在同一公开配置中；完整键名和当前值见 [`user_data/config.json`](../config.json)。不能只添加未被代码读取的键，修改窗口后应让启动校验和针对性测试共同确认覆盖关系。

配置项与算法协议要分开理解。分数归一化到 `[0, 1]`、总分乘以 100、Wilder ATR 的递推系数、评分分项的计算结构、Binance REST/WebSocket 字段和事件流协议、订单 `reduceOnly` 语义及框架订单状态含义是实现协议或数学定义，不是可调配置；可配置的是权重、阈值、窗口、时效、超时和运行开关。

## 评分构成待确认的问题

这些是评分语义提案，不属于当前已应用改动：

1. OI 下降只有在价格上涨时加分，但 OI 下降也可能来自多头平仓；只奖励下降可能漏掉 OI 上升、价格和买盘都强的新龙头。
2. 放量已改为周基准持续活跃度和短基准新增放量，避免重叠滚动窗口快速吞掉持续高量分数；两个部分仍封顶，不无限奖励极端放量。
3. 强平流预热期间所有交易对使用 `liquidation_warmup_score` 对应的中性分（当前总贡献为 2.5 分）。它不改变排名，却会平移绝对分数门槛。
4. 主动买已改为普通评分汇总三根已收盘 15m 的买卖量，快速突破保留单根信号；超过 1.5 仍封顶，后续需评估尺度。
5. 正资金费率对做多是成本，但当前只奖励负资金费率，不扣除正资金费率。

已按用户授权移除 ADL 评分，把原有 10 分平均转给放量和主动买入（两项分别 10 → 15 分），OI 挤空保持 10 分。旧的备选权重表已撤下，当前七项权重合计 100%。账户持仓 ADL 等级仍作为风险日志显示，不参与评分或选币准入。

术语背景参考 Binance 官方 [ADL Risk 接口说明](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#adl-risk)和 [Open Interest 说明](https://www.binance.com/en/academy/articles/what-is-open-interest)。ADL Risk 衡量清算期间发生自动减仓的可能性；OI 增减反映合约的新增或关闭，不能单独确定价格方向。把这些指标如何用于做多评分，属于本策略需要验证的判断。

当前分配的判断依据：OI 下降表示合约关闭，不能独立确定是空头回补；上涨伴随 OI 增加也可能得到新参与者支持。因此保留 OI 挤空加分，但不提高其权重，新增分数用于放量和主动买入。动量保持 32 分，减少进一步放大短周期涨幅的影响。快速核心满分由 52 提高至 62，门槛从 40 提高至 48，保持约 77% 的核心质量要求。该分配是待验证的起点，不是已证实的最优解。参考 [CME Open Interest](https://www.cmegroup.com/education/lessons/open-interest)。

## 周成交量场景回放

启动前每根 100，启动那根 1000，之后每根 500，使用当前实现的真实 K 线取数及计分函数回放：

| 启动后经过时间 | 放量得分（满分 15） |
|---|---:|
| 45 分钟 | 15.00 |
| 2 小时 45 分钟 | 13.38 |
| 5 小时 30 分钟 | 10.50 |
| 24 小时 | 10.50 |
| 48 小时 | 7.03 |

若后续连续三根回落至 100，两部分均降为 0；如果 500 的成交量持续一整周，周基准也会逐步接近 500，不会永久保留启动分。新算法表示相对活跃程度，并不预测涨跌；退出仍按原有趋势、市场普跌及止损规则处理，放量分下降本身不是独立卖出信号。

原始指标日志显示短期量比和持续量比，轮换 JSONB 快照沿用 metrics 字段记录 `volume_ratio`、`volume_activity_ratio`、`volume_recent_mean`、`volume_short_baseline`、`volume_activity_baseline`，可结合当次配置重建评分，不需要变更数据库表。

比较短期与长期均量的指标背景见 [Fidelity Volume Oscillator](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/volume-oscillator)。本策略的 7 天/5 小时/45 分钟及 70%/30% 配比属于待验证的设计选择，不是该资料给出的标准参数或盈利保证。

周基准默认取 7 天以配合持有数天的龙头策略：1 天基准容易在启动后很快上移，3 天更灵敏但也更快消化持续高量，7 天适应更慢；超过一周则更容易保留已经失去时效的低基准。这里采用 7 天的起始值，仍需用实盘日志校准。在 15m 周期下，`volume_activity_baseline_candles` 设置为 96/288/672 分别对应 1/3/7 天，修改后会检查历史长度是否足够。`volume_baseline_windows=20` 和 `volume_window_candles=3` 同样可以配置。

## 市场分层、主动买平滑与轮换恢复

本轮不改变评分权重。以下参数均来自 `config.json`，修改后重启生效。这些阈值是待验证的起点，不是收益回测得出的最优值。

| 配置键 | 默认值 | 作用 |
| --- | --- | --- |
| market_emergency_enabled | true | 启用严重普跌退出 |
| market_emergency_ratio | 0.6 | 至少 60% 龙头候选达到严重跌幅 |
| market_emergency_drop | 0.03 | 候选约 1 小时跌幅至少 3% |
| taker_window_candles | 3 | 普通主动买评分汇总三根连续已收盘主周期买卖量 |
| rotation_recovery_enabled | true | 启用未成交轮换的只读恢复核对 |
| rotation_recovery_grace_seconds | 120 | 提交后至少等待 120 秒再检查 |
| rotation_recovery_interval_seconds | 30 | 两次检查至少间隔 30 秒 |
| rotation_recovery_max_age_seconds | 86400 | 最多自动核对提交后 24 小时内的计划 |
| rotation_recovery_confirmations | 2 | 连续两次证明无成交、无挂单、无仓位才解除等待 |
| rotation_recovery_history_limit | 1000 | 订单历史查询上限；返回达到上限则视为不完整 |

普通市场转弱（当前 80% 候选动量非正）只限制买入；严重普跌同时限制买入并允许紧急退出。两者均要求数据覆盖和时效合格，单币趋势退出和止损独立执行。

三根主动买比值采用 ΣbuyVol / ΣsellVol，避免小成交量样本的比值获得同等权重。快速轮换的主动买门槛及核心分仍使用最新单根值，并核对其时间与突破 K 线一致。日志与快照同时保存两种比值。

轮换恢复检查提交以来的订单历史、普通挂单、条件挂单、交易所仓位，并在网络检查后重新读取本地持仓。无法核实的成交、未知字段、接口失败或历史截断都会保留暂停状态；部分成交未平仓不自动处理。已关闭目标必须按本次轮换标签定位唯一 Trade，并逐笔核对成交订单 ID/数量和空仓状态后，才可按相同的连续核对规则恢复。解除后保留旧仓并重新计轮换冷却，不立即重新买入。进程重启会重新积累连续确认次数。恢复过程记录 recovery_check、recovery_blocked、recovered 事件，沿用现有 PostgreSQL JSONB 审计表，无需改表结构。
