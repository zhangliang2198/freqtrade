/**
 * Trading desk.
 *
 * Top: the bot control bar plus a multi-pane tabbed summary (pairs, status,
 * performance, balance, time breakdown, pairlist, locks).
 * Bottom: open/closed trade tables, the selected trade's detail and a candle
 * chart for the selected pair.
 *
 * In trade mode the bot only caches its own configured timeframe, so the chart
 * defaults to `config.timeframe` and degrades to an empty state for others.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  Banner,
  Button,
  Descriptions,
  Modal,
  RadioGroup,
  Table,
  Tabs,
  TabPane,
  Toast,
  Tooltip,
} from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import {
  IconActivity,
  IconApps,
  IconCandlestickChartStroked,
  IconClock,
  IconDelete,
  IconHistory,
  IconLineChartStroked,
  IconListView,
  IconLock,
  IconRefresh,
  IconTemplate,
  IconTick,
} from '@douyinfe/semi-icons'

import type {
  Daily,
  DailyWeeklyMonthly,
  EntryExitTag,
  PairLock,
  PerformanceEntry,
  Trade as TradeType,
} from '../api/types'
import { decodeCandles, pairlistApi, tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { useSettings } from '../state/settings'
import { useSnapshot } from '../state/snapshot'
import { describeError, usePolling } from '../hooks/usePolling'
import { CandleChart, DonutChart, LineChart, type LinePoint } from '../components/charts'
import { BotControls } from '../components/BotControls'
import { ForceEntryForm } from '../components/ForceEntryForm'
import { ForceExitForm } from '../components/ForceExitForm'
import { PairSummary, type PairSortMethod } from '../components/PairSummary'
import { TradeDetail } from '../components/TradeDetail'
import { TradeList } from '../components/TradeList'
import { TimeframeSelect } from '../components/selects'
import {
  DryRunTag,
  EmptyState,
  KeyValueList,
  Panel,
  StateTag,
  Tag,
  ValuePair,
} from '../components/primitives'
import {
  displayPair,
  formatNumber,
  formatPercent,
  formatPrice,
  formatPriceCurrency,
  formatTimestamp,
  parseTradeDate,
  signClass,
} from '../utils/format'
import { applyCandleStyle } from '../utils/candles'

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

type Period = 'daily' | 'weekly' | 'monthly'
type PerfTab = 'performance' | 'entries' | 'exits' | 'mixTags'

const PERF_OPTIONS = [
  { value: 'performance', label: '交易对' },
  { value: 'entries', label: '入场标签' },
  { value: 'exits', label: '出场原因' },
  { value: 'mixTags', label: '组合标签' },
]

const PERIOD_OPTIONS = [
  { value: 'daily', label: '日' },
  { value: 'weekly', label: '周' },
  { value: 'monthly', label: '月' },
]

/** Parses a `Daily.date` ("2026-09-21") or full timestamp into epoch seconds. */
function periodTime(date: string): number | null {
  if (!date) return null
  const ms = date.includes('T') || date.includes(' ')
    ? parseTradeDate(date)
    : Date.parse(`${date}T00:00:00Z`)
  if (ms === null || Number.isNaN(ms)) return null
  return Math.floor(ms / 1000)
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export function Trade() {
  const api = useApi()
  const location = useLocation()
  const {
    config,
    openTrades,
    profit,
    balance,
    locks,
    whitelist,
    pairlistMethods,
    blacklist,
    refresh,
  } = useSnapshot()
  const { settings, update } = useSettings()

  const navigationState = (location.state ?? null) as
    | { tradeId?: number; pair?: string }
    | null

  const [selectedPair, setSelectedPair] = useState(navigationState?.pair ?? '')
  const [selectedTradeState, setSelectedTrade] = useState<TradeType | null>(null)
  const [pairSort, setPairSort] = useState<PairSortMethod>('normal')
  const [perfTab, setPerfTab] = useState<PerfTab>('performance')
  // Reads and writes the persisted preference: keeping a page-local copy let the
  // settings page and this selector disagree about the same concept.
  const period = settings.timeProfitPeriod
  const setPeriod = useCallback(
    (next: Period) => update({ timeProfitPeriod: next }),
    [update],
  )
  const [chartTimeframe, setChartTimeframe] = useState('')
  const [exitTarget, setExitTarget] = useState<TradeType | null>(null)
  const [entryTarget, setEntryTarget] = useState<{ pair: string; increase: boolean } | null>(null)

  /** The detail panel sits below both tables; selecting a row has to reveal it. */
  const detailRef = useRef<HTMLDivElement | null>(null)

  const pendingTradeId = navigationState?.tradeId ?? null

  const stakeCurrency = config?.stake_currency ?? 'USDT'
  const stakeDecimals = config?.stake_currency_decimals ?? 3
  const tradingMode = config?.trading_mode ?? 'spot'

  /* ---- page-local data -------------------------------------------------- */

  const closedState = usePolling(
    (signal) => tradingApi.trades(api, { limit: 200 }, signal),
    [api],
    { intervalMs: 30_000 },
  )
  const closedTrades = useMemo(() => closedState.data?.trades ?? [], [closedState.data])

  const allTrades = useMemo(() => [...openTrades, ...closedTrades], [openTrades, closedTrades])

  /**
   * The dashboard hands a trade id over through router state. Resolving it
   * during render (instead of in an effect) avoids a cascading re-render and
   * makes the selection valid as soon as the trade shows up in either list.
   */
  const pendingTrade = useMemo(
    () =>
      pendingTradeId === null
        ? null
        : (allTrades.find((t) => t.trade_id === pendingTradeId) ?? null),
    [pendingTradeId, allTrades],
  )

  /**
   * The dashboard fetches 500 closed trades, this page only 200, so a click on a
   * row outside that window used to land here showing "未选择交易" with no
   * explanation. Fetch the exact trade when it is in neither list.
   */
  const pendingInList = useMemo(
    () => pendingTradeId !== null && pendingTrade !== null,
    [pendingTradeId, pendingTrade],
  )
  // Keyed by id so a result for a previous id can never be mistaken for the
  // current one — which removes the need to clear it synchronously in an effect.
  const [fetched, setFetched] = useState<{ id: number; trade: TradeType } | null>(null)
  useEffect(() => {
    if (pendingTradeId === null || pendingInList) return
    let cancelled = false
    tradingApi
      .trade(api, pendingTradeId)
      .then((trade) => {
        if (!cancelled && trade) setFetched({ id: pendingTradeId, trade })
      })
      .catch(() => {
        /* leave it unresolved; the detail panel shows its empty state */
      })
    return () => {
      cancelled = true
    }
  }, [api, pendingTradeId, pendingInList])
  const pendingResolved =
    pendingTrade ?? (fetched && fetched.id === pendingTradeId ? fetched.trade : null)

  /**
   * Re-resolve the selection against the current lists rather than holding the
   * object we were handed. A trade that has been deleted (or that a bot switch
   * moved out of the data set) must stop rendering in the detail panel; keeping
   * the stale object meant the panel described a trade that no longer existed.
   */
  const selectedTrade = useMemo(() => {
    if (!selectedTradeState) return pendingResolved
    return (
      allTrades.find((t) => t.trade_id === selectedTradeState.trade_id) ??
      (pendingResolved?.trade_id === selectedTradeState.trade_id ? pendingResolved : null)
    )
  }, [selectedTradeState, allTrades, pendingResolved])
  const effectivePair = selectedPair || selectedTrade?.pair || whitelist[0] || ''
  const effectiveTimeframe = chartTimeframe || config?.timeframe || ''

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

  const periodState = usePolling<DailyWeeklyMonthly>(
    (signal) => {
      if (period === 'weekly') return tradingApi.weekly(api, 8, signal)
      if (period === 'monthly') return tradingApi.monthly(api, 6, signal)
      return tradingApi.daily(api, 30, signal)
    },
    [api, period],
    { intervalMs: 120_000 },
  )

  const candleState = usePolling(
    effectivePair && effectiveTimeframe
      ? (signal) =>
          tradingApi.pairCandles(
            api,
            {
              pair: effectivePair,
              timeframe: effectiveTimeframe,
              // "默认显示K线数量" is a chart preference; this chart hard-coded
              // 300 while the chart page honoured the setting.
              limit: settings.chartDefaultCandleCount,
            },
            signal,
          )
      : null,
    [api, effectivePair, effectiveTimeframe, settings.chartDefaultCandleCount],
    { enabled: Boolean(effectivePair && effectiveTimeframe), intervalMs: 60_000 },
  )

  const candles = useMemo(
    () =>
      candleState.data
        ? applyCandleStyle(decodeCandles(candleState.data), settings.useHeikinAshiCandles)
        : [],
    [candleState.data, settings.useHeikinAshiCandles],
  )

  const pairTrades = useMemo(
    () => allTrades.filter((t) => t.pair === effectivePair),
    [allTrades, effectivePair],
  )

  /* ---- mutations -------------------------------------------------------- */

  const afterMutation = useCallback(() => {
    // Everything on this page derives from a trade: the tables, the performance
    // table, the period breakdown and the candles. Refreshing only the snapshot
    // and the closed list left the other three showing pre-mutation numbers for
    // up to 60–120s.
    refresh()
    closedState.refresh()
    perfState.refresh()
    periodState.refresh()
    candleState.refresh()
  }, [refresh, closedState, perfState, periodState, candleState])

  const confirmAction = useCallback(
    (
      title: string,
      content: string,
      action: () => Promise<unknown>,
      success: string,
      onDone?: () => void,
    ) => {
      const run = async () => {
        try {
          await action()
          Toast.success({ content: success, duration: 2 })
          onDone?.()
          afterMutation()
        } catch (err) {
          Toast.error({ content: describeError(err as Error) ?? String(err) })
        }
      }
      // Settings offers "平仓前显示确认对话框"; always confirming made that
      // switch inert. Turning it off runs the action straight away.
      if (!settings.confirmDialog) {
        void run()
        return
      }
      Modal.confirm({
        title,
        content,
        okText: '确认',
        cancelText: '取消',
        onOk: run,
      })
    },
    [afterMutation, settings.confirmDialog],
  )

  // Selecting a row updated the detail panel below the fold, so nothing
  // appeared to happen. Chart already scrolls to its panel; this matches it.
  const selectTrade = useCallback((trade: TradeType) => {
    setSelectedTrade(trade)
    setSelectedPair(trade.pair)
    detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  const handleForceExit = useCallback(
    (trade: TradeType, orderType?: string) => {
      confirmAction(
        '强制平仓',
        `确定强制平掉 #${trade.trade_id} ${displayPair(trade.pair)}${
          orderType ? `（${orderType}）` : ''
        } 吗？`,
        () =>
          tradingApi.forceExit(api, {
            tradeid: String(trade.trade_id),
            ...(orderType ? { ordertype: orderType } : {}),
          }),
        '平仓指令已发送',
      )
    },
    [api, confirmAction],
  )

  const handleCancelOpenOrder = useCallback(
    (trade: TradeType) => {
      confirmAction(
        '取消挂单',
        `取消 #${trade.trade_id} ${displayPair(trade.pair)} 的所有未成交挂单？`,
        () => tradingApi.cancelOpenOrder(api, trade.trade_id),
        '已取消挂单',
      )
    },
    [api, confirmAction],
  )

  const handleReloadTrade = useCallback(
    (trade: TradeType) => {
      confirmAction(
        '重新加载交易',
        `从交易所重新同步 #${trade.trade_id} ${displayPair(trade.pair)} 的状态？`,
        () => tradingApi.reloadTrade(api, trade.trade_id),
        '交易已重新加载',
      )
    },
    [api, confirmAction],
  )

  const handleDeleteTrade = useCallback(
    (trade: TradeType) => {
      confirmAction(
        '删除交易',
        `永久删除 #${trade.trade_id} ${displayPair(trade.pair)}？未平仓交易会被同时取消挂单。`,
        () => tradingApi.deleteTrade(api, trade.trade_id),
        '交易已删除',
        // Drop the selection deterministically instead of waiting for the
        // refetch to remove the row; if that refetch fails the stale entry
        // would otherwise keep the detail panel alive.
        () =>
          setSelectedTrade((prev) => (prev?.trade_id === trade.trade_id ? null : prev)),
      )
    },
    [api, confirmAction],
  )

  const handleRemoveLock = useCallback(
    (lock: PairLock) => {
      // Older freqtrade builds omit `id`, in which case locks cannot be deleted.
      const id = lock.id
      if (typeof id !== 'number') {
        Toast.warning({ content: '当前 freqtrade 版本不支持删除锁定。' })
        return
      }
      confirmAction(
        '解除锁定',
        `解除 ${displayPair(lock.pair)} 的锁定（原因：${lock.reason}）？`,
        () => pairlistApi.deleteLock(api, id),
        '锁定已解除',
      )
    },
    [api, confirmAction],
  )

  /* ---- tables ----------------------------------------------------------- */

  const perfRows = useMemo(() => {
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

  const perfColumns = useMemo<ColumnProps<(typeof perfRows)[number]>[]>(
    () => [
      {
        title:
          perfTab === 'performance'
            ? '交易对'
            : perfTab === 'entries'
              ? '入场标签'
              : perfTab === 'exits'
                ? '出场原因'
                : '组合标签',
        dataIndex: 'label',
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
    ],
    [perfTab, stakeCurrency, stakeDecimals],
  )

  const periodRows = useMemo(
    () =>
      (periodState.data?.data ?? [])
        .slice()
        .sort((a, b) => (a.date < b.date ? 1 : -1)),
    [periodState.data],
  )

  const periodPoints = useMemo<LinePoint[]>(() => {
    const points: LinePoint[] = []
    for (const row of (periodState.data?.data ?? []).slice().sort((a, b) =>
      a.date < b.date ? -1 : 1,
    )) {
      const time = periodTime(row.date)
      if (time === null) continue
      // "收益统计口径" chooses which of the two the chart plots.
      points.push({
        time,
        value: settings.timeProfitPreference === 'rel_profit' ? row.rel_profit : row.abs_profit,
      })
    }
    return points
  }, [periodState.data, settings.timeProfitPreference])

  const lockColumns = useMemo<ColumnProps<PairLock>[]>(
    () => [
      {
        title: '交易对',
        dataIndex: 'pair',
        render: (pair: string) => displayPair(pair),
      },
      {
        title: '解锁时间',
        dataIndex: 'lock_end_timestamp',
        width: 170,
        render: (ts: number) => <span className="ft-num">{formatTimestamp(ts)}</span>,
      },
      {
        title: '原因',
        dataIndex: 'reason',
        render: (reason: string) => <Tag variant="plain">{reason}</Tag>,
      },
      {
        title: '状态',
        dataIndex: 'active',
        width: 90,
        render: (active: boolean) =>
          active ? <Tag variant="warn">锁定中</Tag> : <Tag variant="plain">已过期</Tag>,
      },
      {
        title: '',
        dataIndex: 'actions',
        width: 56,
        align: 'center',
        render: (_: unknown, lock: PairLock) => (
          <Tooltip content="解除锁定">
            <Button
              size="small"
              theme="borderless"
              type="danger"
              icon={<IconDelete />}
              onClick={() => handleRemoveLock(lock)}
            />
          </Tooltip>
        ),
      },
    ],
    [handleRemoveLock],
  )

  const balanceSlices = useMemo(
    () =>
      (balance?.currencies ?? [])
        .filter((c) => c.est_stake > 0)
        .sort((a, b) => b.est_stake - a.est_stake)
        .map((c) => ({ label: c.currency, value: c.est_stake })),
    [balance],
  )

  const totalBalance = balance ? balance.total_bot || balance.total : undefined

  return (
    <div className="ft-page">
      <header className="ft-page-head">
        <h1 className="ft-page-title">交易</h1>
        <span className="ft-page-sub">
          {config?.exchange ?? '—'} · {config?.strategy ?? '—'} · {config?.timeframe ?? '—'}
        </span>
        <span className="ft-row" style={{ marginLeft: 'auto', gap: 'var(--ft-gap-4)' }}>
          {config && <StateTag state={config.state} />}
          {config && <DryRunTag dryRun={config.dry_run} />}
          <Tooltip content="刷新全部数据">
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconRefresh />}
              onClick={() => {
                refresh()
                closedState.refresh()
                perfState.refresh()
                periodState.refresh()
                candleState.refresh()
              }}
            />
          </Tooltip>
        </span>
      </header>

      {/* ---------------- control + multi pane ---------------- */}
      <Panel title="控制台" icon={<IconApps />} sub={config?.bot_name}>
        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
          <BotControls onChanged={afterMutation} />

          <Tabs type="line" size="small" defaultActiveKey="pairs">
            <TabPane itemKey="pairs" tab="交易对概览">
              <PairSummary
                pairlist={whitelist}
                currentLocks={locks}
                trades={openTrades}
                selectedPair={effectivePair}
                onSelectPair={setSelectedPair}
                stakeCurrency={stakeCurrency}
                stakeCurrencyDecimals={stakeDecimals}
                sortMethod={pairSort}
                onSortMethodChange={setPairSort}
                startingBalance={balance?.starting_capital}
              />
            </TabPane>

            <TabPane itemKey="general" tab="状态">
              {config ? (
                <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
                  <Descriptions
                    size="small"
                    column={2}
                    data={[
                      { key: '版本', value: config.version },
                      { key: '运行模式', value: config.runmode },
                      {
                        key: '状态',
                        value: (
                          <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                            <StateTag state={config.state} />
                            <DryRunTag dryRun={config.dry_run} />
                          </span>
                        ),
                      },
                      { key: '交易模式', value: config.trading_mode },
                      { key: '交易所', value: config.exchange },
                      { key: '策略', value: config.strategy },
                      { key: '周期', value: config.timeframe },
                      {
                        key: '仓位上限',
                        value: `${config.max_open_trades} × ${config.stake_amount} ${config.stake_currency}`,
                      },
                      { key: '止损', value: formatPercent(config.stoploss) },
                      {
                        key: '交易所止损单',
                        value: config.stoploss_on_exchange ? '已启用' : '未启用',
                      },
                      {
                        key: '追踪止损',
                        value: config.trailing_stop
                          ? `启用（${formatPercent(config.trailing_stop_positive)}）`
                          : '未启用',
                      },
                      { key: '允许做空', value: config.short_allowed ? '是' : '否' },
                      { key: '强制开仓', value: config.force_entry_enable ? '已启用' : '未启用' },
                      {
                        key: '启动时间',
                        value: formatTimestamp(profit?.bot_start_timestamp, { seconds: false }),
                      },
                      { key: '平均持仓', value: profit?.avg_duration ?? '—' },
                      {
                        key: '盈利因子',
                        value: formatNumber(profit?.profit_factor, 2),
                      },
                      {
                        key: '交易额',
                        value: formatPriceCurrency(
                          profit?.trading_volume,
                          stakeCurrency,
                          stakeDecimals,
                        ),
                      },
                      {
                        key: '机器人名称',
                        value: config.bot_name || '—',
                      },
                    ]}
                  />

                  <KeyValueList>
                    <ValuePair label="首次开仓">
                      <span className="ft-num">
                        {formatTimestamp(profit?.first_trade_timestamp)}（
                        {profit?.first_trade_humanized ?? '—'}）
                      </span>
                    </ValuePair>
                    <ValuePair label="最近开仓">
                      <span className="ft-num">
                        {formatTimestamp(profit?.latest_trade_timestamp)}（
                        {profit?.latest_trade_humanized ?? '—'}）
                      </span>
                    </ValuePair>
                    <ValuePair label="未平仓">
                      <span className="ft-num">
                        {openTrades.length} / {config.max_open_trades}
                      </span>
                    </ValuePair>
                    <ValuePair label="最佳交易对">
                      <span>
                        {profit?.best_pair
                          ? `${profit.best_pair} · ${formatPercent(profit.best_pair_profit_ratio)}`
                          : '—'}
                      </span>
                    </ValuePair>
                  </KeyValueList>
                </div>
              ) : (
                <EmptyState icon={<IconApps />} title="暂无配置" />
              )}
            </TabPane>

            <TabPane itemKey="performance" tab="表现">
              <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
                <RadioGroup
                  type="button"
                  buttonSize="small"
                  value={perfTab}
                  onChange={(e) => setPerfTab(e.target.value as PerfTab)}
                  options={PERF_OPTIONS}
                />
                <Table
                  className="ft-table"
                  columns={perfColumns}
                  dataSource={perfRows}
                  rowKey="key"
                  size="small"
                  pagination={false}
                  loading={perfState.loading}
                  empty={<EmptyState icon={<IconTemplate />} title="暂无统计数据" />}
                />
              </div>
            </TabPane>

            <TabPane itemKey="balance" tab="资金">
              <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
                <KeyValueList>
                  <ValuePair label="账户总价值">
                    <span className="ft-num">
                      {formatPriceCurrency(totalBalance, stakeCurrency, stakeDecimals)}
                    </span>
                  </ValuePair>
                  <ValuePair label="起始资金">
                    <span className="ft-num">
                      {formatPriceCurrency(
                        balance?.starting_capital,
                        stakeCurrency,
                        stakeDecimals,
                      )}{' '}
                      ({formatPercent(balance?.starting_capital_ratio)})
                    </span>
                  </ValuePair>
                  <ValuePair label="可用 / 占用">
                    <span className="ft-num">
                      {formatPriceCurrency(balance?.total, stakeCurrency, stakeDecimals)} ·{' '}
                      {formatPriceCurrency(balance?.value, stakeCurrency, stakeDecimals)}
                    </span>
                  </ValuePair>
                  <ValuePair label="备注">{balance?.note || '—'}</ValuePair>
                </KeyValueList>
                <DonutChart slices={balanceSlices} size={170} />
              </div>
            </TabPane>

            <TabPane itemKey="time-breakdown" tab="时段">
              <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
                <RadioGroup
                  type="button"
                  buttonSize="small"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value as Period)}
                  options={PERIOD_OPTIONS}
                />
                <LineChart points={periodPoints} height={200} />
                <Table<Daily>
                  className="ft-table"
                  columns={[
                    { title: '日期', dataIndex: 'date' },
                    {
                      title: `盈亏 ${stakeCurrency}`,
                      dataIndex: 'abs_profit',
                      align: 'right',
                      render: (value: number) => (
                        <span className={`ft-num ${signClass(value)}`}>
                          {formatPrice(value, stakeDecimals)}
                        </span>
                      ),
                    },
                    {
                      title: '收益率',
                      dataIndex: 'rel_profit',
                      align: 'right',
                      render: (value: number) => (
                        <span className={`ft-num ${signClass(value)}`}>
                          {formatPercent(value)}
                        </span>
                      ),
                    },
                    {
                      title: '折算',
                      dataIndex: 'fiat_value',
                      align: 'right',
                      render: (value: number) => <span className="ft-num">{formatPrice(value, 2)}</span>,
                    },
                    {
                      title: '笔数',
                      dataIndex: 'trade_count',
                      align: 'right',
                      width: 70,
                      render: (value: number) => <span className="ft-num">{value}</span>,
                    },
                  ]}
                  dataSource={periodRows}
                  rowKey="date"
                  size="small"
                  pagination={false}
                  loading={periodState.loading}
                  empty={<EmptyState icon={<IconClock />} title="暂无时段统计" />}
                />
              </div>
            </TabPane>

            <TabPane itemKey="pairlist" tab="交易对列表">
              <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
                <div>
                  <div className="ft-rule">
                    <IconListView /> 白名单（{whitelist.length}）
                  </div>
                  {whitelist.length === 0 ? (
                    <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                      白名单不可用，请确认机器人正在运行。
                    </span>
                  ) : (
                    <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
                      {whitelist.map((pair) => (
                        <button
                          key={pair}
                          type="button"
                          onClick={() => setSelectedPair(pair)}
                          style={{
                            border: '1px solid var(--ft-line-strong)',
                            borderRadius: 'var(--ft-radius-sm)',
                            background:
                              pair === effectivePair ? 'var(--ft-paper-3)' : 'transparent',
                            color: 'inherit',
                            padding: '1px 6px',
                            fontSize: 'var(--ft-font-xs)',
                            cursor: 'pointer',
                          }}
                        >
                          {displayPair(pair)}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  <div className="ft-rule">Pairlist 方法</div>
                  {pairlistMethods.length === 0 ? (
                    <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                      未上报 pairlist 方法。
                    </span>
                  ) : (
                    <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
                      {pairlistMethods.map((method, index) => (
                        <Tag key={`${method}-${index}`} variant="plain">
                          {method}
                        </Tag>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  <div className="ft-rule">黑名单（{blacklist?.blacklist?.length ?? 0}）</div>
                  {(blacklist?.blacklist?.length ?? 0) === 0 ? (
                    <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                      黑名单为空。
                    </span>
                  ) : (
                    <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
                      {(blacklist?.blacklist ?? []).map((pair) => (
                        <Tag key={pair} variant="plain" title={pair}>
                          {displayPair(pair)}
                        </Tag>
                      ))}
                    </div>
                  )}
                  {blacklist && Object.keys(blacklist.errors ?? {}).length > 0 && (
                    <Banner
                      type="warning"
                      description={Object.entries(blacklist.errors)
                        .map(([pair, err]) => `${pair}: ${err}`)
                        .join(' · ')}
                      closeIcon={null}
                      style={{ marginTop: 'var(--ft-gap-4)' }}
                    />
                  )}
                </div>
              </div>
            </TabPane>

            <TabPane itemKey="pair-locks" tab="锁">
              <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
                <div className="ft-row">
                  <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                    <IconLock /> 当前 {locks.length} 个锁定
                  </span>
                </div>
                <Table<PairLock>
                  className="ft-table"
                  columns={lockColumns}
                  dataSource={locks}
                  rowKey="id"
                  size="small"
                  pagination={false}
                  empty={<EmptyState icon={<IconLock />} title="当前没有交易对锁定" />}
                />
              </div>
            </TabPane>
          </Tabs>
        </div>
      </Panel>

      {/* ---------------- trade tables ---------------- */}
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
            tradingMode={tradingMode}
            forceEntryEnable={config?.force_entry_enable}
            selectedTradeId={selectedTrade?.trade_id ?? null}
            onSelectTrade={selectTrade}
            onForceExit={handleForceExit}
            onForceExitPartial={setExitTarget}
            onCancelOpenOrder={handleCancelOpenOrder}
            onReloadTrade={handleReloadTrade}
            onDeleteTrade={handleDeleteTrade}
            onIncreasePosition={(trade) =>
              setEntryTarget({ pair: trade.pair, increase: true })
            }
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
            tradingMode={tradingMode}
            selectedTradeId={selectedTrade?.trade_id ?? null}
            onSelectTrade={selectTrade}
            emptyText="暂无已平仓交易。"
          />
        </Panel>
      </div>

      {/* ---------------- detail + chart ---------------- */}
      <div className="ft-grid cols-2">
        <Panel
          title="交易详情"
          icon={<IconTemplate />}
          sub={selectedTrade ? `#${selectedTrade.trade_id}` : undefined}
          ref={detailRef}
        >
          {selectedTrade ? (
            <TradeDetail
              trade={selectedTrade}
              stakeCurrency={stakeCurrency}
              stakeCurrencyDecimals={stakeDecimals}
            />
          ) : (
            <EmptyState
              icon={<IconTemplate />}
              title="未选择交易"
              hint="点击上方任意一行查看详情。"
            />
          )}
        </Panel>

        <Panel
          title="K 线"
          icon={<IconCandlestickChartStroked />}
          sub={
            effectivePair
              ? `${displayPair(effectivePair)} · ${effectiveTimeframe}`
              : '未选择交易对'
          }
          actions={
            <TimeframeSelect
              value={effectiveTimeframe}
              onChange={setChartTimeframe}
              allowEmpty={false}
            />
          }
        >
          {candleState.error ? (
            <EmptyState
              icon={<IconLineChartStroked />}
              title="无法加载K线"
              hint={describeError(candleState.error) ?? '请确认交易对在白名单内。'}
            />
          ) : (
            <CandleChart priceScaleSide={settings.chartLabelSide} candles={candles} trades={pairTrades} height={360} />
          )}
        </Panel>
      </div>

      <div className="ft-row ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
        <span>
          当前交易对 <span className="ft-num">{effectivePair || '—'}</span> · 该交易对相关交易{' '}
          <span className="ft-num">{pairTrades.length}</span> 笔
        </span>
        <span style={{ marginLeft: 'auto' }}>
          <IconTick /> 交易模式下 K 线仅缓存机器人自身周期
        </span>
      </div>

      {/* ---------------- modals ---------------- */}
      <ForceExitForm
        visible={exitTarget !== null}
        trade={exitTarget}
        onClose={() => setExitTarget(null)}
        onSubmitted={afterMutation}
      />

      <ForceEntryForm
        visible={entryTarget !== null}
        pair={entryTarget?.pair ?? effectivePair}
        positionIncrease={entryTarget?.increase ?? false}
        onClose={() => setEntryTarget(null)}
        onSubmitted={afterMutation}
      />
    </div>
  )
}
