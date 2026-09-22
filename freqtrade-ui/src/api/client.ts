/**
 * HTTP client for the freqtrade REST API.
 *
 * One `BotApi` instance == one bot connection. The app can hold several, which
 * is what makes the multi-bot switcher possible.
 *
 * Auth strategy: log in once with HTTP Basic to obtain a JWT pair, then send
 * `Authorization: Bearer <access>`. A 401 triggers a single transparent refresh
 * and retry; if that also fails the session is considered dead and the caller
 * is told to re-authenticate.
 */

import type { AccessAndRefreshToken, AccessToken } from './types'

export class ApiError extends Error {
  status: number
  detail: string
  path: string

  constructor(status: number, detail: string, path: string) {
    super(`${status} ${detail}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.path = path
  }

  /** The bot is reachable but not in a mode that serves this endpoint. */
  get isWrongState(): boolean {
    return this.status === 404 || /not in the correct state/i.test(this.detail)
  }
}

export class AuthError extends Error {
  constructor(message = 'Authentication failed') {
    super(message)
    this.name = 'AuthError'
  }
}

export interface BotConnection {
  id: string
  name: string
  baseUrl: string
  username: string
  password: string
}

interface TokenPair {
  access: string
  refresh: string
}

export type QueryValue = string | number | boolean | undefined | null | (string | number)[]

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  params?: Record<string, QueryValue>
  body?: unknown
  signal?: AbortSignal
  /** Skip auth entirely (used by /ping). */
  anonymous?: boolean
}

function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return ''
  const usp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const v of value) usp.append(key, String(v))
    } else {
      usp.append(key, String(value))
    }
  }
  const qs = usp.toString()
  return qs ? `?${qs}` : ''
}

/** Normalises a user-supplied base URL: strips trailing slashes. */
export function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

function tokenStorageKey(botId: string): string {
  return `ftui.tokens.${botId}`
}

function readTokens(botId: string): TokenPair | null {
  try {
    const raw = localStorage.getItem(tokenStorageKey(botId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as TokenPair
    if (typeof parsed?.access === 'string' && typeof parsed?.refresh === 'string') {
      return parsed
    }
    return null
  } catch {
    return null
  }
}

function writeTokens(botId: string, tokens: TokenPair | null): void {
  try {
    if (tokens) localStorage.setItem(tokenStorageKey(botId), JSON.stringify(tokens))
    else localStorage.removeItem(tokenStorageKey(botId))
  } catch {
    /* storage unavailable (private mode) — sessions simply won't persist */
  }
}

export class BotApi {
  readonly connection: BotConnection
  private tokens: TokenPair | null
  private refreshInFlight: Promise<string> | null = null
  /** Set when the session is unrecoverable, so callers can redirect to login. */
  onAuthFailure: (() => void) | null = null

  constructor(connection: BotConnection) {
    this.connection = { ...connection, baseUrl: normalizeBaseUrl(connection.baseUrl) }
    this.tokens = readTokens(connection.id)
  }

  get id(): string {
    return this.connection.id
  }

  get baseUrl(): string {
    return this.connection.baseUrl
  }

  get isAuthenticated(): boolean {
    return this.tokens !== null
  }

  private url(path: string, params?: Record<string, QueryValue>): string {
    const suffix = path.startsWith('/') ? path : `/${path}`
    return `${this.connection.baseUrl}/api/v1${suffix}${buildQuery(params)}`
  }

  private basicHeader(): string {
    const raw = `${this.connection.username}:${this.connection.password}`
    // btoa is latin-1 only; encode UTF-8 first so non-ASCII passwords work.
    const bytes = new TextEncoder().encode(raw)
    let binary = ''
    for (const b of bytes) binary += String.fromCharCode(b)
    return `Basic ${btoa(binary)}`
  }

  /** Exchanges stored credentials for a JWT pair. */
  async login(): Promise<void> {
    const res = await fetch(this.url('/token/login'), {
      method: 'POST',
      headers: { Authorization: this.basicHeader() },
    })
    if (!res.ok) {
      let detail = 'Incorrect username or password'
      try {
        const parsed = (await res.json()) as { detail?: string }
        if (parsed?.detail) detail = parsed.detail
      } catch {
        /* non-JSON error body */
      }
      throw new AuthError(detail)
    }
    const data = (await res.json()) as AccessAndRefreshToken
    this.tokens = { access: data.access_token, refresh: data.refresh_token }
    writeTokens(this.connection.id, this.tokens)
  }

  logout(): void {
    this.tokens = null
    writeTokens(this.connection.id, null)
  }

  /** Verifies the stored session is still usable. */
  async verifySession(): Promise<boolean> {
    if (!this.tokens) return false
    try {
      await this.request('/ping', { anonymous: true })
      await this.request('/version')
      return true
    } catch {
      return false
    }
  }

  private async refreshAccessToken(): Promise<string> {
    // Collapse concurrent 401s into a single refresh round-trip.
    if (this.refreshInFlight) return this.refreshInFlight

    const refresh = this.tokens?.refresh
    if (!refresh) throw new AuthError('No refresh token')

    this.refreshInFlight = (async () => {
      const res = await fetch(this.url('/token/refresh'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${refresh}` },
      })
      if (!res.ok) {
        this.logout()
        throw new AuthError('Session expired')
      }
      const data = (await res.json()) as AccessToken
      this.tokens = { access: data.access_token, refresh }
      writeTokens(this.connection.id, this.tokens)
      return data.access_token
    })()

    try {
      return await this.refreshInFlight
    } finally {
      this.refreshInFlight = null
    }
  }

  private async rawRequest(
    path: string,
    options: RequestOptions,
    token: string | null,
  ): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (options.body !== undefined) headers['Content-Type'] = 'application/json'
    if (options.anonymous) {
      headers.Authorization = this.basicHeader()
    } else if (token) {
      headers.Authorization = `Bearer ${token}`
    } else {
      headers.Authorization = this.basicHeader()
    }

    return fetch(this.url(path, options.params), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    })
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const token = this.tokens?.access ?? null
    let res = await this.rawRequest(path, options, token)

    // One transparent refresh-and-retry on an expired access token.
    if (res.status === 401 && !options.anonymous && this.tokens?.refresh) {
      try {
        const fresh = await this.refreshAccessToken()
        res = await this.rawRequest(path, options, fresh)
      } catch {
        this.onAuthFailure?.()
        throw new AuthError('Session expired')
      }
    }

    if (!res.ok) {
      let detail = res.statusText || 'Request failed'
      try {
        const parsed = (await res.json()) as { detail?: unknown }
        if (typeof parsed?.detail === 'string') detail = parsed.detail
        else if (parsed?.detail) detail = JSON.stringify(parsed.detail)
      } catch {
        /* body was not JSON */
      }
      if (res.status === 401) {
        this.onAuthFailure?.()
        throw new AuthError(detail)
      }
      throw new ApiError(res.status, detail, path)
    }

    if (res.status === 204) return undefined as T
    const text = await res.text()
    if (!text) return undefined as T
    return JSON.parse(text) as T
  }

  /** Builds the authenticated WebSocket URL for the live message stream. */
  wsUrl(): string {
    const base = this.connection.baseUrl.replace(/^http/, 'ws')
    const token = this.tokens?.access ?? ''
    return `${base}/api/v1/message/ws?token=${encodeURIComponent(token)}`
  }
}
