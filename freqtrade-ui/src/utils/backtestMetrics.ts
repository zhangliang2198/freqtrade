/**
 * Backtest metric/setting row generation.
 *
 * Ported from freqUI's `utils/backtestMetrics.ts`. The row labels, their order
 * and the per-value formatting are reproduced verbatim so the console's
 * "Strategy settings" and "Metrics" panels read identically to the Vue app.
 *
 * The freqtrade `/backtest` response nests one `StrategyBacktestResult` per
 * strategy name:
 *
 *     { strategy: { <name>: StrategyBacktestResult }, metadata: {...} }
 *
 * `generateBacktestMetricRows` / `generateBacktestSettingRows` operate on a
 * single such per-strategy entry (the Vue source's `StrategyBacktestResult`).
 */

import {
  formatNumber,
  formatPercent,
  formatPrice,
  formatTimestamp,
  humanizeDuration,
} from './format'

/* -------------------------------------------------------------------------- */
/* Shapes                                                                      */
/* -------------------------------------------------------------------------- */

/** One closed trade in a backtest result — only the fields we read. */
export interface BacktestTradeRow {
  pair?: string
  profit_ratio?: number
  [key: string]: unknown
}

/** A `results_per_*` / tag / pair summary row. */
export interface BacktestPairResultRow {
  /** Tag name, pair, or `[enter_tag, exit_reason]` for mixed-tag stats. */
  key?: string | string[]
  exit_reason?: string
  trades?: number
  wins?: number
  draws?: number
  losses?: number
  winrate?: number | null
  profit_mean?: number
  profit_total_abs?: number
  profit_total?: number
  cagr?: number
  calmar?: number
  expectancy?: number
  expectancy_ratio?: number
  max_drawdown_abs?: number
  max_drawdown_account?: number
  profit_factor?: number
  sharpe?: number
  sortino?: number
  sqn?: number
  p_value?: number
  [metric: string]: unknown
}

export interface BacktestWalletStats {
  max_drawdown_account?: number
  max_drawdown_abs?: number
  drawdown_duration?: string
  max_drawdown_high?: number
  max_drawdown_low?: number
  drawdown_start_ts?: number
  drawdown_end_ts?: number
  sortino?: number
  sharpe?: number
  calmar?: number
  low_balance?: number
  high_balance?: number
  [key: string]: unknown
}

export interface BacktestPeriodicStat {
  date?: string
  date_ts?: number
  trades?: number
  profit_abs?: number
  profit_factor?: number
  wins?: number
  draws?: number
  /** Deprecated, removed in 2025.3. */
  loses?: number
  losses?: number
}

export interface BacktestPeriodicBreakdown {
  day?: BacktestPeriodicStat[]
  week?: BacktestPeriodicStat[]
  month?: BacktestPeriodicStat[]
  year?: BacktestPeriodicStat[]
  weekday?: BacktestPeriodicStat[]
}

/**
 * A single strategy's backtest result, i.e. `BacktestResult['strategy'][name]`.
 * Deliberately loose: the backend keeps adding optional metrics and the UI must
 * keep rendering older/newer payloads.
 */
export interface BacktestStrategyResult {
  trades?: BacktestTradeRow[]
  results_per_pair?: BacktestPairResultRow[]
  results_per_enter_tag?: BacktestPairResultRow[]
  exit_reason_summary?: BacktestPairResultRow[]
  /** Present in newer backends; replaced `sell_reason_summary`. */
  sell_reason_summary?: BacktestPairResultRow[]
  mix_tag_stats?: BacktestPairResultRow[]
  best_pair?: { key?: string; profit_total?: number } | null
  worst_pair?: { key?: string; profit_total?: number } | null
  periodic_breakdown?: BacktestPeriodicBreakdown
  wallet_stats?: BacktestWalletStats

  stake_currency?: string
  stake_currency_decimals?: number
  strategy_name?: string
  timeframe?: string
  timeframe_detail?: string
  timerange?: string
  trading_mode?: string
  margin_mode?: string
  /** Pairs the backtest ran over, in strategy order. */
  pairlist?: string[]

  total_trades?: number
  trades_per_day?: number
  profit_total?: number
  profit_total_abs?: number
  profit_mean?: number
  cagr?: number
  sortino?: number
  sharpe?: number
  calmar?: number
  sqn?: number
  p_value?: number
  expectancy?: number
  expectancy_ratio?: number
  profit_factor?: number
  market_change?: number

  backtest_start_ts?: number
  backtest_end_ts?: number
  backtest_run_start_ts?: number
  backtest_run_end_ts?: number
  backtest_best_day?: number
  backtest_worst_day?: number
  backtest_best_day_abs?: number
  backtest_worst_day_abs?: number

  max_open_trades?: number
  stoploss?: number
  trailing_stop?: boolean
  trailing_stop_positive?: number
  trailing_stop_positive_offset?: number
  trailing_only_offset_is_reached?: boolean
  use_custom_stoploss?: boolean
  minimal_roi?: Record<string, number>
  use_exit_signal?: boolean
  use_sell_signal?: boolean
  exit_profit_only?: boolean
  sell_profit_only?: boolean
  exit_profit_offset?: number
  sell_profit_offset?: number
  enable_protections?: boolean

  starting_balance?: number
  final_balance?: number
  avg_stake_amount?: number
  total_volume?: number

  winning_days?: number
  draw_days?: number
  losing_days?: number
  winner_holding_min_s?: number
  winner_holding_avg_s?: number
  winner_holding_max_s?: number
  loser_holding_min_s?: number
  loser_holding_avg_s?: number
  loser_holding_max_s?: number
  max_consecutive_wins?: number
  max_consecutive_losses?: number
  rejected_signals?: number
  timedout_entry_orders?: number
  timedout_exit_orders?: number
  canceled_trade_entries?: number
  canceled_entry_orders?: number
  replaced_entry_orders?: number

  csum_min?: number
  csum_max?: number
  max_drawdown_account?: number
  max_drawdown_abs?: number
  drawdown_duration?: string
  max_drawdown_high?: number
  max_drawdown_low?: number
  drawdown_start_ts?: number
  drawdown_end_ts?: number

  trade_count_long?: number
  trade_count_short?: number
  profit_total_long?: number
  profit_total_short?: number
  profit_total_long_abs?: number
  profit_total_short_abs?: number

  [key: string]: unknown
}

/** Alias matching the wording of the original spec: a single backtest result. */
export type BacktestResult = BacktestStrategyResult

/** Metadata attached to an in-memory backtest result. */
export interface BacktestResultMetadata {
  run_id?: string
  filename?: string
  notes?: string
  backtest_run_start_ts?: number
  /** Resolved strategy name (the key inside `strategy`). */
  strategyName: string
  /** Inline notes editor open state. */
  editing?: boolean
  [key: string]: unknown
}

/** One loaded backtest result held in page memory. */
export interface BacktestResultInMemory {
  strategy: BacktestStrategyResult
  metadata: BacktestResultMetadata
}

/** A generated metric/setting row. */
export interface BacktestMetricRow {
  label: string
  value: string
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

const isSet = (value: unknown): boolean => value !== undefined && value !== null

/** Renders any scalar the way Vue's table cell would (empty for unset). */
const asText = (value: unknown): string => (isSet(value) ? String(value) : '')

/** freqUI's `humanizeDurationFromSeconds`: 0/undefined collapse to 'N/A'. */
function durationSeconds(seconds: number | undefined | null): string {
  return seconds ? humanizeDuration(seconds) : 'N/A'
}

/** freqUI's `timestampms`: epoch milliseconds -> "YYYY-MM-DD HH:MM:SS" (UTC). */
function timestampMs(ts: number | undefined | null): string {
  return formatTimestamp(ts ?? 0, { timezone: 'UTC' })
}

/** `"<price> <stake>"`, using the result's own stake decimals. */
function priceStake(
  price: number | null | undefined,
  decimals: number,
  currency: string,
): string {
  return `${formatPrice(price, decimals)} ${currency}`
}

function sortedTrades(trades: BacktestTradeRow[]): BacktestTradeRow[] {
  return trades.slice().sort((a, b) => (a.profit_ratio ?? 0) - (b.profit_ratio ?? 0))
}

function describeTrade(trade: BacktestTradeRow | undefined): string {
  if (!trade) return 'N/A'
  return `${trade.pair} ${formatPercent(trade.profit_ratio, 2)}`
}

function capitalizeFirstLetter(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

/** `{ label: value }` -> `{ label, value }`, preserving order. */
function toRows(entries: Record<string, unknown>[]): BacktestMetricRow[] {
  const rows: BacktestMetricRow[] = []
  for (const entry of entries) {
    const key = Object.keys(entry)[0]
    if (key === undefined) continue
    rows.push({ label: key, value: asText(entry[key]) })
  }
  return rows
}

/* -------------------------------------------------------------------------- */
/* Metric rows                                                                 */
/* -------------------------------------------------------------------------- */

export function generateBacktestMetricRows(result: BacktestResult): BacktestMetricRow[] {
  const trades = result.trades ?? []
  const perPair = result.results_per_pair ?? []
  const ordered = sortedTrades(trades)
  const bestTrade = describeTrade(ordered[ordered.length - 1])
  const worstTrade = describeTrade(ordered[0])
  const pairSummary = perPair[perPair.length - 1]

  const decimals = result.stake_currency_decimals ?? 3
  const stake = result.stake_currency ?? ''
  const stakePrice = (price: number | null | undefined) => priceStake(price, decimals, stake)

  // Long/short split is only meaningful when shorts were actually taken.
  const shortMetrics: Record<string, unknown>[] =
    result.trade_count_short && result.trade_count_short > 0
      ? [
          { '___ ': '___' },
          { 'Long / Short': `${result.trade_count_long} / ${result.trade_count_short}` },
          {
            'Total profit Long': `${formatPercent(result.profit_total_long || 0, 3)} | ${stakePrice(
              result.profit_total_long_abs,
            )}`,
          },
          {
            'Total profit Short': `${formatPercent(result.profit_total_short || 0, 3)} | ${stakePrice(
              result.profit_total_short_abs,
            )}`,
          },
        ]
      : []

  const wallet = result.wallet_stats
  const walletBalanceMetrics: Record<string, unknown>[] = wallet
    ? [
        { '--- Wallet Balance metrics ---': '' },
        {
          'Max Drawdown (wallet balance)': formatPercent(wallet.max_drawdown_account, 3),
        },
        {
          'Max Drawdown abs (wallet balance)': stakePrice(wallet.max_drawdown_abs),
        },
        {
          'Drawdown duration (wallet balance)': wallet.drawdown_duration ?? 'N/A',
        },
        {
          'Profit at Drawdown start | end (wallet balance)': `${stakePrice(
            wallet.max_drawdown_high,
          )} | ${stakePrice(wallet.max_drawdown_low)}`,
        },
        { 'Drawdown start (wallet balance)': timestampMs(wallet.drawdown_start_ts ?? 0) },
        { 'Drawdown end (wallet balance)': timestampMs(wallet.drawdown_end_ts ?? 0) },
        { 'Sortino (wallet balance)': formatNumber(wallet.sortino, 2) },
        { 'Sharpe (wallet balance)': formatNumber(wallet.sharpe, 2) },
        { 'Calmar (wallet balance)': formatNumber(wallet.calmar, 2) },
      ]
    : []

  const entries: Record<string, unknown>[] = [
    {
      'Total Profit': `${formatPercent(result.profit_total, 3)} | ${stakePrice(
        result.profit_total_abs,
      )}`,
    },
    { CAGR: result.cagr ? formatPercent(result.cagr, 3) : 'N/A' },
    { Sortino: formatNumber(result.sortino, 2) },
    { Sharpe: formatNumber(result.sharpe, 2) },
    { Calmar: formatNumber(result.calmar, 2) },
    { 'System Quality Number (SQN)': formatNumber(result.sqn, 2) },
    { 'Mean profit p-value': formatNumber(result.p_value, 3) },
    {
      [`Expectancy ${result.expectancy_ratio ? '(ratio)' : ''}`]: result.expectancy
        ? result.expectancy_ratio
          ? `${formatNumber(result.expectancy, 2)} (${formatNumber(result.expectancy_ratio, 2)})`
          : formatNumber(result.expectancy, 2)
        : 'N/A',
    },
    { 'Profit factor': formatNumber(result.profit_factor, 3) },
    {
      'Total trades / Daily Avg Trades': `${result.total_trades} / ${formatNumber(
        result.trades_per_day,
        2,
      )}`,
    },
    {
      'Best day': `${formatPercent(result.backtest_best_day, 2)} | ${stakePrice(
        result.backtest_best_day_abs,
      )}`,
    },
    {
      'Worst day': `${formatPercent(result.backtest_worst_day, 2)} | ${stakePrice(
        result.backtest_worst_day_abs,
      )}`,
    },
    {
      'Win/Draw/Loss': `${pairSummary?.wins ?? 'N/A'} / ${pairSummary?.draws ?? 'N/A'} / ${
        pairSummary?.losses ?? 'N/A'
      } ${
        isSet(pairSummary?.winrate)
          ? `(WR: ${formatPercent(pairSummary?.winrate ?? 0, 2)})`
          : ''
      }`,
    },
    {
      'Days win/draw/loss': `${result.winning_days ?? 0} / ${result.draw_days ?? 0} / ${
        result.losing_days ?? 0
      }`,
    },
    { 'Min. Duration winners': durationSeconds(result.winner_holding_min_s) },
    { 'Avg. Duration winners': durationSeconds(result.winner_holding_avg_s) },
    { 'Max. Duration winners': durationSeconds(result.winner_holding_max_s) },
    { 'Min. Duration Losers': durationSeconds(result.loser_holding_min_s) },
    { 'Avg. Duration Losers': durationSeconds(result.loser_holding_avg_s) },
    { 'Max. Duration Losers': durationSeconds(result.loser_holding_max_s) },
    {
      'Max Consecutive Wins / Loss':
        result.max_consecutive_wins === undefined
          ? 'N/A'
          : `${result.max_consecutive_wins} / ${result.max_consecutive_losses}`,
    },
    { 'Rejected entry signals': result.rejected_signals },
    {
      'Entry/Exit timeouts': `${result.timedout_entry_orders ?? 0} / ${
        result.timedout_exit_orders ?? 0
      }`,
    },
    { 'Canceled Trade Entries': result.canceled_trade_entries ?? 'N/A' },
    { 'Canceled Entry Orders': result.canceled_entry_orders ?? 'N/A' },
    { 'Replaced Entry Orders': result.replaced_entry_orders ?? 'N/A' },

    ...shortMetrics,

    { ___: '___' },
    {
      'Min/Max balance (closed trades)': `${stakePrice(result.csum_min)} / ${stakePrice(
        result.csum_max,
      )}`,
    },
    {
      'Min/Max balance (wallet balance)': `${stakePrice(wallet?.low_balance)} / ${stakePrice(
        wallet?.high_balance,
      )}`,
    },
    { 'Market change': formatPercent(result.market_change, 3) },
    { '___  ': '___' },
    { 'Max Drawdown (Account)': formatPercent(result.max_drawdown_account, 3) },
    { 'Max Drawdown ABS': stakePrice(result.max_drawdown_abs) },
    { 'Drawdown duration': result.drawdown_duration ?? 'N/A' },
    {
      'Profit at Drawdown start | end': `${stakePrice(result.max_drawdown_high)} | ${stakePrice(
        result.max_drawdown_low,
      )}`,
    },
    { 'Drawdown start': timestampMs(result.drawdown_start_ts) },
    { 'Drawdown end': timestampMs(result.drawdown_end_ts) },
    ...walletBalanceMetrics,
    { '___    ': '___' },
    {
      'Best Pair': `${result.best_pair?.key ?? 'N/A'} ${formatPercent(
        result.best_pair?.profit_total,
        3,
      )}`,
    },
    {
      'Worst Pair': `${result.worst_pair?.key ?? 'N/A'} ${formatPercent(
        result.worst_pair?.profit_total,
        3,
      )}`,
    },
    { 'Best single Trade': bestTrade },
    { 'Worst single Trade': worstTrade },
  ]

  return toRows(entries)
}

/* -------------------------------------------------------------------------- */
/* Setting rows                                                                */
/* -------------------------------------------------------------------------- */

function formatTradingMode(result: BacktestStrategyResult): Record<string, unknown> | null {
  if (!result.trading_mode || !result.margin_mode) return null
  const value =
    result.trading_mode === 'spot'
      ? capitalizeFirstLetter(result.trading_mode)
      : `${capitalizeFirstLetter(result.margin_mode)} ${capitalizeFirstLetter(result.trading_mode)}`
  return { 'Trading Mode': value }
}

export function generateBacktestSettingRows(result: BacktestResult): BacktestMetricRow[] {
  const decimals = result.stake_currency_decimals ?? 3
  const stake = result.stake_currency ?? ''
  const stakePrice = (price: number | null | undefined) => priceStake(price, decimals, stake)
  const tradingMode = formatTradingMode(result)

  const entries: Record<string, unknown>[] = [
    { 'Backtesting from': timestampMs(result.backtest_start_ts) },
    { 'Backtesting to': timestampMs(result.backtest_end_ts) },
    ...(tradingMode ? [tradingMode] : []),
    {
      'BT execution time': durationSeconds(
        (result.backtest_run_end_ts ?? 0) - (result.backtest_run_start_ts ?? 0),
      ),
    },
    { 'Max open trades': result.max_open_trades },
    { Timeframe: result.timeframe },
    { 'Timeframe Detail': result.timeframe_detail || 'N/A' },
    { Timerange: result.timerange },
    { Stoploss: formatPercent(result.stoploss, 2) },
    { 'Trailing Stoploss': result.trailing_stop },
    { 'Trail only when offset is reached': result.trailing_only_offset_is_reached },
    { 'Trailing Stop positive': formatNumber(result.trailing_stop_positive) },
    { 'Trailing stop positive offset': formatNumber(result.trailing_stop_positive_offset) },
    { 'Custom Stoploss': result.use_custom_stoploss },
    { ROI: JSON.stringify(result.minimal_roi) },
    { 'Use Exit Signal': result.use_exit_signal ?? result.use_sell_signal },
    { 'Exit profit only': result.exit_profit_only ?? result.sell_profit_only },
    { 'Exit profit offset': formatNumber(result.exit_profit_offset ?? result.sell_profit_offset) },
    { 'Enable protections': result.enable_protections },
    { 'Starting balance': stakePrice(result.starting_balance) },
    { 'Final balance': stakePrice(result.final_balance) },
    { 'Avg. stake amount': stakePrice(result.avg_stake_amount) },
    { 'Total trade volume': stakePrice(result.total_volume) },
  ]

  return toRows(entries)
}

/* -------------------------------------------------------------------------- */
/* Selectable extra metric columns                                             */
/* -------------------------------------------------------------------------- */

/**
 * Selectable options for the per-pair/tag tables.
 * Selection happens through each table's "Shown metrics" control.
 */
export const availableBacktestMetrics: { field: string; header: string; is_ratio?: boolean }[] = [
  { field: 'sqn', header: 'SQN' },
  { field: 'cagr', header: 'Cagr' },
  { field: 'calmar', header: 'Calmar' },
  { field: 'p_value', header: 'Mean profit p-value' },
  { field: 'expectancy', header: 'Expectancy' },
  { field: 'profit_factor', header: 'Profit Factor' },
  { field: 'sharpe', header: 'Sharpe' },
  { field: 'sortino', header: 'Sortino' },
  { field: 'max_drawdown_account', header: 'Max Drawdown', is_ratio: true },
]
