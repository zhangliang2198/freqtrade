/**
 * Candle visualisation for a loaded backtest result.
 *
 * Pair navigation sits on the left (per-pair profit from the result), the
 * candlestick chart in the middle, and a trade navigator on the right: picking
 * a trade switches to its pair and zooms the chart onto that trade's window.
 *
 * Note: the foundation's `CandleChart` exposes no imperative "focus range" API,
 * so zooming is implemented by slicing the candle array around the trade.
 */

import { useEffect, useMemo, useState } from 'react'
import { Banner, Button, Spin } from '@douyinfe/semi-ui'
import { IconChevronLeft, IconChevronRight, IconClose } from '@douyinfe/semi-icons'

import { CandleChart } from './charts'
import { EmptyState, Panel, Tag } from './primitives'
import { ApiError, type BotApi } from '../api/client'
import { decodeCandles, tradingApi } from '../api/endpoints'
import type { Candle, Trade } from '../api/types'
import { displayPair, formatPercent, signClass } from '../utils/format'
import type { BacktestPairResultRow, BacktestStrategyResult } from '../utils/backtestMetrics'

export interface BacktestResultChartProps {
  result: BacktestStrategyResult
  timeframe: string
  strategy: string
  timerange: string
  api: BotApi
}

/** Candles of padding kept on each side when zoomed onto a trade. */
const FOCUS_PADDING = 15

export function BacktestResultChart({
  result,
  timeframe,
  strategy,
  timerange,
  api,
}: BacktestResultChartProps) {
  const pairs = useMemo(() => result.pairlist ?? [], [result.pairlist])
  const allTrades = useMemo(() => (result.trades ?? []) as unknown as Trade[], [result.trades])

  const [selectedPair, setSelectedPair] = useState<string>('')
  const [candles, setCandles] = useState<Candle[]>([])
  const [loadedKey, setLoadedKey] = useState('')
  const [error, setError] = useState<Error | null>(null)
  const [focusedTradeId, setFocusedTradeId] = useState<number | null>(null)
  const [showPairs, setShowPairs] = useState(true)
  const [showTrades, setShowTrades] = useState(true)

  // The effective pair is derived: an explicit selection wins while it still
  // exists in the result, otherwise the first pair is used. This avoids
  // syncing state from props inside an effect.
  const pair = pairs.includes(selectedPair) ? selectedPair : (pairs[0] ?? '')
  const canFetch = Boolean(api && pair && timeframe)
  const requestKey = `${pair}|${timeframe}|${timerange}|${strategy}`
  // Loading is derived from the request key rather than set inside the effect.
  const loading = canFetch && loadedKey !== requestKey

  useEffect(() => {
    if (!canFetch) return
    let cancelled = false
    const controller = new AbortController()

    tradingApi
      .pairHistory(
        api,
        { pair, timeframe, timerange, strategy, live_mode: false },
        controller.signal,
      )
      .then((history) => {
        if (cancelled) return
        setCandles(decodeCandles(history))
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return
        setError(err instanceof Error ? err : new Error(String(err)))
        setCandles([])
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [canFetch, requestKey, api, pair, timeframe, timerange, strategy])

  const pairTrades = useMemo(
    () => allTrades.filter((trade) => trade.pair === pair),
    [allTrades, pair],
  )

  const pairRows = useMemo(() => {
    const byKey = new Map<string, BacktestPairResultRow>()
    for (const row of result.results_per_pair ?? []) {
      if (typeof row.key === 'string') byKey.set(row.key, row)
    }
    const list = (pairs.length > 0 ? pairs : [...byKey.keys()]).map((name) => ({
      name,
      row: byKey.get(name),
    }))
    list.sort((a, b) => (b.row?.profit_total ?? -Infinity) - (a.row?.profit_total ?? -Infinity))
    return list
  }, [pairs, result.results_per_pair])

  // Zoom the chart onto the focused trade's window (if any).
  const visibleCandles = useMemo(() => {
    if (focusedTradeId === null || candles.length === 0) return candles
    const trade = pairTrades.find((t) => t.trade_id === focusedTradeId)
    if (!trade?.open_timestamp) return candles
    const openSec = Math.floor(trade.open_timestamp / 1000)
    const closeSec = Math.floor((trade.close_timestamp ?? trade.open_timestamp) / 1000)
    let first = candles.findIndex((c) => c.time >= openSec)
    let last = candles.findIndex((c) => c.time >= closeSec)
    if (first === -1) first = 0
    if (last === -1) last = candles.length - 1
    return candles.slice(
      Math.max(0, first - FOCUS_PADDING),
      Math.min(candles.length, last + FOCUS_PADDING + 1),
    )
  }, [candles, focusedTradeId, pairTrades])

  const focusedTrade = pairTrades.find((t) => t.trade_id === focusedTradeId)
  const wrongState = error instanceof ApiError && error.isWrongState

  const selectPair = (name: string) => {
    setSelectedPair(name)
    setFocusedTradeId(null)
  }

  const navigateToTrade = (trade: Trade) => {
    if (trade.pair && trade.pair !== pair) setSelectedPair(trade.pair)
    setFocusedTradeId((current) => (current === trade.trade_id ? null : trade.trade_id))
  }

  if (pairs.length === 0) {
    return (
      <Panel title="可视化" sub={timeframe}>
        <EmptyState title="该回测结果没有交易对" hint="无法加载K线数据" />
      </Panel>
    )
  }

  return (
    <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
      <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
        <Button
          size="small"
          theme="borderless"
          type="tertiary"
          icon={showPairs ? <IconChevronLeft /> : <IconChevronRight />}
          title="交易对导航"
          onClick={() => setShowPairs((v) => !v)}
        />
        <span className="ft-page-sub" style={{ flex: '1 1 auto' }}>
          图表始终显示所选策略的最新数据 · Timerange: {timerange || '（默认区间）'} · {strategy}
        </span>
        <Button
          size="small"
          theme="borderless"
          type="tertiary"
          icon={showTrades ? <IconChevronRight /> : <IconChevronLeft />}
          title="交易导航"
          onClick={() => setShowTrades((v) => !v)}
        />
      </div>

      {wrongState && (
        <Banner
          type="info"
          bordered
          title="需要 webserver 模式"
          description="可视化回测结果需要机器人以 webserver 模式运行。"
        />
      )}

      {error && !wrongState && !loading && (
        <Banner type="danger" bordered title="K线加载失败" description={error.message} />
      )}

      <div className="ft-row" style={{ alignItems: 'stretch', gap: 'var(--ft-gap-4)' }}>
        {showPairs && (
          <Panel title="交易对" sub={`${pairRows.length}`} flush className="ft-nowrap">
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 520, overflowY: 'auto' }}>
              {pairRows.map(({ name, row }) => {
                const selected = name === pair
                return (
                  <li
                    key={name}
                    onClick={() => selectPair(name)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 'var(--ft-gap-3)',
                      padding: '4px 10px',
                      cursor: 'pointer',
                      borderBottom: '1px solid var(--ft-line)',
                      background: selected ? 'var(--ft-paper-3)' : undefined,
                    }}
                  >
                    <span
                      className="ft-nowrap"
                      style={{ fontSize: 'var(--ft-font-sm)', minWidth: 96 }}
                    >
                      {displayPair(name)}
                    </span>
                    <span className="ft-num ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                      {row?.trades ?? 0}
                    </span>
                    <span
                      className={`ft-num ${signClass(row?.profit_total)}`}
                      style={{ marginLeft: 'auto', fontSize: 'var(--ft-font-xs)' }}
                    >
                      {formatPercent(row?.profit_total, 2)}
                    </span>
                  </li>
                )
              })}
            </ul>
          </Panel>
        )}

        <div style={{ flex: '1 1 auto', minWidth: 0 }}>
          <Panel
            title={displayPair(pair)}
            sub={`${timeframe}${focusedTrade ? ` · #${focusedTrade.trade_id}` : ''}`}
            actions={
              focusedTrade ? (
                <Button
                  size="small"
                  theme="borderless"
                  type="tertiary"
                  icon={<IconClose />}
                  onClick={() => setFocusedTradeId(null)}
                >
                  查看全部
                </Button>
              ) : undefined
            }
          >
            {canFetch && loading ? (
              <div style={{ display: 'grid', placeItems: 'center', minHeight: 260 }}>
                <Spin />
              </div>
            ) : (
              <CandleChart
                candles={canFetch ? visibleCandles : []}
                trades={pairTrades}
                height={420}
              />
            )}
          </Panel>
        </div>

        {showTrades && (
          <Panel title="交易" sub={`${pairTrades.length}`} flush className="ft-nowrap">
            {pairTrades.length === 0 ? (
              <EmptyState title="该交易对没有交易" />
            ) : (
              <ul
                style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 520, overflowY: 'auto' }}
              >
                {pairTrades.map((trade) => {
                  const selected = trade.trade_id === focusedTradeId
                  return (
                    <li
                      key={trade.trade_id}
                      onClick={() => navigateToTrade(trade)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 'var(--ft-gap-3)',
                        padding: '4px 10px',
                        cursor: 'pointer',
                        borderBottom: '1px solid var(--ft-line)',
                        background: selected ? 'var(--ft-paper-3)' : undefined,
                      }}
                    >
                      <span className="ft-num ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                        #{trade.trade_id}
                      </span>
                      <Tag variant="plain">{trade.exit_reason ?? '–'}</Tag>
                      <span
                        className={`ft-num ${signClass(trade.profit_ratio)}`}
                        style={{ marginLeft: 'auto', fontSize: 'var(--ft-font-xs)' }}
                      >
                        {formatPercent(trade.profit_ratio, 2)}
                      </span>
                    </li>
                  )
                })}
              </ul>
            )}
          </Panel>
        )}
      </div>
    </div>
  )
}
