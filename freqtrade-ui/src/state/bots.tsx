/**
 * Bot connection registry.
 *
 * Holds every configured bot, the active one, and a stable `BotApi` per bot.
 * Connections persist in localStorage; JWTs live under their own keys so a bot
 * can be forgotten without disturbing the others.
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

import { BotApi, normalizeBaseUrl, type BotConnection } from '../api/client'

const BOTS_KEY = 'ftui.bots'
const ACTIVE_KEY = 'ftui.activeBot'

export interface StoredBot extends BotConnection {
  /** Last known reachable state, refreshed opportunistically. */
  reachable?: boolean
}

interface BotContextValue {
  bots: StoredBot[]
  activeBotId: string | null
  activeBot: StoredBot | null
  api: BotApi | null
  /** Creates and logs in a connection. Throws AuthError on bad credentials. */
  connect: (input: {
    name: string
    baseUrl: string
    username: string
    password: string
  }) => Promise<void>
  disconnect: (id: string) => void
  setActiveBotId: (id: string) => void
  setReachable: (id: string, reachable: boolean) => void
}

const BotContext = createContext<BotContextValue | null>(null)

function readBots(): StoredBot[] {
  try {
    const raw = localStorage.getItem(BOTS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as StoredBot[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function writeBots(bots: StoredBot[]): void {
  try {
    localStorage.setItem(BOTS_KEY, JSON.stringify(bots))
  } catch {
    /* ignore quota / private-mode failures */
  }
}

/** Stable, collision-resistant id for a new connection. */
function makeBotId(baseUrl: string, username: string): string {
  return `${normalizeBaseUrl(baseUrl)}|${username}`
}

export function BotProvider({ children }: { children: ReactNode }) {
  const [bots, setBots] = useState<StoredBot[]>(() => readBots())
  const [activeBotId, setActiveId] = useState<string | null>(
    () => localStorage.getItem(ACTIVE_KEY) ?? null,
  )

  // One BotApi per bot id, kept across renders so refresh state survives.
  const apiCache = useRef(new Map<string, BotApi>())

  const getApi = useCallback((bot: StoredBot): BotApi => {
    let api = apiCache.current.get(bot.id)
    if (!api) {
      api = new BotApi(bot)
      apiCache.current.set(bot.id, api)
    }
    return api
  }, [])

  useEffect(() => {
    writeBots(bots)
  }, [bots])

  useEffect(() => {
    if (activeBotId) localStorage.setItem(ACTIVE_KEY, activeBotId)
    else localStorage.removeItem(ACTIVE_KEY)
  }, [activeBotId])

  // Drop the active pointer if it no longer resolves to a configured bot.
  useEffect(() => {
    if (activeBotId && !bots.some((b) => b.id === activeBotId)) {
      setActiveId(bots[0]?.id ?? null)
    } else if (!activeBotId && bots.length > 0) {
      setActiveId(bots[0].id)
    }
  }, [bots, activeBotId])

  const connect = useCallback<BotContextValue['connect']>(
    async (input) => {
      const baseUrl = normalizeBaseUrl(input.baseUrl)
      const id = makeBotId(baseUrl, input.username)
      const connection: StoredBot = {
        id,
        name: input.name.trim() || baseUrl,
        baseUrl,
        username: input.username,
        password: input.password,
      }

      // Reuse the cached instance when re-connecting the same bot so that a
      // refreshed token is not thrown away.
      let api = apiCache.current.get(id)
      if (api) {
        Object.assign(api.connection, connection)
      } else {
        api = new BotApi(connection)
        apiCache.current.set(id, api)
      }
      await api.login()

      setBots((prev) => {
        const others = prev.filter((b) => b.id !== id)
        return [...others, { ...connection, reachable: true }]
      })
      setActiveId(id)
    },
    [],
  )

  const disconnect = useCallback((id: string) => {
    apiCache.current.get(id)?.logout()
    apiCache.current.delete(id)
    setBots((prev) => prev.filter((b) => b.id !== id))
  }, [])

  const setReachable = useCallback((id: string, reachable: boolean) => {
    setBots((prev) => prev.map((b) => (b.id === id ? { ...b, reachable } : b)))
  }, [])

  const activeBot = useMemo(
    () => bots.find((b) => b.id === activeBotId) ?? null,
    [bots, activeBotId],
  )

  const api = useMemo(() => (activeBot ? getApi(activeBot) : null), [activeBot, getApi])

  // A dead session anywhere sends the app back to login.
  useEffect(() => {
    if (!api) return
    api.onAuthFailure = () => {
      apiCache.current.delete(api.id)
      setBots((prev) => prev.filter((b) => b.id !== api.id))
    }
    return () => {
      api.onAuthFailure = null
    }
  }, [api])

  const value = useMemo<BotContextValue>(
    () => ({
      bots,
      activeBotId,
      activeBot,
      api,
      connect,
      disconnect,
      setActiveBotId: setActiveId,
      setReachable,
    }),
    [bots, activeBotId, activeBot, api, connect, disconnect, setReachable],
  )

  return <BotContext.Provider value={value}>{children}</BotContext.Provider>
}

export function useBots(): BotContextValue {
  const ctx = useContext(BotContext)
  if (!ctx) throw new Error('useBots must be used inside <BotProvider>')
  return ctx
}

/** Convenience accessor for pages that require an authenticated bot. */
export function useApi(): BotApi {
  const { api } = useBots()
  if (!api) throw new Error('No active bot connection')
  return api
}
