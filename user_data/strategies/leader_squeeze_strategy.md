# LeaderSqueezeStrategy（龙头挤空策略）

用于币安 USDⓈ-M 合约的龙头挤空策略，候选入场评分和信号使用顶层 `timeframe`（当前为 `15m`）源 K 线；持仓趋势、普通退出和旧仓轮换资格在同一份完整 15m OHLC 上按 UTC 桶本地聚合为 1h，4h 只作背景观察，不额外订阅高周期 K 线。策略按 `momentum_lookback_candles`（当前为 4）计算候选动量，再产生前 30 个候选并按买入评分排序和筛选，跟随空头拥挤后的挤空行情。策略只开多单，使用 `leverage=5` 倍杠杆，每次开仓分配框架可交易总资金的 `stake_ratio=0.1`（包含策略已有仓位占用，不按剩余余额递减）。常规最多 `max_positions=5` 仓，仅“先买后卖”轮换可临时使用第 6 仓。全仓会共享账户保证金，但在极端行情或保证金不足时仍可能发生强平；这不改变按配置比例分配每次开仓资金的规则。

## 数据与安全门槛

- ETH 全局过滤独立于涨幅榜，始终订阅配置中的 `eth_pair`（当前为 `ETH/USDT:USDT`）并使用主周期 `timeframe`（当前为 `15m`）K 线。最近 `eth_confirm_candles`（当前为 2）根**已收盘** K 线各自收盘价均低于对应的 `trend_ema_candles`（当前为 EMA20）时，暂停新的评分请求、选币、新轮换和开仓；已有仓位继续执行风险检查、止损和退出，已提交轮换继续核对成交，不会仅因 ETH 过滤触发而强制平仓。发出入场信号及实际下单前都会复查该条件。
- ETH 数据至少需要 `trend_ema_candles + eth_confirm_candles`（当前 22）根已收盘 K 线，参与计算的历史 K 线须连续；数据缺失、异常、价格无效或最新 K 线开盘时间距当前超过 `timeframe` 一个周期加 `data_grace_seconds` 时，同样禁止开仓。未收盘 K 线不参与判断。
- ETH 过滤无论是否拦截，均定期输出 INFO 日志：显示上涨、下跌或震荡，以及最近 `eth_confirm_candles` 根已收盘价格、各自 EMA、最新 K 线时间和数据年龄。首次检查及趋势/拦截原因变化立即输出；常规状态按 `status_log_seconds`（当前 300 秒）输出。
- 策略评分常规按 `score_refresh_seconds`（当前 900 秒）刷新；按本批指标最早到期时间提前安排补刷新，名单变化或有效覆盖丢失也会触发补刷新（最快按 `score_retry_seconds`（当前 30 秒）一批，不并发重复请求）。当前交易名单至少 `market_min_coverage_ratio`（当前 80%）必须具备有效数据；刷新不完整时禁止开仓，并按重试间隔重试。首批结果未到达时显示“首批行情与评分加载中”，不误报为评分过期；状态日志分别显示上批是否成功与当前有效覆盖数量。移出当前名单的币不再出现在入场排名，持仓评分仍保留用于退出和轮换。
- 基础评分有效期取 OI、主动买卖、多空比和参与评分 K 线的最早截止时间，重复获取同一份旧数据不会续期。资金费率加分单独按结算/采样时效管理，不会因为资金费率暂时不可用而使基础评分失效。消费后台结果、选币、轮换、发出信号和实际开仓时均复核；有效评分覆盖不足 80% 时暂停新开仓。评分过期但退出指标仍有效时，退出缓存仍正常更新。
- 正常全量刷新时，多空比请求/校验失败，不会丢弃此前已成功取得且仍有效的 OI、主动买卖指标；会报警并仅保留这部分有效行情缓存，绝不作为完整评分参与开仓。行情指标自身失败或过期时仍拒绝使用，不会因降级延长有效期；评分和入场仍使用完整 15m 源 K 线，持仓趋势、普通退出、慢跌/历史破位和旧仓资格使用同一份源数据本地聚合的 1h，4h 仅作背景观察。
- 单币评分只使用已收盘、连续且有效的主周期 K 线；最新 K 线开盘时间距当前超过一个 `timeframe` 周期加 `data_grace_seconds` 时不参与评分。接口返回成功不会让旧 K 线重新变成有效数据。
- 选币、轮换目标和最终下单共用入场/退出一致性检查：按当前已收盘 `timeframe`（15m）K 线重新计算 `momentum_lookback_candles`（当前 4，约 1 小时）根涨幅及 `trend_continuity_candles`（当前 3，约 45 分钟）次收盘上涨比例，不沿用评分缓存中的趋势值；1h 趋势不可用时拒绝正常入场，已满足 1h 趋势退出或 15m 额外急跌条件时记录“已满足趋势退出条件, 禁止开仓”。1h 尚处早期走弱时，只有热度调整后的买入评分达到快速门槛 60 且满足现有 15m 快速突破条件才允许 `earlyweak` 例外；确认的退出条件不能被该例外绕过。取盘口后再次复核。评分权重和热度门槛不变；成交后新行情触发的趋势退出及单笔止损仍正常执行。
- ETH、评分、市场普跌、轮换、入场信号、下单复核及趋势退出统一使用 K 线时效校验。15m 是入场和额外急跌源，1h 是持仓普通/慢跌/历史破位退出及轮换资格源，4h 只写入背景观察，不加权、不拦截；源 K 线不足时跳过相应趋势退出分支并保留独立风险分支，正常入场仍因 1h 不可用而拒绝。异常按交易对/数据类型报警，每 5 分钟最多重复一次。
- ETH 拦截期间不为新开仓排名，但每个主周期仍单独请求已有仓位的 OI、主动买卖指标，不依赖新开仓使用的 拥挤指标接口。多空拥挤、主动买卖和 OI 远端数据使用当前 `timeframe`，OI 取 `oi_sample_count`（当前 4）个样本覆盖约 45 分钟。缓存以交易所数据时间计算有效期（`remote_metric_max_age_seconds`，当前 1860 秒），不是请求完成时间；过期后不作为有效行情缓存；趋势反转退出不依赖这些远端指标。1h/4h 由完整 15m 源 K 线按 UTC 本地聚合，不新增 informative pair 订阅。市场普跌使用每轮最新本地 K 线重新评估，不冻结旧结论。
- 币安全市场/大户多空比、主动买入量、未平仓量、强平事件和资金费率共同计算配置的加权评分。ADL 已从评分中移除，其原有 10% 权重分别转给放量和主动买入，各增加 5%；评分不再请求或依赖 `symbolAdlRisk`。账户持仓的 ADL 风险提示继续保留，仅用于观察。
- 空头拥挤占比取“空头人数占比”和“空头持仓量占比”两者中的最高值；仅当 `short_share_filter_enabled=true` 时，这个最终值必须严格大于 `min_short_share`（当前 50%）才允许开仓；当前开关为 `false`，空头占比不再作为硬门槛，但仍参与拥挤评分。最近 `trend_continuity_candles`（当前 3）次主周期收盘变化中至少达到 `min_trend_continuity`（当前 2/3）上涨，且最近 `momentum_lookback_candles`（当前 4，约 1 小时）根绝对动量必须为正。如果涨幅前 30 中至少 `market_down_ratio`（当前 80%）的交易对 1 小时动量非正，则将这 30 个龙头候选视为市场下跌：只暂停新开仓，已有仓位继续按独立趋势和止损规则管理。另设严重普跌分支：`market_emergency_enabled=true` 且至少 `market_emergency_ratio`（当前 60%）候选的 1 小时跌幅达到 `market_emergency_drop`（当前 3%），才触发 `market_emergency` 紧急退出并暂停开仓；这不是全市场宽度指标。如果不足 `market_min_coverage_ratio`（当前 80%）的交易对有 K 线数据，则市场状态未知：禁止开仓，但不会仅因数据缺失而平仓。放量仍然只是评分项，不是单独的硬性门槛。
- 管理仓位少于 2 个时，选择买入评分达到 40 分基础门槛的最佳候选；后续开仓要求达到 45 分。即使持仓交易对离开涨幅前 30，也继续保留其原评分用于持仓管理；持仓交易对数据不完整时不会按零分处理。轮换目标也必须达到 50 分买入评分，旧仓等待目标完整买入确认后才允许轮换退出。
- 当排名、仓位状态或强平数据流心跳过期时，停止开仓。
- 轮换的确认和买入受全局开仓门槛约束：无法开仓时取消尚未提交买单的计划；候选消失、持仓无有效评分或数据中断会清除连续确认计数。买单提交后不因 ETH 拦截等开仓条件变化丢弃成交跟踪；目标完整成交后，旧仓退出不再依赖这些开仓门槛。
- 选币、轮换候选及实际买入共用交易资格检查：目标必须仍在当前交易名单中，并通过框架对多单的交易对/全局交易锁检查。交易锁按最新已收盘 K 线时间检查；名单、K 线或锁读取异常时拒绝买入。目标失去资格时，仅清除尚未提交买单的计划。
- 市价开仓要求价差不超过 0.10%，预计滑点不超过 0.25%。选币和轮换共用最多 5 秒的 20 档盘口缓存，从请求开始计龄。实际买入确认遇到缓存缺失或到期时补取一次盘口，按框架传入的真实数量复核；请求失败或耗时达到 5 秒则拒绝，不回退旧缓存。补取后再次核对 ETH、账户、数据和评分条件。这会在必要时增加一次同步盘口请求，但不会放宽数据时效或价差/滑点门槛。目标买入完成后不再用目标买盘限制旧仓卖出。盘口检查不保证成交价，买入与卖出仍不是原子操作。
- 外部仓位继续每轮检查止损；使用不超过 20 档的盘口定价时，止损检查和退出定价复用上述短时快照，避免同一币种重复请求，不降低止损检查频率。其他定价配置仍交给框架处理。
- 当前配置开启 `stoploss_on_exchange=true`，`stoploss=-1.0`、`order_types.stoploss="market"`、`stoploss_price_type="mark"`：框架在成交仓位的止损检查中提交交易所止损市价单，并记录止损订单 ID。100% 指单笔初始保证金口径，价格距离为 `abs(stoploss) / 实际杠杆`；例如 5 倍多单的止损价约为成交均价 × 0.8。框架采用止损价与带缓冲强平价中更早保护的位置，不为满足 100% 而把止损放到强平价之后。标记价格触发后按市价成交，费用、资金费、精度和滑点可能使实际亏损偏离 100%。开仓与创建止损是两个请求，并非原子附带单；当前标准流程会在后续主循环检查已成交仓位，60 秒参数不延迟首次建单。币安合约止损为 reduceOnly：主动退出时保留不占用资产的止损，平仓成交后由框架撤掉残余止损；若止损先成交，则核对其成交并关闭交易，避免再次平仓。网络或接口失败会影响建单/撤单确认，日志中的订单提交不等于成交。无效止损订单按框架 emergency_exit 市价退出，临时交易所错误则记录并在后续循环重试。重新加载配置后，框架也会为仍在管理且没有止损单的已有仓位补建；已有更紧的止损不主动放宽。参见 [Freqtrade 止损文档](https://www.freqtrade.io/en/stable/stoploss/) 和 [币安条件单接口](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade#new-algo-order-trade)。
- 外部仓位逐个隔离异常：某个币种的行情、退出判断、止损维护或下单报错时，输出红色错误日志，将其标记为保护未确认并暂停新开仓，但继续处理其余仓位和本轮策略流程。
- UTC 日收益和峰值权益回撤仅用于统计，不触发清仓，也不限制开仓；已移除 `max_drawdown_limit`。旧状态文件中的 `account_stopped` 不再触发停止，正常保存时兼容写入 `false`。模拟盘使用 `user_data/leader_squeeze_state.json`，实盘使用 `user_data/leader_squeeze_state.live.json`，避免模拟权益和轮换记录污染实盘。状态文件损坏或读写失败仍会暂停新开仓，单笔止损、市场普跌、趋势退出及轮换保持有效。
- 首次运行没有状态文件时正常初始化。已有文件损坏、字段无效或无法读取时，输出红色错误日志并锁定新开仓及轮换，保留原文件、不重新建立权益基线；已有仓位仍继续止损和退出。修复文件或权限后重启才能重新读取，不要通过删除文件清除故障。程序无法仅凭文件不存在区分首次运行与人为删除，因此实盘状态文件必须保留。

## 趋势反转退出

趋势退出使用完整 15m 源 K 线的本地 UTC 聚合，与 ETH 的入场 EMA 过滤独立；不额外订阅 1h/4h。普通、快速、慢跌和历史破位分支读取已收盘 1h，1h 数据不足时该趋势分支不触发；正常入场因 1h 不可用而拒绝。持仓趋势退出不等待固定持仓天数，程序硬止损和市场普跌风险分支保持原规则。

参考区间从后向前寻找最近已确认的局部低点：中心 K 线左右各 `reversal_pivot_side_candles`（当前 2）根的 `low` 都必须严格高于中心值；找不到局部低点时使用参考区间最低值作为支撑。ATR 使用 `atr_period`（当前 14）和 Wilder 方法计算，使用信号 K 线之前的全部可用历史（不限于查找支撑的 `reversal_lookback_candles` 根），避免信号下跌改变支撑或波动基线。

1h 普通结构破位要求最后 `reversal_confirm_candles`（当前 2）根 1h 收盘都严格低于 `support - reversal_atr_buffer × ATR`，即连续 2 根 1h、约 2 小时，当前缓冲为 `0.5 × ATR1h`。1h 急跌破位只要求最新一根 1h 收盘严格低于 `support - reversal_fast_atr_buffer × ATR`，当前缓冲为 `1.5 × ATR1h`。慢跌分支最近 `reversal_slow_candles`（当前 5）根 1h 收盘均严格低于各自 EMA20，最新 EMA 低于 5 根前 EMA，最近这些 K 线没有净上涨，且连续弱势段累计下降至少 `reversal_slow_atr_drop`（当前 `1.0 × ATR1h`）；5 根 1h 即 5 小时，跌幅在连续弱势段累计，不会每 5 根重置，收盘恢复到 EMA 或以上则重置。历史破位仍从可用 1h 历史重算原始支撑和 ATR，后续收盘未收复支撑且仍低于原普通阈值时维持退出；重启可重算，超出已加载历史的信号无法追溯。单根普通确认、下影线或单根 EMA 跌破都不会单独触发。

额外 15m 急跌不等待当前 1h 收盘：只用信号开始前已经完整收盘的 1h 支撑和 ATR，以 `reversal_intrabar_atr_buffer`（当前 `1.0 × ATR1h`）为阈值，判断最新 15m 收盘是否跌破；在 `reversal_emergency_memory_candles`（当前 16 根，即 4 小时）内可回溯信号，且后续 15m 收盘必须一直未收复该支撑、当前仍低于普通缓冲阈值。该额外分支与 1h 普通/快速/慢跌/历史分支并列，均不改变程序硬止损或市场普跌风险处理。所有阈值都是待市场验证的起点，不代表最优盈利设置。规则中的波动率计算参考 [Fidelity ATR 指标说明](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/atr)，破位等待收盘确认参考 [Fidelity Chart Patterns 教材（突破确认）](https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Deck_Chart%20patterns.pdf#page=12)。

## 评分公式（当前实现）

时间约定：数据库持仓/订单、K 线、交易所请求和风控 JSON 均使用 UTC；ETH K 线时间和资金费率结算时间在日志中转换为北京时间（`+08:00`），UTC 日收益在北京时间 08:00 切日。PostgreSQL 每个新连接固定 UTC 会话时区，避免把 aware UTC 写入无时区列时变成本地时间。该修复不自动转换历史错误记录；发现持仓开仓时间在未来时暂停新开仓并报警，保留既有仓位的退出处理。修复存量记录前必须停止交易进程并备份，不能对混合时区数据直接全表减 8 小时。

原评分为各项归一化分数乘以配置中的 `weights` 后相加，再乘以协议约定的 100，满分 100。当前权重为：空头拥挤 20%、动量 32%、放量 15%、主动买入 15%、强平 5%、OI 挤空 10%、资金费率 3%。各项分数均限制在 0 到 1 之间。

- 空头拥挤分：`clamp((最终空头占比 - short_score_start_share) / (short_score_full_share - short_score_start_share))`；当前起点为 50%，满分占比为 75%。
- 动量分：`momentum_return_weight × clamp(动量涨幅 / momentum_full_score) + (1 - momentum_return_weight) × 上涨比例`。其中上涨比例是最近 `trend_continuity_candles`（当前 3）次主周期收盘变化中上涨的比例，动量涨幅使用 `momentum_lookback_candles`（当前 4）根；当前 `momentum_full_score=0.03` 时，3% 对应价格部分满分。
- 放量分：`volume_activity_weight × clamp((持续量比 - 1)/(volume_activity_full_ratio - 1)) + (1-volume_activity_weight) × clamp((短期量比 - 1)/(volume_score_full_ratio - 1))`。近期取最近 `volume_window_candles=3` 根已收盘 K 线均量，两个基准均排除这 3 根：短期对比前 `volume_baseline_windows=20` 根（5h）均量，持续对比前 `volume_activity_baseline_candles=672` 根（7 天）均量。持续部分占 70%、3 倍满分；短期部分占 30%、2 倍满分，放量总贡献仍最多 15 分。基准为零时对应部分不加分；不足 675 根已收盘 K 线时不使用缩短窗口冒充周基准。
- 主动买入分：`clamp((主动买卖比 - 1) / (taker_score_full_ratio - 1))`；普通评分取最近 `taker_window_candles=3` 根连续已收盘 15m 的 `ΣbuyVol / ΣsellVol`，不是三个比值的算术平均；`taker_score_full_ratio=1.5` 时达到满分。样本缺失、断档或未收盘时不可用；买卖量均为零时比值为 1，只有买量时按满分比值处理。
- OI 挤空分：只有价格上涨且 OI 下降时计分，使用主周期的 `oi_sample_count`（当前 4）个样本计算变化，并使用 `clamp(-OI变化 / oi_score_full_drop)`；当前 OI 下降 3% 时该项满分。
- 资金费率分：每个全量评分批次安排一个与核心指标并行的后台任务，分别调用一次公开的 `premiumIndex` 和一次公开的 `fundingInfo`。对匹配到的交易对，从 `fundingInfo` 读取 `adjustedFundingRateFloor`（负下限）、`adjustedFundingRateCap`（正上限）和 `fundingIntervalHours`，并按 `rate / interval_hours` 统一为每小时费率。正资金费率表示多头付给空头，做多策略不加分；负资金费率表示空头付给多头，做多触及该交易对自身负下限时贡献 3 分，公式为 `3 × clamp(max(0, -rate / hours) / (-floor / hours))`。接口字段定义见[币安 Funding Rate Info 文档](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#get-funding-rate-info)。
- 资金费率的分数表示当前费率达到该交易对自身上下限的程度，而不是不同交易对之间的绝对每小时收益率排名；同一交易对的 `interval_hours` 在分子和分母中会抵消。日志仍同时显示原始费率、结算间隔、每小时费率、等效 8 小时费率、上下限、下次结算时间和贡献分，并以 1 小时/4 小时/8 小时统一口径展示。若 `fundingInfo` 异常、过期、缺少字段，或返回结果没有当前交易对，则不猜测周期、上下限，资金费率加分为 0，不单独禁止开仓；资金费率最多有效 930 秒，或在下一次结算更早时失效，随后移除旧资金费率加分，基础评分仍可使用。该分数不是确定到账的资金费收益。
- 例如在同一结算间隔下，费率 `-0.4%`、该币负下限 `-2%` 时贡献 `0.6` 分；费率达到 `-2%` 时贡献 `3` 分；正费率贡献 `0` 分。一次实际公开接口采样中 BTC 返回过正负 `0.003`、`8h`，这只是该次接口结果，不是所有交易对或所有时间的固定值；实际上下限和结算间隔按每次成功的 `fundingInfo` 返回值处理。
- 强平分见下方说明；无事件不是正向信号，预热期间使用中性值。

在当前门槛下，原评分不会要求所有指标同时达到极端值。例如，空头 65%、1 小时涨幅 1.5%、最近 3 次上涨 2 次、短期量比 1.5、持续量比 2.0、主动买卖比 1.2、OI 下降 1%、无强平、资金费率不加分时约为 45.9000 分；若涨幅为 2%、短期量比 1.8、持续量比 2.6、主动买卖比 1.3，其余相同则约为 57.6667 分。实际新买入还要经过入场过热降权，买入评分必须达到相应门槛；达到门槛不代表收益或成交得到保证。

## 入场过热降权（只影响买入）

上面的加权总分是**原评分**，范围为 0 到 100，继续用于衡量已有仓位的强弱和执行原有退出逻辑。面向新买入的**买入评分**为 `原评分 × (1 - 过热惩罚)`；过热惩罚只降低新仓的排名和买入资格，不会因为一只已有仓位过去 15 天涨得多就单独把它判为弱仓或强制平仓。

- 过热评估取最新的 `entry_heat_history_days`（当前 15）天已收盘主周期 K 线；在当前 `15m` 配置下为 `1441` 根。`N日涨幅 = 最新收盘价 / N日前收盘价 - 1`；将 `0%` 到 `entry_heat_return_scale`（当前 100%）映射为 `growth=0` 到 `1`，负涨幅按 0 处理，超过上限按 1 处理。
- 最新一根是信号 K 线，不参与参考计算。热度 EMA 使用 `entry_heat_ema_candles`（当前 EMA96），Wilder ATR 使用 `atr_period`（当前 ATR14），都只使用最新信号之前的上一根及其之前的参考历史，不让信号 K 线自己的大波动抬高或压低本次指标。
- 当前收盘相对参考 EMA 的距离按 ATR 标准化：`extension_atr = (当前收盘 - EMA) / ATR`。偏离达到 `entry_heat_extension_start_atr`（当前 2 ATR）才开始产生热度，达到 `entry_heat_extension_full_atr`（当前 6 ATR）时热度满分；中间按线性比例计算 `heat`。
- 最大惩罚由 `entry_heat_max_penalty`（当前 20%）控制，公式为 `entry_heat_max_penalty × growth × (entry_heat_base_fraction + (1 - entry_heat_base_fraction) × heat)`；当前基础占比为 0.25。因此仅有较大历史涨幅、但没有明显远离 EMA 时也只是轻度降权；涨幅和当前追入位置同时过热时才接近最大降权。
- 允许“整理后重新突破”减轻惩罚：以前 `entry_heat_box_candles`（当前 16）根主周期 K 线作为整理箱，箱体 `high-low <= entry_heat_box_max_width_atr`（当前 4 ATR）；最新信号前一根收盘价距 EMA 不超过 `entry_heat_prebreak_extension_max_atr`（当前 2 ATR）；当前收盘价严格突破箱体最高价，且不超过 `箱体最高价 + entry_heat_breakout_overshoot_atr`（当前 1 ATR）。满足时按 `entry_heat_cooled_breakout_factor`（当前 0.5）降低过热惩罚，避免把整理后的健康突破与连续拉升后的追高等同处理。
- 新仓排名、40/45 分门槛、最终订单复核，以及轮换中的新目标均使用买入评分；轮换中的旧仓强弱仍以原评分为准，普通/快速分差分别为 10/15 分。轮换分差实际表示“目标买入评分 - 旧仓原评分”。日志同时显示原评分、15 日涨幅、EMA/ATR 偏离、整理突破、惩罚和买入评分。
- 15 日 K 线不足、过期、不连续或数值无效时，买入评分视为不可用并禁止买入；不会仅因缺少这段历史而强制退出已有仓位。趋势反转、市场普跌、止损等独立退出分支仍按各自的数据条件执行。
- 顶层 `startup_candle_count` 当前为 `1441`，用于覆盖 `entry_heat_history_days` 和其他已配置窗口；启动校验会拒绝不足以覆盖所选窗口的值。Binance Futures 单次最多取 499 根，框架还会为当前 K 线多取 1 根，因此没有缓存的交易对初始化约需 3 次 OHLCV 请求；动态白名单中新出现且没有缓存的交易对走同一初始化路径。交易对上市时间不足配置的热度历史时，即使其他指标有效，也不会把缺失历史当成低涨幅来买入。

以下四个主要参数已写入公开配置（其余可调参数见下表），当前只是待市场验证的起点：`entry_heat_max_penalty=0.20`、`entry_heat_return_scale=1.0`、`entry_heat_extension_start_atr=2.0`、`entry_heat_extension_full_atr=6.0`。它们不代表最优参数，也不承诺降低过热后一定提高收益。

币安全市场强平数据流每个交易对每秒最多发布一条强平快照。因此，强平评分只是市场压力的代理指标，并不代表该时间段内全部强平量的精确总和。预热完成后观察 `liquidation_recent_seconds`（当前 900 秒）强平名义金额，并与此前 `liquidation_window_seconds - liquidation_recent_seconds`（当前 2700 秒）按窗口平均得到的基线比较；基线至少按 `liquidation_min_notional`（当前 1000 USDT）处理，评分为 `clamp((最近窗口金额 / 基线 - 1) / (liquidation_score_full_ratio - 1))`，当前达到 5 倍时满分，最多贡献 5 分。预热完成且没有事件时该项为 0。

首次强平流连接以 INFO 输出“初始化统计窗口”。后续重连，或有效消息间隔超过 `liquidation_stream_max_age_seconds`（当前 15 秒），才输出警告、清空旧统计并按 `liquidation_window_seconds`（当前 3600 秒）重新预热。预热期间强平评分使用 `liquidation_warmup_score`（当前 0.5）中性值；连接和其他风控条件恢复后，无需等满整个窗口才能开仓。全市场心跳统一按该窗口清理事件和空缓存，不依赖币种是否进入排名。

## 当前轮换规则

只有常规仓位已满（`max_positions`，当前 5 仓）时才轮换；有空位按普通入场规则买入。先检查快速通道，再检查普通通道。新票使用**热度折扣后的买入评分**，旧票使用**原评分**。

| 条件 | 普通通道 | 快速通道 |
|---|---:|---:|
| 新票最低买入评分 | 50 | 60 |
| 比旧票高出的分数 | 10 | 15 |
| 旧票原评分 | 严格低于 45 | 不设 45 分上限 |
| 旧票最短持有 | 30 分钟 | 15 分钟 |
| 已收盘 K 线确认 | 连续 2 根 | 1 根 |
| 距上次授权轮换买入 | 30 分钟 | 15 分钟 |

旧仓先按 1h 持仓资格筛选：最新 1h 收盘低于 EMA20，且 EMA 相对 3 小时前下降，或本根 1h 的 high、low、close 均低于上根；最新 1h 高点不得超过此前 3 根 1h 高点中的最高值；最近 3 根先前小时的最高收盘价到最新 1h 收盘价回撤至少 `replacement_weak_atr_drop`（当前 `0.5 × ATR1h`）。通过后才继续原双通道的分差、确认和冷却条件；趋势资格本身不因持仓天数放宽，也不额外放宽程序硬止损。仍创新高的持仓受到保护。外部仓位年龄从进程发现时开始计算。高分目标无法单独跳过全局、数据、趋势、交易锁或盘口检查。

快速通道额外要求：最新收盘突破此前 `replacement_fast_breakout_candles`（当前 8）根高点，但高出不超过 `replacement_fast_max_breakout_atr × ATR`（当前 1 × ATR）；最新单根成交量至少是之前 `replacement_fast_volume_baseline_candles`（当前 20）根均量的 `replacement_fast_volume_ratio`（当前 1.5）倍；收盘位于本根振幅的 `replacement_fast_close_location`（当前 65%）以上；最新单根主动买卖比至少为 `replacement_fast_taker_ratio`（当前 1.2）；用最新 K 线指标重算的动量、放量、主动买入三个评分贡献合计至少为 `replacement_fast_core_score`（当前 48/62）。快速核心分使用最新单根主动买卖比，该样本时间必须与突破 K 线一致；普通原评分仍使用三根汇总值。因此单靠 OI 或强平附加分不能获得快速轮换资格。单根突破量比与原评分的 45m 双基准量比是不同指标，快速目标仍需满足单根 1.5 倍放量。

确认按新旧两票共同的已收盘 K 线时间计数。同一根 K 线内的评分重试不会增加计数；跳过一根、条件失效或组合变化从 1 开始。候选保持：上一目标仍合格且落后最高分不超过 3 分时优先沿用，避免微小名次变化反复清零。两条通道的确认计数不混用；重启后未完成的观察计数重新建立。

轮换全局冷却从实际授权提交目标买单时开始，创建或取消未提交计划不启动冷却。同一个主周期时间段最多授权一次轮换。旧票重新买入冷却由 `replacement_reentry_cooldown_minutes`（当前 30 分钟）控制，提交时先登记，确认轮换完成后再从当时重新计算，随状态文件保存；可阻止立即换回。下单前重新检查通道分差、突破/停滞条件及仓位数变化。分差不等于预期收益，也不保证覆盖交易费用。

先买目标且只允许本轮目标入选，入场最低分取追加门槛与所选通道门槛中的较大值。普通开仓最多 5 仓；满仓时只有带本轮唯一标识的目标买单可使用第 6 个名额，且不会开第 7 仓。

下单前保存轮换标识、目标、旧仓及按交易所合约精度处理后的请求数量，进入“等待买入确认”。仅创建 Trade、订单接受或部分成交都不能触发轮换卖出；必须本轮标识对应的目标 Trade 仍有多仓、无待处理普通订单、没有已成交退出，且终态买单的累计实际成交数量达到请求数量，才允许退出旧仓。
目标完整成交后进入“等待旧仓退出”，继续尝试退出旧仓；在旧仓退出完成前不允许任何其他开仓或第二次轮换。成交数量不足、目标已退出或下单结果不明时保留旧仓并暂停新开仓，输出核对提示。不会为“完成轮换”自动卖掉部分成交的新仓，也不会盲目重复买入。

轮换状态与冷却时间写入现有风控状态文件；正常重启后用数据库订单成交记录重新核对，不靠内存中“曾下单”的标记判断。没有本地目标仓位的待确认轮换可进行只读恢复核对：提交满 120 秒、至少间隔 30 秒连续两次确认没有任何成交、普通或条件挂单、交易所及本地目标仓位，才解除等待并重新计冷却；保留旧仓，不立即重买。历史截断、接口异常、无法核实的成交或提交超过 24 小时均不自动解除。目标已平仓时，只有唯一匹配本次轮换标签的已关闭 Trade、交易所历史成交 ID/数量与本地逐笔匹配，且连续两次确认无挂单和目标仓位，才允许解除等待。重启后重新计确认次数；旧计划可使用已持久化的最后轮换时间，时间无效则保持暂停。若部分成交或结果不明而无法自动确认，需先核对交易所订单、数据库和实际持仓；确认没有待处理订单、仓位已妥善处理后，停止服务，仅将状态文件中的 `rotation` 设为 `null` 再重启。不要删除整个状态文件或清除峰值统计。

买入与卖出仍是独立订单，不保证旧仓卖出一定成功；卖出失败时可暂时保持 6 仓，但禁止继续开仓。独立止损、账户风控和趋势反转退出仍可随时执行，不受“买不成不轮换卖旧仓”限制。

## 运行日志

`leader_squeeze.status_log_seconds` 控制 ETH、策略、选币、仓位和账户风控的常规日志间隔，当前为 `300` 秒。开仓限制、候选或轮换计划变化会提前输出状态；开仓复核、退出信号、风控触发和异常即时记录。不会为打印日志额外请求行情或发送交易。

| 标识 | 内容 | 终端颜色 |
| --- | --- | --- |
| ✅ / ⛔ ETH 主周期 | 当前趋势、确认窗口收盘价与配置 EMA、不拦截/拦截原因 | 绿 / 黄 |
| 🧭 策略状态 | 全局开仓许可、行情完整性、评分/仓位/强平流心跳年龄、评分任务、市场状态 | 青 / 黄 |
| 📊 / 🏆 / 🎯 评分与选币 | 原评分分项、过热降权、买入排名、入选名单，以及占比、动量、资金费率原始值/间隔/每小时费率/等效 8h、下次结算、贡献、仓位容量、价差和滑点筛选结果 | 紫 |
| 📦 仓位状态与持仓 | 每 5 分钟显示仓位数量，分别列出方向、数量、杠杆、开仓价、未实现盈亏与止损记录；区分策略仓位和外部仓位 | 汇总青；盈亏绿 / 红 |
| 🛡️ 账户风控 | 权益、UTC 日收益和峰值回撤（均仅统计）、状态文件健康度、权益更新时间 | 青 / 黄 / 红 |
| 🔄 / 🚪 轮换与退出 | 弱仓原评分与目标买入评分、轮换确认，以及退出原因和当前收益 | 紫 / 黄 |
| ⚠️ / 🚨 / 🔌 异常 | 数据缺失、订单或止损失败、状态文件读写异常、数据流重连 | 黄 / 红 |

每批评分汇总输出原评分明细、入场过热评估、原始指标和资金费率四张表；选币结果表按买入评分列出排名、配置热度历史涨幅、热度折扣、是否入选与筛选原因。持仓明细表汇总策略及外部仓位，并显示当前标记价、开仓分数、热度涨幅和热度折扣；折扣只是新买入参考，不用于降低旧仓的强弱评分。轮换审计快照在每个 `snapshot.pairs[pair]` 下保存 `multi_timeframe.holding`、`multi_timeframe.background`、`multi_timeframe.entry`、`multi_timeframe.rotation`、`multi_timeframe.emergency` 五类上下文，便于区分 1h 持仓、4h 背景、入场、旧仓轮换和 15m 额外急跌判断。当前价取最近同步的交易所 `markPrice`，不额外请求行情；仓位同步失败或超过 `position_stale_seconds`（当前 60 秒）时标为“旧”，缺值显示“未知”。状态表沿用 `status_log_seconds` 刷新间隔及状态变化触发机制。终端按实际宽度换行，整张表一次输出；文件和 API 日志保留纯文本表格。

新仓首次买入成交（含部分成交终态）后，把最终下单复核时的买入评分写入该 Trade 的自定义数据，普通开仓与轮换开仓均适用，之后重启读取已保存分数。提交后、记录落库前发生重启时，若无法取得复核快照，只显示历史 `squeeze_XX` 标签分并标注“标签”；旧版标签可能是未扣热度的原评分。外部仓位、无分数标签的旧轮换仓或其他没有记录的仓位显示“未记录”，不使用当前分数回填历史。

颜色通过 Freqtrade 的 Rich 终端处理器呈现；纯文本日志和 API 日志保留中文、图标及字段，不写入 ANSI 控制字符。终端不支持颜色或关闭彩色输出时，仍可按图标和文字辨认。持仓与止损均显示缓存/数据库已知状态，并非再次向交易所实时确认；模拟盘钱包的未实现盈亏字段固定为零。开仓复核和退出信号日志也不代表订单已经成交，实际成交以框架订单日志和交易所状态为准。

## 配置

当前 `user_data/config.json` 已设置 `dry_run: false`，启动即为实盘。修改配置文件不会自动重启已运行的进程。

框架的 `max_open_trades` 为 `6`，用于容纳轮换临时名额；策略的 `leader_squeeze.max_positions` 仍为 `5`。这不是把普通开仓上限改成 6：策略在选币与实际下单两处限制普通仓位数，并用本轮唯一标识限制轮换第 6 单。

启动时校验 `max_positions` 为正整数，框架容量至少为 `max_positions + 1`（框架无限仓位配置也可通过，策略自身上限仍生效）。容量不足会在读取风控状态和启动行情线程之前明确报错，不带着无法完成先买后卖轮换的配置运行。

启动时只需要通过 `-c` 传入 `user_data/config.json`；其中的
`add_config_files` 设置会自动加载其他配置文件：

- `config-pairlists.json`：交易对白名单和涨幅榜选择器链。
- `config-blacklist.json`：排除的交易对模式。
- `config-private.json`：数据库 URL、交易所凭据、Telegram 设置和 API 服务凭据。请将文件权限保持为 `0600`，并且不要提交到代码库。

```bash
uv run freqtrade trade -c user_data/config.json
```

策略主类保留流程编排，职责单一的辅助方法已拆到同级文件，共 8 个 helper：`leader_squeeze_config.py`（配置校验）、`leader_squeeze_data.py`（行情与指标）、`leader_squeeze_execution.py`（订单与外部仓位）、`leader_squeeze_reporting.py`（日志与表格）、`leader_squeeze_storage.py`（状态与快照）、`leader_squeeze_support.py`（通用支持）、`leader_squeeze_audit.py`（轮换审计写库）和 `leader_squeeze_trend.py`（多周期趋势与反转）。修改策略时应同时查看对应职责文件。

## 数据库

未配置 `db_url` 时，实盘模式使用 `tradesv3.sqlite`。当前设置将 PostgreSQL
URL 保存在 `config-private.json` 中；必要时可以使用环境变量覆盖：

```bash
export FREQTRADE__DB_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DATABASE'
```

不要提交交易所、数据库、Telegram、代理或 API 服务凭据。

服务使用的 PostgreSQL 已创建 `leader_rotation_events` 表，用于记录轮换现场和结果。记录类型包括 `evaluation`、`candidate_observed`、`plan_created`、`cancelled`、`entry_approved`、`entry_rejected`、`execution_status`、`target_filled`、`review_required`、`order_filled`、`exit_allowed`、`completed`、`blocked`、`startup`、`external_exit_submitted`（外部退出订单提交）、`external_exit_failed`（外部退出失败）和 `state_save_failed`（轮换状态保存失败）。每条记录的 `snapshot` 使用 JSONB 保存评分、分项评分、热度、配置、指标、持仓、仓位、实际检查结果、旧仓是否创新高以及 `multi_timeframe.exit_reason`（`_trend_exit_details` 文本），`reason` 保存未轮换或阻断原因；快照不包含凭据。标记为一次性事件的相同状态和快照指纹不会重复写入。

审计写入使用独立事务，不和交易订单事务绑定；数据库暂不可用时先写入本地 outbox，服务启动或后续重试继续提交，`event_id` 保证幂等。实盘和模拟盘分别使用 `rotation_audit_spool_live`、`rotation_audit_spool_dry_run` 指定的 spool 文件。当前进程需要重启后才开始记录，历史轮换不会回填。查询示例见 [轮换审计查询](leader_squeeze_rotation_queries.sql)。

## 实盘前需要了解的限制

- 策略的 `stoploss = -1` 表示约 100% 的单笔保证金风险；5 倍杠杆对应约 20% 的逆向价格波动。数据库内的仓位会受到框架强平缓冲价的约束，但外部仓位的自定义止损没有使用该缓冲，可能先触发强平。账户峰值回撤仅统计，不再提供账户级自动清仓保护。
- `manage_external_positions: true` 会接管不在当前数据库中的交易所仓位，包括直接平掉外部空单。请勿将它理解为仅监控仓位。
- 本策略依赖实时多空比、OI、强平流、后台线程和墙上时钟，不支持用普通历史 K 线回测验证完整行为；单元测试通过也不代表收益已验证。


## 参数调整入口

`user_data/config.json` 的 `leader_squeeze` 当前包含策略运行所需的全部 127 个公开参数；策略启动时严格要求配置完整，不从代码补默认值。修改后需要重启进程。ADL 权重已平均转入放量和主动买入，总分仍为 100；快速核心分门槛由 40/52 调为 48/62，热度及其余轮换门槛保持不变，双通道轮换使用表中数值。逐项试算和待确认的评分建议见 [参数试算](leader_squeeze_parameter_analysis.md)。

| 当前配置中的评分/热度参数 | 当前值 | 含义 |
|---|---:|---|
| short_score_start_share / short_score_full_share | 0.50 / 0.75 | 空头分起点/满分占比，与入场硬门槛独立 |
| momentum_return_weight | 0.80 | 动量内部涨幅占比，连续性占剩余 0.20 |
| volume_score_full_ratio / taker_score_full_ratio | 2.0 / 1.5 | 短期放量部分/主动买卖比达到满分的尺度（普通三根汇总、快速单根） |
| oi_score_full_drop | 0.03 | 上涨时 OI 降幅达到满分的尺度 |
| liquidation_score_full_ratio / liquidation_warmup_score | 5.0 / 0.5 | 强平满分倍数/预热时归一化分数 |
| entry_heat_ema_candles / entry_heat_box_candles | 96 / 16 | 热度 EMA 周期/整理箱长度 |
| entry_heat_box_max_width_atr | 4.0 | 整理箱宽度上限 |
| entry_heat_prebreak_extension_max_atr | 2.0 | 突破前收盘距 EMA 的最大距离 |
| entry_heat_breakout_overshoot_atr | 1.0 | 热度整理突破允许超过箱顶的距离 |
| entry_heat_cooled_breakout_factor | 0.5 | 整理突破后惩罚乘数 |
| entry_heat_base_fraction | 0.25 | 不考虑当前偏离时的基础惩罚占比 |

轮换参数均以 `replacement_` 开头；快速通道以 `replacement_fast_` 开头。旧仓的停滞、1h EMA/结构走弱、此前 3 根 1h 高点和 `replacement_weak_atr_drop=0.5` 回撤条件先于通道判断；`replacement_entry_score`、`replacement_weak_score`、`replacement_score_gap` 再分别控制普通新票门槛、弱仓线和分差；`replacement_no_new_high_candles=4` 表示当前 1h 根与此前 3 根；`replacement_candidate_hysteresis=3` 是候选保持分差；`replacement_reentry_cooldown_minutes=30` 是旧票买回冷却。快速突破参数的名称和当前值直接列在配置中。`replacement_fast_enabled=false` 可关闭快速通道。

主周期和启动历史由顶层 `timeframe`、`startup_candle_count` 配置；`holding_timeframe=1h`、`background_timeframe=4h`、`trend_slope_candles=3`、`reversal_intrabar_atr_buffer=1.0`、`reversal_emergency_memory_candles=16` 和 `replacement_weak_atr_drop=0.5` 控制多周期趋势、15m 额外急跌和旧仓资格。热度天数、ATR 周期、EMA 周期、动量/连续性/成交量/OI 窗口、强平窗口、数据时效、网络超时、状态文件、审计 outbox 和其余轮换参数均由公开 `leader_squeeze` 配置读取。当前配置仍是 `15m`、15 天、ATR14、4/3/3/20 和 OI4，但这些值不再写死在代码中；启动时会拒绝非法比例、零分母、非整数窗口、历史覆盖不足及高于可用核心分上限的快速门槛。

公式的结构性常量仍属于算法协议，不是配置项：分数归一化到 `[0, 1]`、总分乘以 100、Wilder ATR 的递推系数、Binance 接口字段/事件流协议、订单 `reduceOnly` 语义和框架订单状态含义由实现定义。窗口、阈值、权重、时效和超时等策略参数才从 `config.json` 调整；不要把协议常量或公式系数当成可单独热更新的配置。

市场分层、主动买窗口和轮换恢复参数见 [参数试算](leader_squeeze_parameter_analysis.md#市场分层主动买平滑与轮换恢复)。原始指标表同时显示汇总和最新单根主动买卖比；轮换快照保留两项指标及时间、严重普跌状态和恢复核对结果。恢复事件包括 `recovery_check`、`recovery_blocked`、`recovered`。

2026-09-16 外部 review 的核实、修复与未采纳建议见 [review 核实记录](leader_squeeze_review_20260916.md)。日志计算缓存仅覆盖一次输出；下单及退出判断不复用该缓存。

候选池上限由 `config-pairlists.json` 中 `PercentChangePairList.number_assets=30` 控制；成交额、上市时间和价差过滤保留，符合条件不足时实际候选少于 30。持仓保留项可能使日志总行数超过 30。市场覆盖和普跌门槛按实际候选数计算，30 个候选时 80% 为 24 个、严重普跌 60% 为 18 个。

等额分仓使用 `wallets.get_total_stake_amount() × stake_ratio`，盘口预检查也使用同一资金基数，最终仍按实际下单量复核。基数遵守框架 tradable_balance_ratio 或 available_capital 规则，不是固定初始本金，也不等于包含所有外部仓位的账户总权益。盈利、亏损、出入金及外部占用变化后，新仓金额会相应变化；已有仓位不会自动补齐。资金或交易所上限不足、目标小于最小下单金额时返回 0 跳过，计算异常也不会回退为框架建议的大额下单。stake_ratio 必须为正，并满足 `(max_positions + 1) × stake_ratio <= 1`，为先买后卖临时仓位预留预算。当前 1,000 USDT、99% 可交易比例时，忽略费用与盈亏，每笔保证金 99 USDT，5 倍名义金额约 495 USDT。

追加开仓门槛本次从 50 降为 45（additional_entry_score）；普通轮换目标门槛仍为 50，快速轮换仍为 60。上涨连续性仍是最近三次收盘变化至少两次上涨，评分构成保持不变。
