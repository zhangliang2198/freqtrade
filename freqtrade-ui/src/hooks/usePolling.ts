/**
 * Polling data hooks.
 *
 * A deliberately small stand-in for a query library: one hook for "fetch on
 * mount, then re-fetch on an interval, with manual refresh", and one for
 * "re-fetch whenever the live message stream says something changed".
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'

export interface AsyncState<T> {
  data: T | undefined
  error: Error | undefined
  loading: boolean
  /** True while a background re-fetch is in flight and stale data is shown. */
  refreshing: boolean
  refresh: () => void
}

interface PollingOptions {
  /** Milliseconds between polls. 0 or undefined disables polling. */
  intervalMs?: number
  enabled?: boolean
  /** Pause polling while the tab is hidden (default true). */
  pauseWhenHidden?: boolean
}

export function usePolling<T>(
  fetcher: ((signal: AbortSignal) => Promise<T>) | null,
  deps: unknown[],
  options: PollingOptions = {},
): AsyncState<T> {
  const { intervalMs = 0, enabled = true, pauseWhenHidden = true } = options

  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<Error | undefined>(undefined)
  const [loading, setLoading] = useState(enabled && fetcher !== null)
  const [refreshing, setRefreshing] = useState(false)
  const [nonce, setNonce] = useState(0)

  // Keep the latest fetcher without making it a dependency of the effect.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const hasData = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  const run = useCallback(async () => {
    const fn = fetcherRef.current
    if (!fn || !enabled) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    if (hasData.current) setRefreshing(true)
    else setLoading(true)

    try {
      const result = await fn(controller.signal)
      if (controller.signal.aborted) return
      setData(result)
      setError(undefined)
      hasData.current = true
    } catch (err) {
      if (controller.signal.aborted) return
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(err instanceof Error ? err : new Error(String(err)))
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [enabled])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  // `deps` are the fetch's identity. When they change, the payload on screen
  // belongs to a different query — another bot, another page — so it must not
  // linger. Without this a bot switch kept showing the previous bot's trades and
  // profit, and would keep showing them forever if the new request failed, while
  // the snapshot provider had already reset (so shell and page disagreed).
  // Comparing element identity means a manual refresh (nonce) does not clear,
  // which would otherwise flash on every poll.
  const prevDeps = useRef<unknown[] | null>(null)

  // Initial fetch + re-fetch whenever deps change.
  useEffect(() => {
    if (!enabled || !fetcherRef.current) {
      setLoading(false)
      return
    }
    const prev = prevDeps.current
    prevDeps.current = deps
    if (prev && (deps.length !== prev.length || deps.some((d, i) => !Object.is(d, prev[i])))) {
      setData(undefined)
      setError(undefined)
    }
    hasData.current = false
    void run()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce, run, ...deps])

  // Interval polling, suspended while the tab is hidden.
  useEffect(() => {
    if (!intervalMs || !enabled) return
    const id = window.setInterval(() => {
      if (pauseWhenHidden && document.hidden) return
      void run()
    }, intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs, enabled, pauseWhenHidden, run])

  return { data, error, loading, refreshing, refresh }
}

/**
 * Runs `onChange` whenever the supplied key changes. Used to fold WebSocket
 * pushes into pages that otherwise poll.
 */
export function useLiveRefresh(key: number, onChange: () => void, enabled = true): void {
  const first = useRef(true)
  const cb = useRef(onChange)
  cb.current = onChange

  useEffect(() => {
    if (!enabled) return
    if (first.current) {
      first.current = false
      return
    }
    cb.current()
  }, [key, enabled])
}

/** Human-readable message for an API failure, with mode-awareness. */
export function describeError(error: Error | undefined): string | undefined {
  if (!error) return undefined
  if (error instanceof ApiError) {
    if (error.isWrongState) return '此功能需要 webserver 模式运行'
    return error.detail
  }
  return error.message
}
