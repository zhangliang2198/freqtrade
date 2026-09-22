/**
 * Live message stream.
 *
 * freqtrade pushes trade/whitelist/candle events over
 * `ws(s)://<host>/api/v1/message/ws?token=<jwt>`. The socket is authenticated
 * by the JWT query parameter, so it must be rebuilt whenever the active bot or
 * its session changes.
 *
 * The provider keeps the socket alive with exponential backoff, exposes a
 * connection status for the topbar, and publishes a per-topic "tick" counter
 * that pages watch to trigger a cheap re-fetch instead of polling.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import type { WsEnvelope, WsMessageType } from '../api/types'
import { useBots } from './bots'

/** Topics the console subscribes to by default. */
const DEFAULT_TOPICS: WsMessageType[] = [
  'status',
  'entry',
  'entry_fill',
  'entry_cancel',
  'exit',
  'exit_fill',
  'exit_cancel',
  'whitelist',
  'new_candle',
  'warning',
  'exception',
  'protection_trigger',
  'protection_trigger_global',
  'liquidation_warning',
]

export type LiveStatus = 'connecting' | 'connected' | 'disconnected' | 'idle'

export interface LiveEvent {
  id: number
  type: WsMessageType
  data: unknown
  receivedAt: number
}

interface LiveContextValue {
  status: LiveStatus
  /** Monotonic counter bumped on every inbound message. */
  revision: number
  /** Per-topic counters, so a page can react to just its own topics. */
  ticks: Partial<Record<WsMessageType, number>>
  /** Most recent events, newest first (bounded ring). */
  events: LiveEvent[]
  send: (payload: unknown) => boolean
  reconnect: () => void
}

const LiveContext = createContext<LiveContextValue | null>(null)

const MAX_EVENTS = 60

export function LiveProvider({ children }: { children: ReactNode }) {
  const { api, activeBotId } = useBots()

  const [status, setStatus] = useState<LiveStatus>('idle')
  const [revision, setRevision] = useState(0)
  const [ticks, setTicks] = useState<Partial<Record<WsMessageType, number>>>({})
  const [events, setEvents] = useState<LiveEvent[]>([])

  const socketRef = useRef<WebSocket | null>(null)
  const retryRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const closedByUs = useRef(false)
  const eventId = useRef(0)
  const [manualNonce, setManualNonce] = useState(0)

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  const send = useCallback((payload: unknown): boolean => {
    const socket = socketRef.current
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload))
      return true
    }
    return false
  }, [])

  const reconnect = useCallback(() => {
    retryRef.current = 0
    setManualNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    if (!api || !activeBotId) {
      setStatus('idle')
      return
    }

    let disposed = false
    closedByUs.current = false

    const open = () => {
      if (disposed) return
      setStatus('connecting')

      let socket: WebSocket
      try {
        socket = new WebSocket(api.wsUrl())
      } catch {
        setStatus('disconnected')
        return
      }
      socketRef.current = socket

      socket.onopen = () => {
        if (disposed) return
        retryRef.current = 0
        setStatus('connected')
        socket.send(JSON.stringify({ type: 'subscribe', data: DEFAULT_TOPICS }))
      }

      socket.onmessage = (raw) => {
        if (disposed) return
        let envelope: WsEnvelope
        try {
          envelope = JSON.parse(raw.data as string) as WsEnvelope
        } catch {
          return
        }
        if (!envelope?.type) return

        setRevision((n) => n + 1)
        setTicks((prev) => ({ ...prev, [envelope.type]: (prev[envelope.type] ?? 0) + 1 }))

        // `analyzed_df` fires per pair per candle and would swamp the feed.
        if (envelope.type !== 'analyzed_df') {
          eventId.current += 1
          const entry: LiveEvent = {
            id: eventId.current,
            type: envelope.type,
            data: envelope.data,
            receivedAt: Date.now(),
          }
          setEvents((prev) => [entry, ...prev].slice(0, MAX_EVENTS))
        }
      }

      socket.onerror = () => {
        /* onclose always follows; handle reconnection there */
      }

      socket.onclose = () => {
        if (disposed || closedByUs.current) return
        setStatus('disconnected')
        // 1s, 2s, 4s … capped at 30s.
        const delay = Math.min(1000 * 2 ** retryRef.current, 30_000)
        retryRef.current += 1
        clearTimer()
        timerRef.current = window.setTimeout(open, delay)
      }
    }

    open()

    return () => {
      disposed = true
      closedByUs.current = true
      clearTimer()
      const socket = socketRef.current
      socketRef.current = null
      if (!socket) return

      if (socket.readyState === WebSocket.CONNECTING) {
        // Closing during the handshake makes the browser log a spurious
        // "WebSocket is closed before the connection is established" warning —
        // which React StrictMode triggers on every mount in development. Let
        // the handshake settle first, then close.
        socket.onopen = () => socket.close()
        socket.onmessage = null
      } else if (socket.readyState === WebSocket.OPEN) {
        socket.close()
      }
    }
  }, [api, activeBotId, manualNonce])

  const value = useMemo<LiveContextValue>(
    () => ({ status, revision, ticks, events, send, reconnect }),
    [status, revision, ticks, events, send, reconnect],
  )

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>
}

export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext)
  if (!ctx) throw new Error('useLive must be used inside <LiveProvider>')
  return ctx
}

/** Ticks for a specific set of topics — pages use this to trigger re-fetches. */
export function useTopicTick(topics: WsMessageType[]): number {
  const { ticks } = useLive()
  return useMemo(
    () => topics.reduce((sum, topic) => sum + (ticks[topic] ?? 0), 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ticks, topics.join(',')],
  )
}
