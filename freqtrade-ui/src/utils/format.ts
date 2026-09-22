/**
 * Number, time and pair formatting.
 *
 * Mirrors freqUI's formatter semantics so values read the same way, but with a
 * fixed locale so output is stable regardless of the browser's regional
 * settings (mixed separators in a trading table are worse than consistency).
 */

const LOCALE = 'en-US'

/** `undefined`/`null` guard used throughout the formatters. */
export function isSet(value: unknown): value is number {
  return value !== undefined && value !== null && value !== ('' as unknown)
}

/** Formats a ratio (0.1234) as a percentage string ("12.34%"). */
export function formatPercent(
  value: number | null | undefined,
  decimals = 2,
  fallback = 'N/A',
): string {
  if (!isSet(value) || !Number.isFinite(value)) return fallback
  return `${(value * 100).toLocaleString(LOCALE, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}%`
}

/** Formats a number without grouping, trimming to `decimals` places. */
export function formatNumber(value: number | null | undefined, decimals = 15): string {
  if (!isSet(value) || !Number.isFinite(value)) return 'N/A'
  return value.toLocaleString(LOCALE, {
    useGrouping: false,
    maximumFractionDigits: decimals,
  })
}

export const formatPrice = formatNumber

export function formatPriceCurrency(
  price: number | null | undefined,
  currency?: string | null,
  decimals = 3,
): string {
  const value = formatPrice(price, decimals)
  return currency ? `${value} ${currency}` : value
}

/** Adaptive precision: tiny prices keep more digits, large ones fewer. */
export function formatDecimal(value: number | null | undefined): string {
  if (!isSet(value) || !Number.isFinite(value)) return 'N/A'
  const abs = Math.abs(value)
  let decimals: number
  if (abs < 1e-7) decimals = 15
  else if (abs < 1e-6) decimals = 11
  else if (abs < 1e-4) decimals = 8
  else if (abs < 0.01) decimals = 5
  else if (abs < 1) decimals = 5
  else if (abs < 10) decimals = 4
  else if (abs < 100) decimals = 3
  else decimals = 2
  return formatNumber(value, decimals)
}

/** Compact form for stat tiles: 1.23K / 4.56M. */
export function formatCompact(value: number | null | undefined, decimals = 2): string {
  if (!isSet(value) || !Number.isFinite(value)) return 'N/A'
  const abs = Math.abs(value)
  if (abs >= 1e9) return `${(value / 1e9).toFixed(decimals)}B`
  if (abs >= 1e6) return `${(value / 1e6).toFixed(decimals)}M`
  if (abs >= 1e3) return `${(value / 1e3).toFixed(decimals)}K`
  return formatDecimal(value)
}

/* -------------------------------------------------------------------------- */
/* Time                                                                        */
/* -------------------------------------------------------------------------- */

/**
 * Formats an epoch-millisecond timestamp. `timezone` accepts an IANA name or
 * 'UTC'; 'local' uses the browser zone.
 */
export function formatTimestamp(
  ts: number | null | undefined,
  options: { timezone?: string; dateOnly?: boolean; seconds?: boolean; fallback?: string } = {},
): string {
  const { timezone = 'UTC', dateOnly = false, seconds = true, fallback = 'N/A' } = options
  if (!isSet(ts) || ts <= 0) return fallback

  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return fallback

  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone === 'local' ? undefined : timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(dateOnly
      ? {}
      : { hour: '2-digit', minute: '2-digit', ...(seconds ? { second: '2-digit' } : {}) }),
    hour12: false,
  }).formatToParts(date)

  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00'
  const day = `${get('year')}-${get('month')}-${get('day')}`
  if (dateOnly) return day
  return `${day} ${get('hour')}:${get('minute')}${seconds ? `:${get('second')}` : ''}`
}

/** Formats a freqtrade date string ("2026-09-21 04:02:17") as epoch ms. */
export function parseTradeDate(value: string | null | undefined): number | null {
  if (!value) return null
  // freqtrade emits UTC "YYYY-MM-DD HH:MM:SS"; make it ISO before parsing.
  const iso = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`
  const ms = Date.parse(iso)
  return Number.isNaN(ms) ? null : ms
}

/** Humanises a duration given in seconds. */
export function humanizeDuration(seconds: number | null | undefined): string {
  if (!isSet(seconds) || seconds < 0) return 'N/A'
  const s = Math.floor(seconds)
  const days = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  const parts: string[] = []
  if (days) parts.push(`${days}d`)
  if (hours) parts.push(`${hours}h`)
  if (minutes && !days) parts.push(`${minutes}m`)
  if (!parts.length) parts.push(`${s}s`)
  return parts.join(' ')
}

/** Relative "3m ago" style label for recent timestamps. */
export function timeAgo(ts: number | null | undefined): string {
  if (!isSet(ts) || ts <= 0) return 'N/A'
  const diff = Date.now() - ts
  if (diff < 0) return 'just now'
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/* -------------------------------------------------------------------------- */
/* Pairs                                                                       */
/* -------------------------------------------------------------------------- */

export interface SplitPair {
  base: string
  quote: string
  /** The pair without its settle suffix, e.g. "BTC/USDT". */
  short: string
}

/** Splits "BTC/USDT:USDT" into its parts, tolerating spot and odd symbols. */
export function splitPair(pair: string | null | undefined): SplitPair {
  if (!pair) return { base: '', quote: '', short: '' }
  const short = pair.split(':')[0]
  const [base, quote] = short.split('/')
  if (!quote) return { base: short, quote: '', short }
  return { base, quote, short }
}

/** Compact display form: "BTC/USDT:USDT" -> "BTC/USDT". */
export function displayPair(pair: string | null | undefined): string {
  return splitPair(pair).short || (pair ?? '')
}

/* -------------------------------------------------------------------------- */
/* Sign helpers — drive the profit/loss colouring everywhere                    */
/* -------------------------------------------------------------------------- */

export type Sign = 'up' | 'down' | 'flat'

export function signOf(value: number | null | undefined): Sign {
  if (!isSet(value) || !Number.isFinite(value) || value === 0) return 'flat'
  return value > 0 ? 'up' : 'down'
}

export function signClass(value: number | null | undefined): string {
  const sign = signOf(value)
  if (sign === 'up') return 'ft-up'
  if (sign === 'down') return 'ft-down'
  return 'ft-flat'
}
