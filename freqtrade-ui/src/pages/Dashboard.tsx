/**
 * Dashboard — a fixed, dense grid of the panels freqUI lets you drag around.
 *
 * Drag-and-drop is deliberately not implemented: a stable responsive grid keeps
 * the same information density without a layout store. Everything that can come
 * from the shared snapshot does; the rest is polled at a slower cadence.
 */

import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Banner, Button, RadioGroup, Spin, Table, Tooltip } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import {
  IconActivity,
  IconBarChartVStroked,
  IconCoinMoney,
  IconHistogram,
  IconHistory,
  IconLineChartStroked,
  IconListView,
  IconPercentage,
  IconPieChartStroked,
  IconPulse,
  IconRefresh,
  IconServer,
  IconTemplate,
  IconTestScore,
} from '@douyinfe/semi-icons'

import type { EntryExitTag, PerformanceEntry, StrategyResponse, Trade } from '../api/types'
import { decodeWalletHistory, tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { useSettings } from '../state/settings'
import { useSnapshot } from '../state/snapshot'
import { usePolling } from '../hooks/usePolling'
import { BarChart, DonutChart, LineChart, type BarDatum, type LinePoint } from '../components/charts'
import { TradeList } from '../components/TradeList'
import {
  DryRunTag,
  EmptyState,
  KeyValueList,
  Panel,
  StatTile,
  StateTag,
  Tag,
  ValuePair,
  type Tone,
} from '../components/primitives'
import {
  formatCompact,
  formatNumber,
  formatPercent,
  formatPrice,
  formatPriceCurrency,
  formatTimestamp,
  signClass,
  signOf,
} from '../utils/format'

/* -------------------------------------------------------------------------- */
/* Strategy parameters (the API returns these but the shared type omits them)   */
/* -------------------------------------------------------------------------- */

interface StrategyParam {
  name: string
  space?: string
  value?: unknown
  param_type?: string
}

type StrategyWithParams = StrategyResponse & { params?: StrategyParam[] }

/* -------------------------------------------------------------------------- */
/* Derived series helpers                                                      */
/* -------------------------------------------------------------------------- */

/** Maps a signed value onto a StatTile tone. */
function toneOf(value: number | null | undefined): Tone {
  const sign = signOf(value)
  if (sign === 'up') return 'up'
  if (sign === 'down') return 'down'
  return 'neutral'
}

function closedSorted(trades: Trade[]): Trade[] {
  return trades.slice().sort((a, b) => (a.close_timestamp ?? 0) - (b.close_timestamp ?? 0))
}

/** Cumulative realised profit over time, deduplicated per timestamp. */
function cumulativePoints(trades: Trade[]): LinePoint[] {
  const sorted = closedSorted(trades)
  const byTime = new Map<number, number>()
  let acc = 0

  const first = sorted[0]
  if (first?.open_timestamp) byTime.set(Math.floor(first.open_timestamp / 1000), 0)

  for (const trade of sorted) {
    if (!trade.close_timestamp) continue
    acc += trade.profit_abs ?? 0
    byTime.set(Math.floor(trade.close_timestamp / 1000), acc)
  }

  return [...byTime.entries()]
    .map(([time, value]) => ({ time, value }))
    .sort((a, b) => a.time - b.time)
}

/** Histogram of trade profit ratios (as percentages) across ~20 bins. */
function distributionBars(trades: Trade[], binCount = 20): BarDatum[] {
  const ratios = trades
    .map((t) => t.profit_ratio)
    .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
  if (ratios.length === 0) return []

  const min = Math.min(...ratios)
  const max = Math.max(...ratios)
  const span = max - min || Math.abs(max) || 1
  const width = span / binCount
  const counts = new Array<number>(binCount).fill(0)

  for (const ratio of ratios) {
    let index = Math.floor((ratio - min) / width)
    if (!Number.isFinite(index)) index = 0
    if (index < 0) index = 0
    if (index >= binCount) index = binCount - 1
    counts[index] += 1
  }

  return counts.map((count, i) => ({
    label: `${((min + i * width) * 100).toFixed(1)}%`,
    value: count,
  }))
}

/** One bar per closed trade, ordered by close time. */
function perTradeBars(trades: Trade[]): BarDatum[] {
  return closedSorted(trades).map((trade) => ({
    label: `#${trade.trade_id}`,
    value: Number(((trade.profit_ratio ?? 0) * 100).toFixed(4)),
  }))
}

interface PerfRow {
  key: string
  label: string
  profitPct: number
  profitAbs: number
  count: number
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

type PerfTab = 'performance' | 'entries' | 'exits' | 'mixTags'

const PERF_OPTIONS = [
  { value: 'performance', label: '交易对' },
  { value: 'entries', label: '入场标签' },
  { value: 'exits', label: '出场原因' },
  { value: 'mixTags', label: '组合标签' },
]

export function Dashboard() {
  const api = useApi()
  const navigate = useNavigate()
  const { config, openTrades, count, profit, balance, loading, error, slowUpdated, refresh } =
    useSnapshot()
  const { settings } = useSettings()

  const [profitScope, setProfitScope] = useState<'all' | 'long' | 'short'>('all')
  const [perfTab, setPerfTab] = useState<PerfTab>('performance')

  /* ---- slow, page-local data ------------------------------------------- */

  const closedState = usePolling(
    (signal) => tradingApi.trades(api, { limit: 500 }, signal),
    [api],
    { intervalMs: 30_000 },
  )
  const closedTrades = useMemo(() => closedState.data?.trades ?? [], [closedState.data])

  const profitAllState = usePolling((signal) => tradingApi.profitAll(api, signal), [api], {
    intervalMs: 60_000,
  })

  const strategyState = usePolling<StrategyWithParams>(
    config?.strategy
      ? (signal) =>
          tradingApi.strategy(api, config.strategy, signal) as Promise<StrategyWithParams>
      : null,
    [api, config?.strategy],
    { enabled: Boolean(config?.strategy) },
  )

  const walletState = usePolling(
    async (signal) => decodeWalletHistory(await tradingApi.historicBalance(api, signal)),
    [api],
    { intervalMs: 120_000 },
  )

  const perfState = usePolling<PerformanceEntry[] | EntryExitTag[]>(
    (signal) => {
      if (perfTab === 'entries') return tradingApi.entries(api, signal)
      if (perfTab === 'exits') return tradingApi.exits(api, signal)
      if (perfTab === 'mixTags') return tradingApi.mixTags(api, signal)
      return tradingApi.performance(api, signal)
    },
    [api, perfTab],
    { intervalMs: 60_000 },
  )

  /* ---- stat row --------------------------------------------------------- */

  const openCount = count?.current ?? openTrades.length
  const maxCount = count?.max ?? config?.max_open_trades ?? 0
  const stakeCurrency = config?.stake_currency ?? balance?.stake ?? 'USDT'
  const stakeDecimals = config?.stake_currency_decimals ?? 3

  const activeProfit = useMemo(() => {
    const all = profitAllState.data
    if (!all?.short) return all?.all ?? profit
    return all[profitScope]
  }, [profitAllState.data, profit, profitScope])

  const totalBalance = balance ? balance.total_bot || balance.total : undefined
  const startingRatio = balance
    ? balance.total_bot
      ? balance.starting_capital_ratio_bot
      : balance.starting_capital_ratio
    : undefined

  /* ---- series ----------------------------------------------------------- */

  const cumPoints = useMemo(() => cumulativePoints(closedTrades), [closedTrades])
  const distBars = useMemo(
    () => distributionBars(closedTrades, settings.profitDistributionBins),
    [closedTrades, settings.profitDistributionBins],
  )
  const tradeBars = useMemo(() => perTradeBars(closedTrades), [closedTrades])

  const donutSlices = useMemo(
    () =>
      (balance?.currencies ?? [])
        .filter((c) => c.est_stake > 0)
        .sort((a, b) => b.est_stake - a.est_stake)
        .map((c) => ({ label: c.currency, value: c.est_stake })),
    [balance],
  )

  const strategyGroups = useMemo(() => {
    const params = strategyState.data?.params ?? []
    const groups = new Map<string, StrategyParam[]>()
    for (const param of params) {
      const space = param.space ?? 'default'
      const bucket = groups.get(space)
      if (bucket) bucket.push(param)
      else groups.set(space, [param])
    }
    return [...groups.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([space, list]) => ({
        space,
        params: list.slice().sort((a, b) => a.name.localeCompare(b.name)),
      }))
  }, [strategyState.data])

  const perfRows = useMemo<PerfRow[]>(() => {
    const data = perfState.data ?? []
    if (perfTab === 'performance') {
      return (data as PerformanceEntry[]).map((entry) => ({
        key: entry.pair,
        label: entry.pair,
        profitPct: entry.profit_pct ?? entry.profit ?? 0,
        profitAbs: entry.profit_abs ?? 0,
        count: entry.count ?? 0,
      }))
    }
    return (data as EntryExitTag[]).map((entry, index) => ({
      key: `${entry.enter_tag ?? entry.exit_reason ?? entry.mix_tag ?? 'tag'}-${index}`,
      label: entry.enter_tag ?? entry.exit_reason ?? entry.mix_tag ?? '—',
      profitPct: entry.profit_pct ?? 0,
      profitAbs: entry.profit_abs ?? 0,
      count: entry.count ?? 0,
    }))
  }, [perfState.data, perfTab])

  const perfColumns = useMemo<ColumnProps<PerfRow>[]>(() => {
    const firstTitle =
      perfTab === 'performance'
        ? '交易对'
        : perfTab === 'entries'
          ? '入场标签'
          : perfTab === 'exits'
            ? '出场原因'
            : '组合标签'
    return [
      {
        title: firstTitle,
        dataIndex: 'label',
        render: (value: string) => <span className="ft-nowrap">{value}</span>,
      },
      {
        title: '收益率',
        dataIndex: 'profitPct',
        align: 'right',
        width: 110,
        render: (value: number) => (
          <span className={`ft-num ${signClass(value)}`}>{formatNumber(value, 2)}%</span>
        ),
      },
      {
        title: `盈亏 ${stakeCurrency}`,
        dataIndex: 'profitAbs',
        align: 'right',
        width: 130,
        render: (value: number) => (
          <span className={`ft-num ${signClass(value)}`}>{formatPrice(value, stakeDecimals)}</span>
        ),
      },
      {
        title: '笔数',
        dataIndex: 'count',
        align: 'right',
        width: 70,
        render: (value: number) => <span className="ft-num">{value}</span>,
      },
    ]
  }, [perfTab, stakeCurrency, stakeDecimals])

  const openDetail = (trade: Trade) => {
    navigate('/trade', { state: { tradeId: trade.trade_id, pair: trade.pair } })
  }

  /** Metric/value rows for the profit panel (freqUI's BotProfit table). */
  const profitItems = useMemo<{ metric: string; value: ReactNode }[]>(() => {
    if (!activeProfit) return []
    const p = activeProfit
    return [
      {
        metric: '已平仓 ROI',
        value: (
          <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
            <span className="ft-num">
              {formatPriceCurrency(p.profit_closed_coin, stakeCurrency, stakeDecimals)}
            </span>
            <span className={`ft-num ${signClass(p.profit_closed_ratio_mean)}`}>
              ({formatPercent(p.profit_closed_ratio_mean)})
            </span>
          </span>
        ),
      },
      {
        metric: '全部交易 ROI',
        value: (
          <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
            <span className="ft-num">
              {formatPriceCurrency(p.profit_all_coin, stakeCurrency, stakeDecimals)}
            </span>
            <span className={`ft-num ${signClass(p.profit_all_ratio_mean)}`}>
              ({formatPercent(p.profit_all_ratio_mean)})
            </span>
          </span>
        ),
      },
      {
        metric: '交易总数',
        value: (
          <span className="ft-num">
            {p.trade_count ?? 0}（已平 {p.closed_trade_count ?? 0}）
          </span>
        ),
      },
      {
        metric: '机器人启动',
        value: (
          <span className="ft-num">
            {formatTimestamp(p.bot_start_timestamp, { seconds: false })}
          </span>
        ),
      },
      {
        metric: '首次开仓',
        value: (
          <span className="ft-num">
            {formatTimestamp(p.first_trade_timestamp, { seconds: false })}
          </span>
        ),
      },
      {
        metric: '最近开仓',
        value: (
          <span className="ft-num">
            {formatTimestamp(p.latest_trade_timestamp, { seconds: false })}
          </span>
        ),
      },
      {
        metric: '胜 / 负',
        value: (
          <span className="ft-num">
            {p.winning_trades ?? 0} / {p.losing_trades ?? 0}
          </span>
        ),
      },
      {
        metric: '胜率',
        value: <span className="ft-num">{formatPercent(p.winrate)}</span>,
      },
      {
        metric: '期望 (ratio)',
        value: (
          <span className="ft-num">
            {formatNumber(p.expectancy, 2)} ({formatNumber(p.expectancy_ratio, 2)})
          </span>
        ),
      },
      {
        metric: 'CAGR',
        value: <span className="ft-num">{formatPercent(p.cagr)}</span>,
      },
      {
        metric: 'Calmar / Sharpe',
        value: (
          <span className="ft-num">
            {formatNumber(p.calmar, 2)} / {formatNumber(p.sharpe, 2)}
          </span>
        ),
      },
      {
        metric: 'Sortino',
        value: <span className="ft-num">{formatNumber(p.sortino, 2)}</span>,
      },
      {
        metric: '平均持仓',
        value: <span className="ft-num">{p.avg_duration ?? '—'}</span>,
      },
      {
        metric: '最佳交易对',
        value: (
          <span>
            {p.best_pair ? `${p.best_pair} · ${formatPercent(p.best_pair_profit_ratio)}` : '—'}
          </span>
        ),
      },
      {
        metric: '交易额',
        value: (
          <span className="ft-num">
            {formatPriceCurrency(p.trading_volume, stakeCurrency, stakeDecimals)}
          </span>
        ),
      },
      {
        metric: '盈利因子',
        value: <span className="ft-num">{formatNumber(p.profit_factor, 2)}</span>,
      },
      {
        metric: '最大回撤',
        value: (
          <span className={`ft-num ${signClass(p.max_drawdown)}`}>
            {formatPercent(p.max_drawdown)} (
            {formatPriceCurrency(p.max_drawdown_abs, stakeCurrency, stakeDecimals)})
          </span>
        ),
      },
      {
        metric: '当前回撤',
        value: (
          <span className={`ft-num ${signClass(p.current_drawdown)}`}>
            {formatPercent(p.current_drawdown)} (
            {formatPriceCurrency(p.current_drawdown_abs, stakeCurrency, stakeDecimals)})
          </span>
        ),
      },
    ]
  }, [activeProfit, stakeCurrency, stakeDecimals])

  if (loading && !config) {
    return (
      <div className="ft-page">
        <div style={{ padding: 'var(--ft-gap-7)', textAlign: 'center' }}>
          <Spin size="large" />
        </div>
      </div>
    )
  }

  return (
    <div className="ft-page">
      <header className="ft-page-head">
        <h1 className="ft-page-title">仪表盘</h1>
        <span className="ft-page-sub">
          {config?.bot_name ? `${config.bot_name} · ` : ''}
          {config?.exchange ?? '—'} · {config?.strategy ?? '—'}
        </span>
        <span className="ft-row" style={{ marginLeft: 'auto', gap: 'var(--ft-gap-4)' }}>
          {config && <StateTag state={config.state} />}
          {config && <DryRunTag dryRun={config.dry_run} />}
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            更新于 {slowUpdated ? formatTimestamp(slowUpdated, { seconds: false }) : '—'}
          </span>
          <Tooltip content="立即刷新">
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconRefresh />}
              onClick={() => {
                refresh()
                closedState.refresh()
                profitAllState.refresh()
                perfState.refresh()
              }}
            />
          </Tooltip>
        </span>
      </header>

      {error ? <Banner type="danger" description={error} closeIcon={null} /> : null}

      {/* ---------------- stat row ---------------- */}
      <div className="ft-grid cols-6">
        <StatTile
          icon={<IconListView />}
          label="未平仓 / 上限"
          value={`${openCount} / ${maxCount}`}
          meta={
            count?.total_stake !== undefined
              ? `占用 ${formatPriceCurrency(count.total_stake, stakeCurrency, stakeDecimals)}`
              : undefined
          }
        />
        <StatTile
          icon={<IconCoinMoney />}
          label="总收益"
          value={formatPercent(profit?.profit_all_ratio)}
          tone={toneOf(profit?.profit_all_ratio)}
          meta={
            <span className={signClass(profit?.profit_all_coin)}>
              {formatPriceCurrency(profit?.profit_all_coin, stakeCurrency, stakeDecimals)}
            </span>
          }
        />
        <StatTile
          icon={<IconHistory />}
          label="已平仓收益"
          value={formatPriceCurrency(profit?.profit_closed_coin, stakeCurrency, stakeDecimals)}
          tone={toneOf(profit?.profit_closed_coin)}
          meta={`${formatPercent(profit?.profit_closed_ratio)} · ${
            profit?.closed_trade_count ?? 0
          } 笔`}
        />
        <StatTile
          icon={<IconPercentage />}
          label="胜率"
          value={formatPercent(profit?.winrate)}
          tone={toneOf((profit?.winrate ?? 0) - 0.5)}
          meta={`${profit?.winning_trades ?? 0} 胜 / ${profit?.losing_trades ?? 0} 负`}
        />
        <StatTile
          icon={<IconPieChartStroked />}
          label="账户余额"
          value={formatPriceCurrency(totalBalance, stakeCurrency, stakeDecimals)}
          meta={
            startingRatio !== undefined
              ? `较起始资金 ${formatPercent(startingRatio)}`
              : `起始 ${formatPriceCurrency(
                  balance?.starting_capital,
                  stakeCurrency,
                  stakeDecimals,
                )}`
          }
        />
        <StatTile
          icon={<IconTestScore />}
          label="最佳交易对"
          value={profit?.best_pair ? profit.best_pair.split(':')[0] : '—'}
          compact
          tone={toneOf(profit?.best_pair_profit_ratio)}
          meta={
            profit?.best_pair
              ? `${formatPercent(profit.best_pair_profit_ratio)} · ${formatPriceCurrency(
                  profit.best_pair_profit_abs,
                  stakeCurrency,
                  stakeDecimals,
                )}`
              : undefined
          }
        />
      </div>

      {/* ---------------- curves ---------------- */}
      <div className="ft-grid cols-2">
        <Panel title="累计收益曲线" icon={<IconLineChartStroked />} sub="已平仓累计盈亏">
          <LineChart points={cumPoints} height={220} />
        </Panel>

        <Panel
          title="资金曲线"
          icon={<IconPulse />}
          sub={walletState.error ? '不可用' : `${walletState.data?.length ?? 0} 个采样点`}
        >
          {walletState.error ? (
            <EmptyState
              icon={<IconLineChartStroked />}
              title="暂无历史资金数据"
              hint="该接口在部分版本 / 模式下不可用，升级 freqtrade 后可用。"
            />
          ) : (
            <LineChart points={walletState.data ?? []} height={220} />
          )}
        </Panel>
      </div>

      {/* ---------------- distribution / per-trade / composition ---------------- */}
      <div className="ft-grid cols-3">
        <Panel title="收益分布" icon={<IconBarChartVStroked />} sub="按收益率分箱">
          <BarChart bars={distBars} height={200} signColored={false} />
        </Panel>

        <Panel title="逐笔收益" icon={<IconHistogram />} sub="按平仓时间">
          <BarChart bars={tradeBars} height={200} />
        </Panel>

        <Panel title="资金构成" icon={<IconPieChartStroked />} sub={stakeCurrency}>
          <DonutChart slices={donutSlices} />
        </Panel>
      </div>

      {/* ---------------- bot status + profit ---------------- */}
      <div className="ft-grid cols-2">
        <Panel title="Bot 状态" icon={<IconServer />} sub={config?.version}>
          {config ? (
            <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
              <KeyValueList>
                <ValuePair label="版本">
                  <span className="ft-num">{config.version}</span>
                </ValuePair>
                <ValuePair label="状态">
                  <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                    <StateTag state={config.state} />
                    <Tag variant="plain">{config.runmode}</Tag>
                  </span>
                </ValuePair>
                <ValuePair label="交易模式">
                  <span>
                    {config.trading_mode}
                    {config.trading_mode !== 'spot' && config.margin_mode
                      ? ` · ${config.margin_mode}`
                      : ''}
                    {config.demo_trading ? ' · Demo' : ''}
                  </span>
                </ValuePair>
                <ValuePair label="交易所">
                  <span>{config.exchange}</span>
                </ValuePair>
                <ValuePair label="策略">
                  <span>{config.strategy}</span>
                </ValuePair>
                <ValuePair label="周期">
                  <Tag variant="plain">{config.timeframe}</Tag>
                </ValuePair>
                <ValuePair label="仓位上限">
                  <span className="ft-num">
                    {config.max_open_trades} × {config.stake_amount} {config.stake_currency}
                  </span>
                </ValuePair>
                <ValuePair label="止损">
                  <span className="ft-num">{formatPercent(config.stoploss)}</span>
                </ValuePair>
                <ValuePair label="运行方式">
                  <DryRunTag dryRun={config.dry_run} />
                </ValuePair>
                <ValuePair label="启动时间">
                  <span className="ft-num">
                    {formatTimestamp(profit?.bot_start_timestamp, { seconds: false })}
                  </span>
                </ValuePair>
                <ValuePair label="平均持仓">
                  <span className="ft-num">{profit?.avg_duration ?? '—'}</span>
                </ValuePair>
                <ValuePair label="盈利因子">
                  <span className="ft-num">{formatNumber(profit?.profit_factor, 2)}</span>
                </ValuePair>
                <ValuePair label="交易额">
                  <span className="ft-num">
                    {formatPriceCurrency(profit?.trading_volume, stakeCurrency, stakeDecimals)}
                  </span>
                </ValuePair>
                <ValuePair label="止损单">
                  <span>
                    {config.stoploss_on_exchange ? '已挂交易所止损' : '未挂交易所止损'}
                    {config.trailing_stop ? ' · 追踪止损' : ''}
                  </span>
                </ValuePair>
              </KeyValueList>

              <div className="ft-subhead">策略参数</div>
              {strategyGroups.length === 0 ? (
                <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  {strategyState.error
                    ? '策略参数不可用（需要 webserver 模式）'
                    : '该策略没有参数'}
                </span>
              ) : (
                <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
                  {strategyGroups.map((group) => (
                    <div key={group.space}>
                      <div className="ft-rule">{group.space}</div>
                      <KeyValueList>
                        {group.params.map((param) => (
                          <ValuePair
                            key={param.name}
                            label={param.name}
                            title={param.param_type}
                          >
                            <span className="ft-num">{String(param.value ?? '—')}</span>
                          </ValuePair>
                        ))}
                      </KeyValueList>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <EmptyState icon={<IconServer />} title="暂无配置" />
          )}
        </Panel>

        <Panel
          title="收益"
          icon={<IconCoinMoney />}
          sub={stakeCurrency}
          actions={
            profitAllState.data?.short ? (
              <RadioGroup
                type="button"
                buttonSize="small"
                value={profitScope}
                onChange={(e) => setProfitScope(e.target.value as 'all' | 'long' | 'short')}
                options={[
                  { label: '全部', value: 'all' },
                  { label: '多', value: 'long' },
                  { label: '空', value: 'short' },
                ]}
              />
            ) : undefined
          }
          flush
          bodyClassName="ft-scroll-x ft-list-viewport"
        >
          {activeProfit ? (
            <Table<{ metric: string; value: ReactNode }>
              className="ft-table"
              columns={[
                { title: '指标', dataIndex: 'metric', width: 150 },
                { title: '数值', dataIndex: 'value' },
              ]}
              dataSource={profitItems}
              rowKey="metric"
              size="small"
              pagination={false}
            />
          ) : (
            <EmptyState icon={<IconCoinMoney />} title="暂无收益数据" />
          )}
        </Panel>
      </div>

      {/* ---------------- trades ---------------- */}
      <div className="ft-grid cols-2">
        <Panel
          title="持仓"
          icon={<IconActivity />}
          sub={`${openTrades.length} 笔`}
          flush
        >
          <TradeList
            trades={openTrades}
            activeTrades
            stakeCurrency={stakeCurrency}
            stakeCurrencyDecimals={stakeDecimals}
            tradingMode={config?.trading_mode}
            onSelectTrade={openDetail}
            emptyText="当前没有未平仓交易。"
          />
        </Panel>

        <Panel
          title="已平仓"
          icon={<IconHistory />}
          sub={`最近 ${closedTrades.length} 笔`}
          flush
        >
          <TradeList
            trades={closedTrades}
            loading={closedState.loading}
            showFilter
            stakeCurrency={stakeCurrency}
            stakeCurrencyDecimals={stakeDecimals}
            tradingMode={config?.trading_mode}
            onSelectTrade={openDetail}
            emptyText="暂无已平仓交易。"
          />
        </Panel>
      </div>

      {/* ---------------- performance ---------------- */}
      <Panel
        title="表现"
        icon={<IconTemplate />}
        sub={perfState.loading ? '加载中…' : `${perfRows.length} 行`}
        flush
        bodyClassName="ft-scroll-x ft-list-viewport"
        actions={
          <RadioGroup
            type="button"
            buttonSize="small"
            value={perfTab}
            onChange={(e) => setPerfTab(e.target.value as PerfTab)}
            options={PERF_OPTIONS}
          />
        }
      >
        {/* Two tables side by side. One full-width table would put a ~120px label
            at one end of a 1500px column and its numbers at the other; splitting
            the rows fills the width and halves the height. */}
        <div className="ft-perf-split">
          {[0, 1].map((half) => {
            const size = Math.ceil(perfRows.length / 2)
            const rows = half === 0 ? perfRows.slice(0, size) : perfRows.slice(size)
            // Keep the right table out of the DOM when there is nothing to put
            // in it, so a short list renders as a single full-width table.
            if (half === 1 && rows.length === 0) return null
            return (
              <div className="ft-scroll-x" key={half}>
                <Table<PerfRow>
                  className="ft-table"
                  columns={perfColumns}
                  dataSource={rows}
                  rowKey="key"
                  size="small"
                  pagination={false}
                  loading={perfState.loading && half === 0}
                  empty={<EmptyState icon={<IconTemplate />} title="暂无统计数据" />}
                />
              </div>
            )
          })}
        </div>
      </Panel>

      <div className="ft-row ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
        <span>
          未平仓合计{' '}
          <span className="ft-num">
            {formatCompact(openTrades.reduce((sum, trade) => sum + (trade.profit_abs ?? 0), 0), 2)}
          </span>{' '}
          {stakeCurrency}
        </span>
        <span style={{ marginLeft: 'auto' }}>
          数据来源：共享快照 + 页面级轮询（已平仓 30s / 收益 60s / 资金 120s）
        </span>
      </div>
    </div>
  )
}
