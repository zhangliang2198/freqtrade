/**
 * Profit presentation.
 *
 * One rule across the whole app: a signed value is rendered as a triangle, a
 * percentage and an absolute amount, coloured green/red. Neutral values stay
 * greyscale so that "no data" never looks like a loss.
 */

import type { Trade } from '../api/types'
import { formatPercent, formatPriceCurrency, signOf } from '../utils/format'

export type ProfitMode = 'default' | 'total' | 'realized'

const MODE_LABEL: Record<ProfitMode, string> = {
  default: 'Current profit',
  total: 'Total profit',
  realized: 'Realized profit',
}

function Triangle({ sign }: { sign: 'up' | 'down' | 'flat' }) {
  if (sign === 'flat') {
    return <span style={{ color: 'var(--ft-ink-4)' }}>–</span>
  }
  const up = sign === 'up'
  return (
    <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
      <path
        d={up ? 'M5 1 L9 8 L1 8 Z' : 'M5 9 L1 2 L9 2 Z'}
        fill={up ? 'var(--ft-up)' : 'var(--ft-down)'}
      />
    </svg>
  )
}

export interface ProfitPillProps {
  profitRatio?: number | null
  profitAbs?: number | null
  stakeCurrency?: string | null
  /** Tooltip override. */
  title?: string
  /** Hide the absolute amount, leaving just the percentage. */
  percentOnly?: boolean
  decimals?: number
}

export function ProfitPill({
  profitRatio,
  profitAbs,
  stakeCurrency,
  title,
  percentOnly,
  decimals = 2,
}: ProfitPillProps) {
  const hasRatio = profitRatio !== undefined && profitRatio !== null
  const hasAbs = profitAbs !== undefined && profitAbs !== null

  if (!hasRatio && !hasAbs) {
    return <span className="ft-flat ft-num">–</span>
  }

  const sign = signOf(hasRatio ? profitRatio : profitAbs)
  const cls = sign === 'up' ? 'ft-up' : sign === 'down' ? 'ft-down' : 'ft-flat'

  return (
    <span
      className={`ft-num ${cls}`}
      title={title}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}
    >
      <Triangle sign={sign} />
      {hasRatio && <span>{formatPercent(profitRatio, decimals)}</span>}
      {!percentOnly && hasAbs && (
        <span className="ft-muted">
          ({stakeCurrency ? formatPriceCurrency(profitAbs, stakeCurrency, 3) : formatPriceCurrency(profitAbs, null, 3)})
        </span>
      )}
    </span>
  )
}

/** Reads the right ratio/abs pair off a trade for the requested mode. */
export function tradeProfitValues(
  trade: Trade,
  mode: ProfitMode,
): { ratio: number | null | undefined; abs: number | null | undefined } {
  if (mode === 'total') {
    const t = trade as Trade & { total_profit_ratio?: number; total_profit_abs?: number }
    return { ratio: t.total_profit_ratio ?? trade.profit_ratio, abs: t.total_profit_abs ?? trade.profit_abs }
  }
  if (mode === 'realized') {
    return { ratio: trade.realized_profit_ratio, abs: trade.realized_profit }
  }
  return { ratio: trade.profit_ratio, abs: trade.profit_abs }
}

export function TradeProfit({
  trade,
  mode = 'default',
  percentOnly,
}: {
  trade: Trade
  mode?: ProfitMode
  percentOnly?: boolean
}) {
  const { ratio, abs } = tradeProfitValues(trade, mode)
  return (
    <ProfitPill
      profitRatio={ratio}
      profitAbs={abs}
      stakeCurrency={trade.quote_currency || 'USDT'}
      percentOnly={percentOnly}
      title={`${MODE_LABEL[mode]}${ratio !== null && ratio !== undefined ? `: ${formatPercent(ratio)}` : ''}`}
    />
  )
}
