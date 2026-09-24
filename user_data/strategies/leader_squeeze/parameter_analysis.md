# 强势龙头跟随参数试算与当前配置说明

本文记录当前策略和公开配置已经落地的参数、离线试算结果，以及仍需确认的评分语义。文中的数值都是当前实现使用的起点；它们没有经过收益回测，因此不能称为最佳值。

## 当前评分公式

当前评分总分为 100 × Σ（配置权重 × 分项分）。价格、成交量和主动买盘分项限制在 0 到 1，资金费率分项限制在 -1 到 1，因此总分范围为 -3 到 100。当前权重和尺度如下；表中数值是当前公开配置的试算起点。

| 项目 | 权重/满分贡献 | 当前公式和尺度 |
|---|---:|---|
| 动量 | 44 分 | `momentum_return_weight` × clamp（动量涨幅/`momentum_full_score`）+（1 − `momentum_return_weight`）×上涨连续性；当前为 80% / 3% |
| 放量 | 27 分 | 70% 持续活跃度（45m 均量/此前 7 天均量，3 倍满分）+ 30% 新增放量（45m 均量/此前 5h 均量，2 倍满分）；基准均排除最近 3 根 |
| 主动买 | 26 分 | clamp（（主动买卖比 − 1）/（`taker_score_full_ratio` − 1））；普通比值取最近三根已收盘 15m 的 ΣbuyVol / ΣsellVol，1.5 达满分 |
| OI 参考 | 0 分 | 当前停用；不请求 OI 接口 |
| 资金费率 | ±3 分 | 负费率按该币负下限归一化并加分；正费率按正上限归一化并扣分 |

当前所有核心评分请求使用顶层 `timeframe`（15m）。完整 15m OHLC 是入场、轮换快速突破和多周期聚合的源数据；1h/4h 在本地按 UTC 桶聚合，不额外订阅高周期 K 线。动量窗口由 `momentum_lookback_candles=4`、连续性由 `trend_continuity_candles=3`、量比窗口由 `volume_window_candles=3`、`volume_baseline_windows=20` 和 `volume_activity_baseline_candles=672` 控制。直接反映价格、成交量和主动买盘的三项合计 97 分；快速核心门槛为 75，即 75/97，保持原来约 77% 的严格程度。总评分只负责衡量强度，入场还必须通过下面的分层漏斗。

## 分层入场漏斗

入场不再用一个总分门槛让强度和位置相互抵消。候选池（核心池动量达标票 + 侦察票）依次经过：

1. 硬条件：数据时效、趋势、流动性、交易资格、市场状态和末端过热检查；任何一项失败都淘汰。
2. 形态阶段：先要求整理突破有放量确认（`entry_setup_breakout_volume_multiple=1.5`，突破根量 ≥ 20 根均量 1.5 倍），否则不算"启动"；形态评分至少 `entry_setup_min_score=50`；普通候选偏离 EMA 达 `entry_setup_late_extension_atr=5.0 ATR` 时直接淘汰。最近 `entry_setup_launch_candles=2` 根 15m 属于新鲜启动窗口；确认的整理突破会影响形态评分和启动优先序，并单独将末端拒绝上限放宽至 `< entry_heat_extension_full_atr=6.0 ATR`，不改变买入评分。
3. 优先序选股：通过硬条件和形态门槛的候选按 `_entry_priority_key` 排序 —— 启动新鲜度（本轮突破 > 上一根突破 > 中继）→ 整理突破 → 45m/7d 相对放量 → 强度分 → 交易对；综合评分在这里**只作最低门槛**，不再决定先后。随后逐个计算风险预算门槛 `entry_risk_base_score + entry_risk_premium × 风险占用`。先令仓位利用率 `slot=(仓位数-1)/(max_positions-1)`，再按 `风险占用 = slot × (1 + entry_risk_correlation_weight × 相关性浓度) / (1 + entry_risk_correlation_weight)` 计算并截断到 [0,1]。相关性浓度 = 候选与现有持仓最近 `entry_risk_correlation_window=96` 根 15m 收益的平均相关系数 ÷ `entry_risk_correlation_full_weight=0.75`（截断到 [0,1]）。重叠不足 `entry_risk_correlation_min_overlap=48` 时取 `entry_risk_correlation_unknown=1.0`，即按完全同向保守处理。
4. 硬上限：总名义敞口超过 `entry_risk_max_gross_ratio=4.4`、总保证金占用超过 `entry_risk_max_margin_ratio=0.88`，或候选与现有持仓相关性达到 `entry_risk_cluster_correlation=0.85` 的簇超过 `entry_risk_cluster_max_positions=5` 个时直接淘汰，强度分不能越过。已有仓位优先使用交易所钱包的实际保证金与名义价值，框架交易作为模拟盘及同步间隙的回退；同轮待开候选按每仓最大保证金和配置杠杆预留，无法可靠估值时拒绝新开仓。
5. 最终复核：发出信号、取得盘口和实际下单前再次检查硬条件、形态阶段、仓位槽位、按实时仓位重算的风险门槛、硬上限和交易资格；选择时与复核时取更严的门槛。

当前配置下第 1 仓门槛 40.0；满仓且完全同向时达到 `entry_risk_base_score + entry_risk_premium = 60.0`；满仓但彼此独立（相关性 0）时约为 53.3，因为分散化本身就是风险下降。形态门槛是绝对值，不再按池子百分位截断。常规最多 20 个仓位；先买后卖轮换最多临时使用第 21 个仓位。所有仓位均不超过 4% 保证金和 5 倍杠杆时，两个敞口上限可容纳 21 个仓位；实际旧仓或手动仓更大时会更早拦截。轮换目标与普通新仓共用同一个按风险占用计算的评分门槛，不另设普通/快速通道固定分数；满仓下当前配置约为 53.3–60。该漏斗保留能够通过筛选的候选，任何一层都不会因候选数量不足而降低硬条件或形态最低分。

仓位金额不再固定使用 4% 保证金，而是先把单笔计划损失限制为可交易资金的 `entry_risk_per_trade=1%`：以入场时冻结的 `1.5 × ATR1h` 作为 1R，并夹在价格的 0.8% 到 12%，再用 `保证金 = 资金 × 1% ÷ (1R价格比例 × 实际杠杆)` 反推仓位。`stake_ratio=4%` 只作为单仓保证金上限。成交后同一个 1R 同时成为初始保护止损，因此“风险预算”与真实退出边界采用同一口径；跳空、滑点、费用和止损建单失败仍可能使实际损失超过计划值。

候选宇宙由 `pairlists` 决定：`VolumePairList(min_value=3000000, number_assets=1000)` 之后用两个 `PairInformationFilter` 白名单要求 `info.contractType=PERPETUAL` 与 `info.underlyingType=COIN`（fail-closed），再过 `AgeFilter(min_days_listed=15)` 与 `SpreadFilter(max_spread_ratio=0.0015)`；`min_value` 高于 `liquidity_discovery_min_quote_volume` 会提前滤掉部分发现池，因此配置值应小于或等于该发现池下限。已删除 `PercentChangePairList`。策略按已收盘 15m K 线拆池：核心池 ≥ `liquidity_core_min_quote_volume`（1000 万）定义市场宽度并贡献动量达标候选；发现池 ≥ `liquidity_discovery_min_quote_volume`（300 万）中满足动量 > 0、连续性 ≥ 2/3、45m/5h > 1、45m/7d > 1 的票取本地分前 `scout_max_candidates`（30）个进入侦察池；候选池 = 核心达标票 + 侦察票；评分池 = 候选池 + 持仓。榜外持仓不参与市场普跌分母，只保留评分用于持仓监控与轮换。市场覆盖按核心池计算（80%），候选远端指标覆盖率按 `candidate_min_metric_ratio`（80%）单独计算。

## 多周期行为

多周期阈值是当前实现的待验证起点，不能称为最优盈利设置。入场评分仍在 15m 上按原权重计算；4h 只作为背景观察，既不加权，也不单独拦截。正常入场要求 1h 持仓数据可用；1h 处于早期走弱时，只有启用快速通道、买入评分达到按风险占用计算的当前门槛，并通过 15m 快速突破质量检查才允许例外。快速质量检查包括突破、放量、主动买和核心分至少 `replacement_fast_core_score=75/97`；确认的退出条件始终拒绝入场。

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| `holding_timeframe` | `1h` | 持仓趋势、普通/慢跌/历史破位退出及旧仓轮换资格使用的本地聚合周期 |
| `background_timeframe` | `4h` | 仅记录背景趋势观察，不进入评分、不拦截入场 |
| `trend_slope_candles` | 3 | 1h EMA 与 3 小时前 EMA 比较，并用于持仓走弱和背景上下文 |
| `reversal_intrabar_atr_buffer` | 1.0 | 15m 额外急跌相对信号前完整 1h 支撑的 ATR 缓冲 |
| `reversal_emergency_memory_candles` | 16 | 15m 额外急跌最多回溯 16 根已收盘源 K 线 |
| `replacement_weak_atr_drop` | 0.5 | 旧仓最近 3 根先前小时最高收盘价到最新 1h 收盘价的最低回撤（ATR1h 倍数） |

1h 普通结构退出仍使用最近 2 根 1h 收盘和 `reversal_atr_buffer=0.5 × ATR1h`，1h 急跌分支使用 `reversal_fast_atr_buffer=1.5 × ATR1h`；慢跌确认使用 5 根 1h，即 5 小时，EMA20 走弱和连续弱势段累计跌幅规则不变。历史破位从可用 1h 历史重算并要求未收复原支撑且仍低于原普通阈值。15m 额外急跌不等待当前 1h 收盘，只以信号开始前已经完整的 1h 支撑和 ATR 为基准，在 1.0 ATR 阈值下检查最新 15m 收盘，并可在 16 根 15m 内回溯；回溯信号之后必须未收复支撑且当前仍在普通缓冲以下。

旧仓轮换不再要求池子百分位：普通通道要求原评分低于 `replacement_weak_score=45`，快速通道不设旧仓固定分数线，两者都必须通过 1h 资格：最新 1h close < EMA20，且（EMA 相对 3 小时前下降，或本根 high、low、close 均低于上根）；最新 1h high 不得超过此前 3 根 1h high 的最高值，最近 3 根先前小时最高收盘价到最新收盘价的回撤至少为 0.5 ATR1h。新目标从排除已有仓位后的候选中按与新仓相同的优先序逐个检查，不设前 10% 限制。目标通过形态、风险评分门槛、分差和通道质量后，才进入确认和冷却；持仓趋势退出不等待固定持仓天数，程序硬止损保留，普通市场转弱只暂停新开仓，严重普跌才触发市场紧急退出。

## 当前实现的离线试算

以下结果使用测试中的指标构造辅助函数，并调用当前实现的 LeaderSqueezeStrategy._apply_scores()。试算将强平分设为 0、资金费率分设为 0，没有网络请求，也没有读取私有配置。

| 情景 | 构造条件 | 当前原评分 |
|---|---|---:|
| 普通基准 | 1h 涨幅 1.5%、连续性 2/3、短期量比 1.5、持续量比 2.0、主动买 1.2 | **47.3667** |
| 较强 | 在基准上改为 1h 涨幅 2%、短期量比 1.8、持续量比 2.6、主动买 1.3 | **66.5333** |
| 核心强势 | 1h 涨幅 3%、连续性 3/3、短期量比 2.0、持续量比 3.0、主动买 1.5 | **97.0000** |
| 核心强势加 OI 变化 | 上一行情景再加入任意 OI 变化 | **97.0000** |

分项核对：47.3667 分由动量 23.4667、放量 13.5、主动买 10.4 构成。66.5333 分由动量 29.3333、放量 21.6、主动买 15.6 构成。97 分情景为 44+27+26；OI 和强平当前均不改变分数。资金费率可在这些分数上调整 -3 到 +3 分。

## 热度与形态检查

买入评分不再按 15 日涨幅扣分，15 日涨幅只作观察，不参与评分或排序。入场仍要求完整的热度历史，以计算 EMA/ATR 偏离和识别整理突破；偏离质量进入形态分，普通候选达到 `entry_setup_late_extension_atr=5.0 ATR` 时硬拒绝。满足启动整理突破条件的候选形态分和优先序会相应变化，末端硬拒绝上限可到 `entry_heat_extension_full_atr=6.0 ATR`。因此，热度历史用于位置和形态检查，不是买入评分折扣。

## 已开放的评分和热度参数

以下参数已经写入公开配置，并由策略启动时校验和读取，状态为“已开放”。当前配置值如下：

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| entry_risk_base_score | 40.0 | 第 1 仓（无风险占用）使用的强度评分门槛 |
| entry_risk_premium | 20.0 | 风险占用达到满值时追加的分数；与 base 相加为模型最严门槛 60 |
| profit_lock_arm_r | 0.5 | 峰值达到 0.5R 即武装盈利棘轮，至少锁到成本加手续费 |
| profit_no_progress_max_r | 0.5 | 允许等于武装点：0.5R 以下由无进展退出覆盖，0.5R 以上由棘轮接管 |
| entry_risk_per_trade | 0.01 | 单仓初始止损对应的账户计划风险；当前为可交易资金的 1% |
| entry_risk_initial_stop_enabled | true | 成交后使用冻结的 1R 价格距离建立初始保护止损 |
| entry_risk_correlation_weight | 0.5 | 相关性对风险占用的放大权重；0 表示只看仓位数 |
| entry_risk_correlation_window | 96 | 计算相关性的 15m 收益根数（约 24 小时） |
| entry_risk_correlation_min_overlap | 48 | 相关系数所需的最少重叠根数，不足则视为不可用 |
| entry_risk_correlation_full_weight | 0.75 | 平均相关性达到此值即计为完全同向（浓度 1.0） |
| entry_risk_correlation_unknown | 1.0 | 相关性不可用时的浓度取值；1.0 为保守（按完全同向） |
| entry_risk_max_gross_ratio | 4.4 | 硬上限：总名义敞口 / 权益；每仓不超过 4% 和 5x 时可容纳 21 个仓位 |
| entry_risk_max_margin_ratio | 0.88 | 硬上限：总保证金 / 权益；每仓不超过 4% 时可容纳 21 个仓位 |
| entry_risk_cluster_correlation | 0.85 | 判定“同一笔交易”的相关系数阈值 |
| entry_risk_cluster_max_positions | 5 | 硬上限：单个高相关簇允许的最大仓位数 |
| entry_setup_min_score | 50.0 | 形态阶段的最低评分 |
| entry_setup_enabled | true | 是否启用形态筛选与末端追高硬闸门 |
| entry_setup_score_points | 启动35/中继20/偏离30/整理20/距离15 | 形态评分各组成项的分值 |
| liquidity_core_min_quote_volume | 10000000 | 核心池下限；定义市场宽度并贡献常规候选 |
| liquidity_discovery_min_quote_volume | 3000000 | 发现池下限；pairlist `min_value` 当前为 300 万，实际候选带为 300 万–1000 万 |
| scout_max_candidates | 30 | 侦察池每轮最多进入评分池的数量 |
| candidate_min_metric_ratio | 0.80 | 候选池远端指标成功率下限 |
| profit_lock_strong_score / profit_lock_fading_score | 45.0 / 20.0 | 盈利保护档位的绝对评分门槛 |
| entry_setup_launch_candles | 2 | 新鲜启动识别窗口，最近 2 根 15m K 线 |
| entry_setup_late_extension_atr | 5.0 | 普通候选偏离 EMA 达 5 ATR 时硬拒绝；整理突破使用 6 ATR 硬上限 |
| min_absolute_momentum | 0.0 | 1h 涨幅必须严格为正 |
| min_trend_continuity | 2/3 | 最近 3 次变化至少 2 次上涨 |
| momentum_full_score | 0.03 | 1h 涨幅达到 3% 时，动量价格部分满分 |
| momentum_return_weight | 0.80 | 动量分中价格涨幅的比例；连续性比例为 1 减此值 |
| volume_score_full_ratio | 2.0 | 短期量比达到此值时，新增放量部分满分 |
| volume_activity_weight | 0.7 | 持续活跃度占放量分的 70%，新增放量占 30% |
| volume_activity_full_ratio | 3.0 | 持续量比达到此值时，持续部分满分 |
| volume_activity_baseline_candles | 672 | 此前一周 15m K 线作为均量基准，排除最近 3 根 |
| taker_score_full_ratio | 1.5 | 主动买卖比达到此值时主动买分满分 |
| oi_score_full_drop | 0.03 | 停用保留参数；OI 权重为 0 时不请求接口 |

热度参数也已经开放：

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| entry_heat_extension_start_atr | 2.0 | 偏离 EMA 超过 2 ATR 后，形态分中的偏离质量逐步下降 |
| entry_heat_extension_full_atr | 6.0 | 已确认整理突破候选的末端硬拒绝上限；普通候选仍使用 5 ATR |
| entry_heat_ema_candles | 96 | 热度参考 EMA96，约 24 小时 |
| entry_heat_box_candles | 16 | 整理箱体 16 根，约 4 小时 |
| entry_heat_box_max_width_atr | 4.0 | 整理箱体宽度上限 |
| entry_heat_prebreak_extension_max_atr | 2.0 | 突破前收盘距 EMA 的偏离上限 |
| entry_heat_breakout_overshoot_atr | 1.0 | 突破后允许超过箱体高点的 ATR 倍数 |

热度历史由 `entry_heat_history_days` 控制，当前为 15 天；在顶层 `timeframe=15m` 且 `startup_candle_count=1441` 时，对应 1441 根已收盘 K 线。趋势和热度 ATR 周期由 `atr_period` 控制，当前为 Wilder ATR14。`startup_candle_count` 必须覆盖公开配置中的热度和指标窗口，策略启动校验会拒绝历史不足的组合；修改配置后需要重启进程。

## 已实现的双通道轮换参数

当前公开配置已经使用以下实际键名和数值。普通轮换和快速轮换均由先买后卖流程执行，目标完整成交后才允许退出旧仓。

| 配置键 | 当前值 | 作用 |
|---|---:|---|
| replacement_weak_score | 45.0 | 普通轮换旧仓原评分必须低于此值 |
| replacement_score_gap | 10.0 | 普通目标买入评分至少领先旧仓原评分 10 分 |
| replacement_confirmations | 2 | 普通通道需要 2 根连续不同的已收盘 15m K 线确认 |
| replacement_min_age_minutes | 30 | 普通旧仓最短持有 30 分钟 |
| replacement_cooldown_minutes | 30 | 普通轮换冷却 30 分钟 |
| replacement_no_new_high_candles | 4 | 旧仓最近 4 根 1h K 线中，最新高点不得超过此前 3 根高点 |
| replacement_candidate_hysteresis | 3.0 | 仅当前三项优先字段（阶段、突破新鲜度、相对放量）相同时，允许按评分差保留上一候选 |
| replacement_reentry_cooldown_minutes | 30 | 轮换后同一交易对重新进入的冷却时间 |
| replacement_fast_enabled | true | 启用快速轮换 |
| replacement_fast_score_gap | 15.0 | 快速目标至少领先旧仓原评分 15 分 |
| replacement_fast_confirmations | 1 | 快速通道需要 1 根已收盘 15m K 线确认 |
| replacement_fast_min_age_minutes | 15 | 快速旧仓最短持有 15 分钟 |
| replacement_fast_cooldown_minutes | 15 | 快速轮换冷却 15 分钟 |
| replacement_fast_core_score | 75.0 | 动量、放量、主动买三项核心分至少 75/97 |
| replacement_fast_breakout_candles | 8 | 突破前参考 8 根已收盘 K 线高点 |
| replacement_fast_volume_baseline_candles | 20 | 单根 15m 量比使用前 20 根均量 |
| replacement_fast_volume_ratio | 1.5 | 单根 15m 量比至少 1.5 |
| replacement_fast_taker_ratio | 1.2 | 最新单根主动买卖比至少 1.2，时间必须匹配突破 K 线 |
| replacement_fast_close_location | 0.65 | 收盘位于本根振幅的 65% 以上 |
| replacement_fast_max_breakout_atr | 1.0 | 突破前高后最多超出 1 ATR |

快速通道的核心分上限 97 来自动量 44 分、放量 27 分和主动买 26 分；`replacement_fast_core_score=75` 表示至少取得其中 75 分，维持约 77.3% 的严格程度。快速通道不要求旧仓原评分低于 45，但仍要求旧仓通过 1h 走弱、回撤和最近 3 根 1h 高点保护条件；目标不受前 10% 限制，按与普通新仓相同的启动新鲜度、整理突破、相对放量及强度分优先序逐个检查，并通过分层漏斗中的硬条件、形态检查及 15m 突破、量比、主动买和收盘位置检查。普通与快速通道的目标门槛都取 `entry_risk_base_score + entry_risk_premium × 风险占用`（按当前账户占用计算，当前配置下约 53.3～60），不再附加通道固定分数。

## 轮换审计记录

服务使用的 PostgreSQL 已创建 `leader_rotation_events` 表。轮换现场和结果会记录为 `evaluation`、`candidate_observed`、`plan_created`、`cancelled`、`entry_approved`、`entry_rejected`、`execution_status`、`target_filled`、`review_required`、`order_filled`、`exit_allowed`、`completed`、`blocked`、`startup` 和 `state_save_failed` 等事件。

每条事件的 `snapshot` 是 JSONB，保存原评分及分项评分、热度、实际配置、指标、持仓/仓位、轮换门控、旧仓后段排名、目标前段排名、实际检查结果（包括旧仓是否创新高）和 `multi_timeframe.exit_reason`（`_trend_exit_details` 文本）；每个 `snapshot.pairs[pair]` 还保存 `multi_timeframe.holding`、`multi_timeframe.background`、`multi_timeframe.entry`、`multi_timeframe.rotation`、`multi_timeframe.emergency` 五类上下文。`reason` 保存观察、取消、阻断或失败原因。快照不包含凭据。对带一次性语义的事件，相同状态与快照指纹不会重复刷写；评分评估仍可保留每次新的现场快照。

审计写入使用独立事务，不加入交易订单事务。数据库不可用时先写入本地 outbox，服务启动或定时重试恢复写入；`event_id` 提供幂等保护。实盘和模拟盘使用不同的 spool 文件，路径由 `rotation_audit_spool_live` 与 `rotation_audit_spool_dry_run` 配置。当前进程需重启后才开始记录，历史轮换不会回填。查询示例见 [轮换审计查询](rotation_queries.sql)。

## 当前可配置的窗口与运行参数

此前写在文档中的固定窗口已经全部移到本目录 `config.json`。当前 134 个 `leader_squeeze` 配置键均由启动时严格读取，代码不再补默认值；修改后必须重启，且启动校验会检查窗口关系、最少历史和时效范围。主周期、启动历史和其他策略参数都随策略目录一起维护，主 `user_data/config.json` 只负责框架装配。策略目录只保留主策略和辅助实现两个 Python 文件：

| 配置项 | 当前值 | 作用 |
|---|---:|---|
| `timeframe` / `startup_candle_count` | `15m` / `1441` | 入场源周期和启动时预加载的历史数量 |
| `holding_timeframe` / `background_timeframe` | `1h` / `4h` | 持仓/退出/轮换周期和仅观察的背景周期 |
| `trend_slope_candles` | 3 | EMA 与 3 根更早的同周期收盘比较 |
| `entry_heat_history_days` | 15 | 入场热度涨幅历史天数 |
| `atr_period` / `trend_ema_candles` | 14 / 20 | Wilder ATR 周期和趋势 EMA 周期 |
| `eth_confirm_candles` | 2 | 仅用于 ETH 15m 趋势状态和日志观察，不作为恢复拦截条件 |
| `eth_fast_atr_buffer` | 3.0 | ETH 快速急跌 ATR 阈值 |
| `eth_cooldown_candles` | 8 | ETH 急跌触发后暂停开仓 8 根 ETH 15m K 线 |
| `reversal_pivot_side_candles` | 2 | 结构支撑局部低点两侧窗口 |
| `momentum_lookback_candles` / `trend_continuity_candles` | 4 / 3 | 动量和收盘连续性窗口 |
| `volume_window_candles` / `volume_baseline_windows` | 3 / 20 | 近期均量窗口和此前短期基准根数 |
| `candle_min_history` / `oi_sample_count` | 21 / 4 | 评分 K 线最少历史；OI 样本数为停用保留参数 |
| `score_refresh_seconds` / `score_candle_close_delay_seconds` | 900 / 30 | 评分最长间隔；下一根 15m 收盘后等待 30 秒再刷新 |
| `exit_evaluation_failure_limit` | 6 | 同一持仓退出评估连续失败达到该次数后暂停新开仓并告警 |
| `metric_request_timeout_seconds` / `funding_request_timeout_seconds` | 10 / 5 | 远端指标和资金费率请求超时 |
| `metric_request_retries` / `metric_retry_backoff_seconds` | 1 / 0.5 | 网络或 HTTP 临时错误的单次有限重试和初始退避 |
| `raw_metrics_log_enabled` | `false` | 是否打印独立的原始指标与资金费率明细表；不影响评分 |
| `position_sync_seconds` / `position_stale_seconds` | 30 / 60 | 仓位同步和状态过旧阈值 |
| `risk_state_checkpoint_seconds` | 60 | 例行权益状态写盘间隔；轮换变化仍立即保存 |

反转分支的 `reversal_lookback_candles`、`reversal_confirm_candles`、`reversal_atr_buffer`、`reversal_fast_atr_buffer`、`reversal_slow_candles` 和 `reversal_slow_atr_drop`，以及新增的 `reversal_intrabar_atr_buffer=1.0`、`reversal_emergency_memory_candles=16`、`replacement_weak_atr_drop=0.5`、热度、轮换、评分、数据时效、网络、状态文件和审计 outbox 参数，也都在同一公开配置中；完整键名和当前值见 [策略配置](config.json)。不能只添加未被代码读取的键，修改窗口后应让启动校验和针对性测试共同确认覆盖关系。

配置项与算法协议要分开理解。核心分项归一化到 `[0, 1]`、资金费率归一化到 `[-1, 1]`、总分乘以 100、Wilder ATR 的递推系数、评分分项的计算结构、Binance REST/WebSocket 字段和事件流协议、订单 `reduceOnly` 语义及框架订单状态含义是实现协议或数学定义，不是可调配置；可配置的是权重、阈值、窗口、时效、超时和运行开关。

## 当前评分取舍

OI 下降既可能来自空头回补，也可能来自多头平仓。当前把 OI 权重设为 0，并同步停止 OI 请求；强平评分、强平数据流及其开仓门禁已整块删除，避免低置信度指标影响交易或因远端故障暂停策略。释放出的 8 分分配给动量、放量和主动买盘，三项合计 97 分。快速核心门槛从 69/89 同比调整为 75/97，保持约 77% 的严格程度。

资金费率保留 3 分权重，但改为有符号调整：负费率最多加 3 分，正费率最多扣 3 分，缺失或过期时回到 0 且不阻止开仓。放量仍使用周基准持续活跃度和短基准新增放量；主动买普通评分汇总三根已收盘 15m，快速突破保留最新单根信号。上述分配是待实盘日志验证的起点，不是已证实的最优解。OI 的含义可参考 [CME Open Interest](https://www.cmegroup.com/education/lessons/open-interest)。

## 周成交量场景回放

启动前每根 100，启动那根 1000，之后每根 500，使用当前实现的真实 K 线取数及计分函数回放：

| 启动后经过时间 | 放量得分（满分 27） |
|---|---:|
| 45 分钟 | 27.00 |
| 2 小时 45 分钟 | 24.09 |
| 5 小时 30 分钟 | 18.90 |
| 24 小时 | 18.90 |
| 48 小时 | 12.66 |

若后续连续三根回落至 100，两部分均降为 0；如果 500 的成交量持续一整周，周基准也会逐步接近 500，不会永久保留启动分。新算法表示相对活跃程度，并不预测涨跌；退出仍按原有趋势、市场普跌及止损规则处理，放量分下降本身不是独立卖出信号。

原始指标日志显示短期量比和持续量比，轮换 JSONB 快照沿用 metrics 字段记录 `volume_ratio`、`volume_activity_ratio`、`volume_recent_mean`、`volume_short_baseline`、`volume_activity_baseline`，可结合当次配置重建评分，不需要变更数据库表。

比较短期与长期均量的指标背景见 [Fidelity Volume Oscillator](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/volume-oscillator)。本策略的 7 天/5 小时/45 分钟及 70%/30% 配比属于待验证的设计选择，不是该资料给出的标准参数或盈利保证。

周基准默认取 7 天以配合持有数天的龙头策略：1 天基准容易在启动后很快上移，3 天更灵敏但也更快消化持续高量，7 天适应更慢；超过一周则更容易保留已经失去时效的低基准。这里采用 7 天的起始值，仍需用实盘日志校准。在 15m 周期下，`volume_activity_baseline_candles` 设置为 96/288/672 分别对应 1/3/7 天，修改后会检查历史长度是否足够。`volume_baseline_windows=20` 和 `volume_window_candles=3` 同样可以配置。

## 市场分层、主动买平滑与轮换恢复

以下参数均来自 `config.json`，修改后重启生效。这些阈值是待验证的起点，不是收益回测得出的最优值。

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
