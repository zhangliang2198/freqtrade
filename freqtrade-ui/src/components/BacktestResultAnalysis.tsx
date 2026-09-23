/**
 * Full analysis view for one loaded backtest result.
 *
 * Composes the settings/metrics key-value panels, the per-group result tables
 * and the periodic breakdown around the single-trade list.
 */

import { useMemo, useState } from 'react'
import { Table } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import { IconBeaker, IconInfoCircle, IconLoopTextStroked } from '@douyinfe/semi-icons'

import { useSettings } from '../state/settings'
import { Panel } from './primitives'
import { BacktestResultPeriodBreakdown } from './BacktestResultPeriodBreakdown'
import { BacktestResultTablePer } from './BacktestResultTablePer'
import { TradeList } from './TradeList'
import {
  generateBacktestMetricRows,
  generateBacktestSettingRows,
  type BacktestMetricRow,
  type BacktestStrategyResult,
} from '../utils/backtestMetrics'
import type { Trade } from '../api/types'

interface KeyValueRow extends BacktestMetricRow {
  __id: string
}

const isSeparator = (value: string) => value === '___'

export interface BacktestResultAnalysisProps {
  result: BacktestStrategyResult
  stakeCurrency: string
  stakeCurrencyDecimals: number
}

export function BacktestResultAnalysis({
  result,
  stakeCurrency,
  stakeCurrencyDecimals,
}: BacktestResultAnalysisProps) {
  const { settings } = useSettings()
  // Shared across every per-group table, mirroring freqUI's settings store.
  // Seeded from the settings page, which offers this exact list; starting
  // from [] made that control inert.
  const [extraMetrics, setExtraMetrics] = useState<string[]>(settings.backtestAdditionalMetrics)

  const settingRows = useMemo<KeyValueRow[]>(
    () => generateBacktestSettingRows(result).map((row, i) => ({ ...row, __id: `s-${i}` })),
    [result],
  )

  const metricRows = useMemo<KeyValueRow[]>(
    () => generateBacktestMetricRows(result).map((row, i) => ({ ...row, __id: `m-${i}` })),
    [result],
  )

  const keyValueColumns = useMemo<ColumnProps<KeyValueRow>[]>(
    () => [
      {
        key: 'label',
        title: 'Setting',
        width: '48%',
        render: (_: unknown, row: KeyValueRow) => {
          if (isSeparator(row.value)) {
            return (
              <span className="ft-mono-sm ft-faint" style={{ letterSpacing: '0.08em' }}>
                {row.label}
              </span>
            )
          }
          if (row.label.startsWith('---')) {
            return (
              <span style={{ fontWeight: 600, color: 'var(--ft-ink-0)' }}>{row.label}</span>
            )
          }
          return <span className="ft-muted">{row.label}</span>
        },
      },
      {
        key: 'value',
        title: 'Value',
        render: (_: unknown, row: KeyValueRow) =>
          isSeparator(row.value) ? (
            <span className="ft-mono-sm ft-faint">{row.value}</span>
          ) : (
            <span className="ft-num">{row.value}</span>
          ),
      },
    ],
    [],
  )

  const metricColumns = useMemo<ColumnProps<KeyValueRow>[]>(
    () =>
      keyValueColumns.map((column) =>
        column.key === 'label' ? { ...column, title: 'Metric' } : column,
      ),
    [keyValueColumns],
  )

  const trades = (result.trades ?? []) as unknown as Trade[]
  const perPair = result.results_per_pair ?? []
  const perEnterTag = result.results_per_enter_tag ?? []
  const exitReasonSummary = result.exit_reason_summary ?? result.sell_reason_summary ?? []

  return (
    <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
      <div className="ft-page-head">
        <h2 className="ft-page-title">回测结果</h2>
        <span className="ft-page-sub ft-mono-sm">{result.strategy_name ?? ''}</span>
        <span className="ft-page-sub">
          {result.timeframe ?? ''}
          {result.timerange ? ` · ${result.timerange}` : ''}
        </span>
      </div>

      <div className="ft-grid cols-2">
        <Panel title="策略设置" icon={<IconInfoCircle />} flush>
          <Table<KeyValueRow>
            className="ft-table"
            columns={keyValueColumns}
            dataSource={settingRows}
            rowKey="__id"
            size="small"
            pagination={false}
          />
        </Panel>

        <Panel title="指标" icon={<IconBeaker />} flush>
          <Table<KeyValueRow>
            className="ft-table"
            columns={metricColumns}
            dataSource={metricRows}
            rowKey="__id"
            size="small"
            pagination={false}
          />
        </Panel>
      </div>

      <BacktestResultTablePer
        title="按入场标签"
        results={perEnterTag}
        stakeCurrency={stakeCurrency}
        stakeCurrencyDecimals={stakeCurrencyDecimals}
        keyHeader="Enter Tag"
        extraMetrics={extraMetrics}
        onExtraMetricsChange={setExtraMetrics}
      />

      <BacktestResultTablePer
        title="按出场原因"
        results={exitReasonSummary}
        stakeCurrency={stakeCurrency}
        stakeCurrencyDecimals={stakeCurrencyDecimals}
        keyHeader="Exit Reason"
        extraMetrics={extraMetrics}
        onExtraMetricsChange={setExtraMetrics}
      />

      {result.mix_tag_stats && (
        <BacktestResultTablePer
          title="按混合标签"
          results={result.mix_tag_stats ?? []}
          stakeCurrency={stakeCurrency}
          stakeCurrencyDecimals={stakeCurrencyDecimals}
          keyHeaders={['Enter Tag', 'Exit Tag']}
          extraMetrics={extraMetrics}
          onExtraMetricsChange={setExtraMetrics}
        />
      )}

      <BacktestResultTablePer
        title="按交易对"
        results={perPair}
        stakeCurrency={stakeCurrency}
        stakeCurrencyDecimals={stakeCurrencyDecimals}
        keyHeader="Pair"
        extraMetrics={extraMetrics}
        onExtraMetricsChange={setExtraMetrics}
      />

      {result.periodic_breakdown && (
        <BacktestResultPeriodBreakdown periodicBreakdown={result.periodic_breakdown} />
      )}

      <Panel title="单笔交易" icon={<IconLoopTextStroked />} sub={`${trades.length} 笔`} flush>
        <TradeList
          trades={trades}
          showFilter
          stakeCurrency={stakeCurrency}
          stakeCurrencyDecimals={stakeCurrencyDecimals}
          tradingMode={result.trading_mode ?? 'spot'}
        />
      </Panel>
    </div>
  )
}
