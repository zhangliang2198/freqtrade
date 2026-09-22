/**
 * Download historical OHLCV / trade data.
 *
 * The POST returns a background job id; progress is followed through
 * `useJobPolling` and rendered by the shared `BackgroundJobTracking` panel.
 */

import { useMemo, useState } from 'react'
import {
  Banner,
  Button,
  Collapse,
  Input,
  InputNumber,
  Select,
  Switch,
  Toast,
  Tooltip,
} from '@douyinfe/semi-ui'
import { IconClose, IconDownload, IconPlus } from '@douyinfe/semi-icons'

import { Panel } from '../components/primitives'
import { BackgroundJobTracking } from '../components/BackgroundJobTracking'
import { ExchangeSelect, SwitchRow, TimeRangeSelect, type ExchangeSelection } from '../components/selects'
import { downloadApi } from '../api/endpoints'
import type { DownloadDataPayload } from '../api/types'
import { ApiError } from '../api/client'
import { useBots } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import { useJobPolling } from '../hooks/useJobPolling'

/**
 * The foundation's `DownloadDataPayload` predates `timeframes` (it declares a
 * singular `timeframe`), `candle_types`, `prepend_data` and the exchange mode
 * fields. The backend schema accepts all of them, so the payload is built
 * against this local shape and cast at the call site.
 */
interface DownloadPayload {
  pairs: string[]
  timeframes: string[]
  days?: number
  timerange?: string
  erase?: boolean
  download_trades?: boolean
  prepend_data?: boolean
  candle_types?: string[]
  exchange?: string
  trading_mode?: string
  margin_mode?: string
}

const PAIR_TEMPLATES: { label: string; pairs: string[] }[] = [
  { label: '所有 USDT 现货对', pairs: ['.*/USDT'] },
  { label: '所有 USDT 合约对', pairs: ['.*/USDT:USDT'] },
]

const CANDLE_TYPES = [
  { value: 'spot', label: 'Spot' },
  { value: 'futures', label: 'Futures' },
  { value: 'funding_rate', label: 'Funding Rate' },
  { value: 'mark', label: 'Mark' },
  { value: 'index', label: 'Index' },
  { value: 'premiumIndex', label: 'Premium Index' },
]

export function DownloadData() {
  const { api } = useBots()
  const { whitelist } = useSnapshot()
  const { jobs, track, clearFinished } = useJobPolling(api, true)

  const [pairs, setPairs] = useState<string[]>(['BTC/USDT', 'ETH/USDT'])
  const [timeframes, setTimeframes] = useState<string[]>(['5m', '1h'])

  const [useCustomTimerange, setUseCustomTimerange] = useState(false)
  const [timerange, setTimerange] = useState('')
  const [days, setDays] = useState<number>(30)

  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [erase, setErase] = useState(false)
  const [prependData, setPrependData] = useState(false)
  const [downloadTrades, setDownloadTrades] = useState(false)
  const [candleTypes, setCandleTypes] = useState<string[]>([])
  const [customExchange, setCustomExchange] = useState(false)
  const [exchange, setExchange] = useState<ExchangeSelection>({
    exchange: 'binance',
    trading_mode: 'spot',
    margin_mode: '',
  })

  const [starting, setStarting] = useState(false)
  const [wrongState, setWrongState] = useState(false)

  const updatePair = (index: number, value: string) =>
    setPairs((prev) => prev.map((pair, i) => (i === index ? value : pair)))
  const removePair = (index: number) =>
    setPairs((prev) => prev.filter((_, i) => i !== index))
  const addPair = () => setPairs((prev) => [...prev, ''])

  const updateTimeframe = (index: number, value: string) =>
    setTimeframes((prev) => prev.map((tf, i) => (i === index ? value : tf)))
  const removeTimeframe = (index: number) =>
    setTimeframes((prev) => prev.filter((_, i) => i !== index))
  const addTimeframe = () => setTimeframes((prev) => [...prev, ''])

  const buildPayload = useMemo(
    () =>
      (): DownloadPayload => {
        const payload: DownloadPayload = {
          pairs: pairs.filter((pair) => pair !== ''),
          timeframes: timeframes.filter((tf) => tf !== ''),
        }

        if (useCustomTimerange && timerange) payload.timerange = timerange
        else payload.days = days

        // Advanced options only apply while the section is expanded.
        if (advancedOpen) {
          payload.erase = erase
          payload.download_trades = downloadTrades

          if (customExchange) {
            payload.exchange = exchange.exchange
            payload.trading_mode = exchange.trading_mode
            payload.margin_mode = exchange.margin_mode
          }
          if (candleTypes.length > 0) payload.candle_types = candleTypes
          if (prependData) payload.prepend_data = true
        }

        return payload
      },
    [
      pairs,
      timeframes,
      useCustomTimerange,
      timerange,
      days,
      advancedOpen,
      erase,
      downloadTrades,
      customExchange,
      exchange,
      candleTypes,
      prependData,
    ],
  )

  const startDownload = async () => {
    if (!api) return
    setStarting(true)
    try {
      const job = await downloadApi.start(api, buildPayload() as unknown as DownloadDataPayload)
      if (job?.job_id) track(job.job_id, 'download_data')
      Toast.success('数据下载已启动')
    } catch (err) {
      if (err instanceof ApiError && err.isWrongState) {
        setWrongState(true)
      } else {
        Toast.error(err instanceof Error ? err.message : '无法启动数据下载')
      }
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">下载数据</h1>
        <span className="ft-page-sub">下载历史 K 线与成交数据到本地数据目录</span>
      </div>

      {wrongState && (
        <Banner
          type="info"
          bordered
          title="需要 webserver 模式"
          description="下载数据需要机器人以 webserver 模式运行。"
        />
      )}

      <BackgroundJobTracking jobs={jobs} onClear={clearFinished} />

      <Panel
        title="下载数据"
        icon={<IconDownload />}
        actions={
          <Button
            size="small"
            type="primary"
            icon={<IconDownload />}
            loading={starting}
            disabled={!api || pairs.filter((p) => p !== '').length === 0}
            onClick={() => void startDownload()}
          >
            开始下载
          </Button>
        }
      >
        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
          <div className="ft-grid cols-2">
            {/* Pairs ------------------------------------------------------ */}
            <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
              <div className="ft-row" style={{ justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 600 }}>选择交易对</span>
                <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  交易对模板
                </span>
              </div>
              <div className="ft-row" style={{ alignItems: 'flex-start', gap: 'var(--ft-gap-4)' }}>
                <div className="ft-col" style={{ gap: 4, flex: '1 1 auto', minWidth: 0 }}>
                  {pairs.map((pair, index) => (
                    <div className="ft-row" key={index} style={{ gap: 4 }}>
                      <Input
                        size="small"
                        value={pair}
                        placeholder="Pair"
                        onChange={(value) => updatePair(index, value)}
                        style={{ flex: '1 1 auto', minWidth: 0 }}
                      />
                      <Button
                        size="small"
                        theme="borderless"
                        type="tertiary"
                        icon={<IconClose />}
                        onClick={() => removePair(index)}
                      />
                    </div>
                  ))}
                  <Button size="small" icon={<IconPlus />} onClick={addPair} style={{ alignSelf: 'flex-start' }}>
                    添加交易对
                  </Button>
                </div>

                <div className="ft-col" style={{ gap: 4, flex: '0 0 180px' }}>
                  {PAIR_TEMPLATES.map((template) => (
                    <Tooltip key={template.label} content={template.pairs.join('\n')}>
                      <Button
                        size="small"
                        onClick={() => setPairs((prev) => [...prev, ...template.pairs])}
                      >
                        {template.label}
                      </Button>
                    </Tooltip>
                  ))}
                  <Button
                    size="small"
                    disabled={whitelist.length === 0}
                    title="使用交易对列表（需先运行交易对配置）"
                    onClick={() => setPairs([...whitelist])}
                  >
                    使用交易对列表
                  </Button>
                </div>
              </div>
            </div>

            {/* Timeframes ------------------------------------------------- */}
            <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
              <span style={{ fontWeight: 600 }}>选择时间周期</span>
              <div className="ft-col" style={{ gap: 4 }}>
                {timeframes.map((tf, index) => (
                  <div className="ft-row" key={index} style={{ gap: 4 }}>
                    <Input
                      size="small"
                      value={tf}
                      placeholder="Timeframe"
                      onChange={(value) => updateTimeframe(index, value)}
                      style={{ flex: '1 1 auto', minWidth: 0 }}
                    />
                    <Button
                      size="small"
                      theme="borderless"
                      type="tertiary"
                      icon={<IconClose />}
                      onClick={() => removeTimeframe(index)}
                    />
                  </div>
                ))}
                <Button
                  size="small"
                  icon={<IconPlus />}
                  onClick={addTimeframe}
                  style={{ alignSelf: 'flex-start' }}
                >
                  添加周期
                </Button>
              </div>
            </div>
          </div>

          {/* Time selection --------------------------------------------- */}
          <div
            style={{
              border: '1px solid var(--ft-line)',
              borderRadius: 'var(--ft-radius)',
              padding: 'var(--ft-gap-5)',
            }}
          >
            <div className="ft-row" style={{ justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 600 }}>时间范围</span>
              <SwitchRow
                label="使用自定义区间"
                checked={useCustomTimerange}
                onChange={setUseCustomTimerange}
              />
            </div>
            <div style={{ marginTop: 'var(--ft-gap-4)' }}>
              {useCustomTimerange ? (
                <TimeRangeSelect value={timerange} onChange={setTimerange} />
              ) : (
                <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
                  <span style={{ fontSize: 'var(--ft-font-sm)' }}>下载天数</span>
                  <InputNumber
                    size="small"
                    hideButtons
                    min={1}
                    step={1}
                    value={days}
                    onChange={(value) => setDays(value === '' ? 1 : Number(value))}
                    style={{ width: 120 }}
                  />
                </div>
              )}
            </div>
          </div>

          {/* Advanced --------------------------------------------------- */}
          <Collapse activeKey={advancedOpen ? 'advanced' : undefined} onChange={() => setAdvancedOpen((v) => !v)}>
            <Collapse.Panel itemKey="advanced" header="高级选项">
              <Banner
                type="info"
                bordered
                description="高级选项（删除数据、下载成交记录、自定义交易所）仅在展开时生效。"
              />

              <div className="ft-col" style={{ gap: 'var(--ft-gap-4)', marginTop: 'var(--ft-gap-4)' }}>
                <SwitchRow label="删除已有数据" checked={erase} onChange={setErase} />
                <SwitchRow
                  label="下载时前置数据"
                  checked={prependData}
                  onChange={setPrependData}
                />
                <SwitchRow
                  label="下载成交记录而非 OHLCV 数据"
                  checked={downloadTrades}
                  onChange={setDownloadTrades}
                />

                <div className="ft-row" style={{ gap: 'var(--ft-gap-5)', alignItems: 'flex-start' }}>
                  <div style={{ flex: '0 0 260px' }}>
                    <Select
                      size="small"
                      multiple
                      value={candleTypes}
                      optionList={CANDLE_TYPES}
                      placeholder="选择 K 线类型"
                      onChange={(value) =>
                        setCandleTypes(Array.isArray(value) ? value.map(String) : [])
                      }
                      style={{ width: '100%' }}
                    />
                  </div>
                  <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                    未选择时 freqtrade 会自动下载常规运行所需的 K 线类型。
                  </span>
                </div>

                <div
                  style={{
                    border: '1px solid var(--ft-line)',
                    borderRadius: 'var(--ft-radius)',
                    padding: 'var(--ft-gap-4)',
                  }}
                >
                  <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
                    <Switch
                      size="small"
                      checked={customExchange}
                      onChange={setCustomExchange}
                    />
                    <span style={{ fontSize: 'var(--ft-font-sm)' }}>自定义交易所</span>
                  </div>
                  {customExchange && (
                    <div style={{ marginTop: 'var(--ft-gap-4)' }}>
                      <ExchangeSelect api={api} value={exchange} onChange={setExchange} />
                    </div>
                  )}
                </div>
              </div>
            </Collapse.Panel>
          </Collapse>
        </div>
      </Panel>
    </div>
  )
}
