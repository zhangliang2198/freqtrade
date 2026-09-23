/**
 * Lookahead-bias analysis.
 *
 * Starts a background analysis job, waits for it to settle, then reads the
 * result and reports whether the strategy produced future-dependent signals.
 */

import { useState } from 'react'
import { Banner, Button, InputNumber, Switch, Table, Toast, Tooltip } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import { IconAlertTriangle, IconPlay, IconSearch } from '@douyinfe/semi-icons'

import { Panel, Tag } from '../components/primitives'
import { BackgroundJobTracking } from '../components/BackgroundJobTracking'
import { StrategySelect, TimeframeSelect, TimeRangeSelect } from '../components/selects'
import { analysisApi, type LookaheadResult } from '../api/endpoints'
import { ApiError } from '../api/client'
import { useBots } from '../state/bots'
import { useJobPolling } from '../hooks/useJobPolling'
import { formatPercent } from '../utils/format'

interface ResultRow {
  __id: string
  strategy: string
  has_bias: boolean
  total_signals: number
  biased_entry_signals: number
  biased_exit_signals: number
  biased_indicators: string[]
}

export function LookaheadAnalysis() {
  const { api } = useBots()
  const { jobs, track, clearFinished, waitFor } = useJobPolling(api, true)

  const [strategy, setStrategy] = useState('')
  const [timeframe, setTimeframe] = useState('')
  const [timerange, setTimerange] = useState('')
  const [minTradeAmount, setMinTradeAmount] = useState(10)
  const [targetedTradeAmount, setTargetedTradeAmount] = useState(20)
  const [allowLimitOrders, setAllowLimitOrders] = useState(false)

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<LookaheadResult | null>(null)
  const [wrongState, setWrongState] = useState(false)

  const startAnalysis = async () => {
    if (!api || !strategy) return
    setRunning(true)
    setResult(null)
    try {
      const job = await analysisApi.startLookahead(api, {
        strategy,
        minimum_trade_amount: minTradeAmount,
        targeted_trade_amount: targetedTradeAmount,
        lookahead_allow_limit_orders: allowLimitOrders,
        ...(timeframe ? { timeframe } : {}),
        ...(timerange ? { timerange } : {}),
      })
      track(job.job_id, 'lookahead_analysis')
      const status = await waitFor(job.job_id)
      // null means the job was dismissed from the tracking panel.
      if (!status) return
      if (status.status === 'failed') {
        Toast.error(status.error || '未来函数分析失败')
        return
      }
      const analysis = await analysisApi.lookaheadResult(api, job.job_id)
      if (analysis.status === 'ended' && analysis.result) {
        setResult(analysis.result)
      } else {
        Toast.error(analysis.status_msg || '未来函数分析失败')
      }
    } catch (err) {
      if (err instanceof ApiError && err.isWrongState) {
        setWrongState(true)
      } else {
        Toast.error(err instanceof Error ? err.message : '无法运行未来函数分析')
      }
    } finally {
      setRunning(false)
    }
  }

  const rows: ResultRow[] = result
    ? [
        {
          __id: 'result',
          strategy: result.strategy,
          has_bias: result.has_bias,
          total_signals: result.total_signals,
          biased_entry_signals: result.biased_entry_signals,
          biased_exit_signals: result.biased_exit_signals,
          biased_indicators: result.biased_indicators ?? [],
        },
      ]
    : []

  const columns: ColumnProps<ResultRow>[] = [
    {
      key: 'strategy',
      title: 'Strategy',
      render: (_: unknown, row: ResultRow) => <span className="ft-mono-sm">{row.strategy}</span>,
    },
    {
      key: 'has_bias',
      title: 'Has bias',
      width: 110,
      render: (_: unknown, row: ResultRow) => (
        <Tag variant={row.has_bias ? 'down' : 'up'}>{row.has_bias ? 'Yes' : 'No'}</Tag>
      ),
    },
    {
      key: 'total_signals',
      title: 'Total signals',
      align: 'right',
      width: 130,
      render: (_: unknown, row: ResultRow) => <span className="ft-num">{row.total_signals}</span>,
    },
    {
      key: 'biased_entry_signals',
      title: 'Biased entry signals',
      align: 'right',
      width: 160,
      render: (_: unknown, row: ResultRow) => (
        <span className={`ft-num ${row.biased_entry_signals ? 'ft-down' : ''}`}>
          {row.biased_entry_signals}
        </span>
      ),
    },
    {
      key: 'biased_exit_signals',
      title: 'Biased exit signals',
      align: 'right',
      width: 160,
      render: (_: unknown, row: ResultRow) => (
        <span className={`ft-num ${row.biased_exit_signals ? 'ft-down' : ''}`}>
          {row.biased_exit_signals}
        </span>
      ),
    },
    {
      key: 'biased_indicators',
      title: 'Biased indicators',
      render: (_: unknown, row: ResultRow) =>
        row.biased_indicators.length > 0 ? (
          <span className="ft-row wrap" style={{ gap: 4 }}>
            {row.biased_indicators.map((indicator) => (
              <Tag key={indicator} variant="warn">
                {indicator}
              </Tag>
            ))}
          </span>
        ) : (
          <span className="ft-faint">–</span>
        ),
    },
  ]

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">未来函数分析</h1>
        <span className="ft-page-sub">检测策略是否存在 lookahead bias</span>
      </div>

      {wrongState && (
        <Banner
          type="info"
          bordered
          title="需要 webserver 模式"
          description="未来函数分析需要机器人以 webserver 模式运行。"
        />
      )}

      <BackgroundJobTracking jobs={jobs} onClear={clearFinished} />

      <Panel
        title="分析参数"
        icon={<IconSearch />}
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
            title="Lookahead analysis"
            description="通过比较完整数据集与逐步缩短区间上生成的信号，检查策略是否存在未来函数。若指标或信号随未来数据变化，说明存在 lookahead bias，回测结果将不可靠。"
          />

          <div className="ft-formgrid">
            <span className="ft-row ft-formlabel">策略</span>
            <StrategySelect api={api} value={strategy} onChange={setStrategy} disabled={running} />

            <span className="ft-row ft-formlabel">时间周期</span>
            <TimeframeSelect value={timeframe} onChange={setTimeframe} disabled={running} />

            <span className="ft-row ft-formlabel">
              最小交易数
              <Tooltip content="分析在评估偏差前需要达到的最小交易数。">
                <span className="ft-faint" style={{ cursor: 'help' }}>
                  ?
                </span>
              </Tooltip>
            </span>
            <InputNumber
              size="small"
              hideButtons
              min={1}
              value={minTradeAmount}
              disabled={running}
              onChange={(value) => setMinTradeAmount(value === '' ? 1 : Number(value))}
            />

            <span className="ft-row ft-formlabel">
              目标交易数
              <Tooltip content="分析尝试达到的目标交易数，需大于等于最小交易数。">
                <span className="ft-faint" style={{ cursor: 'help' }}>
                  ?
                </span>
              </Tooltip>
            </span>
            <InputNumber
              size="small"
              hideButtons
              min={1}
              value={targetedTradeAmount}
              disabled={running}
              onChange={(value) => setTargetedTradeAmount(value === '' ? 1 : Number(value))}
            />

            <span className="ft-row ft-formlabel">
              允许限价单
              <Tooltip content="在分析中允许限价单（可能导致误报）。">
                <span className="ft-faint" style={{ cursor: 'help' }}>
                  ?
                </span>
              </Tooltip>
            </span>
            <span className="ft-row">
              <Switch
                size="small"
                checked={allowLimitOrders}
                disabled={running}
                onChange={setAllowLimitOrders}
              />
            </span>

            <span className="ft-row ft-formlabel">分析区间</span>
            <TimeRangeSelect value={timerange} onChange={setTimerange} disabled={running} />
          </div>
        </div>
      </Panel>

      {result && (
        <Panel title="分析结果" icon={<IconAlertTriangle />} flush>
          <div className="ft-col" style={{ gap: 'var(--ft-gap-4)', padding: 'var(--ft-gap-5)' }}>
            {result.has_bias ? (
              <Banner
                type="danger"
                bordered
                icon={<IconAlertTriangle />}
                title="检测到未来函数"
                description="策略根据可用数据生成了不同的信号。该策略的回测结果很可能不可靠。"
              />
            ) : (
              <Banner
                type="success"
                bordered
                title="未检测到未来函数"
                description="策略在各分析区间内产生了一致的信号。"
              />
            )}

            <div className="ft-row" style={{ gap: 'var(--ft-gap-6)' }}>
              <span>
                <span className="ft-faint">信号总数 </span>
                <span className="ft-num">{result.total_signals}</span>
              </span>
              <span>
                <span className="ft-faint">有偏入场信号 </span>
                <span className="ft-num">{result.biased_entry_signals}</span>
              </span>
              <span>
                <span className="ft-faint">有偏出场信号 </span>
                <span className="ft-num">{result.biased_exit_signals}</span>
              </span>
              <span>
                <span className="ft-faint">偏差比例 </span>
                <span className="ft-num">
                  {formatPercent(
                    result.total_signals
                      ? (result.biased_entry_signals + result.biased_exit_signals) /
                          result.total_signals
                      : 0,
                    2,
                  )}
                </span>
              </span>
            </div>
          </div>

          <Table<ResultRow>
            className="ft-table"
            columns={columns}
            dataSource={rows}
            rowKey="__id"
            size="small"
            pagination={false}
          />
        </Panel>
      )}
    </div>
  )
}
