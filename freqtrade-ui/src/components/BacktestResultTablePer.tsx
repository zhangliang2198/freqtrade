/**
 * Per-pair / per-tag / per-exit-reason backtest result table.
 *
 * One row per group, with the group key (pair, enter tag, exit reason or the
 * `[enter tag, exit reason]` pair) followed by the standard trade metrics and
 * any additional metric columns the user selected.
 */

import { useMemo } from 'react'
import { Select, Table } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import { IconBeaker } from '@douyinfe/semi-icons'

import { Panel } from './primitives'
import {
  availableBacktestMetrics,
  type BacktestPairResultRow,
} from '../utils/backtestMetrics'
import { formatPercent, formatPrice, signClass } from '../utils/format'

export interface BacktestResultTablePerProps {
  title: string
  results: BacktestPairResultRow[]
  stakeCurrency: string
  stakeCurrencyDecimals: number
  /** Single group-key column header (pair, tag, exit reason, …). */
  keyHeader?: string
  /** Multiple group-key column headers — used by the mixed-tag table. */
  keyHeaders?: string[]
  /** Fields of `availableBacktestMetrics` currently shown. */
  extraMetrics: string[]
  onExtraMetricsChange: (metrics: string[]) => void
}

interface KeyField {
  label: string
  format: (row: BacktestPairResultRow) => string
}

interface TableRow extends BacktestPairResultRow {
  __keys: string[]
}

/** Semi's Select emits either a scalar or an array; normalise to string[]. */
function toMetricList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((v) => String(v))
  if (value === undefined || value === null || value === '') return []
  return [String(value)]
}

export function BacktestResultTablePer({
  title,
  results,
  stakeCurrency,
  stakeCurrencyDecimals,
  keyHeader,
  keyHeaders,
  extraMetrics,
  onExtraMetricsChange,
}: BacktestResultTablePerProps) {
  const keyFields = useMemo<KeyField[]>(() => {
    const headers = keyHeaders ?? []
    if (headers.length > 0) {
      return headers.map((header, i) => ({
        label: header,
        format: (row) => {
          const value = row.key
          if (Array.isArray(value)) return value[i] ?? row.exit_reason ?? 'OTHER'
          return value || row.exit_reason || 'OTHER'
        },
      }))
    }
    return [
      {
        label: keyHeader ?? '',
        format: (row) => {
          const value = row.key
          if (Array.isArray(value)) return value[0] ?? row.exit_reason ?? 'OTHER'
          return value || row.exit_reason || 'OTHER'
        },
      },
    ]
  }, [keyHeaders, keyHeader])

  const tableItems = useMemo<TableRow[]>(
    () => results.map((row) => ({ ...row, __keys: keyFields.map((field) => field.format(row)) })),
    [results, keyFields],
  )

  const metrics = useMemo(
    () => availableBacktestMetrics.filter((metric) => extraMetrics.includes(metric.field)),
    [extraMetrics],
  )

  const metricOptions = useMemo(
    () => availableBacktestMetrics.map((metric) => ({ value: metric.field, label: metric.header })),
    [],
  )

  const columns = useMemo<ColumnProps<TableRow>[]>(() => {
    const cols: ColumnProps<TableRow>[] = keyFields.map((field, i) => ({
      key: `key_${i}`,
      title: field.label,
      render: (_: unknown, row: TableRow) => (
        <span className="ft-mono-sm" style={{ color: 'var(--ft-ink-0)' }}>
          {row.__keys[i]}
        </span>
      ),
    }))

    cols.push(
      {
        key: 'trades',
        title: 'Trades',
        align: 'right',
        width: 84,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num">{row.trades ?? '–'}</span>
        ),
      },
      {
        key: 'profit_mean',
        title: 'Avg Profit %',
        align: 'right',
        width: 110,
        render: (_: unknown, row: TableRow) => (
          <span className={`ft-num ${signClass(row.profit_mean)}`}>
            {formatPercent(row.profit_mean, 2)}
          </span>
        ),
      },
      {
        key: 'profit_total_abs',
        title: `Tot Profit ${stakeCurrency}`,
        align: 'right',
        width: 140,
        render: (_: unknown, row: TableRow) => (
          <span className={`ft-num ${signClass(row.profit_total_abs)}`}>
            {formatPrice(row.profit_total_abs, stakeCurrencyDecimals)}
          </span>
        ),
      },
      {
        key: 'profit_total',
        title: 'Tot Profit %',
        align: 'right',
        width: 120,
        render: (_: unknown, row: TableRow) => (
          <span className={`ft-num ${signClass(row.profit_total)}`}>
            {formatPercent(row.profit_total, 2)}
          </span>
        ),
      },
      {
        key: 'wins',
        title: 'Wins',
        align: 'right',
        width: 74,
        render: (_: unknown, row: TableRow) => <span className="ft-num ft-up">{row.wins ?? '–'}</span>,
      },
      {
        key: 'draws',
        title: 'Draws',
        align: 'right',
        width: 74,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num ft-muted">{row.draws ?? '–'}</span>
        ),
      },
      {
        key: 'losses',
        title: 'Losses',
        align: 'right',
        width: 74,
        render: (_: unknown, row: TableRow) => (
          <span className="ft-num ft-down">{row.losses ?? '–'}</span>
        ),
      },
    )

    for (const metric of metrics) {
      cols.push({
        key: metric.field,
        title: metric.header,
        align: 'right',
        width: 120,
        render: (_: unknown, row: TableRow) => {
          const value = row[metric.field]
          const text = metric.is_ratio
            ? formatPercent(value as number, 2)
            : formatPrice(value as number, 2)
          return <span className="ft-num">{text}</span>
        },
      })
    }

    return cols
  }, [keyFields, metrics, stakeCurrency, stakeCurrencyDecimals])

  return (
    <Panel
      title={title}
      icon={<IconBeaker />}
      sub={`${results.length} 组`}
      flush
      actions={
        <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            显示指标
          </span>
          <Select
            size="small"
            multiple
            maxTagCount={2}
            value={extraMetrics}
            optionList={metricOptions}
            placeholder="附加指标"
            onChange={(value) => onExtraMetricsChange(toMetricList(value))}
            style={{ minWidth: 200 }}
          />
        </span>
      }
    >
      <Table<TableRow>
        className="ft-table"
        columns={columns}
        dataSource={tableItems}
        rowKey={(row?: TableRow) => row?.__keys.join('|') || 'TOTAL'}
        size="small"
        pagination={false}
        empty="无数据"
      />
    </Panel>
  )
}
