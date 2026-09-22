/**
 * Periodic (day / week / month / year / weekday) backtest breakdown.
 *
 * The segmented control mirrors freqUI: it defaults to months and only offers
 * the extra periods the backend actually returned.
 */

import { useMemo, useState } from 'react'
import { RadioGroup, Table } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import { IconLoopTextStroked } from '@douyinfe/semi-icons'

import { Panel } from './primitives'
import type { BacktestPeriodicBreakdown, BacktestPeriodicStat } from '../utils/backtestMetrics'
import { formatNumber, formatPercent, formatPrice, signClass } from '../utils/format'

type PeriodKey = 'day' | 'week' | 'month' | 'year' | 'weekday'

interface PeriodOption {
  value: PeriodKey
  label: string
}

interface TableRow extends BacktestPeriodicStat {
  __id: string
}

export function BacktestResultPeriodBreakdown({
  periodicBreakdown,
}: {
  periodicBreakdown: BacktestPeriodicBreakdown
}) {
  const options = useMemo<PeriodOption[]>(() => {
    const list: PeriodOption[] = [
      { value: 'day', label: '日' },
      { value: 'week', label: '周' },
      { value: 'month', label: '月' },
    ]
    if (periodicBreakdown.year) list.push({ value: 'year', label: '年' })
    if (periodicBreakdown.weekday) list.push({ value: 'weekday', label: '星期' })
    return list
  }, [periodicBreakdown])

  const [period, setPeriod] = useState<PeriodKey>('month')

  const rows = useMemo<TableRow[]>(
    () =>
      (periodicBreakdown[period] ?? []).map((row, index) => ({
        ...row,
        __id: `${period}-${index}`,
      })),
    [periodicBreakdown, period],
  )

  const columns = useMemo<ColumnProps<TableRow>[]>(
    () => [
      {
        key: 'date',
        title: 'Date',
        render: (_: unknown, row: TableRow) => (
          <span className="ft-mono-sm" style={{ color: 'var(--ft-ink-0)' }}>
            {row.date ?? '–'}
          </span>
        ),
      },
      {
        key: 'trades',
        title: 'Trades',
        align: 'right',
        width: 84,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num">{row.trades ?? 'N/A'}</span>
        ),
      },
      {
        key: 'profit_abs',
        title: 'Total Profit',
        align: 'right',
        width: 130,
        render: (_: unknown, row: TableRow) => (
          <span className={`ft-num ${signClass(row.profit_abs)}`}>
            {formatNumber(row.profit_abs, 2)}
          </span>
        ),
      },
      {
        key: 'profit_factor',
        title: 'Profit Factor',
        align: 'right',
        width: 120,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num">{formatPrice(row.profit_factor ?? null, 2)}</span>
        ),
      },
      {
        key: 'wins',
        title: 'Wins',
        align: 'right',
        width: 74,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num ft-up">{row.wins ?? 'N/A'}</span>
        ),
      },
      {
        key: 'draws',
        title: 'Draws',
        align: 'right',
        width: 74,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num ft-muted">{row.draws ?? 'N/A'}</span>
        ),
      },
      {
        key: 'losses',
        title: 'Losses',
        align: 'right',
        width: 74,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num ft-down">{row.loses ?? row.losses ?? 'N/A'}</span>
        ),
      },
      {
        key: 'win_rate',
        title: 'Win Rate',
        align: 'right',
        width: 100,
        render: (_: unknown, row: TableRow) => {
          const losses = row.loses ?? row.losses ?? 0
          const total = (row.wins ?? 0) + (row.draws ?? 0) + losses
          return (
            <span className="ft-num">
              {formatPercent((row.wins ?? 0) / total, 2)}
            </span>
          )
        },
      },
    ],
    [],
  )

  return (
    <Panel
      title="周期分解"
      icon={<IconLoopTextStroked />}
      flush
      actions={
        <RadioGroup
          type="button"
          buttonSize="small"
          value={period}
          options={options.map((option) => ({ label: option.label, value: option.value }))}
          onChange={(e) => setPeriod(String(e.target.value) as PeriodKey)}
        />
      }
    >
      <Table<TableRow>
        className="ft-table"
        columns={columns}
        dataSource={rows}
        rowKey="__id"
        size="small"
        pagination={false}
        empty="无数据"
      />
    </Panel>
  )
}
