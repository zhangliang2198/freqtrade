/**
 * Client-side UI settings.
 *
 * Mirrors freqUI's `uiSettings` store: purely presentational preferences that
 * never touch the bot's own configuration, persisted to `localStorage`.
 *
 * The store is a module-level singleton observed through `useSyncExternalStore`
 * so it is *self-sufficient*: `useSettings()` keeps working (and keeps
 * persisting) even when `<SettingsProvider>` has not been mounted yet. The
 * provider exists to expose the same value through context, which keeps the
 * usual React data flow for consumers that read it in the tree.
 */

import {
  createContext,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react'

const STORAGE_KEY = 'ftui.settings'

/* -------------------------------------------------------------------------- */
/* Shape                                                                       */
/* -------------------------------------------------------------------------- */

export type OpenTradesInTitle = 'showPill' | 'asTitle' | 'noOpenTrades'
export type ChartLabelSide = 'left' | 'right'
export type TimeProfitPeriod = 'daily' | 'weekly' | 'monthly'
export type TimeProfitPreference = 'abs_profit' | 'rel_profit'

export interface NotificationSettings {
  entry_fill: boolean
  exit_fill: boolean
  entry_cancel: boolean
  exit_cancel: boolean
}

export interface Settings {
  /** How open trades are surfaced in the shell header. */
  openTradesInTitle: OpenTradesInTitle
  /** 'UTC' or 'local' — consumed by `formatTimestamp`. */
  timezone: string
  confirmDialog: boolean
  multiPaneButtonsShowText: boolean
  chartLabelSide: ChartLabelSide
  useHeikinAshiCandles: boolean
  useReducedPairCalls: boolean
  chartDefaultCandleCount: number
  showMarkArea: boolean
  multiPairSelection: boolean
  profitDistributionBins: number
  timeProfitPeriod: TimeProfitPeriod
  timeProfitPreference: TimeProfitPreference
  /** Extra columns shown per pair / per tag in backtest result tables. */
  backtestAdditionalMetrics: string[]
  notifications: NotificationSettings
}

export const DEFAULT_SETTINGS: Settings = {
  openTradesInTitle: 'showPill',
  timezone: 'UTC',
  confirmDialog: true,
  multiPaneButtonsShowText: false,
  chartLabelSide: 'right',
  useHeikinAshiCandles: false,
  useReducedPairCalls: true,
  chartDefaultCandleCount: 250,
  showMarkArea: true,
  multiPairSelection: false,
  profitDistributionBins: 20,
  timeProfitPeriod: 'daily',
  timeProfitPreference: 'abs_profit',
  backtestAdditionalMetrics: ['profit_factor', 'expectancy'],
  notifications: {
    entry_fill: true,
    exit_fill: true,
    entry_cancel: true,
    exit_cancel: true,
  },
}

/* -------------------------------------------------------------------------- */
/* Persistence                                                                 */
/* -------------------------------------------------------------------------- */

const OPEN_TRADES_VALUES: OpenTradesInTitle[] = ['showPill', 'asTitle', 'noOpenTrades']
const LABEL_SIDES: ChartLabelSide[] = ['left', 'right']
const TIME_PERIODS: TimeProfitPeriod[] = ['daily', 'weekly', 'monthly']
const TIME_PREFS: TimeProfitPreference[] = ['abs_profit', 'rel_profit']

function pick<T extends string>(value: unknown, allowed: T[], fallback: T): T {
  return typeof value === 'string' && (allowed as string[]).includes(value) ? (value as T) : fallback
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.min(max, Math.max(min, Math.round(n)))
}

function stringList(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) return [...fallback]
  return value.filter((v): v is string => typeof v === 'string')
}

/** Normalises a persisted (possibly stale or partial) blob onto the current shape. */
function normalize(raw: unknown): Settings {
  const input = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const notifications = (
    input.notifications && typeof input.notifications === 'object' ? input.notifications : {}
  ) as Record<string, unknown>

  return {
    openTradesInTitle: pick(
      input.openTradesInTitle,
      OPEN_TRADES_VALUES,
      DEFAULT_SETTINGS.openTradesInTitle,
    ),
    timezone:
      typeof input.timezone === 'string' && input.timezone
        ? input.timezone
        : DEFAULT_SETTINGS.timezone,
    confirmDialog: bool(input.confirmDialog, DEFAULT_SETTINGS.confirmDialog),
    multiPaneButtonsShowText: bool(
      input.multiPaneButtonsShowText,
      DEFAULT_SETTINGS.multiPaneButtonsShowText,
    ),
    chartLabelSide: pick(input.chartLabelSide, LABEL_SIDES, DEFAULT_SETTINGS.chartLabelSide),
    useHeikinAshiCandles: bool(
      input.useHeikinAshiCandles,
      DEFAULT_SETTINGS.useHeikinAshiCandles,
    ),
    useReducedPairCalls: bool(input.useReducedPairCalls, DEFAULT_SETTINGS.useReducedPairCalls),
    chartDefaultCandleCount: clampNumber(
      input.chartDefaultCandleCount,
      DEFAULT_SETTINGS.chartDefaultCandleCount,
      50,
      5000,
    ),
    showMarkArea: bool(input.showMarkArea, DEFAULT_SETTINGS.showMarkArea),
    multiPairSelection: bool(input.multiPairSelection, DEFAULT_SETTINGS.multiPairSelection),
    profitDistributionBins: clampNumber(
      input.profitDistributionBins,
      DEFAULT_SETTINGS.profitDistributionBins,
      5,
      100,
    ),
    timeProfitPeriod: pick(input.timeProfitPeriod, TIME_PERIODS, DEFAULT_SETTINGS.timeProfitPeriod),
    timeProfitPreference: pick(
      input.timeProfitPreference,
      TIME_PREFS,
      DEFAULT_SETTINGS.timeProfitPreference,
    ),
    backtestAdditionalMetrics: stringList(
      input.backtestAdditionalMetrics,
      DEFAULT_SETTINGS.backtestAdditionalMetrics,
    ),
    notifications: {
      entry_fill: bool(notifications.entry_fill, DEFAULT_SETTINGS.notifications.entry_fill),
      exit_fill: bool(notifications.exit_fill, DEFAULT_SETTINGS.notifications.exit_fill),
      entry_cancel: bool(notifications.entry_cancel, DEFAULT_SETTINGS.notifications.entry_cancel),
      exit_cancel: bool(notifications.exit_cancel, DEFAULT_SETTINGS.notifications.exit_cancel),
    },
  }
}

function readStored(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_SETTINGS }
    return normalize(JSON.parse(raw) as unknown)
  } catch {
    // Corrupt JSON or storage unavailable (private mode) — fall back to defaults.
    return { ...DEFAULT_SETTINGS }
  }
}

function writeStored(settings: Settings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    /* quota / private-mode failures are non-fatal */
  }
}

/* -------------------------------------------------------------------------- */
/* Store                                                                       */
/* -------------------------------------------------------------------------- */

let current: Settings = readStored()
const listeners = new Set<() => void>()

function emit(): void {
  for (const listener of listeners) listener()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function getSnapshot(): Settings {
  return current
}

function update(partial: Partial<Settings>): void {
  const merged: Settings = { ...current, ...partial }
  // `notifications` is the one nested object — merge it so a single switch
  // never resets its three siblings.
  if (partial.notifications) {
    merged.notifications = { ...current.notifications, ...partial.notifications }
  }
  current = normalize(merged)
  writeStored(current)
  emit()
}

function reset(): void {
  current = normalize({ ...DEFAULT_SETTINGS })
  writeStored(current)
  emit()
}

/* -------------------------------------------------------------------------- */
/* React binding                                                               */
/* -------------------------------------------------------------------------- */

export interface SettingsContextValue {
  settings: Settings
  /** Shallow-merges a patch; nested `notifications` is merged too. */
  update: (partial: Partial<Settings>) => void
  reset: () => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

export function SettingsProvider({ children }: { children: ReactNode }) {
  const settings = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  const value = useMemo<SettingsContextValue>(() => ({ settings, update, reset }), [settings])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

/**
 * Reads UI settings. Works both inside and outside `<SettingsProvider>`: when no
 * provider is mounted the hook binds straight to the module store, so a missing
 * provider degrades to "still functional" rather than throwing.
 */
export function useSettings(): SettingsContextValue {
  const fromContext = useContext(SettingsContext)
  const settings = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  const fallback = useMemo<SettingsContextValue>(
    () => ({ settings, update, reset }),
    [settings],
  )
  return fromContext ?? fallback
}
