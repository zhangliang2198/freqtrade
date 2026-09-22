/**
 * Shared selectors for strategies, timeframes, exchanges, FreqAI models and
 * timeranges.
 *
 * The resource-backed selectors hit webserver-mode endpoints, which a bot in
 * trade mode answers with "Bot is not in the correct state". That is an
 * expected state rather than an error, so those controls degrade to a plain
 * text input seeded from `show_config` instead of failing the page.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Input, Select, Switch, Tooltip } from '@douyinfe/semi-ui'
import { IconRefresh } from '@douyinfe/semi-icons'

import { infoApi } from '../api/endpoints'
import type { BotApi } from '../api/client'
import { ApiError } from '../api/client'

/* -------------------------------------------------------------------------- */
/* Resource hook                                                               */
/* -------------------------------------------------------------------------- */

interface ResourceState<T> {
  data: T | undefined
  /** True when the bot is reachable but not in webserver mode. */
  unavailable: boolean
  loading: boolean
  reload: () => void
}

function useResource<T>(
  api: BotApi | null,
  loader: ((api: BotApi) => Promise<T>) | null,
): ResourceState<T> {
  const [data, setData] = useState<T | undefined>(undefined)
  const [unavailable, setUnavailable] = useState(false)
  const [loading, setLoading] = useState(false)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!api || !loader) return
    let cancelled = false
    setLoading(true)
    loader(api)
      .then((result) => {
        if (cancelled) return
        setData(result)
        setUnavailable(false)
      })
      .catch((err) => {
        if (cancelled) return
        // 404 / "not in the correct state" simply means trade mode.
        if (err instanceof ApiError && err.isWrongState) setUnavailable(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, unavailable, loading, reload }
}

/* -------------------------------------------------------------------------- */
/* Strategy                                                                    */
/* -------------------------------------------------------------------------- */

export function StrategySelect({
  api,
  value,
  onChange,
  placeholder = '选择策略',
  disabled,
  allowFreeText = true,
}: {
  api: BotApi | null
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  /** Fall back to a text input when the strategy list is unavailable. */
  allowFreeText?: boolean
}) {
  const { data, unavailable, reload, loading } = useResource(api, (a) => infoApi.strategies(a))

  const options = useMemo(
    () => Object.keys(data?.strategies ?? {}).map((name) => ({ value: name, label: name })),
    [data],
  )

  if (unavailable && allowFreeText) {
    return (
      <Input
        size="small"
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={onChange}
      />
    )
  }

  return (
    <div className="ft-row" style={{ gap: 4, width: '100%' }}>
      <Select
        size="small"
        value={value || undefined}
        onChange={(v) => onChange(String(v ?? ''))}
        optionList={options}
        placeholder={placeholder}
        disabled={disabled}
        loading={loading}
        filter
        style={{ flex: '1 1 auto', minWidth: 0 }}
      />
      <Tooltip content="刷新策略列表">
        <Button
          size="small"
          theme="borderless"
          type="tertiary"
          icon={<IconRefresh />}
          onClick={reload}
          disabled={disabled}
        />
      </Tooltip>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Timeframe                                                                   */
/* -------------------------------------------------------------------------- */

export const TIMEFRAMES = [
  '1m',
  '3m',
  '5m',
  '15m',
  '30m',
  '1h',
  '2h',
  '4h',
  '6h',
  '8h',
  '12h',
  '1d',
  '3d',
  '1w',
  '2w',
  '1M',
  '1y',
]

export function TimeframeSelect({
  value,
  onChange,
  belowTimeframe,
  disabled,
  allowEmpty = true,
}: {
  value: string
  onChange: (value: string) => void
  /** Restrict options to those strictly shorter than this timeframe. */
  belowTimeframe?: string
  disabled?: boolean
  allowEmpty?: boolean
}) {
  const options = useMemo(() => {
    let list = TIMEFRAMES
    if (belowTimeframe) {
      const index = TIMEFRAMES.indexOf(belowTimeframe)
      if (index > 0) list = TIMEFRAMES.slice(0, index)
    }
    const mapped = list.map((tf) => ({ value: tf, label: tf }))
    return allowEmpty ? [{ value: '', label: '使用策略默认值' }, ...mapped] : mapped
  }, [belowTimeframe, allowEmpty])

  return (
    <Select
      size="small"
      value={value ?? ''}
      onChange={(v) => onChange(String(v ?? ''))}
      optionList={options}
      disabled={disabled}
      placeholder="使用策略默认值"
      style={{ width: '100%' }}
    />
  )
}

/* -------------------------------------------------------------------------- */
/* Exchange + trade mode                                                       */
/* -------------------------------------------------------------------------- */

export interface ExchangeSelection {
  exchange: string
  trading_mode: string
  margin_mode: string
}

export function ExchangeSelect({
  api,
  value,
  onChange,
  disabled,
}: {
  api: BotApi | null
  value: ExchangeSelection
  onChange: (value: ExchangeSelection) => void
  disabled?: boolean
}) {
  const { data, unavailable, reload, loading } = useResource(api, (a) => infoApi.exchanges(a))

  const exchanges = data?.exchanges ?? []
  // `classname` is what the API accepts back; `name` is the display label.
  const current = exchanges.find(
    (e) => e.classname === value.exchange || e.name === value.exchange,
  )

  const exchangeOptions = useMemo(
    () =>
      exchanges.map((e) => ({
        value: e.classname || e.name,
        label: e.name,
      })),
    [exchanges],
  )

  const tradeModeOptions = useMemo(() => {
    const modes = current?.trade_modes ?? []
    return modes.map((tm) => ({
      value: `${tm.trading_mode}|${tm.margin_mode}`,
      label: `${tm.trading_mode}${tm.margin_mode ? ` · ${tm.margin_mode}` : ''}`,
    }))
  }, [current])

  if (unavailable) {
    return (
      <Input
        size="small"
        value={value.exchange}
        disabled={disabled}
        onChange={(v) => onChange({ ...value, exchange: v })}
        placeholder="交易所名称"
      />
    )
  }

  return (
    <div className="ft-row" style={{ gap: 4, width: '100%' }}>
      <Select
        size="small"
        value={value.exchange || undefined}
        onChange={(v) => onChange({ ...value, exchange: String(v ?? '') })}
        optionList={exchangeOptions}
        placeholder="选择交易所"
        disabled={disabled}
        loading={loading}
        filter
        style={{ flex: '1 1 auto', minWidth: 0 }}
      />
      <Select
        size="small"
        value={value.trading_mode ? `${value.trading_mode}|${value.margin_mode}` : undefined}
        onChange={(v) => {
          const [trading_mode, margin_mode] = String(v ?? '').split('|')
          onChange({ ...value, trading_mode, margin_mode })
        }}
        optionList={tradeModeOptions}
        placeholder="模式"
        disabled={disabled || tradeModeOptions.length < 2}
        style={{ width: 132 }}
      />
      <Tooltip content="刷新交易所列表">
        <Button
          size="small"
          theme="borderless"
          type="tertiary"
          icon={<IconRefresh />}
          onClick={reload}
          disabled={disabled}
        />
      </Tooltip>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* FreqAI model                                                                */
/* -------------------------------------------------------------------------- */

export function FreqAIModelSelect({
  api,
  value,
  onChange,
  disabled,
}: {
  api: BotApi | null
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const { data, unavailable, reload, loading } = useResource(api, (a) => infoApi.freqaiModels(a))
  const options = (data?.freqaimodels ?? []).map((m) => ({ value: m, label: m }))

  if (unavailable) {
    return (
      <Input
        size="small"
        value={value}
        disabled={disabled}
        onChange={onChange}
        placeholder="模型名称"
      />
    )
  }

  return (
    <div className="ft-row" style={{ gap: 4, width: '100%' }}>
      <Select
        size="small"
        value={value || undefined}
        onChange={(v) => onChange(String(v ?? ''))}
        optionList={options}
        placeholder="使用配置默认值"
        disabled={disabled}
        loading={loading}
        filter
        style={{ flex: '1 1 auto', minWidth: 0 }}
      />
      <Button
        size="small"
        theme="borderless"
        type="tertiary"
        icon={<IconRefresh />}
        onClick={reload}
        disabled={disabled}
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Timerange                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * Converts a freqtrade timerange part ("20260101" / "20260101T1200") into the
 * date and time inputs. Accepts 10/13-digit unix timestamps too.
 */
export function parseTimeRangePart(part: string): { date: string; time: string } {
  if (!part) return { date: '', time: '' }
  const digits = part.replace(/\D/g, '')
  if (digits.length === 10 || digits.length === 13) {
    const ms = digits.length === 10 ? Number(digits) * 1000 : Number(digits)
    const d = new Date(ms)
    if (Number.isNaN(d.getTime())) return { date: '', time: '' }
    const pad = (n: number) => String(n).padStart(2, '0')
    return {
      date: `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`,
      time: `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`,
    }
  }
  const m = /^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?$/.exec(part)
  if (!m) return { date: '', time: '' }
  const [, y, mo, d, hh, mm, ss] = m
  return {
    date: `${y}-${mo}-${d}`,
    time: hh ? `${hh}:${mm}${ss ? `:${ss}` : ''}` : '',
  }
}

/** Builds a timerange part, emitting the lowest precision that keeps the info. */
export function buildTimeRangePart(date: string, time: string): string {
  if (!date) return ''
  const compact = date.replace(/-/g, '')
  if (!time) return compact
  const [hh = '00', mm = '00', ss = '00'] = time.split(':')
  if (hh === '00' && mm === '00' && ss === '00') return compact
  if (ss === '00') return `${compact}T${hh}${mm}`
  return `${compact}T${hh}${mm}${ss}`
}

export function TimeRangeSelect({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const [from, setFrom] = useState(() => parseTimeRangePart(value.split('-')[0] ?? ''))
  const [to, setTo] = useState(() => parseTimeRangePart(value.split('-')[1] ?? ''))

  // Re-sync when the value changes from outside (e.g. loading a backtest).
  useEffect(() => {
    const [a, b] = value.split('-')
    setFrom(parseTimeRangePart(a ?? ''))
    setTo(parseTimeRangePart(b ?? ''))
  }, [value])

  const emit = (nextFrom: typeof from, nextTo: typeof to) => {
    const start = buildTimeRangePart(nextFrom.date, nextFrom.time)
    const end = buildTimeRangePart(nextTo.date, nextTo.time)
    onChange(start || end ? `${start}-${end}` : '')
  }

  return (
    <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
      <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
        <Input
          size="small"
          type="date"
          value={from.date}
          disabled={disabled}
          onChange={(v) => {
            const next = { ...from, date: v }
            setFrom(next)
            emit(next, to)
          }}
          style={{ flex: '1 1 0' }}
        />
        <Input
          size="small"
          value={from.time}
          placeholder="HH:mm"
          disabled={disabled}
          onChange={(v) => {
            const next = { ...from, time: v }
            setFrom(next)
            emit(next, to)
          }}
          style={{ width: 84 }}
        />
      </div>
      <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
        <Input
          size="small"
          type="date"
          value={to.date}
          disabled={disabled}
          onChange={(v) => {
            const next = { ...to, date: v }
            setTo(next)
            emit(from, next)
          }}
          style={{ flex: '1 1 0' }}
        />
        <Input
          size="small"
          value={to.time}
          placeholder="HH:mm"
          disabled={disabled}
          onChange={(v) => {
            const next = { ...to, time: v }
            setTo(next)
            emit(from, next)
          }}
          style={{ width: 84 }}
        />
      </div>
      <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
        <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
          Timerange
        </span>
        <span className="ft-mono-sm">{value || '（未设置，使用默认区间）'}</span>
        {value && (
          <Button
            size="small"
            theme="borderless"
            type="tertiary"
            onClick={() => {
              setFrom({ date: '', time: '' })
              setTo({ date: '', time: '' })
              onChange('')
            }}
            disabled={disabled}
          >
            清除
          </Button>
        )}
      </div>
    </div>
  )
}

/** Small labelled checkbox row used across the tool pages. */
export function SwitchRow({
  label,
  help,
  checked,
  onChange,
  disabled,
}: {
  label: string
  help?: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="ft-row" style={{ gap: 'var(--ft-gap-4)', minHeight: 26 }}>
      <Switch size="small" checked={checked} onChange={onChange} disabled={disabled} />
      <span style={{ fontSize: 'var(--ft-font-sm)' }}>{label}</span>
      {help && (
        <Tooltip content={help}>
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)', cursor: 'help' }}>
            ?
          </span>
        </Tooltip>
      )}
    </div>
  )
}
