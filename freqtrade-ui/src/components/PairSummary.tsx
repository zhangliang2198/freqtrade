/**
 * Per-pair aggregate list.
 *
 * Merges the whitelist with open trades and active locks so a single row tells
 * you everything about a pair: whether a position is open, whether it is locked
 * (and until when / why), and how it is currently doing.
 */

import { useMemo, useState } from 'react'
import { Input, Select, Tooltip } from '@douyinfe/semi-ui'
import { IconLock, IconSearch } from '@douyinfe/semi-icons'

import type { PairLock, Trade } from '../api/types'
import { formatPriceCurrency, formatTimestamp } from '../utils/format'
import { ProfitPill, TradeProfit } from './ProfitPill'
import { EmptyState } from './primitives'

export type PairSortMethod = 'normal' | 'profit'

interface CombinedPair {
  pair: string
  trade?: Trade
  lock?: PairLock
  lockReason: string
  profitRatio: number
  profitAbs: number
  tradeCount: number
}

export interface PairSummaryProps {
  pairlist: string[]
  currentLocks?: PairLock[]
  trades: Trade[]
  selectedPair?: string
  onSelectPair?: (pair: string) => void
  stakeCurrency?: string
  stakeCurrencyDecimals?: number
  sortMethod?: PairSortMethod
  onSortMethodChange?: (method: PairSortMethod) => void
  startingBalance?: number
}

export function PairSummary({
  pairlist,
  currentLocks = [],
  trades,
  selectedPair,
  onSelectPair,
  stakeCurrency = 'USDT',
  stakeCurrencyDecimals = 3,
  sortMethod = 'normal',
  onSortMethodChange,
  startingBalance = 0,
}: PairSummaryProps) {
  const [filter, setFilter] = useState('')

  const combined = useMemo<CombinedPair[]>(() => {
    const rows: CombinedPair[] = []

    for (const pair of pairlist) {
      const pairTrades = trades.filter((t) => t.pair === pair)
      const locks = currentLocks
        .filter((l) => l.pair === pair)
        .slice()
        // Longest lock first.
        .sort((a, b) => b.lock_end_timestamp - a.lock_end_timestamp)

      const lock = locks[0]
      const lockReason = lock
        ? `${formatTimestamp(lock.lock_end_timestamp)} · ${lock.reason}`
        : ''

      let profitRatio = 0
      let profitAbs = 0
      for (const trade of pairTrades) {
        profitRatio += trade.profit_ratio ?? 0
        profitAbs += trade.profit_abs ?? 0
      }
      if (sortMethod === 'profit' && startingBalance > 0) {
        profitRatio = profitAbs / startingBalance
      }

      rows.push({
        pair,
        trade: pairTrades[0],
        lock,
        lockReason,
        profitRatio,
        profitAbs,
        tradeCount: pairTrades.length,
      })
    }

    if (sortMethod === 'profit') {
      return rows.sort((a, b) => b.profitRatio - a.profitRatio)
    }

    // Open trades first → available → locked (soonest unlock last).
    return rows.sort((a, b) => {
      if (a.trade && !b.trade) return -1
      if (!a.trade && b.trade) return 1
      if (a.trade && b.trade) return a.trade.trade_id - b.trade.trade_id
      if (!a.lock && b.lock) return -1
      if (a.lock && !b.lock) return 1
      if (a.lock && b.lock) return a.lock.lock_end_timestamp - b.lock.lock_end_timestamp
      return a.pair.localeCompare(b.pair)
    })
  }, [pairlist, trades, currentLocks, sortMethod, startingBalance])

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return combined
    return combined.filter((row) => row.pair.toLowerCase().includes(needle))
  }, [combined, filter])

  return (
    <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
      <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
        <Input
          size="small"
          prefix={<IconSearch />}
          placeholder="过滤交易对"
          value={filter}
          onChange={setFilter}
          showClear
          style={{ flex: '1 1 auto', minWidth: 0 }}
        />
        <Select
          size="small"
          value={sortMethod}
          onChange={(v) => onSortMethodChange?.(String(v) as PairSortMethod)}
          optionList={[
            { value: 'normal', label: '默认排序' },
            { value: 'profit', label: '按盈亏排序' },
          ]}
          style={{ width: 124 }}
        />
        <span className="ft-faint ft-num" style={{ fontSize: 'var(--ft-font-xs)' }}>
          {visible.length}/{combined.length}
        </span>
      </div>

      {visible.length === 0 ? (
        <EmptyState icon={<IconSearch />} title="没有匹配的交易对" hint="白名单为空或过滤条件过严。" />
      ) : (
        <div className="ft-pair-grid">
          {visible.map((row) => {
            const isSelected = row.pair === selectedPair
            return (
              <button
                key={row.pair}
                type="button"
                onClick={() => onSelectPair?.(row.pair)}
                title={`${formatPriceCurrency(
                  row.profitAbs,
                  stakeCurrency,
                  stakeCurrencyDecimals,
                )} · ${row.pair} · ${row.tradeCount} 笔交易`}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--ft-gap-4)',
                  width: '100%',
                  textAlign: 'left',
                  padding: '4px 8px',
                  border: 'none',
                  borderBottom: '1px solid var(--ft-line)',
                  borderRight: '1px solid var(--ft-line)',
                  background: isSelected ? 'var(--ft-paper-3)' : 'transparent',
                  color: 'inherit',
                  cursor: 'pointer',
                  fontSize: 'var(--ft-font-sm)',
                }}
              >
                <span
                  className="ft-nowrap"
                  style={{ fontWeight: isSelected ? 600 : 500, minWidth: 0 }}
                >
                  {row.pair}
                </span>
                {row.lock && (
                  <Tooltip content={`已锁定 · ${row.lockReason}`}>
                    <span style={{ color: 'var(--ft-warn)', display: 'inline-flex' }}>
                      <IconLock size="small" />
                    </span>
                  </Tooltip>
                )}
                {row.tradeCount > 0 && (
                  <span className="ft-faint ft-num" style={{ fontSize: 'var(--ft-font-xs)' }}>
                    ×{row.tradeCount}
                  </span>
                )}
                <span style={{ marginLeft: 'auto' }}>
                  {row.trade ? (
                    <TradeProfit trade={row.trade} />
                  ) : row.tradeCount > 0 ? (
                    <ProfitPill
                      profitRatio={row.profitRatio}
                      profitAbs={row.profitAbs}
                      stakeCurrency={stakeCurrency}
                    />
                  ) : (
                    <span className="ft-faint">–</span>
                  )}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
