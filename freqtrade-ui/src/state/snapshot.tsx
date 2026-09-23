/**
 * Global bot snapshot.
 *
 * One polling loop for the data the shell and most pages need, mirroring
 * freqUI's fast/slow refresh split:
 *
 *   fast (5 s)  — open trades, locks, trade count
 *   slow (60 s) — show_config, profit, balance, whitelist/blacklist, historic wallet
 *
 * WebSocket pushes bump a revision which triggers an immediate fast refresh, so
 * live events are reflected without waiting for the next tick.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { infoApi, pairlistApi, tradingApi } from '../api/endpoints'
import type {
  Balances,
  BlacklistResponse,
  Count,
  Locks,
  OpenTradeSchema,
  Profit,
  ShowConfig,
  WhitelistResponse,
} from '../api/types'
import { useBots } from './bots'
import { useLive } from './live'

export interface BotSnapshot {
  config?: ShowConfig
  openTrades: OpenTradeSchema[]
  count?: Count
  profit?: Profit
  balance?: Balances
  locks: Locks['locks']
  whitelist: string[]
  pairlistMethods: string[]
  blacklist?: BlacklistResponse
  /** Populated when the last refresh failed, so the shell can show it. */
  error?: string
  /**
   * Per-loop freshness. A single timestamp could not be honest: the fast loop
   * runs every 5s and the slow one every 60s, so one value either overstated the
   * age of balance/profit (60s data stamped 5s ago) or understated the rest.
   */
  fastUpdated?: number
  slowUpdated?: number
}

interface SnapshotContextValue extends BotSnapshot {
  loading: boolean
  /** True while a manual refresh is in flight. */
  refreshing: boolean
  refresh: () => void
  /** True while a websocket event is being reconciled. */
  live: boolean
}

const SnapshotContext = createContext<SnapshotContextValue | null>(null)

const FAST_MS = 5_000
const SLOW_MS = 60_000

export function SnapshotProvider({ children }: { children: ReactNode }) {
  const { api, activeBotId, setReachable } = useBots()
  const { ticks, status: liveStatus } = useLive()

  const [snapshot, setSnapshot] = useState<BotSnapshot>({ openTrades: [], locks: [], whitelist: [], pairlistMethods: [] })
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)
  // `loading` is only true on the first load and on a bot switch, so a manual
  // refresh previously gave no feedback anywhere.
  const [refreshing, setRefreshing] = useState(false)

  // Reset immediately when the active bot changes so stale figures never leak.
  useEffect(() => {
    setSnapshot({ openTrades: [], locks: [], whitelist: [], pairlistMethods: [] })
    setLoading(true)
  }, [activeBotId])

  const refresh = useCallback(() => {
    setRefreshing(true)
    setNonce((n) => n + 1)
  }, [])

  const fetchFast = useCallback(async () => {
    if (!api) return
    // Mirrors fetchSlow: a failure keeps the previous value instead of
    // substituting an empty one. `.catch(() => [])` here meant a single
    // transient error rendered as an empty portfolio in the topbar, the nav
    // badge and every open-trades table.
    const [statusR, locksR, countResult] = await Promise.allSettled([
      tradingApi.status(api),
      pairlistApi.locks(api),
      tradingApi.count(api),
    ])
    const anyOk =
      statusR.status === 'fulfilled' ||
      locksR.status === 'fulfilled' ||
      countResult.status === 'fulfilled'
    setSnapshot((prev) => ({
      ...prev,
      openTrades:
        statusR.status === 'fulfilled' && Array.isArray(statusR.value)
          ? statusR.value
          : prev.openTrades,
      locks:
        locksR.status === 'fulfilled' ? (locksR.value?.locks ?? prev.locks) : prev.locks,
      count: countResult.status === 'fulfilled' ? countResult.value : prev.count,
      // Only claim freshness when something actually refreshed.
      fastUpdated: anyOk ? Date.now() : prev.fastUpdated,
    }))
  }, [api])

  const fetchSlow = useCallback(async () => {
    if (!api) return
    const results = await Promise.allSettled([
      infoApi.showConfig(api),
      tradingApi.profit(api),
      tradingApi.balance(api),
      pairlistApi.whitelist(api),
      pairlistApi.blacklist(api),
    ])

    const [configR, profitR, balanceR, whitelistR, blacklistR] = results

    setSnapshot((prev) => ({
      ...prev,
      config: configR.status === 'fulfilled' ? configR.value : prev.config,
      profit: profitR.status === 'fulfilled' ? profitR.value : prev.profit,
      balance: balanceR.status === 'fulfilled' ? balanceR.value : prev.balance,
      whitelist:
        whitelistR.status === 'fulfilled'
          ? (whitelistR.value as WhitelistResponse).whitelist ?? []
          : prev.whitelist,
      pairlistMethods:
        whitelistR.status === 'fulfilled'
          ? (whitelistR.value as WhitelistResponse).method ?? []
          : prev.pairlistMethods,
      blacklist: blacklistR.status === 'fulfilled' ? blacklistR.value : prev.blacklist,
      error: configR.status === 'rejected' ? String(configR.reason?.message ?? configR.reason) : undefined,
      slowUpdated: Date.now(),
    }))

    setReachable(activeBotId ?? '', configR.status === 'fulfilled')
    setLoading(false)
    setRefreshing(false)
  }, [api, activeBotId, setReachable])

  // Slow loop: full refresh, and whenever the active bot changes.
  useEffect(() => {
    if (!api) {
      setLoading(false)
      return
    }
    let cancelled = false
    const run = () => {
      if (cancelled) return
      // Same guard the fast loop and usePolling already apply: a hidden tab has
      // no reason to keep pulling five endpoints every minute.
      if (document.hidden) return
      void fetchSlow()
    }
    run()
    const id = window.setInterval(run, SLOW_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [api, fetchSlow, nonce])

  // Fast loop.
  useEffect(() => {
    if (!api) return
    void fetchFast()
    const id = window.setInterval(() => {
      if (document.hidden) return
      void fetchFast()
    }, FAST_MS)
    return () => window.clearInterval(id)
  }, [api, fetchFast, nonce])

  // Reconcile on live trade events without waiting for the next poll.
  const tradeTick =
    (ticks.entry_fill ?? 0) +
    (ticks.exit_fill ?? 0) +
    (ticks.entry_cancel ?? 0) +
    (ticks.exit_cancel ?? 0) +
    (ticks.exit ?? 0) +
    (ticks.entry ?? 0)

  useEffect(() => {
    if (!api || tradeTick === 0) return
    const id = window.setTimeout(() => {
      void fetchFast()
      void tradingApi.profit(api).then((profit) => setSnapshot((p) => ({ ...p, profit }))).catch(() => undefined)
    }, 250)
    return () => window.clearTimeout(id)
  }, [tradeTick, api, fetchFast])

  // `whitelist` and `status` are the slow loop's payloads. They were subscribed
  // and counted but never read, so a pushed pairlist rotation or config change
  // waited for the next 60s poll to appear.
  const slowTick = (ticks.whitelist ?? 0) + (ticks.status ?? 0)

  useEffect(() => {
    if (!api || slowTick === 0) return
    const id = window.setTimeout(() => {
      void fetchSlow()
    }, 250)
    return () => window.clearTimeout(id)
  }, [slowTick, api, fetchSlow])

  const value = useMemo<SnapshotContextValue>(
    () => ({ ...snapshot, loading, refreshing, refresh, live: liveStatus === 'connected' }),
    [snapshot, loading, refreshing, refresh, liveStatus],
  )

  return <SnapshotContext.Provider value={value}>{children}</SnapshotContext.Provider>
}

export function useSnapshot(): SnapshotContextValue {
  const ctx = useContext(SnapshotContext)
  if (!ctx) throw new Error('useSnapshot must be used inside <SnapshotProvider>')
  return ctx
}

/** Convenience: the open-trade count for nav badges and titles. */
export function useOpenTradeCount(): number {
  return useSnapshot().openTrades.length
}
