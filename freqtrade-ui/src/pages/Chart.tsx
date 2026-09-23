/**
 * K-line chart page.
 *
 * Works in both bot states the API exposes:
 *
 *   trade mode     — the bot serves candles it has cached for its *own*
 *                    timeframe, and the pair universe is the whitelist.
 *   webserver mode — `/available_pairs` enumerates every cached pair for the
 *                    chosen timeframe, and any pair can be inspected.
 *
 * Empty results are a normal outcome (the pair/timeframe simply is not cached),
 * so they are explained rather than treated as errors.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Banner, Button, Select, SideSheet, Switch, Tooltip } from '@douyinfe/semi-ui'
import {
  IconArrowDown,
  IconArrowUp,
  IconCandlestickChartStroked,
  IconConfigStroked,
  IconList,
  IconRefresh,
} from '@douyinfe/semi-icons'

import { ApiError } from '../api/client'
import { decodeCandles, pairlistApi, tradingApi } from '../api/endpoints'
import type { Candle, PairHistory, Trade } from '../api/types'
import { CandleChart } from '../components/charts'
import { Panel, StatTile } from '../components/primitives'
import {
  PlotConfigurator,
  loadActivePlotConfig,
  plotConfigColumns,
} from '../components/PlotConfigurator'
import { TimeframeSelect } from '../components/selects'
import { TradeList } from '../components/TradeList'
import { useApi } from '../state/bots'
import { useTopicTick } from '../state/live'
import { useSettings } from '../state/settings'
import { useSnapshot } from '../state/snapshot'
import { formatNumber, formatTimestamp, timeAgo } from '../utils/format'
import { toHeikinAshi } from '../utils/candles'

const MAX_COMPARE_PAIRS = 4

/* -------------------------------------------------------------------------- */
/* Data helpers                                                                */
/* -------------------------------------------------------------------------- */

interface PairDataset {
  history?: PairHistory
  candles: Candle[]
  error?: string
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.detail
  if (err instanceof Error) return err.message
  return String(err)
}

/** Fetches candles for every selected pair; one failure never sinks the rest. */
function usePairDatasets(
  api: ReturnType<typeof useApi>,
  pairs: string[],
  timeframe: string,
  limit: number,
  revision: number,
  /** When set, only these columns are requested (POST /pair_candles). */
  columns?: string[],
): { datasets: Record<string, PairDataset>; loading: boolean } {
  const pairsKey = pairs.join('|')
  const columnsKey = columns?.join(',') ?? ''
  const [datasets, setDatasets] = useState<Record<string, PairDataset>>({})
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!pairs.length) {
      setDatasets({})
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)

    void (async () => {
      const results = await Promise.all(
        pairs.map(async (pair): Promise<[string, PairDataset]> => {
          try {
            const history = await tradingApi.pairCandles(api, { pair, timeframe, limit, columns })
            return [pair, { history, candles: decodeCandles(history) }]
          } catch (err) {
            return [pair, { candles: [], error: errorText(err) }]
          }
        }),
      )
      if (cancelled) return
      setDatasets(Object.fromEntries(results))
      setLoading(false)
    })()

    return () => {
      cancelled = true
    }
    // `pairsKey` stands in for the array identity of `pairs`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, pairsKey, timeframe, limit, revision, columnsKey])

  return { datasets, loading }
}

/** Closed trades for the selected pairs, keyed by pair. */
function usePairTrades(
  api: ReturnType<typeof useApi>,
  pairs: string[],
  revision: number,
): Record<string, Trade[]> {
  const pairsKey = pairs.join('|')
  const [byPair, setByPair] = useState<Record<string, Trade[]>>({})

  useEffect(() => {
    if (!pairs.length) {
      setByPair({})
      return
    }
    let cancelled = false

    void (async () => {
      try {
        // `/trades` takes only limit/offset/order_by_id — it has no `pair`
        // parameter and silently ignores one, returning the whole history. The
        // panel therefore used to label 168 global trades as the focused pair's
        // records. Fetch once and split here instead of asking per pair.
        const response = await tradingApi.trades(api, { limit: 500 })
        if (cancelled) return
        const grouped: Record<string, Trade[]> = {}
        for (const pair of pairs) grouped[pair] = []
        for (const trade of response?.trades ?? []) {
          if (grouped[trade.pair]) grouped[trade.pair].push(trade)
        }
        setByPair(grouped)
      } catch {
        if (!cancelled) setByPair(Object.fromEntries(pairs.map((pair) => [pair, []])))
      }
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, pairsKey, revision])

  return byPair
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export function Chart() {
  const api = useApi()
  const { config, whitelist, openTrades } = useSnapshot()
  const { settings, update } = useSettings()

  const isWebserver = config?.runmode === 'webserver'
  const botTimeframe = config?.timeframe ?? '5m'

  const [timeframe, setTimeframe] = useState(botTimeframe)
  const [availablePairs, setAvailablePairs] = useState<string[]>([])
  const [pairsUnavailable, setPairsUnavailable] = useState(false)
  const [selectedPairs, setSelectedPairs] = useState<string[]>([])
  const [showVolume, setShowVolume] = useState(true)
  const [selectedTradeId, setSelectedTradeId] = useState<number | null>(null)
  const [plotConfigOpen, setPlotConfigOpen] = useState(false)
  const [plotConfig, setPlotConfig] = useState(() => loadActivePlotConfig())
  const [nonce, setNonce] = useState(0)

  const chartRef = useRef<HTMLDivElement | null>(null)

  // Follow the bot's own timeframe when it becomes known / changes.
  useEffect(() => {
    setTimeframe(botTimeframe)
  }, [botTimeframe])

  /* Pair universe --------------------------------------------------------- */

  // The whitelist array identity changes on every snapshot refresh; keying on
  // its content keeps this from re-fetching `/available_pairs` needlessly.
  const whitelistKey = whitelist.join(',')

  useEffect(() => {
    if (!isWebserver) {
      setAvailablePairs(whitelist)
      setPairsUnavailable(false)
      return
    }
    let cancelled = false
    pairlistApi
      .availablePairs(api, { timeframe })
      .then((response) => {
        if (cancelled) return
        setAvailablePairs(response?.pairs ?? [])
        setPairsUnavailable(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        // A bot that flipped out of webserver mode answers "not in the correct
        // state"; fall back to the whitelist instead of showing an error.
        setPairsUnavailable(err instanceof ApiError && err.isWrongState)
        setAvailablePairs(whitelist)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, isWebserver, timeframe, whitelistKey])

  // Keep the selection valid: drop pairs that vanished, seed the first one.
  useEffect(() => {
    if (!availablePairs.length) return
    setSelectedPairs((prev) => {
      const valid = prev.filter((pair) => availablePairs.includes(pair))
      const capped = settings.multiPairSelection ? valid : valid.slice(0, 1)
      if (capped.length) return capped
      return [availablePairs[0]]
    })
  }, [availablePairs, settings.multiPairSelection])

  // Compare mode is capped so the pane grid stays readable.
  const chartPairs = useMemo(
    () =>
      settings.multiPairSelection
        ? selectedPairs.slice(0, MAX_COMPARE_PAIRS)
        : selectedPairs.slice(0, 1),
    [selectedPairs, settings.multiPairSelection],
  )

  const focusPair = chartPairs[0] ?? ''

  /* Data ------------------------------------------------------------------ */

  const candleTick = useTopicTick(['new_candle'])
  const tradeTick = useTopicTick(['entry', 'entry_fill', 'exit', 'exit_fill'])

  const usedColumns = useMemo(() => plotConfigColumns(plotConfig), [plotConfig])

  const { datasets, loading } = usePairDatasets(
    api,
    chartPairs,
    timeframe,
    settings.chartDefaultCandleCount,
    candleTick + nonce,
    // "只请求必要的列" — the GET endpoint cannot filter columns, so the setting
    // switches to the POST variant. This also finally sends the plot
    // configurator's column selection, which was displayed but never requested.
    settings.useReducedPairCalls && usedColumns.length ? usedColumns : undefined,
  )
  const closedTrades = usePairTrades(api, chartPairs, tradeTick + nonce)

  const tradesByPair = useMemo(() => {
    const map: Record<string, Trade[]> = {}
    for (const pair of chartPairs) {
      const closed = closedTrades[pair] ?? []
      const open = openTrades.filter((trade) => trade.pair === pair)
      map[pair] = [...closed, ...open]
    }
    return map
  }, [chartPairs, closedTrades, openTrades])

  const focusDataset = focusPair ? datasets[focusPair] : undefined
  const history = focusDataset?.history
  const datasetColumns = useMemo(() => history?.all_columns ?? history?.columns ?? [], [history])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  const onSelectTrade = useCallback((trade: Trade) => {
    setSelectedTradeId(trade.trade_id)
    chartRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [])

  const isTradeModeTimeframeMismatch = !isWebserver && timeframe !== botTimeframe

  /* Render ---------------------------------------------------------------- */

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">K 线图</h1>
        <span className="ft-page-sub">
          {isWebserver
            ? 'webserver 模式 · 可选任意已缓存交易对'
            : `交易模式 · 机器人周期 ${botTimeframe}`}
        </span>
        <div style={{ marginLeft: 'auto' }} className="ft-row">
          <Button
            size="small"
            icon={<IconRefresh spin={loading} />}
            onClick={refresh}
            disabled={!chartPairs.length}
          >
            刷新
          </Button>
        </div>
      </div>

      {pairsUnavailable && (
        <Banner
          type="warning"
          bordered
          title="无法读取可用交易对"
          description="机器人当前不在 webserver 模式，已回退到白名单。若需要查看所有已缓存交易对，请以 webserver 模式启动机器人。"
        />
      )}

      {isTradeModeTimeframeMismatch && (
        <Banner
          type="warning"
          bordered
          title={`交易模式下只缓存了机器人自身周期（${botTimeframe}）的K线`}
          description={`当前选择的是 ${timeframe}，机器人通常没有该周期的缓存，图表会显示为空。切换回 ${botTimeframe} 即可看到数据。`}
        />
      )}

      {/* Controls --------------------------------------------------------- */}
      <Panel
        title="图表控制"
        icon={<IconCandlestickChartStroked />}
        sub={`${chartPairs.length}/${MAX_COMPARE_PAIRS} 交易对 · ${timeframe}`}
        actions={
          <Tooltip content="配置主图 / 子图指标列">
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconConfigStroked />}
              onClick={() => setPlotConfigOpen(true)}
            >
              图表配置
            </Button>
          </Tooltip>
        }
      >
        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
          <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-5)' }}>
            <div className="ft-col" style={{ gap: 2, flex: '1 1 260px', minWidth: 200 }}>
              <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                交易对
              </span>
              {settings.multiPairSelection ? (
                <Select
                  size="small"
                  multiple
                  max={MAX_COMPARE_PAIRS}
                  maxTagCount={MAX_COMPARE_PAIRS}
                  value={selectedPairs}
                  onChange={(value) =>
                    setSelectedPairs(Array.isArray(value) ? value.map(String) : [])
                  }
                  optionList={availablePairs.map((pair) => ({ value: pair, label: pair }))}
                  placeholder="选择交易对（最多 4 个）"
                  filter
                  style={{ width: '100%' }}
                />
              ) : (
                <Select
                  size="small"
                  value={focusPair || undefined}
                  onChange={(value) => setSelectedPairs(value ? [String(value)] : [])}
                  optionList={availablePairs.map((pair) => ({ value: pair, label: pair }))}
                  placeholder={availablePairs.length ? '选择交易对' : '暂无可用交易对'}
                  filter
                  style={{ width: '100%' }}
                />
              )}
            </div>

            <div className="ft-col" style={{ gap: 2, width: 120 }}>
              <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                周期
              </span>
              <TimeframeSelect value={timeframe} onChange={setTimeframe} allowEmpty={false} />
            </div>

            <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', paddingTop: 14 }}>
              <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-5)' }}>
                <label className="ft-row" style={{ gap: 6, fontSize: 'var(--ft-font-sm)' }}>
                  <Switch size="small" checked={showVolume} onChange={setShowVolume} />
                  显示成交量
                </label>
                <label className="ft-row" style={{ gap: 6, fontSize: 'var(--ft-font-sm)' }}>
                  <Switch
                    size="small"
                    checked={settings.useHeikinAshiCandles}
                    onChange={(checked) => update({ useHeikinAshiCandles: checked })}
                  />
                  Heikin-Ashi
                </label>
                <label className="ft-row" style={{ gap: 6, fontSize: 'var(--ft-font-sm)' }}>
                  <Switch
                    size="small"
                    checked={settings.multiPairSelection}
                    onChange={(checked) => update({ multiPairSelection: checked })}
                  />
                  多交易对
                </label>
                <label className="ft-row" style={{ gap: 6, fontSize: 'var(--ft-font-sm)' }}>
                  <Switch
                    size="small"
                    checked={settings.showMarkArea}
                    onChange={(checked) => update({ showMarkArea: checked })}
                  />
                  显示标记
                </label>
              </div>
            </div>
          </div>

          {usedColumns.length > 0 && (
            <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-2)' }}>
              <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                绘图列
              </span>
              {usedColumns.map((column) => (
                <span className="ft-tag" key={column}>
                  {column}
                </span>
              ))}
            </div>
          )}
        </div>
      </Panel>

      {/* Stats strip ------------------------------------------------------ */}
      <div className="ft-grid cols-6">
        <StatTile
          icon={<IconCandlestickChartStroked />}
          label="已加载K线"
          value={formatNumber(focusDataset?.candles.length ?? 0, 0)}
          meta={`请求上限 ${settings.chartDefaultCandleCount}`}
        />
        <StatTile
          icon={<IconRefresh />}
          label="最近分析"
          value={history ? timeAgo(history.last_analyzed_ts) : '–'}
          meta={history ? formatTimestamp(history.last_analyzed_ts) : '尚未分析'}
          compact
        />
        <StatTile icon={<IconList />} label="数据开始" value={history?.data_start ?? '–'} compact />
        <StatTile icon={<IconList />} label="数据结束" value={history?.data_stop ?? '–'} compact />
        <StatTile
          icon={<IconArrowUp />}
          label="多头信号"
          value={formatNumber(history ? history.enter_long_signals || history.buy_signals : 0, 0)}
          meta={`离场 ${history ? history.exit_long_signals || history.sell_signals : 0}`}
        />
        <StatTile
          icon={<IconArrowDown />}
          label="空头信号"
          value={formatNumber(history ? history.enter_short_signals : 0, 0)}
          meta={`离场 ${history ? history.exit_short_signals : 0}`}
        />
      </div>

      {/* Charts + trade pane ---------------------------------------------- */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) 360px',
          gap: 'var(--ft-gap-5)',
          alignItems: 'start',
        }}
      >
        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)', minWidth: 0 }} ref={chartRef}>
          {chartPairs.length === 0 ? (
            <Panel title="K 线">
              <div className="ft-empty">
                <span className="ft-empty-icon">
                  <IconCandlestickChartStroked />
                </span>
                <div>没有可显示的交易对</div>
                <div className="ft-faint">
                  {availablePairs.length
                    ? '请选择交易对。'
                    : isWebserver
                      ? '该周期没有已缓存的交易对，请先下载数据或选择其他周期。'
                      : '白名单为空，请检查机器人的 pairlist 配置。'}
                </div>
              </div>
            </Panel>
          ) : (
            chartPairs.map((pair) => {
              const dataset = datasets[pair]
              const candles =
                settings.useHeikinAshiCandles && dataset?.candles
                  ? toHeikinAshi(dataset.candles)
                  : (dataset?.candles ?? [])
              return (
                <Panel
                  key={pair}
                  title={pair}
                  icon={<IconCandlestickChartStroked />}
                  sub={
                    dataset
                      ? `${dataset.candles.length} 根K线${dataset.error ? ' · 加载失败' : ''}`
                      : loading
                        ? '加载中…'
                        : ''
                  }
                  actions={
                    <span className="ft-mono-sm ft-faint">
                      {history?.strategy ?? config?.strategy ?? ''}
                    </span>
                  }
                >
                  {dataset?.error ? (
                    <Banner type="danger" bordered title="加载K线失败" description={dataset.error} />
                  ) : (
                    <CandleChart
                      priceScaleSide={settings.chartLabelSide}
                      candles={candles}
                      trades={settings.showMarkArea ? (tradesByPair[pair] ?? []) : []}
                      height={chartPairs.length > 1 ? 260 : 460}
                      showVolume={showVolume}
                    />
                  )}
                </Panel>
              )
            })
          )}
        </div>

        <Panel
          title="交易记录"
          icon={<IconList />}
          sub={focusPair ? `${(tradesByPair[focusPair] ?? []).length} 笔` : undefined}
          flush
        >
          {focusPair ? (
            <TradeList
              trades={tradesByPair[focusPair] ?? []}
              activeTrades={false}
              loading={loading && !focusDataset}
              stakeCurrency={config?.stake_currency ?? 'USDT'}
              stakeCurrencyDecimals={config?.stake_currency_decimals ?? 3}
              tradingMode={config?.trading_mode ?? 'spot'}
              selectedTradeId={selectedTradeId}
              onSelectTrade={onSelectTrade}
              emptyText="该交易对暂无交易记录"
            />
          ) : (
            <div className="ft-empty">
              <div>选择交易对后显示其交易记录</div>
            </div>
          )}
        </Panel>
      </div>

      <SideSheet
        title="图表配置"
        placement="right"
        width={460}
        visible={plotConfigOpen}
        onCancel={() => setPlotConfigOpen(false)}
      >
        <PlotConfigurator
          columns={datasetColumns}
          onChange={(next) => setPlotConfig(next)}
        />
      </SideSheet>
    </div>
  )
}
