/**
 * Types for the freqtrade REST API (api_version 2.5x).
 *
 * Field names mirror the backend schemas exactly, including their snake_case.
 * Where the backend returns positional arrays (candle data, log rows) the type
 * reflects that and a decoder in `endpoints.ts` maps it to a friendly object.
 */

/* -------------------------------------------------------------------------- */
/* Info                                                                        */
/* -------------------------------------------------------------------------- */

export interface Ping {
  status: string
}

export interface Version {
  version: string
}

export interface Health {
  bot_start: string
  bot_start_ts: number
  bot_startup: string
  bot_startup_ts: number
  last_process: string | null
  last_process_ts: number | null
}

export interface SysInfo {
  cpu_pct: number[]
  cpu_count: number
  cpu_load: number[]
  cpu_load_avg: number
  ram_pct: number
}

export interface OrderTypeMapping {
  entry: string
  exit: string
  emergency_exit: string
  stoploss: string
  stoploss_on_exchange: boolean
  stoploss_on_exchange_interval: number | null
}

export interface PricingConfig {
  price_side: string
  use_order_book: boolean
  order_book_top: number
  price_last_balance?: number
  check_depth_of_market?: { enabled: boolean; bids_to_ask_delta: number }
}

export interface ShowConfig {
  version: string
  strategy_version: string | null
  api_version: number
  dry_run: boolean
  trading_mode: 'spot' | 'margin' | 'futures'
  margin_mode?: 'cross' | 'isolated'
  short_allowed: boolean
  stake_currency: string
  stake_amount: string | number
  available_capital: number | null
  stake_currency_decimals: number
  max_open_trades: number
  minimal_roi: Record<string, number>
  stoploss: number
  stoploss_on_exchange: boolean
  trailing_stop: boolean
  trailing_stop_positive: number | null
  trailing_stop_positive_offset: number
  trailing_only_offset_is_reached: boolean
  unfilledtimeout: { entry: number; exit: number; unit: string; exit_timeout_count: number }
  order_types: OrderTypeMapping
  use_custom_stoploss: boolean
  timeframe: string
  timeframe_ms: number
  timeframe_min: number
  exchange: string
  demo_trading: boolean
  strategy: string
  force_entry_enable: boolean
  exit_pricing: PricingConfig
  entry_pricing: PricingConfig
  bot_name: string
  state: BotState
  runmode: string
  position_adjustment_enable?: boolean
  max_entry_position_adjustment?: number
}

export type BotState = 'running' | 'stopped' | 'paused' | 'unknown'

/* -------------------------------------------------------------------------- */
/* Profit & performance                                                        */
/* -------------------------------------------------------------------------- */

export interface Profit {
  profit_closed_coin: number
  profit_closed_percent_mean: number
  profit_closed_ratio_mean: number
  profit_closed_percent_sum: number
  profit_closed_ratio_sum: number
  profit_closed_percent: number
  profit_closed_ratio: number
  profit_closed_fiat: number
  profit_all_coin: number
  profit_all_percent_mean: number
  profit_all_ratio_mean: number
  profit_all_percent_sum: number
  profit_all_ratio_sum: number
  profit_all_percent: number
  profit_all_ratio: number
  profit_all_fiat: number
  trade_count: number
  closed_trade_count: number
  first_trade_date: string
  first_trade_humanized: string
  first_trade_timestamp: number
  latest_trade_date: string
  latest_trade_humanized: string
  latest_trade_timestamp: number
  avg_duration: string
  best_pair: string
  best_rate: number
  best_pair_profit_ratio: number
  best_pair_profit_abs: number
  winning_trades: number
  losing_trades: number
  profit_factor: number
  winrate: number
  expectancy: number
  expectancy_ratio: number
  sharpe?: number
  sortino?: number
  calmar?: number
  cagr?: number
  max_drawdown?: number
  max_drawdown_abs?: number
  max_drawdown_start?: string
  max_drawdown_start_timestamp?: number
  max_drawdown_end?: string
  max_drawdown_end_timestamp?: number
  current_drawdown?: number
  current_drawdown_abs?: number
  current_drawdown_high?: number
  current_drawdown_start?: string
  current_drawdown_start_timestamp?: number
  trading_volume?: number
  bot_start_date?: string
  bot_start_timestamp?: number
}

export interface ProfitAll {
  all: Profit
  long: Profit
  short: Profit
}

export interface PerformanceEntry {
  profit_ratio: number
  profit_pct: number
  profit_abs: number
  count: number
  pair: string
  profit: number
}

export interface EntryExitTag {
  enter_tag?: string
  exit_reason?: string
  mix_tag?: string
  profit_ratio: number
  profit_pct: number
  profit_abs: number
  count: number
}

export interface StatsDuration {
  wins: number | null
  draws: number | null
  losses: number | null
}

export interface ExitReasonStats {
  wins: number
  losses: number
  draws: number
}

export interface Stats {
  durations: StatsDuration
  exit_reasons: Record<string, ExitReasonStats>
}

export interface Daily {
  date: string
  abs_profit: number
  rel_profit: number
  starting_balance: number
  fiat_value: number
  trade_count: number
}

export interface DailyWeeklyMonthly {
  data: Daily[]
  stake_currency: string
  fiat_display_currency: string
}

export interface Count {
  current: number
  max: number
  total_stake: number
}

export interface WalletHistory {
  columns: string[]
  data: (string | number)[][]
  length: number
  capture_start_ts: number
}

/* -------------------------------------------------------------------------- */
/* Balance                                                                     */
/* -------------------------------------------------------------------------- */

export interface BalanceCurrency {
  currency: string
  free: number
  balance: number
  used: number
  bot_owned: number | null
  est_stake: number
  est_stake_bot: number | null
  stake: string
  side: 'long' | 'short' | ''
  is_position: boolean
  position: number
  is_bot_managed: boolean
}

export interface Balances {
  currencies: BalanceCurrency[]
  total: number
  total_bot: number
  symbol: string
  value: number
  value_bot: number
  stake: string
  note: string
  starting_capital: number
  starting_capital_ratio: number
  starting_capital_fiat: number
  starting_capital_ratio_bot: number
  starting_capital_fiat_bot: number
}

/* -------------------------------------------------------------------------- */
/* Trades                                                                      */
/* -------------------------------------------------------------------------- */

export interface Trade {
  trade_id: number
  pair: string
  base_currency: string
  quote_currency: string
  is_open: boolean
  exchange: string
  amount: number
  amount_requested: number
  stake_amount: number
  max_stake_amount: number
  strategy: string
  enter_tag: string | null
  timeframe: number
  fee_open: number
  fee_open_cost: number | null
  fee_open_currency: string | null
  fee_close: number
  fee_close_cost: number | null
  fee_close_currency: string | null
  open_date: string
  open_timestamp: number
  open_fill_date: string | null
  open_fill_timestamp: number | null
  open_rate: number
  open_rate_requested: number
  open_trade_value: number
  close_date: string | null
  close_timestamp: number | null
  close_rate: number | null
  close_rate_requested: number | null
  close_profit: number | null
  close_profit_pct: number | null
  close_profit_abs: number | null
  realized_profit: number
  realized_profit_ratio: number | null
  trade_duration_s: number | null
  trade_duration: number | null
  profit_ratio: number
  profit_pct: number
  profit_abs: number
  profit_fiat: number | null
  exit_reason: string | null
  exit_order_status: string | null
  stop_loss_abs: number
  stop_loss_ratio: number | null
  stop_loss_pct: number | null
  stoploss_last_update: string | null
  stoploss_last_update_timestamp: number | null
  initial_stop_loss_abs: number
  initial_stop_loss_ratio: number | null
  initial_stop_loss_pct: number | null
  min_rate: number | null
  max_rate: number | null
  leverage: number
  interest_rate: number
  liquidation_price: number | null
  is_short: boolean
  funding_fees: number | null
  trading_mode: string
  amount_precision: number | null
  price_precision: number | null
  precision_mode: number | null
  contract_size: number | null
  orders?: TradeOrder[]
  has_open_orders?: boolean
  open_orders?: TradeOrder[]
  nr_of_successful_entries?: number
  nr_of_successful_exits?: number
}

export interface TradeOrder {
  order_id: string
  status: string
  symbol: string
  order_type: string
  side: string
  price: number
  average: number | null
  amount: number
  filled: number | null
  remaining: number | null
  cost: number
  order_date: string
  order_timestamp: number
  order_filled_date: string | null
  order_filled_timestamp: number | null
  order_update_date: string | null
  order_update_timestamp: number | null
  ft_order_side: string
  ft_pair: string
  ft_is_open: boolean
}

export interface TradesResponse {
  trades: Trade[]
  trades_count: number
  total_trades: number
  offset: number
}

export interface TradeListParams {
  limit?: number
  offset?: number
  order_by_id?: boolean
  pair?: string
}

export interface ListCustomData {
  key: string
  type: string
  value: unknown
  created_at: number
  value_type?: string
}

export interface ForceEnterPayload {
  pair: string
  side?: 'long' | 'short'
  price?: number
  ordertype?: string
  stakeamount?: number
  amount?: number
  leverage?: number
  enter_tag?: string
}

export interface ForceEnterResponse {
  trade_id: number
  pair: string
  amount: number
  stake_amount: number
  open_rate: number
  open_date: string
  is_short?: boolean
}

export interface ForceExitPayload {
  tradeid: string
  ordertype?: string
  amount?: number
  price?: number
}

export interface ResultMsg {
  result: string
  trade_id?: number
}

export interface StatusMsg {
  status: string
}

export interface DeleteTrade {
  result: string
  trade_id: number
  cancel_order_count: number
}

export interface OpenTradeSchema extends Trade {
  has_open_orders?: boolean
  open_orders?: TradeOrder[]
}

/* -------------------------------------------------------------------------- */
/* Locks & pairlist                                                            */
/* -------------------------------------------------------------------------- */

export interface PairLock {
  id: number
  pair: string
  lock_time: string
  lock_timestamp: number
  lock_end_time: string
  lock_end_timestamp: number
  reason: string
  active: boolean
}

export interface Locks {
  lock_count: number
  locks: PairLock[]
}

export interface WhitelistResponse {
  whitelist: string[]
  length?: number
  method?: string[]
}

export interface BlacklistResponse {
  blacklist: string[]
  blacklist_expanded: string[]
  /** Keyed by pair. `DELETE /blacklist` reports failures here, not as an error. */
  errors: Record<string, { error_msg: string }>
  length: number
  method: string[]
}

export interface MarketInfo {
  symbol: string
  base: string
  quote: string
  spot: boolean
  swap: boolean
  active: boolean
}

export interface MarketResponse {
  markets: Record<string, MarketInfo>
  exchange_id: string
}

/* -------------------------------------------------------------------------- */
/* Candle data                                                                 */
/* -------------------------------------------------------------------------- */

export interface PairHistory {
  strategy: string
  pair: string
  timeframe: string
  timeframe_ms: number
  columns: string[]
  all_columns: string[]
  data: (string | number | boolean | null)[][]
  annotations: unknown[]
  length: number
  buy_signals: number
  sell_signals: number
  enter_long_signals: number
  exit_long_signals: number
  enter_short_signals: number
  exit_short_signals: number
  last_analyzed: string
  last_analyzed_ts: number
  data_start_ts: number
  data_start: string
  data_stop: string
  data_stop_ts: number
}

/** A candle decoded from the positional `PairHistory.data` matrix. */
export interface Candle {
  time: number
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  enterTag: string
  exitTag: string
  enterLong: number
  exitLong: number
  enterShort: number
  exitShort: number
}

export interface PlotConfig {
  [key: string]: unknown
}

export interface AvailablePairs {
  pairs: string[]
  length: number
}

/** One strategy parameter, as returned by `GET /strategy/{name}`. */
export interface StrategyParam {
  name: string
  space?: string
  value?: unknown
  param_type?: string
  [key: string]: unknown
}

export interface StrategyResponse {
  strategy: string
  code: string
  timeframe?: string
  params?: StrategyParam[]
}

export interface PlotConfigResponse {
  plot_config?: PlotConfig
}

/* -------------------------------------------------------------------------- */
/* Webserver-mode resources                                                    */
/* -------------------------------------------------------------------------- */

export interface StrategyListResponse {
  strategies: Record<string, string>
}

export interface ExchangeListResponse {
  exchanges: ValidExchange[]
}

/**
 * One entry from `GET /exchanges` (webserver mode only).
 *
 * Mirrors `ValidExchangesType` in `freqtrade/ft_types/valid_exchanges_type.py`.
 * `classname` is what the API expects back when selecting an exchange; `name` is
 * the human-facing label.
 */
export interface ValidExchange {
  name: string
  classname: string
  valid: boolean
  supported: boolean
  comment: string
  comment_futures: string
  dex: boolean
  is_alias: boolean
  alias_for: string | null
  trade_modes: ExchangeTradeMode[]
}

export interface ExchangeTradeMode {
  trading_mode: string
  margin_mode: string
}

export interface HyperoptLossListResponse {
  hyperopt_loss_functions: string[]
}

export interface FreqAIModelListResponse {
  freqaimodels: string[]
}

export interface BgJobStarted {
  job_id: string
}

export interface BackgroundTaskStatus {
  job_id: string
  job_category: string
  /** `pending` is emitted before the worker flips `running` on. */
  status: 'pending' | 'running' | 'success' | 'failed'
  running: boolean
  progress?: number
  progress_tasks?: Record<string, { progress: number; total: number }>
  status_message?: string
  error?: string
  result?: unknown
  duration?: number
  start_time?: number
}

/**
 * Body of `POST /download_data`.
 *
 * Mirrors `DownloadDataPayload` in `freqtrade/rpc/api_server/api_schemas.py`:
 * `timeframes` (plural) is the real field, `days` and `timerange` are
 * alternatives, and the candle-type / prepend options are version-gated.
 */
export interface DownloadDataPayload {
  pairs: string[]
  timeframes?: string[]
  days?: number
  timerange?: string
  erase?: boolean
  download_trades?: boolean
  candle_types?: string[]
  prepend_data?: boolean
  exchange?: string
  trading_mode?: string
  margin_mode?: string
}

/** One entry from `GET /pairlists/available`. */
export interface PairlistResponse {
  name: string
  description: string
  is_pairlist_generator: boolean
  params: Record<string, unknown>
}

export interface PairListsResponse {
  pairlists: PairlistResponse[]
}

export interface PairlistEvaluatePayload {
  pairlists: { method: string; [key: string]: unknown }[]
  timeframe: string
  timeframe_detail?: string
  exchange?: string
  stake_currency?: string
  timerange?: string
  lookback?: number
}

export interface WhitelistEvaluateResponse {
  result?: { whitelist: string[]; length: number }
  background_task?: BackgroundTaskStatus
}

/* -------------------------------------------------------------------------- */
/* Backtest                                                                    */
/* -------------------------------------------------------------------------- */

export interface BacktestPayload {
  strategy: string
  timeframe?: string
  timeframe_detail?: string
  timerange?: string
  max_open_trades?: number
  stake_amount?: string | number
  dry_run_wallet?: number
  fee?: number
  enable_protections?: boolean
  use_custom_stoploss?: boolean
  enable_dynamic_whitelist?: boolean
  dry_run?: boolean
}

export interface BacktestHistoryEntry {
  filename: string
  strategy: string
  notes: string
  backtest_start_time: number
  backtest_start_ts: number
  backtest_end_ts: number
  timeframe: string
  timeframe_detail?: string
}

export interface BacktestResult {
  metadata: Record<string, unknown>
  strategy: Record<string, unknown>
  results_per_pair?: Record<string, unknown>[]
  results_per_enter_tag?: Record<string, unknown>[]
  exit_reason_summary?: Record<string, unknown>[]
  left_open_trades?: Record<string, unknown>[]
  total_trades?: number
  trades?: Record<string, unknown>[]
  daily_stats?: Record<string, unknown>[]
  [key: string]: unknown
}

export interface BacktestResponse {
  status?: string
  running?: boolean
  status_msg?: string
  progress?: number
  backtest_result?: BacktestResult
  backtest_history?: BacktestHistoryEntry[]
  trade_count?: number
  config?: Record<string, unknown>
  background_task?: BackgroundTaskStatus
}

/* -------------------------------------------------------------------------- */
/* Logs                                                                        */
/* -------------------------------------------------------------------------- */

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

/** Raw log row as delivered by the API: a positional tuple. */
export type LogRow = [string, number, string, LogLevel, string]

export interface LogsResponse {
  log_count: number
  logs: LogRow[]
}

export interface LogEntry {
  time: string
  timestamp: number
  logger: string
  level: LogLevel
  message: string
}

/* -------------------------------------------------------------------------- */
/* Auth                                                                        */
/* -------------------------------------------------------------------------- */

export interface AccessToken {
  access_token: string
}

export interface AccessAndRefreshToken extends AccessToken {
  refresh_token: string
}

/* -------------------------------------------------------------------------- */
/* WebSocket                                                                   */
/* -------------------------------------------------------------------------- */

export type WsMessageType =
  | 'status'
  | 'warning'
  | 'exception'
  | 'startup'
  | 'whitelist'
  | 'analyzed_df'
  | 'new_candle'
  | 'entry'
  | 'entry_fill'
  | 'entry_cancel'
  | 'exit'
  | 'exit_fill'
  | 'exit_cancel'
  | 'protection_trigger'
  | 'protection_trigger_global'
  | 'liquidation_warning'
  | 'strategy_msg'

export interface WsEnvelope<T = unknown> {
  type: WsMessageType
  data: T
}

export interface WsRequest {
  type: 'subscribe' | 'unsubscribe'
  data: WsMessageType[]
}
