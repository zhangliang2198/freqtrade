/**
 * Recursive-formula analysis.
 *
 * Compares indicator values computed with different startup candle counts; a
 * non-zero difference means the indicator depends on how much history was
 * loaded and may behave differently between backtest and live runs.
 */

import { useMemo, useState } from 'react'
import { Banner, Button, Input, Table, Toast, Tooltip } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import { IconAlertTriangle, IconLoopTextStroked, IconPlay } from '@douyinfe/semi-icons'

import { Panel } from '../components/primitives'
import { BackgroundJobTracking } from '../components/BackgroundJobTracking'
import { StrategySelect, TimeframeSelect, TimeRangeSelect } from '../components/selects'
import { analysisApi, type RecursiveResult } from '../api/endpoints'
import { ApiError } from '../api/client'
import { useBots } from '../state/bots'
import { useJobPolling } from '../hooks/useJobPolling'
import { formatPercent } from '../utils/format'

interface RecursiveRow {
  __id: string
  indicator: string
  [candle: string]: string | number
}

/** `"199,399,499"` -> `[199, 399, 499]`, dropping blanks and non-positives. */
function parseStartupCandles(input: string): number[] {
  return input
    .split(',')
    .map((value) => Number(value.trim()))
    .filter((value) => Number.isFinite(value) && value > 0)
}

export function RecursiveAnalysis() {
  const { api } = useBots()
  const { jobs, track, clearFinished, waitFor } = useJobPolling(api, true)

  const [strategy, setStrategy] = useState('')
  const [timeframe, setTimeframe] = useState('')
  const [timerange, setTimerange] = useState('')
  const [startupCandleInput, setStartupCandleInput] = useState('199,399,499,999,1999')

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RecursiveResult | null>(null)
  const [wrongState, setWrongState] = useState(false)

  const startupCandles = useMemo(
    () => parseStartupCandles(startupCandleInput),
    [startupCandleInput],
  )

  const startAnalysis = async () => {
    if (!api || !strategy) return
    setRunning(true)
    setResult(null)
    try {
      const job = await analysisApi.startRecursive(api, {
        strategy,
        ...(timeframe ? { timeframe } : {}),
        ...(timerange ? { timerange } : {}),
        ...(startupCandles.length > 0 ? { startup_candle: startupCandles } : {}),
      })
      track(job.job_id, 'recursive_analysis')
      const status = await waitFor(job.job_id)
      // null means the job was dismissed from the tracking panel.
      if (!status) return
      if (status.status === 'failed') {
        Toast.error(status.error || '递归公式分析失败')
        return
      }
      const analysis = await analysisApi.recursiveResult(api, job.job_id)
      if (analysis.status === 'ended' && analysis.result) {
        setResult(analysis.result)
      } else {
        Toast.error(analysis.status_msg || '递归公式分析失败')
      }
    } catch (err) {
      if (err instanceof ApiError && err.isWrongState) {
        setWrongState(true)
      } else {
        Toast.error(err instanceof Error ? err.message : '无法运行递归公式分析')
      }
    } finally {
      setRunning(false)
    }
  }

  const indicators = useMemo(() => Object.keys(result?.results ?? {}), [result])

  const candleColumns = useMemo(() => result?.startup_candles ?? [], [result])

  const rows = useMemo<RecursiveRow[]>(
    () =>
      indicators.map((indicator, index) => ({
        __id: `ind-${index}`,
        indicator,
        ...(result?.results[indicator] ?? {}),
      })),
    [indicators, result],
  )

  const columns = useMemo<ColumnProps<RecursiveRow>[]>(() => {
    const cols: ColumnProps<RecursiveRow>[] = [
      {
        key: 'indicator',
        title: 'Indicator',
        width: 200,
        render: (_: unknown, row: RecursiveRow) => (
          <span className="ft-mono-sm" style={{ color: 'var(--ft-ink-0)' }}>
            {row.indicator}
          </span>
        ),
      },
    ]
    for (const candle of candleColumns) {
      cols.push({
        key: String(candle),
        title: String(candle),
        align: 'right',
        width: 110,
        render: (_: unknown, row: RecursiveRow) => {
          const value = row[String(candle)]
          return (
            <span className="ft-num">
              {formatPercent(typeof value === 'number' ? value : null, 3, '-')}
            </span>
          )
        },
      })
    }
    return cols
  }, [candleColumns])

  const hasIssues = indicators.length > 0

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">递归公式分析</h1>
        <span className="ft-page-sub">检测指标是否受启动K线数量影响</span>
      </div>

      {wrongState && (
        <Banner
          type="info"
          bordered
          title="需要 webserver 模式"
          description="递归公式分析需要机器人以 webserver 模式运行。"
        />
      )}

      <BackgroundJobTracking jobs={jobs} onClear={clearFinished} />

      <Panel
        title="分析参数"
        icon={<IconLoopTextStroked />}
        actions={
          <Button
            size="small"
            type="primary"
            icon={<IconPlay />}
            loading={running}
            disabled={!api || !strategy || running}
            onClick={() => void startAnalysis()}
          >
            开始分析
          </Button>
        }
      >
        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
          <Banner
            type="info"
            bordered
            title="Recursive analysis"
            description="通过比较不同启动K线数量下计算的指标值，检查策略指标是否存在递归公式问题。存在差异的指标很可能受启动数据量影响，从而在回测与实盘之间产生不一致的结果。"
          />

          <div className="ft-formgrid">
            <span className="ft-row ft-formlabel">策略</span>
            <StrategySelect api={api} value={strategy} onChange={setStrategy} disabled={running} />

            <span className="ft-row ft-formlabel">时间周期</span>
            <TimeframeSelect value={timeframe} onChange={setTimeframe} disabled={running} />

            <span className="ft-row ft-formlabel">
              启动K线数量
              <Tooltip content="以逗号分隔的启动K线数量列表，留空使用后端默认值。">
                <span className="ft-faint" style={{ cursor: 'help' }}>
                  ?
                </span>
              </Tooltip>
            </span>
            <div className="ft-col" style={{ gap: 'var(--ft-gap-2)' }}>
              <Input
                size="small"
                value={startupCandleInput}
                placeholder="例如 199,399,499,999,1999"
                disabled={running}
                onChange={setStartupCandleInput}
              />
              <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                解析为 {startupCandles.length} 个数值
              </span>
            </div>

            <span className="ft-row ft-formlabel">分析区间</span>
            <TimeRangeSelect value={timerange} onChange={setTimerange} disabled={running} />
          </div>
        </div>
      </Panel>

      {result && (
        <Panel title="分析结果" icon={<IconAlertTriangle />} flush>
          <div className="ft-col" style={{ gap: 'var(--ft-gap-4)', padding: 'var(--ft-gap-5)' }}>
            <div className="ft-row" style={{ gap: 'var(--ft-gap-6)', flexWrap: 'wrap' }}>
              <span>
                <span className="ft-faint">Strategy: </span>
                <span className="ft-mono-sm">{result.strategy}</span>
              </span>
              <span>
                <span className="ft-faint">Recommended startup candle count: </span>
                <span className="ft-num">{result.strategy_scc ?? 'N/A'}</span>
              </span>
              <span>
                <span className="ft-faint">受影响的指标数: </span>
                <span className="ft-num">{indicators.length}</span>
              </span>
            </div>

            {!hasIssues ? (
              <Banner
                type="success"
                bordered
                title="未检测到递归公式问题"
                description="在改变启动K线数量时，策略指标没有发生变化。"
              />
            ) : (
              <Banner
                type="warning"
                bordered
                icon={<IconAlertTriangle />}
                title={`${indicators.length} 个指标受启动K线数量影响`}
                description="下表数值为相对于启动K线最多时的百分比差异。非零值表示存在递归公式问题。"
              />
            )}
          </div>

          {hasIssues && (
            <div className="ft-scroll-x">
              <Table<RecursiveRow>
                className="ft-table"
                columns={columns}
                dataSource={rows}
                rowKey="__id"
                size="small"
                pagination={false}
              />
            </div>
          )}
        </Panel>
      )}
    </div>
  )
}
