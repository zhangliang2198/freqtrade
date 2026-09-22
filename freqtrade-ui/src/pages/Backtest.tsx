/**
 * Backtesting page.
 *
 * Owns the in-memory result store, the run form, and the 1 s progress poll
 * against `GET /backtest`. Background-job tracking is not used here: freqtrade
 * reports backtest progress on the endpoint itself rather than through
 * `/background`.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Banner,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Progress,
  Switch,
  Table,
  TabPane,
  Tabs,
  Toast,
  Tooltip,
} from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import {
  IconBeaker,
  IconChevronLeft,
  IconChevronRight,
  IconDelete,
  IconPlay,
  IconRefresh,
  IconStop,
} from '@douyinfe/semi-icons'

import { EmptyState, Panel } from '../components/primitives'
import {
  FreqAIModelSelect,
  StrategySelect,
  TimeframeSelect,
  TimeRangeSelect,
} from '../components/selects'
import { BacktestHistoryLoad } from '../components/BacktestHistoryLoad'
import { BacktestResultAnalysis } from '../components/BacktestResultAnalysis'
import { BacktestResultChart } from '../components/BacktestResultChart'
import { BacktestResultSelect } from '../components/BacktestResultSelect'
import { backtestApi } from '../api/endpoints'
import { ApiError, type BotApi } from '../api/client'
import type { BacktestHistoryEntry, BacktestPayload, BacktestResponse } from '../api/types'
import { useBots } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import {
  generateBacktestMetricRows,
  type BacktestResultInMemory,
  type BacktestStrategyResult,
} from '../utils/backtestMetrics'
import { formatPercent } from '../utils/format'

/* -------------------------------------------------------------------------- */
/* Result unwrapping                                                           */
/* -------------------------------------------------------------------------- */

/** `BacktestPayload` predates caching/FreqAI; the backend accepts both. */
interface BacktestRunPayload extends BacktestPayload {
  backtest_cache?: string
  freqaimodel?: string
  freqai?: { identifier: string }
}

/**
 * The foundation's `BacktestResponse` omits `step`; the backend's
 * `BacktestResponse` schema includes it (e.g. "startup", "backtest").
 */
interface BacktestStatus extends BacktestResponse {
  step?: string
}

/**
 * Unwraps `/backtest`'s nested `backtest_result` into the page's in-memory
 * store, keyed by `run_id` (freqUI's fallback key otherwise).
 */
function unwrapResult(response: BacktestResponse): Record<string, BacktestResultInMemory> {
  const doc = response.backtest_result as
    | {
        strategy?: Record<string, BacktestStrategyResult>
        metadata?: Record<string, Record<string, unknown>>
      }
    | undefined
  if (!doc?.strategy) return {}

  const metadata = doc.metadata ?? {}
  const out: Record<string, BacktestResultInMemory> = {}

  for (const [name, strategy] of Object.entries(doc.strategy)) {
    const meta = metadata[name] ?? {}
    const runId = typeof meta.run_id === 'string' ? meta.run_id : undefined
    const totalTrades = typeof strategy.total_trades === 'number' ? strategy.total_trades : 0
    const profitTotal = typeof strategy.profit_total === 'number' ? strategy.profit_total : 0
    const key = runId ?? `${name}_${totalTrades}_${profitTotal.toFixed(3)}`

    out[key] = {
      strategy,
      metadata: {
        ...meta,
        run_id: runId,
        filename: typeof meta.filename === 'string' ? meta.filename : undefined,
        notes: typeof meta.notes === 'string' ? meta.notes : '',
        strategyName: name,
        editing: false,
      },
    }
  }
  return out
}

/* -------------------------------------------------------------------------- */
/* Result comparison                                                           */
/* -------------------------------------------------------------------------- */

interface ComparisonRow {
  __id: string
  __label: string
  [key: string]: string
}

/** Metric-by-metric comparison of every loaded result (freqUI's compare tab). */
function BacktestComparison({
  results,
}: {
  results: Record<string, BacktestResultInMemory>
}) {
  const { rows, columns } = useMemo(() => {
    const keys = Object.keys(results)
    const order: string[] = []
    const byLabel = new Map<string, Record<string, string>>()

    for (const key of keys) {
      for (const row of generateBacktestMetricRows(results[key].strategy)) {
        let entry = byLabel.get(row.label)
        if (!entry) {
          entry = {}
          byLabel.set(row.label, entry)
          order.push(row.label)
        }
        entry[key] = row.value
      }
    }

    const data: ComparisonRow[] = order.map((label, index) => ({
      __id: `row-${index}`,
      __label: label,
      ...(byLabel.get(label) ?? {}),
    }))

    const cols: ColumnProps<ComparisonRow>[] = [
      {
        key: '__label',
        title: 'Metric',
        width: 240,
        render: (_: unknown, row: ComparisonRow) => (
          <span className="ft-muted">{row.__label}</span>
        ),
      },
      ...keys.map((key) => ({
        key,
        title: results[key].metadata.strategyName,
        align: 'right' as const,
        render: (_: unknown, row: ComparisonRow) => (
          <span className="ft-num">{row[key] ?? ''}</span>
        ),
      })),
    ]

    return { rows: data, columns: cols }
  }, [results])

  return (
    <Panel
      title="回测结果对比"
      icon={<IconBeaker />}
      sub={`${Object.keys(results).length} 个结果`}
      flush
    >
      <Table<ComparisonRow>
        className="ft-table"
        columns={columns}
        dataSource={rows}
        rowKey="__id"
        size="small"
        pagination={false}
      />
    </Panel>
  )
}

/* -------------------------------------------------------------------------- */
/* Run form helpers                                                            */
/* -------------------------------------------------------------------------- */

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <>
      <span
        className="ft-row"
        style={{
          fontSize: 'var(--ft-font-sm)',
          color: 'var(--ft-ink-3)',
          justifyContent: 'flex-end',
          gap: 4,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
        {hint && (
          <Tooltip content={hint}>
            <span className="ft-faint" style={{ cursor: 'help' }}>
              ?
            </span>
          </Tooltip>
        )}
      </span>
      <div style={{ minWidth: 0 }}>{children}</div>
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

type BacktestTab = 'history' | 'run' | 'results' | 'compare' | 'visualize'

const POLL_MS = 1000

export function Backtest() {
  const { api } = useBots()
  const { config } = useSnapshot()

  /* ---------------------------------------------------------------- state */
  const [tab, setTab] = useState<BacktestTab>('run')
  const [showSidebar, setShowSidebar] = useState(true)
  const [results, setResults] = useState<Record<string, BacktestResultInMemory>>({})
  const [selectedKey, setSelectedKey] = useState('')
  const [wrongState, setWrongState] = useState(false)

  // Run form.
  const [strategy, setStrategy] = useState('')
  const [selectedTimeframe, setSelectedTimeframe] = useState('')
  const [detailTimeframe, setDetailTimeframe] = useState('')
  const [timerange, setTimerange] = useState('')
  const [maxOpenTrades, setMaxOpenTrades] = useState<number | null>(null)
  const [stakeAmount, setStakeAmount] = useState<number | null>(null)
  const [stakeUnlimited, setStakeUnlimited] = useState(false)
  const [startingCapital, setStartingCapital] = useState<number | null>(null)
  const [enableProtections, setEnableProtections] = useState(false)
  const [allowCache, setAllowCache] = useState(true)
  const [freqAIEnabled, setFreqAIEnabled] = useState(false)
  const [freqAIModel, setFreqAIModel] = useState('')
  const [freqAIIdentifier, setFreqAIIdentifier] = useState('')

  // Run progress.
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [step, setStep] = useState('')
  const [tradeCount, setTradeCount] = useState(0)

  const intervalRef = useRef<number | null>(null)

  const canRun = config?.runmode === 'webserver'
  const selected = results[selectedKey]
  const resultKeys = Object.keys(results)

  /* -------------------------------------------------------------- helpers */
  const stopPolling = useCallback(() => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  const applyStatus = useCallback((data: BacktestStatus) => {
    setRunning(Boolean(data.running))
    setProgress(data.progress ?? 0)
    setStep(data.step ?? '')
    setTradeCount(data.trade_count ?? 0)
  }, [])

  const handleError = useCallback((err: unknown, fallback: string) => {
    if (err instanceof ApiError && err.isWrongState) {
      setWrongState(true)
      return
    }
    Toast.error(err instanceof Error ? err.message : fallback)
  }, [])

  /** Stores every strategy in the response, selecting the last one. */
  const storeResult = useCallback((response: BacktestResponse) => {
    const next = unwrapResult(response)
    const keys = Object.keys(next)
    if (keys.length === 0) return false
    setResults((prev) => ({ ...prev, ...next }))
    setSelectedKey(keys[keys.length - 1])
    return true
  }, [])

  const pollOnce = useCallback(async () => {
    if (!api) return
    try {
      const data = await backtestApi.get(api)
      applyStatus(data)
      if (data.running === false) {
        stopPolling()
        if (data.status === 'error') {
          Toast.error(`回测失败：${data.status_msg ?? '未知错误'}`)
        } else if (data.backtest_result && storeResult(data)) {
          Toast.success('回测完成')
          setTab('results')
        }
      }
    } catch (err) {
      stopPolling()
      handleError(err, '回测状态读取失败')
    }
  }, [api, applyStatus, handleError, stopPolling, storeResult])

  const startPolling = useCallback(() => {
    if (intervalRef.current !== null) return
    intervalRef.current = window.setInterval(() => void pollOnce(), POLL_MS)
  }, [pollOnce])

  // Tear the loop down on unmount / bot switch.
  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling, api])

  /* -------------------------------------------------------------- actions */
  const buildPayload = useCallback((): BacktestRunPayload => {
    const payload: BacktestRunPayload = {
      strategy,
      timerange,
      enable_protections: enableProtections,
    }
    if (maxOpenTrades) payload.max_open_trades = maxOpenTrades
    if (stakeUnlimited) {
      payload.stake_amount = 'unlimited'
    } else {
      const value = Number(stakeAmount)
      if (value) payload.stake_amount = value.toString()
    }
    const capital = Number(startingCapital)
    if (capital) payload.dry_run_wallet = capital
    if (selectedTimeframe) payload.timeframe = selectedTimeframe
    if (detailTimeframe) payload.timeframe_detail = detailTimeframe
    if (!allowCache) payload.backtest_cache = 'none'
    if (freqAIEnabled) {
      payload.freqaimodel = freqAIModel
      if (freqAIIdentifier !== '') payload.freqai = { identifier: freqAIIdentifier }
    }
    return payload
  }, [
    strategy,
    timerange,
    enableProtections,
    maxOpenTrades,
    stakeUnlimited,
    stakeAmount,
    startingCapital,
    selectedTimeframe,
    detailTimeframe,
    allowCache,
    freqAIEnabled,
    freqAIModel,
    freqAIIdentifier,
  ])

  const startBacktest = async () => {
    if (!api || !canRun) return
    try {
      const data = await backtestApi.start(api, buildPayload())
      applyStatus(data)
      setRunning(true)
      startPolling()
      Toast.success('回测已启动')
    } catch (err) {
      handleError(err, '无法启动回测')
    }
  }

  const loadBacktest = async () => {
    if (!api || !canRun) return
    try {
      const data = await backtestApi.get(api)
      applyStatus(data)
      if (data.running) {
        startPolling()
      } else if (data.backtest_result && storeResult(data)) {
        Toast.success('已载入回测结果')
        setTab('results')
      } else {
        Toast.warning('没有可载入的回测结果')
      }
    } catch (err) {
      handleError(err, '无法载入回测结果')
    }
  }

  const stopBacktest = async () => {
    if (!api) return
    try {
      const data = await backtestApi.abort(api)
      applyStatus(data)
      stopPolling()
      Toast.warning('已请求停止回测')
    } catch (err) {
      handleError(err, '无法停止回测')
    }
  }

  const resetBacktest = async () => {
    if (!api) return
    try {
      const data = await backtestApi.reset(api)
      applyStatus(data)
      stopPolling()
      setResults({})
      setSelectedKey('')
      Toast.success('回测已重置')
    } catch (err) {
      handleError(err, '无法重置回测')
    }
  }

  const removeResult = (key: string) => {
    const next = { ...results }
    delete next[key]
    setResults(next)
    if (selectedKey === key) setSelectedKey(Object.keys(next)[0] ?? '')
  }

  const handleHistoryLoad = (_entry: BacktestHistoryEntry, response: BacktestResponse) => {
    storeResult(response)
  }

  const handleNotesSaved = (key: string, notes: string) => {
    setResults((prev) => {
      const entry = prev[key]
      if (!entry) return prev
      return { ...prev, [key]: { ...entry, metadata: { ...entry.metadata, notes } } }
    })
  }

  /* ----------------------------------------------------------------- view */
  const runningLabel = useMemo(() => {
    if (!running) return ''
    const percent = formatPercent(progress, 2)
    return `回测运行中：${step || '…'} ${percent}${tradeCount ? ` · ${tradeCount} 笔` : ''}`
  }, [running, step, progress, tradeCount])

  const renderRunForm = () => (
    <Panel
      title="回测参数"
      icon={<IconBeaker />}
      sub={canRun ? undefined : '需要 webserver 模式'}
      actions={
        <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
          <Button
            size="small"
            type="primary"
            icon={<IconPlay />}
            disabled={!canRun || !strategy || running}
            onClick={() => void startBacktest()}
          >
            开始回测
          </Button>
          <Button
            size="small"
            icon={<IconRefresh />}
            disabled={!canRun || running}
            onClick={() => void loadBacktest()}
          >
            载入结果
          </Button>
          <Button size="small" icon={<IconStop />} disabled={!running} onClick={() => void stopBacktest()}>
            停止
          </Button>
          <Button
            size="small"
            type="danger"
            icon={<IconDelete />}
            disabled={!canRun || running}
            onClick={() => void resetBacktest()}
          >
            重置
          </Button>
        </span>
      }
    >
      <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
        <div>
          <div style={{ fontSize: 'var(--ft-font-xs)', color: 'var(--ft-ink-4)', marginBottom: 4 }}>
            策略
          </div>
          <StrategySelect api={api} value={strategy} onChange={setStrategy} disabled={running} />
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'max-content minmax(0, 1fr)',
            gap: 'var(--ft-gap-4) var(--ft-gap-5)',
            alignItems: 'center',
            border: '1px solid var(--ft-line)',
            borderRadius: 'var(--ft-radius)',
            padding: 'var(--ft-gap-5)',
          }}
        >
          <Field label="时间周期">
            <TimeframeSelect
              value={selectedTimeframe}
              onChange={setSelectedTimeframe}
              disabled={running}
            />
          </Field>
          <Field label="明细周期" hint="用于模拟K线内价格变化的次级周期，不设置则不启用。">
            <TimeframeSelect
              value={detailTimeframe}
              onChange={setDetailTimeframe}
              belowTimeframe={selectedTimeframe}
              disabled={running}
            />
          </Field>
          <Field label="最大同时持仓">
            <InputNumber
              size="small"
              hideButtons
              min={1}
              value={maxOpenTrades ?? undefined}
              placeholder="使用策略默认值"
              disabled={running}
              onChange={(value) => setMaxOpenTrades(value === '' ? null : Number(value))}
              style={{ width: '100%' }}
            />
          </Field>
          <Field label="起始资金">
            <InputNumber
              size="small"
              hideButtons
              min={0}
              step={10}
              value={startingCapital ?? undefined}
              placeholder="使用配置默认值"
              disabled={running}
              onChange={(value) => setStartingCapital(value === '' ? null : Number(value))}
              style={{ width: '100%' }}
            />
          </Field>
          <Field label="质押金额">
            <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
              <InputNumber
                size="small"
                hideButtons
                min={0}
                step={10}
                value={stakeAmount ?? undefined}
                placeholder="使用策略默认值"
                disabled={running || stakeUnlimited}
                onChange={(value) => setStakeAmount(value === '' ? null : Number(value))}
                style={{ flex: '1 1 auto', minWidth: 0 }}
              />
              <Checkbox
                checked={stakeUnlimited}
                disabled={running}
                onChange={(e) => setStakeUnlimited(Boolean(e.target.checked))}
              >
                不限制
              </Checkbox>
            </div>
          </Field>
          <Field label="启用 Protections">
            <Switch
              size="small"
              checked={enableProtections}
              disabled={running}
              onChange={setEnableProtections}
            />
          </Field>
          <Field label="缓存回测结果">
            <Switch size="small" checked={allowCache} disabled={running} onChange={setAllowCache} />
          </Field>
          <Field label="FreqAI">
            <Switch
              size="small"
              checked={freqAIEnabled}
              disabled={running}
              onChange={setFreqAIEnabled}
            />
          </Field>
          {freqAIEnabled && (
            <>
              <Field label="FreqAI 模型">
                <FreqAIModelSelect
                  api={api}
                  value={freqAIModel}
                  onChange={setFreqAIModel}
                  disabled={running}
                />
              </Field>
              <Field label="Identifier">
                <Input
                  size="small"
                  value={freqAIIdentifier}
                  placeholder="使用配置默认值"
                  disabled={running}
                  onChange={setFreqAIIdentifier}
                />
              </Field>
            </>
          )}
        </div>

        <div>
          <div style={{ fontSize: 'var(--ft-font-xs)', color: 'var(--ft-ink-4)', marginBottom: 4 }}>
            回测区间
          </div>
          <TimeRangeSelect value={timerange} onChange={setTimerange} disabled={running} />
        </div>

        {running && (
          <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
            <Progress
              percent={Math.max(0, Math.min(100, progress * 100))}
              showInfo
              size="small"
              format={(p) => `${(p ?? 0).toFixed(2)}%`}
            />
            <span className="ft-mono-sm ft-muted">{runningLabel}</span>
          </div>
        )}
      </div>
    </Panel>
  )

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">回测</h1>
        <span className="ft-page-sub">
          {canRun ? 'webserver 模式' : '需要 webserver 模式'}
          {config?.strategy ? ` · 当前策略 ${config.strategy}` : ''}
        </span>
        {running && <span className="ft-mono-sm ft-muted">{runningLabel}</span>}
      </div>

      {(!config || config.runmode !== 'webserver') && (
        <Banner
          type="info"
          bordered
          title="回测需要机器人以 webserver 模式运行"
          description="当前机器人不在 webserver 模式下运行，回测、载入结果与重置均不可用。"
        />
      )}

      {wrongState && canRun && (
        <Banner
          type="warning"
          bordered
          title="回测接口暂不可用"
          description="机器人报告该接口不在正确的状态，请确认以 webserver 模式启动。"
        />
      )}

      <div className="ft-row" style={{ alignItems: 'stretch', gap: 'var(--ft-gap-5)' }}>
        {showSidebar && api && (
          <div style={{ flex: '0 0 288px', width: 288, minWidth: 0 }}>
            <BacktestResultSelect
              results={results}
              selectedKey={selectedKey}
              onSelect={setSelectedKey}
              onRemove={removeResult}
              onNotesSaved={handleNotesSaved}
            />
          </div>
        )}

        <div className="ft-col" style={{ flex: '1 1 auto', minWidth: 0, gap: 'var(--ft-gap-4)' }}>
          <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
            <Tooltip content={showSidebar ? '收起结果列表' : '展开结果列表'}>
              <Button
                size="small"
                theme="borderless"
                type="tertiary"
                icon={showSidebar ? <IconChevronLeft /> : <IconChevronRight />}
                onClick={() => setShowSidebar((v) => !v)}
              />
            </Tooltip>
            <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
              已加载 {resultKeys.length} 个结果
            </span>
          </div>

          <Tabs
            size="small"
            type="line"
            activeKey={tab}
            onChange={(key) => setTab(String(key) as BacktestTab)}
          >
            <TabPane tab="载入结果" itemKey="history">
              {api ? (
                <BacktestHistoryLoad
                  api={api}
                  onLoad={handleHistoryLoad}
                  loadedRunIds={resultKeys}
                  onUnload={removeResult}
                />
              ) : (
                <EmptyState title="未连接机器人" />
              )}
            </TabPane>

            <TabPane tab="运行回测" itemKey="run">
              {renderRunForm()}
            </TabPane>

            <TabPane tab="分析结果" itemKey="results" disabled={!selected}>
              {selected && api ? (
                <BacktestResultAnalysis
                  result={selected.strategy}
                  stakeCurrency={selected.strategy.stake_currency ?? config?.stake_currency ?? ''}
                  stakeCurrencyDecimals={
                    selected.strategy.stake_currency_decimals ??
                    config?.stake_currency_decimals ??
                    3
                  }
                />
              ) : (
                <EmptyState title="没有已加载的回测结果" hint="运行回测或从历史记录载入" />
              )}
            </TabPane>

            {resultKeys.length > 1 && (
              <TabPane tab="对比结果" itemKey="compare">
                <BacktestComparison results={results} />
              </TabPane>
            )}

            <TabPane tab="可视化" itemKey="visualize" disabled={!selected}>
              {selected && api ? (
                <BacktestResultChart
                  result={selected.strategy}
                  timeframe={selected.strategy.timeframe ?? selectedTimeframe}
                  strategy={selected.metadata.strategyName}
                  timerange={selected.strategy.timerange ?? timerange}
                  api={api as BotApi}
                />
              ) : (
                <EmptyState title="没有已加载的回测结果" hint="运行回测或从历史记录载入" />
              )}
            </TabPane>
          </Tabs>
        </div>
      </div>
    </div>
  )
}
