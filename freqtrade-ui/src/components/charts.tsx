/**
 * Charts.
 *
 * Financial series use lightweight-charts; the balance donut is a small inline
 * SVG (a pie chart is not worth a second charting dependency).
 *
 * All colours are pulled from the CSS custom properties at render time so the
 * charts follow the black/white theme, with hue reserved for signed values.
 */

import { useEffect, useMemo, useRef } from 'react'
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'

import type { Candle, Trade } from '../api/types'
import { EmptyState } from './primitives'
import { IconLineChartStroked } from '@douyinfe/semi-icons'

/* -------------------------------------------------------------------------- */
/* Theme plumbing                                                              */
/* -------------------------------------------------------------------------- */

interface ChartTheme {
  background: string
  text: string
  grid: string
  border: string
  up: string
  down: string
  neutral: string
}

function readTheme(): ChartTheme {
  const style = getComputedStyle(document.body)
  const get = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    background: get('--ft-paper-1', '#121212'),
    text: get('--ft-ink-3', '#8f8f8f'),
    grid: get('--ft-line', '#262626'),
    border: get('--ft-line-strong', '#383838'),
    up: get('--ft-up', '#4ade80'),
    down: get('--ft-down', '#f87171'),
    neutral: get('--ft-ink-4', '#6b6b6b'),
  }
}

/** Re-runs `setup` whenever the chart host resizes or the theme flips. */
function useChartHost(
  setup: (host: HTMLElement, theme: ChartTheme) => () => void,
  deps: unknown[],
) {
  const hostRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let dispose: (() => void) | undefined
    let cancelled = false

    const mount = () => {
      if (cancelled || !hostRef.current) return
      dispose?.()
      dispose = setup(hostRef.current, readTheme())
    }

    mount()

    // Theme changes flip the attribute on <body>; observe it.
    const observer = new MutationObserver(mount)
    observer.observe(document.body, { attributes: true, attributeFilter: ['theme-mode'] })

    const resize = new ResizeObserver(() => {
      // lightweight-charts handles resize via applyOptions on the chart itself;
      // remounting is simplest and cheap for these sizes.
      mount()
    })
    resize.observe(host)

    return () => {
      cancelled = true
      observer.disconnect()
      resize.disconnect()
      dispose?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return hostRef
}

function baseOptions(theme: ChartTheme, height: number) {
  return {
    height,
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: theme.text,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
      fontSize: 10,
    },
    grid: {
      vertLines: { color: theme.grid, style: LineStyle.Dotted },
      horzLines: { color: theme.grid, style: LineStyle.Dotted },
    },
    rightPriceScale: { borderColor: theme.border },
    timeScale: { borderColor: theme.border, timeVisible: true, secondsVisible: false },
    crosshair: { mode: CrosshairMode.Normal },
    handleScroll: true,
    handleScale: true,
  }
}

/* -------------------------------------------------------------------------- */
/* Candlestick                                                                 */
/* -------------------------------------------------------------------------- */

export function CandleChart({
  candles,
  trades = [],
  height = 360,
  showVolume = true,
  pricePrecision,
  maxMarkedTrades = 40,
}: {
  candles: Candle[]
  /** Trades drawn as entry/exit markers. */
  trades?: Trade[]
  height?: number
  showVolume?: boolean
  pricePrecision?: number
  /**
   * Cap on how many trades get markers. Each trade contributes two labelled
   * markers; with a few hundred closed trades the labels overlap into an
   * unreadable band, so only the most recent ones are drawn.
   */
  maxMarkedTrades?: number
}) {
  const markerKey = trades.map((t) => `${t.trade_id}:${t.is_open}`).join(',')

  const hostRef = useChartHost(
    (host, theme) => {
      const chart: IChartApi = createChart(host, {
        ...baseOptions(theme, height),
        width: host.clientWidth,
      })

      const priceFormat =
        pricePrecision !== undefined
          ? { type: 'price' as const, precision: pricePrecision, minMove: 10 ** -pricePrecision }
          : { type: 'price' as const, precision: 6, minMove: 1e-6 }

      const candleSeries: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
        upColor: theme.up,
        downColor: theme.down,
        borderUpColor: theme.up,
        borderDownColor: theme.down,
        wickUpColor: theme.up,
        wickDownColor: theme.down,
        priceFormat,
      })

      candleSeries.setData(
        candles.map((c) => ({
          time: c.time as UTCTimestamp,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        })),
      )

      let volumeSeries: ISeriesApi<'Histogram'> | undefined
      if (showVolume) {
        volumeSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume',
          color: theme.neutral,
        })
        chart.priceScale('volume').applyOptions({
          scaleMargins: { top: 0.82, bottom: 0 },
        })
        volumeSeries.setData(
          candles.map((c) => ({
            time: c.time as UTCTimestamp,
            value: c.volume,
            color: c.close >= c.open ? `${theme.up}55` : `${theme.down}55`,
          })),
        )
      }

      // Entry/exit markers, placed on the candle nearest each trade timestamp.
      // Only the most recent `maxMarkedTrades` are drawn: the labels of a few
      // hundred trades overlap into an unreadable band across the chart.
      if (trades.length && candles.length) {
        const times = candles.map((c) => c.time)
        const nearest = (ms: number) => {
          const target = Math.floor(ms / 1000)
          let best = times[0]
          let bestDelta = Math.abs(target - best)
          for (const t of times) {
            const delta = Math.abs(target - t)
            if (delta < bestDelta) {
              best = t
              bestDelta = delta
            }
          }
          return best
        }

        const recent = [...trades]
          .sort(
            (a, b) =>
              (b.close_timestamp ?? b.open_timestamp ?? 0) -
              (a.close_timestamp ?? a.open_timestamp ?? 0),
          )
          .slice(0, maxMarkedTrades)

        // Every recent trade gets a marker; exit markers stay unlabelled on
        // purpose because exit reasons are long ("stop_loss on exchange") and
        // repeat, which is what turns a busy chart into a solid block.
        const markers: SeriesMarker<Time>[] = []
        for (const trade of recent) {
          const isShort = trade.is_short
          if (trade.open_timestamp) {
            markers.push({
              time: nearest(trade.open_timestamp) as UTCTimestamp,
              position: isShort ? 'aboveBar' : 'belowBar',
              color: isShort ? theme.down : theme.up,
              shape: isShort ? 'arrowDown' : 'arrowUp',
              text: `#${trade.trade_id}`,
            })
          }
          if (trade.close_timestamp) {
            markers.push({
              time: nearest(trade.close_timestamp) as UTCTimestamp,
              position: isShort ? 'belowBar' : 'aboveBar',
              color: theme.neutral,
              shape: 'circle',
            })
          }
        }
        markers.sort((a, b) => (a.time as number) - (b.time as number))

        // Candle spacing, used to keep labels from colliding. Markers are all
        // drawn; only the *text* is thinned, so a cluster of trades stays
        // visible without becoming a solid run of ids. This pass must run in
        // chronological order for the running comparison to mean anything.
        let step = 0
        if (times.length > 1) {
          const gaps: number[] = []
          for (let i = 1; i < times.length; i += 1) gaps.push(times[i] - times[i - 1])
          gaps.sort((a, b) => a - b)
          step = gaps[Math.floor(gaps.length / 2)] || 0
        }
        const minLabelGap = step * 8
        let lastLabelled = Number.NEGATIVE_INFINITY
        for (const marker of markers) {
          if (!marker.text) continue
          const at = marker.time as number
          if (at - lastLabelled >= minLabelGap) lastLabelled = at
          else delete marker.text
        }

        createSeriesMarkers(candleSeries, markers)
      }

      chart.timeScale().fitContent()

      const onResize = () => chart.applyOptions({ width: host.clientWidth })
      const resizeObserver = new ResizeObserver(onResize)
      resizeObserver.observe(host)

      return () => {
        resizeObserver.disconnect()
        chart.remove()
      }
    },
    [candles, markerKey, height, showVolume, pricePrecision],
  )

  if (!candles.length) {
    return (
      <EmptyState
        icon={<IconLineChartStroked />}
        title="暂无K线数据"
        hint="该周期没有数据。交易模式下只有机器人自身周期（见顶栏 timeframe）有缓存。"
      />
    )
  }

  return <div className="ft-chart" ref={hostRef} />
}

/* -------------------------------------------------------------------------- */
/* Line                                                                        */
/* -------------------------------------------------------------------------- */

export interface LinePoint {
  time: number
  value: number
}

export function LineChart({
  points,
  height = 200,
  /** Colour each segment by whether the value is above/below zero. */
  signColored = false,
  color,
  baseline,
}: {
  points: LinePoint[]
  height?: number
  signColored?: boolean
  color?: string
  /** Draw a dashed reference line at this value. */
  baseline?: number
}) {
  const hostRef = useChartHost(
    (host, theme) => {
      const chart = createChart(host, {
        ...baseOptions(theme, height),
        width: host.clientWidth,
      })

      const stroke = color ?? (signColored ? theme.up : theme.text)

      const series = chart.addSeries(LineSeries, {
        color: stroke,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      })

      series.setData(
        points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })),
      )

      if (baseline !== undefined) {
        series.createPriceLine({
          price: baseline,
          color: theme.border,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: '',
        })
      }

      chart.timeScale().fitContent()

      const resizeObserver = new ResizeObserver(() =>
        chart.applyOptions({ width: host.clientWidth }),
      )
      resizeObserver.observe(host)

      return () => {
        resizeObserver.disconnect()
        chart.remove()
      }
    },
    [points, height, signColored, color, baseline],
  )

  if (!points.length) {
    return (
      <EmptyState icon={<IconLineChartStroked />} title="暂无数据" />
    )
  }

  return <div className="ft-chart" ref={hostRef} />
}

/* -------------------------------------------------------------------------- */
/* Bars                                                                        */
/* -------------------------------------------------------------------------- */

export interface BarDatum {
  label: string
  value: number
}

export function BarChart({
  bars,
  height = 200,
  signColored = true,
}: {
  bars: BarDatum[]
  height?: number
  signColored?: boolean
}) {
  // lightweight-charts needs numeric or time keys; use the index and relabel.
  const hostRef = useChartHost(
    (host, theme) => {
      const chart = createChart(host, {
        ...baseOptions(theme, height),
        width: host.clientWidth,
      })

      const series = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      })

      series.setData(
        bars.map((bar, index) => ({
          time: (index + 1) as UTCTimestamp,
          value: bar.value,
          color: signColored
            ? bar.value >= 0
              ? theme.up
              : theme.down
            : theme.text,
        })),
      )

      chart.timeScale().fitContent()

      const resizeObserver = new ResizeObserver(() =>
        chart.applyOptions({ width: host.clientWidth }),
      )
      resizeObserver.observe(host)

      return () => {
        resizeObserver.disconnect()
        chart.remove()
      }
    },
    [bars, height, signColored],
  )

  if (!bars.length) {
    return <EmptyState icon={<IconLineChartStroked />} title="暂无数据" />
  }

  return (
    <div className="ft-col" style={{ gap: 0 }}>
      <div className="ft-chart" ref={hostRef} />
      {/* lightweight-charts cannot render arbitrary category labels cheaply,
          so the axis labels are rendered beneath as a dense ticker strip. */}
      <div
        className="ft-row ft-mono-sm ft-faint"
        style={{ gap: 'var(--ft-gap-5)', overflowX: 'auto', padding: '0 8px 6px' }}
      >
        {bars.slice(-12).map((bar) => (
          <span key={bar.label} className="ft-nowrap">
            {bar.label}
          </span>
        ))}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Donut (balance composition)                                                 */
/* -------------------------------------------------------------------------- */

export interface DonutSlice {
  label: string
  value: number
}

/**
 * Monochrome donut: slices are drawn in stepped greys so the composition reads
 * without spending hue, which stays reserved for profit/loss.
 */
export function DonutChart({
  slices,
  size = 190,
  thickness = 26,
}: {
  slices: DonutSlice[]
  size?: number
  thickness?: number
}) {
  const total = slices.reduce((sum, s) => sum + Math.max(0, s.value), 0)

  const arcs = useMemo(() => {
    if (total <= 0) return []
    const radius = (size - thickness) / 2
    const circumference = 2 * Math.PI * radius
    let offset = 0

    return slices
      .filter((s) => s.value > 0)
      .map((slice, index) => {
        const fraction = slice.value / total
        const length = fraction * circumference
        const arc = {
          label: slice.label,
          value: slice.value,
          fraction,
          // Stepped greys keep adjacent slices distinguishable.
          shade: 0.15 + (index % 6) * 0.14,
          dashArray: `${length} ${circumference - length}`,
          dashOffset: -offset,
          radius,
          circumference,
        }
        offset += length
        return arc
      })
  }, [slices, total, size, thickness])

  if (total <= 0) {
    return <EmptyState icon={<IconLineChartStroked />} title="无持仓余额" />
  }

  return (
    <div className="ft-row" style={{ gap: 'var(--ft-gap-6)', alignItems: 'center' }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img">
        <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
          {arcs.map((arc) => (
            <circle
              key={arc.label}
              cx={size / 2}
              cy={size / 2}
              r={arc.radius}
              fill="none"
              stroke="var(--ft-ink-0)"
              strokeOpacity={arc.shade}
              strokeWidth={thickness}
              strokeDasharray={arc.dashArray}
              strokeDashoffset={arc.dashOffset}
            />
          ))}
        </g>
        <text
          x="50%"
          y="47%"
          textAnchor="middle"
          fill="var(--ft-ink-3)"
          style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}
        >
          TOTAL
        </text>
        <text
          x="50%"
          y="58%"
          textAnchor="middle"
          fill="var(--ft-ink-0)"
          style={{ fontSize: 16, fontWeight: 600, fontFamily: 'var(--ft-mono)' }}
        >
          {total.toFixed(2)}
        </text>
      </svg>

      <div className="ft-col" style={{ gap: 5, minWidth: 0, flex: '1 1 auto' }}>
        {arcs.map((arc) => (
          <div className="ft-row" key={arc.label} style={{ gap: 'var(--ft-gap-4)' }}>
            <span
              style={{
                width: 9,
                height: 9,
                flex: '0 0 9px',
                borderRadius: 2,
                background: 'var(--ft-ink-0)',
                opacity: arc.shade,
              }}
            />
            <span className="ft-nowrap" style={{ fontSize: 'var(--ft-font-sm)', minWidth: 0 }}>
              {arc.label}
            </span>
            <span className="ft-num ft-muted" style={{ marginLeft: 'auto' }}>
              {(arc.fraction * 100).toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
