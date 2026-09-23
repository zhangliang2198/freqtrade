/**
 * Candle transforms shared by every chart in the app.
 *
 * Lives outside the pages because more than one page draws a chart and they must
 * agree: the chart page honoured the Heikin-Ashi preference while the trade
 * desk's chart silently did not.
 */

import type { Candle } from '../api/types'

/** Heikin-Ashi candles, derived client-side from the raw OHLCV series. */
export function toHeikinAshi(candles: Candle[]): Candle[] {
  const out: Candle[] = []
  for (let i = 0; i < candles.length; i += 1) {
    const candle = candles[i]
    const close = (candle.open + candle.high + candle.low + candle.close) / 4
    const previous = out[i - 1]
    const open = previous
      ? (previous.open + previous.close) / 2
      : (candle.open + candle.close) / 2
    out.push({
      ...candle,
      open,
      close,
      high: Math.max(candle.high, open, close),
      low: Math.min(candle.low, open, close),
    })
  }
  return out
}

/** Applies the user's candle-style preference to a raw series. */
export function applyCandleStyle(candles: Candle[], heikinAshi: boolean): Candle[] {
  return heikinAshi ? toHeikinAshi(candles) : candles
}
