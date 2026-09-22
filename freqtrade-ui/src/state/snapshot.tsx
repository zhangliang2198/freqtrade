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
  lastUpdated?: number
}

interface SnapshotContextValue extends BotSnapshot {
  loading: boolean
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

  // Reset immediately when the active bot changes so stale figures never leak.
  useEffect(() => {
    setSnapshot({ openTrades: [], locks: [], whitelist: [], pairlistMethods: [] })
    setLoading(true)
  }, [activeBotId])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  const fetchFast = useCallback(async () => {
    if (!api) return
    const [openTrades, locks, count] = await Promise.all([
      tradingApi.status(api).catch(() => [] as OpenTradeSchema[]),
      pairlistApi.locks(api).catch(() => ({ lock_count: 0, locks: [] }) as Locks),
      tradingApi.count(api).catch(() => undefined),
    ])
    setSnapshot((prev) => ({
      ...prev,
      openTrades: Array.isArray(openTrades) ? openTrades : [],
      locks: locks?.locks ?? [],
      count,
      lastUpdated: Date.now(),
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
      lastUpdated: Date.now(),
    }))

    setReachable(activeBotId ?? '', configR.status === 'fulfilled')
    setLoading(false)
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

  const value = useMemo<SnapshotContextValue>(
    () => ({ ...snapshot, loading, refresh, live: liveStatus === 'connected' }),
    [snapshot, loading, refresh, liveStatus],
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
