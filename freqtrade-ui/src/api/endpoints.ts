/**
 * Typed wrappers for every freqtrade REST endpoint the console uses.
 *
 * Grouped by concern, mirroring the backend's own router split. Functions that
 * hit endpoints unavailable outside webserver mode are marked in their docs so
 * the UI can degrade instead of erroring.
 */

import { BotApi } from './client'
import type {
  AccessAndRefreshToken,
  AvailablePairs,
  BackgroundTaskStatus,
  BacktestHistoryEntry,
  BacktestPayload,
  BacktestResponse,
  BalanceCurrency,
  Balances,
  BgJobStarted,
  BlacklistResponse,
  Candle,
  Count,
  Daily,
  DailyWeeklyMonthly,
  DeleteTrade,
  DownloadDataPayload,
  EntryExitTag,
  ExchangeListResponse,
  ForceEnterPayload,
  ForceEnterResponse,
  ForceExitPayload,
  FreqAIModelListResponse,
  Health,
  HyperoptLossListResponse,
  ListCustomData,
  Locks,
  LogEntry,
  LogsResponse,
  MarketResponse,
  OpenTradeSchema,
  PairHistory,
  PairListsResponse,
  PairLock,
  PerformanceEntry,
  Ping,
  PlotConfig,
  Profit,
  ProfitAll,
  ResultMsg,
  ShowConfig,
  Stats,
  StatusMsg,
  StrategyListResponse,
  StrategyResponse,
  SysInfo,
  Trade,
  TradesResponse,
  Version,
  WalletHistory,
  WhitelistEvaluateResponse,
  WhitelistResponse,
} from './types'

/* -------------------------------------------------------------------------- */
/* Decoders — positional API arrays → typed objects                            */
/* -------------------------------------------------------------------------- */

const columnIndex = (columns: string[]) => {
  const index = new Map<string, number>()
  columns.forEach((name, i) => index.set(name, i))
  return index
}

function num(value: unknown): number {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : 0
}

/** Decodes the `data` matrix of a /pair_candles response into candle objects. */
export function decodeCandles(history: PairHistory): Candle[] {
  if (!history?.data?.length || !history.columns?.length) return []
  const idx = columnIndex(history.columns)
  const at = (row: (string | number | boolean | null)[], name: string): unknown => {
    const i = idx.get(name)
    return i === undefined ? undefined : row[i]
  }

  const candles: Candle[] = []
  for (const row of history.data) {
    const time = num(at(row, '__date_ts') ?? at(row, 'date_ts'))
    if (!time) continue
    candles.push({
      time: Math.floor(time / 1000) as number,
      date: String(at(row, 'date') ?? ''),
      open: num(at(row, 'open')),
      high: num(at(row, 'high')),
      low: num(at(row, 'low')),
      close: num(at(row, 'close')),
      volume: num(at(row, 'volume')),
      enterTag: String(at(row, 'enter_tag') ?? ''),
      exitTag: String(at(row, 'exit_tag') ?? ''),
      enterLong: num(at(row, 'enter_long')),
      exitLong: num(at(row, 'exit_long')),
      enterShort: num(at(row, 'enter_short')),
      exitShort: num(at(row, 'exit_short')),
    })
  }
  // lightweight-charts requires strictly ascending, unique timestamps.
  candles.sort((a, b) => a.time - b.time)
  return candles.filter((c, i) => i === 0 || c.time !== candles[i - 1].time)
}

export function decodeLogs(response: LogsResponse): LogEntry[] {
  if (!response?.logs?.length) return []
  return response.logs.map((row) => ({
    time: String(row[0] ?? ''),
    timestamp: num(row[1]),
    logger: String(row[2] ?? ''),
    level: (row[3] ?? 'INFO') as LogEntry['level'],
    message: String(row[4] ?? ''),
  }))
}

/** Decodes /historic_balance rows into `{time, value}` points. */
export function decodeWalletHistory(history: WalletHistory): { time: number; value: number }[] {
  if (!history?.data?.length || !history.columns?.length) return []
  const idx = columnIndex(history.columns)
  const tsIdx = idx.get('__date_ts') ?? 1
  const valueIdx = idx.get('total_quote') ?? 2
  return history.data
    .map((row) => ({ time: Math.floor(num(row[tsIdx]) / 1000), value: num(row[valueIdx]) }))
    .filter((p) => p.time > 0)
    .sort((a, b) => a.time - b.time)
}

/* -------------------------------------------------------------------------- */
/* Info                                                                        */
/* -------------------------------------------------------------------------- */

export const infoApi = {
  ping: (api: BotApi, signal?: AbortSignal) =>
    api.request<Ping>('/ping', { anonymous: true, signal }),

  version: (api: BotApi, signal?: AbortSignal) => api.request<Version>('/version', { signal }),

  showConfig: (api: BotApi, signal?: AbortSignal) =>
    api.request<ShowConfig>('/show_config', { signal }),

  health: (api: BotApi, signal?: AbortSignal) => api.request<Health>('/health', { signal }),

  sysinfo: (api: BotApi, signal?: AbortSignal) => api.request<SysInfo>('/sysinfo', { signal }),

  logs: async (api: BotApi, limit = 200, signal?: AbortSignal) =>
    decodeLogs(await api.request<LogsResponse>('/logs', { params: { limit }, signal })),

  strategies: (api: BotApi, signal?: AbortSignal) =>
    api.request<StrategyListResponse>('/strategies', { signal }),

  exchanges: (api: BotApi, signal?: AbortSignal) =>
    api.request<ExchangeListResponse>('/exchanges', { signal }),

  hyperoptLoss: (api: BotApi, signal?: AbortSignal) =>
    api.request<HyperoptLossListResponse>('/hyperoptloss', { signal }),

  freqaiModels: (api: BotApi, signal?: AbortSignal) =>
    api.request<FreqAIModelListResponse>('/freqaimodels', { signal }),
}

/* -------------------------------------------------------------------------- */
/* Trading info                                                                */
/* -------------------------------------------------------------------------- */

export const tradingApi = {
  balance: (api: BotApi, signal?: AbortSignal) => api.request<Balances>('/balance', { signal }),

  count: (api: BotApi, signal?: AbortSignal) => api.request<Count>('/count', { signal }),

  entries: (api: BotApi, signal?: AbortSignal) =>
    api.request<EntryExitTag[]>('/entries', { signal }),

  exits: (api: BotApi, signal?: AbortSignal) => api.request<EntryExitTag[]>('/exits', { signal }),

  mixTags: (api: BotApi, signal?: AbortSignal) =>
    api.request<EntryExitTag[]>('/mix_tags', { signal }),

  performance: (api: BotApi, signal?: AbortSignal) =>
    api.request<PerformanceEntry[]>('/performance', { signal }),

  profit: (api: BotApi, signal?: AbortSignal) => api.request<Profit>('/profit', { signal }),

  profitAll: (api: BotApi, signal?: AbortSignal) =>
    api.request<ProfitAll>('/profit_all', { signal }),

  stats: (api: BotApi, signal?: AbortSignal) => api.request<Stats>('/stats', { signal }),

  daily: (api: BotApi, timescale = 7, signal?: AbortSignal) =>
    api.request<DailyWeeklyMonthly>('/daily', { params: { timescale }, signal }),

  weekly: (api: BotApi, timescale = 4, signal?: AbortSignal) =>
    api.request<DailyWeeklyMonthly>('/weekly', { params: { timescale }, signal }),

  monthly: (api: BotApi, timescale = 3, signal?: AbortSignal) =>
    api.request<DailyWeeklyMonthly>('/monthly', { params: { timescale }, signal }),

  historicBalance: (api: BotApi, signal?: AbortSignal) =>
    api.request<WalletHistory>('/historic_balance', { signal }),

  status: (api: BotApi, signal?: AbortSignal) =>
    api.request<OpenTradeSchema[]>('/status', { signal }),

  trades: (api: BotApi, params: Record<string, string | number> = {}, signal?: AbortSignal) =>
    api.request<TradesResponse>('/trades', { params, signal }),

  trade: (api: BotApi, tradeId: number, signal?: AbortSignal) =>
    api.request<Trade>(`/trade/${tradeId}`, { signal }),

  deleteTrade: (api: BotApi, tradeId: number) =>
    api.request<DeleteTrade>(`/trades/${tradeId}`, { method: 'DELETE' }),

  cancelOpenOrder: (api: BotApi, tradeId: number) =>
    api.request<OpenTradeSchema>(`/trades/${tradeId}/open-order`, { method: 'DELETE' }),

  reloadTrade: (api: BotApi, tradeId: number) =>
    api.request<OpenTradeSchema>(`/trades/${tradeId}/reload`, { method: 'POST' }),

  customData: (api: BotApi, tradeId: number, signal?: AbortSignal) =>
    api.request<ListCustomData[]>(`/trades/${tradeId}/custom-data`, { signal }),

  openCustomData: (api: BotApi, signal?: AbortSignal) =>
    api.request<ListCustomData[]>('/trades/open/custom-data', { signal }),

  forceEnter: (api: BotApi, payload: ForceEnterPayload) =>
    api.request<ForceEnterResponse>('/forceenter', { method: 'POST', body: payload }),

  forceExit: (api: BotApi, payload: ForceExitPayload) =>
    api.request<ResultMsg>('/forceexit', { method: 'POST', body: payload }),

  pairCandles: (
    api: BotApi,
    params: { pair: string; timeframe: string; limit?: number; timerange?: string },
    signal?: AbortSignal,
  ) => api.request<PairHistory>('/pair_candles', { params, signal }),

  pairHistory: (
    api: BotApi,
    params: {
      pair: string
      timeframe: string
      timerange?: string
      strategy?: string
      live_mode?: boolean
    },
    signal?: AbortSignal,
  ) => api.request<PairHistory>('/pair_history', { params, signal }),

  plotConfig: (api: BotApi, params: { strategy?: string; pair?: string }, signal?: AbortSignal) =>
    api.request<PlotConfig>('/plot_config', { params, signal }),

  markets: (api: BotApi, signal?: AbortSignal) =>
    api.request<MarketResponse>('/markets', { signal }),

  strategy: (api: BotApi, strategy: string, signal?: AbortSignal) =>
    api.request<StrategyResponse>(`/strategy/${encodeURIComponent(strategy)}`, { signal }),
}

/* -------------------------------------------------------------------------- */
/* Bot control                                                                 */
/* -------------------------------------------------------------------------- */

export const controlApi = {
  start: (api: BotApi) => api.request<StatusMsg>('/start', { method: 'POST' }),
  stop: (api: BotApi) => api.request<StatusMsg>('/stop', { method: 'POST' }),
  pause: (api: BotApi) => api.request<StatusMsg>('/pause', { method: 'POST' }),
  stopEntry: (api: BotApi) => api.request<StatusMsg>('/stopentry', { method: 'POST' }),
  reloadConfig: (api: BotApi) => api.request<StatusMsg>('/reload_config', { method: 'POST' }),
}

/* -------------------------------------------------------------------------- */
/* Pairlist & locks                                                            */
/* -------------------------------------------------------------------------- */

export const pairlistApi = {
  whitelist: (api: BotApi, signal?: AbortSignal) =>
    api.request<WhitelistResponse>('/whitelist', { signal }),

  blacklist: (api: BotApi, signal?: AbortSignal) =>
    api.request<BlacklistResponse>('/blacklist', { signal }),

  addBlacklist: (api: BotApi, pairs: string[]) =>
    api.request<BlacklistResponse>('/blacklist', { method: 'POST', body: { blacklist: pairs } }),

  // The backend declares `pairs_to_delete: list[str] = Query([])`, so the pairs
  // must go on the query string as repeated keys — not in a JSON body.
  deleteBlacklist: (api: BotApi, pairs: string[]) =>
    api.request<BlacklistResponse>('/blacklist', {
      method: 'DELETE',
      params: { pairs_to_delete: pairs },
    }),

  locks: (api: BotApi, signal?: AbortSignal) => api.request<Locks>('/locks', { signal }),

  createLock: (
    api: BotApi,
    payload: { pair: string; until: string; reason?: string; side?: string },
  ) => api.request<Locks>('/locks', { method: 'POST', body: payload }),

  deleteLock: (api: BotApi, lockId: number) =>
    api.request<Locks>(`/locks/${lockId}`, { method: 'DELETE' }),

  deleteLocks: (api: BotApi, lockIds: number[]) =>
    api.request<Locks>('/locks/delete', { method: 'POST', body: { lock_ids: lockIds } }),

  available: (api: BotApi, signal?: AbortSignal) =>
    api.request<PairListsResponse>('/pairlists/available', { signal }),

  evaluate: (api: BotApi, payload: Record<string, unknown>) =>
    api.request<BgJobStarted>('/pairlists/evaluate', { method: 'POST', body: payload }),

  evaluateResult: (api: BotApi, jobId: string, signal?: AbortSignal) =>
    api.request<WhitelistEvaluateResponse>(`/pairlists/evaluate/${jobId}`, { signal }),

  availablePairs: (api: BotApi, params: Record<string, string>, signal?: AbortSignal) =>
    api.request<AvailablePairs>('/available_pairs', { params, signal }),
}

/* -------------------------------------------------------------------------- */
/* Backtest                                                                    */
/* -------------------------------------------------------------------------- */

export const backtestApi = {
  start: (api: BotApi, payload: BacktestPayload) =>
    api.request<BacktestResponse>('/backtest', { method: 'POST', body: payload }),

  get: (api: BotApi, signal?: AbortSignal) =>
    api.request<BacktestResponse>('/backtest', { signal }),

  abort: (api: BotApi) => api.request<BacktestResponse>('/backtest/abort'),

  reset: (api: BotApi) => api.request<BacktestResponse>('/backtest', { method: 'DELETE' }),

  history: (api: BotApi, signal?: AbortSignal) =>
    api.request<BacktestHistoryEntry[]>('/backtest/history', { signal }),

  historyResult: (
    api: BotApi,
    params: { filename: string; strategy?: string },
    signal?: AbortSignal,
  ) => api.request<BacktestResponse>('/backtest/history/result', { params, signal }),

  deleteHistory: (api: BotApi, filename: string) =>
    api.request<BacktestHistoryEntry[]>(`/backtest/history/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    }),

  marketChange: (api: BotApi, filename: string, signal?: AbortSignal) =>
    api.request<BacktestResponse>(
      `/backtest/history/${encodeURIComponent(filename)}/market_change`,
      { signal },
    ),

  wallet: (api: BotApi, filename: string, strategy: string, signal?: AbortSignal) =>
    api.request<WalletHistory>(
      `/backtest/history/${encodeURIComponent(filename)}/${encodeURIComponent(strategy)}/wallet`,
      { signal },
    ),

  /** Persists a note against a stored backtest result. */
  saveNotes: (
    api: BotApi,
    payload: { run_id: string; filename: string; notes: string; strategy: string },
  ) =>
    api.request<BacktestHistoryEntry[]>(
      `/backtest/history/${encodeURIComponent(payload.filename)}`,
      { method: 'PATCH', body: payload },
    ),
}

/* -------------------------------------------------------------------------- */
/* Background jobs & download data                                             */
/* -------------------------------------------------------------------------- */

export const backgroundApi = {
  list: (api: BotApi, signal?: AbortSignal) =>
    api.request<BackgroundTaskStatus[]>('/background', { signal }),

  get: (api: BotApi, jobId: string, signal?: AbortSignal) =>
    api.request<BackgroundTaskStatus>(`/background/${jobId}`, { signal }),

  stop: (api: BotApi, jobId: string) =>
    api.request<BackgroundTaskStatus>(`/background/${jobId}`, { method: 'DELETE' }),

  /** Removes finished jobs; returns the ones still running. */
  clear: (api: BotApi) =>
    api.request<BackgroundTaskStatus[]>('/background/clear', { method: 'DELETE' }),
}

export const downloadApi = {
  start: (api: BotApi, payload: DownloadDataPayload) =>
    api.request<BgJobStarted>('/download_data', { method: 'POST', body: payload }),
}

/* -------------------------------------------------------------------------- */
/* Analysis (webserver mode)                                                   */
/* -------------------------------------------------------------------------- */

export interface LookaheadPayload {
  strategy: string
  timeframe?: string
  timerange?: string
  minimum_trade_amount: number
  targeted_trade_amount: number
  lookahead_allow_limit_orders: boolean
}

export interface LookaheadResult {
  strategy: string
  has_bias: boolean
  total_signals: number
  biased_entry_signals: number
  biased_exit_signals: number
  biased_indicators: string[]
}

export interface LookaheadResponse {
  status: string
  running: boolean
  status_msg?: string
  result?: LookaheadResult
}

export interface RecursivePayload {
  strategy: string
  timeframe?: string
  timerange?: string
  startup_candle?: number[]
}

export interface RecursiveResult {
  strategy: string
  startup_candles: number[]
  strategy_scc: number
  results: Record<string, Record<string, number>>
}

export interface RecursiveResponse {
  status: string
  running: boolean
  status_msg?: string
  result?: RecursiveResult
}

export const analysisApi = {
  startLookahead: (api: BotApi, payload: LookaheadPayload) =>
    api.request<BgJobStarted>('/lookahead_analysis', { method: 'POST', body: payload }),

  lookaheadResult: (api: BotApi, jobId: string, signal?: AbortSignal) =>
    api.request<LookaheadResponse>(`/lookahead_analysis/${jobId}`, { signal }),

  startRecursive: (api: BotApi, payload: RecursivePayload) =>
    api.request<BgJobStarted>('/recursive_analysis', { method: 'POST', body: payload }),

  recursiveResult: (api: BotApi, jobId: string, signal?: AbortSignal) =>
    api.request<RecursiveResponse>(`/recursive_analysis/${jobId}`, { signal }),
}

/* -------------------------------------------------------------------------- */
/* Convenience re-exports for callers that want the raw shapes                  */
/* -------------------------------------------------------------------------- */

export type { AccessAndRefreshToken, BalanceCurrency, Daily, PairLock, Trade, WhitelistEvaluateResponse }
