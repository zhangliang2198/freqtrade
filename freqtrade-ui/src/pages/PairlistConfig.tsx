/**
 * Pairlist configurator.
 *
 * Builds a freqtrade `pairlists` chain, evaluates it server-side and shows the
 * resulting whitelist. Everything the bot needs is assembled into the exact
 * payload `/pairlists/evaluate` expects — notably, falsy parameter values are
 * omitted so the backend's own defaults win, mirroring freqUI's store.
 *
 * Requires webserver mode; a bot in trade mode answers "not in the correct
 * state" and gets an explanatory banner instead of an error state.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  Banner,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Select,
  Switch,
  Tabs,
  TabPane,
  Toast,
  Tooltip,
} from '@douyinfe/semi-ui'
import {
  IconAlertTriangle,
  IconArrowDown,
  IconArrowUp,
  IconClose,
  IconCopy,
  IconDelete,
  IconDownload,
  IconInfoCircle,
  IconList,
  IconPlay,
  IconPlus,
  IconRefresh,
  IconSave,
} from '@douyinfe/semi-icons'

import { ApiError } from '../api/client'
import { pairlistApi } from '../api/endpoints'
import { BackgroundJobTracking } from '../components/BackgroundJobTracking'
import { Panel, Tag } from '../components/primitives'
import { ExchangeSelect, type ExchangeSelection } from '../components/selects'
import { describeError } from '../hooks/usePolling'
import { useJobPolling } from '../hooks/useJobPolling'
import { useApi } from '../state/bots'
import { useSnapshot } from '../state/snapshot'

/* -------------------------------------------------------------------------- */
/* Types                                                                       */
/* -------------------------------------------------------------------------- */

type ParamType = 'string' | 'number' | 'boolean' | 'option' | 'list'

interface PairlistParam {
  type?: ParamType
  default?: unknown
  description?: string
  help?: string
  options?: string[]
  value?: unknown
}

interface PairlistInfo {
  name: string
  description: string
  is_pairlist_generator: boolean
  params: Record<string, PairlistParam>
}

interface ChainItem extends PairlistInfo {
  id: string
  showParameters: boolean
}

interface SavedConfig {
  name: string
  pairlists: ChainItem[]
  blacklist: string[]
}

interface PairlistConfigStore {
  savedConfigs: SavedConfig[]
  configName: string
}

const STORAGE_KEY = 'ftui.pairlistConfigs'
const DEFAULT_CONFIG_NAME = 'default'

/** Pairlist handlers that generate a list rather than filter one. */
const GENERATOR_NAMES = new Set([
  'StaticPairList',
  'VolumePairList',
  'ProducerPairList',
  'RemotePairList',
  'MarketCapPairList',
])

/* -------------------------------------------------------------------------- */
/* Coercion                                                                    */
/* -------------------------------------------------------------------------- */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function makeId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

function normalizeParams(raw: unknown): Record<string, PairlistParam> {
  if (!isRecord(raw)) return {}
  const params: Record<string, PairlistParam> = {}
  for (const [key, value] of Object.entries(raw)) {
    if (!isRecord(value)) continue
    const type = value.type
    params[key] = {
      type:
        type === 'number' || type === 'boolean' || type === 'option' || type === 'list'
          ? type
          : 'string',
      default: value.default,
      description: typeof value.description === 'string' ? value.description : key,
      help: typeof value.help === 'string' ? value.help : undefined,
      options: Array.isArray(value.options) ? value.options.map(String) : undefined,
    }
  }
  return params
}

/**
 * `/pairlists/available` returns `{ pairlists: PairlistResponse[] }`. The shared
 * type describes a dictionary instead, so both shapes are accepted here.
 */
function normalizeAvailable(response: unknown): PairlistInfo[] {
  const raw = isRecord(response) ? response.pairlists : undefined
  const list: PairlistInfo[] = []

  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (!isRecord(item) || typeof item.name !== 'string' || !item.name) continue
      list.push({
        name: item.name,
        description: typeof item.description === 'string' ? item.description : '',
        is_pairlist_generator: Boolean(item.is_pairlist_generator),
        params: normalizeParams(item.params),
      })
    }
  } else if (isRecord(raw)) {
    for (const [name, value] of Object.entries(raw)) {
      const record = isRecord(value) ? value : {}
      list.push({
        name,
        description: typeof record.description === 'string' ? record.description : '',
        // The dictionary form carries no generator flag; fall back to the
        // known generator handler names.
        is_pairlist_generator: GENERATOR_NAMES.has(name),
        params: normalizeParams(record.params),
      })
    }
  }

  // Generators first, then alphabetical — the order the chain must start in.
  return list.sort((a, b) =>
    a.is_pairlist_generator === b.is_pairlist_generator
      ? a.name.localeCompare(b.name)
      : a.is_pairlist_generator
        ? -1
        : 1,
  )
}

/* -------------------------------------------------------------------------- */
/* Storage                                                                     */
/* -------------------------------------------------------------------------- */

function emptyConfig(name: string): SavedConfig {
  return { name, pairlists: [], blacklist: [] }
}

function normalizeChainItem(raw: unknown): ChainItem | null {
  if (!isRecord(raw) || typeof raw.name !== 'string' || !raw.name) return null
  return {
    id: typeof raw.id === 'string' && raw.id ? raw.id : makeId(),
    name: raw.name,
    description: typeof raw.description === 'string' ? raw.description : '',
    is_pairlist_generator: Boolean(raw.is_pairlist_generator),
    showParameters: Boolean(raw.showParameters),
    params: normalizeParams(raw.params),
  }
}

function readStore(): PairlistConfigStore {
  const fallback: PairlistConfigStore = {
    savedConfigs: [emptyConfig(DEFAULT_CONFIG_NAME)],
    configName: DEFAULT_CONFIG_NAME,
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as unknown
    if (!isRecord(parsed)) return fallback

    const savedConfigs: SavedConfig[] = []
    if (Array.isArray(parsed.savedConfigs)) {
      for (const entry of parsed.savedConfigs) {
        if (!isRecord(entry) || typeof entry.name !== 'string' || !entry.name) continue
        const pairlists: ChainItem[] = []
        if (Array.isArray(entry.pairlists)) {
          for (const item of entry.pairlists) {
            const normalized = normalizeChainItem(item)
            if (normalized) pairlists.push(normalized)
          }
        }
        savedConfigs.push({
          name: entry.name,
          pairlists,
          blacklist: Array.isArray(entry.blacklist) ? entry.blacklist.map(String) : [],
        })
      }
    }
    if (!savedConfigs.length) return fallback

    const configName =
      typeof parsed.configName === 'string' && savedConfigs.some((c) => c.name === parsed.configName)
        ? parsed.configName
        : savedConfigs[0].name

    return { savedConfigs, configName }
  } catch {
    return fallback
  }
}

function writeStore(store: PairlistConfigStore): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    /* storage unavailable — the in-memory chain still evaluates */
  }
}

/* -------------------------------------------------------------------------- */
/* Payload                                                                     */
/* -------------------------------------------------------------------------- */

function convertToParamType(type: ParamType | undefined, value: unknown): unknown {
  if (type === 'number') return Number(value)
  if (type === 'boolean') return Boolean(value)
  if (type === 'list') {
    if (Array.isArray(value)) return value
    return String(value)
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
  }
  return String(value)
}

function configToPayloadItems(chain: ChainItem[]): Record<string, unknown>[] {
  return chain.map((item) => {
    const payload: Record<string, unknown> = { method: item.name }
    for (const [key, param] of Object.entries(item.params)) {
      // Falsy values are omitted on purpose: the backend then applies its own
      // default, exactly like freqUI's pairlistConfig store.
      if (param?.value) payload[key] = convertToParamType(param.type, param.value)
    }
    return payload
  })
}

/* -------------------------------------------------------------------------- */
/* Parameter editors                                                           */
/* -------------------------------------------------------------------------- */

/** Comma-separated editor for `list` parameters, with a local draft. */
function ListParamEditor({
  value,
  onChange,
  disabled,
}: {
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
}) {
  const [text, setText] = useState(() => value.join(', '))
  // The list this editor last produced, so an incoming echo of it does not
  // overwrite a half-typed draft (e.g. a trailing comma).
  const lastEmitted = useRef<string | null>(null)

  useEffect(() => {
    const joined = value.join('\u0000')
    if (lastEmitted.current === joined) return
    setText(value.join(', '))
  }, [value])

  return (
    <Input
      size="small"
      value={text}
      disabled={disabled}
      placeholder="逗号分隔"
      onChange={(next) => {
        setText(next)
        const parsed = next
          .split(',')
          .map((part) => part.trim())
          .filter(Boolean)
        lastEmitted.current = parsed.join('\u0000')
        onChange(parsed)
      }}
      style={{ width: '100%' }}
    />
  )
}

function ParamEditor({
  paramKey,
  param,
  onChange,
}: {
  paramKey: string
  param: PairlistParam
  onChange: (value: unknown) => void
}) {
  const label = param.description || paramKey

  let control: ReactNode
  switch (param.type) {
    case 'boolean':
      control = (
        <Switch
          size="small"
          checked={Boolean(param.value)}
          onChange={(checked) => onChange(checked)}
        />
      )
      break
    case 'number':
      control = (
        <InputNumber
          size="small"
          value={typeof param.value === 'number' ? param.value : Number(param.value ?? 0) || 0}
          onChange={(next) => onChange(Number(next))}
          style={{ width: '100%' }}
        />
      )
      break
    case 'option':
      control = (
        <Select
          size="small"
          value={param.value === undefined || param.value === null ? undefined : String(param.value)}
          onChange={(next) => onChange(next === undefined ? '' : String(next))}
          optionList={(param.options ?? []).map((option) => ({
            value: option,
            label: option || '(默认)',
          }))}
          placeholder="使用默认值"
          style={{ width: '100%' }}
        />
      )
      break
    case 'list':
      control = (
        <ListParamEditor
          value={Array.isArray(param.value) ? (param.value as string[]) : []}
          onChange={onChange}
        />
      )
      break
    default:
      control = (
        <Input
          size="small"
          value={param.value === undefined || param.value === null ? '' : String(param.value)}
          onChange={(next) => onChange(next)}
          style={{ width: '100%' }}
        />
      )
  }

  return (
    <div className="ft-row" style={{ gap: 'var(--ft-gap-4)', alignItems: 'flex-start' }}>
      <span
        style={{
          flex: '0 0 38%',
          fontSize: 'var(--ft-font-xs)',
          color: 'var(--ft-ink-3)',
          paddingTop: 4,
          minWidth: 0,
        }}
        title={param.help || label}
      >
        {label}
        <span className="ft-faint"> · {param.type ?? 'string'}</span>
      </span>
      <div style={{ flex: '1 1 auto', minWidth: 0 }}>{control}</div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export function PairlistConfig() {
  const api = useApi()
  const { config: botConfig } = useSnapshot()

  const [available, setAvailable] = useState<PairlistInfo[]>([])
  const [availableError, setAvailableError] = useState<string | undefined>(undefined)
  const [wrongState, setWrongState] = useState(false)
  const [loadingAvailable, setLoadingAvailable] = useState(false)
  const [reloadNonce, setReloadNonce] = useState(0)

  const [store, setStore] = useState<PairlistConfigStore>(() => readStore())
  const [working, setWorking] = useState<SavedConfig>(() => {
    const initial = readStore()
    const selected = initial.savedConfigs.find((c) => c.name === initial.configName)
    return clone(selected ?? initial.savedConfigs[0])
  })
  const [nameDraft, setNameDraft] = useState(() => readStore().configName)

  const [stakeCurrency, setStakeCurrency] = useState(botConfig?.stake_currency ?? 'USDT')
  const [customExchange, setCustomExchange] = useState(false)
  const [selectedExchange, setSelectedExchange] = useState<ExchangeSelection>({
    exchange: botConfig?.exchange ?? '',
    trading_mode: botConfig?.trading_mode ?? 'spot',
    margin_mode: botConfig?.margin_mode ?? '',
  })

  const [whitelist, setWhitelist] = useState<string[]>([])
  const [evaluating, setEvaluating] = useState(false)
  const [view, setView] = useState<'config' | 'results'>('config')
  const [copyFrom, setCopyFrom] = useState('')

  const { jobs, track, dismiss, clearFinished, waitFor } = useJobPolling(api, Boolean(api))

  // Keep the stake currency in step with the bot until the user edits it.
  useEffect(() => {
    if (botConfig?.stake_currency) setStakeCurrency(botConfig.stake_currency)
  }, [botConfig?.stake_currency])

  /* Available pairlists ---------------------------------------------------- */

  useEffect(() => {
    let cancelled = false
    setLoadingAvailable(true)
    pairlistApi
      .available(api)
      .then((response) => {
        if (cancelled) return
        setAvailable(normalizeAvailable(response))
        setWrongState(false)
        setAvailableError(undefined)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setWrongState(err instanceof ApiError && err.isWrongState)
        setAvailableError(describeError(err as Error) ?? '无法读取 pairlist 列表')
        setAvailable([])
      })
      .finally(() => {
        if (!cancelled) setLoadingAvailable(false)
      })
    return () => {
      cancelled = true
    }
  }, [api, reloadNonce])

  /* Persistence ----------------------------------------------------------- */

  const persist = useCallback((next: PairlistConfigStore) => {
    setStore(next)
    writeStore(next)
  }, [])

  const selectConfig = (name: string) => {
    const existing = store.savedConfigs.find((c) => c.name === name)
    if (existing) {
      setWorking(clone(existing))
      setNameDraft(name)
      persist({ ...store, configName: name })
      return
    }
    const fresh = emptyConfig(name)
    persist({ savedConfigs: [...store.savedConfigs, fresh], configName: name })
    setWorking(clone(fresh))
    setNameDraft(name)
  }

  const saveConfig = () => {
    const name = nameDraft.trim() || working.name.trim() || DEFAULT_CONFIG_NAME
    const next: SavedConfig = { ...clone(working), name }
    const index = store.savedConfigs.findIndex((c) => c.name === name)
    const savedConfigs =
      index > -1
        ? store.savedConfigs.map((c, i) => (i === index ? next : c))
        : [...store.savedConfigs, next]
    persist({ savedConfigs, configName: name })
    setWorking(clone(next))
    setNameDraft(name)
    Toast.success(`已保存配置「${name}」`)
  }

  const duplicateConfig = () => {
    const base = (nameDraft.trim() || working.name || DEFAULT_CONFIG_NAME).replace(/_copy\d*$/, '')
    let name = `${base}_copy`
    let suffix = 2
    while (store.savedConfigs.some((c) => c.name === name)) {
      name = `${base}_copy${suffix}`
      suffix += 1
    }
    const copy: SavedConfig = {
      name,
      pairlists: clone(working.pairlists).map((item) => ({ ...item, id: makeId() })),
      blacklist: [...working.blacklist],
    }
    persist({ savedConfigs: [...store.savedConfigs, copy], configName: name })
    setWorking(clone(copy))
    setNameDraft(name)
  }

  const deleteConfig = () => {
    const name = working.name
    const remaining = store.savedConfigs.filter((c) => c.name !== name)
    if (!remaining.length) {
      const fresh = emptyConfig(DEFAULT_CONFIG_NAME)
      persist({ savedConfigs: [fresh], configName: DEFAULT_CONFIG_NAME })
      setWorking(clone(fresh))
      setNameDraft(DEFAULT_CONFIG_NAME)
      return
    }
    persist({ savedConfigs: remaining, configName: remaining[0].name })
    setWorking(clone(remaining[0]))
    setNameDraft(remaining[0].name)
  }

  /* Chain editing --------------------------------------------------------- */

  const updateChain = (pairlists: ChainItem[]) => setWorking((prev) => ({ ...prev, pairlists }))

  const addToConfig = (info: PairlistInfo, index: number) => {
    const params: Record<string, PairlistParam> = {}
    for (const [key, param] of Object.entries(info.params)) {
      params[key] = {
        ...param,
        value: param.default !== undefined ? param.default : '',
      }
    }
    const item: ChainItem = {
      id: makeId(),
      name: info.name,
      description: info.description,
      is_pairlist_generator: info.is_pairlist_generator,
      showParameters: false,
      params,
    }
    const next = [...working.pairlists]
    next.splice(index, 0, item)
    updateChain(next)
  }

  const removeFromConfig = (index: number) => {
    updateChain(working.pairlists.filter((_, i) => i !== index))
  }

  const moveItem = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= working.pairlists.length) return
    const next = [...working.pairlists]
    const [item] = next.splice(index, 1)
    next.splice(target, 0, item)
    updateChain(next)
  }

  const setParamValue = (index: number, key: string, value: unknown) => {
    updateChain(
      working.pairlists.map((item, i) =>
        i === index ? { ...item, params: { ...item.params, [key]: { ...item.params[key], value } } } : item,
      ),
    )
  }

  const toggleParameters = (index: number) => {
    updateChain(
      working.pairlists.map((item, i) =>
        i === index ? { ...item, showParameters: !item.showParameters } : item,
      ),
    )
  }

  /* Blacklist ------------------------------------------------------------- */

  const setBlacklist = (blacklist: string[]) => setWorking((prev) => ({ ...prev, blacklist }))

  /* Payload + evaluation -------------------------------------------------- */

  const firstIsGenerator = Boolean(working.pairlists[0]?.is_pairlist_generator)
  const valid = working.pairlists.length > 0 && firstIsGenerator

  const payload = useMemo(() => {
    const body: Record<string, unknown> = {
      pairlists: configToPayloadItems(working.pairlists),
      stake_currency: stakeCurrency,
      blacklist: working.blacklist.filter(Boolean),
    }
    if (customExchange) {
      body.exchange = selectedExchange.exchange
      body.trading_mode = selectedExchange.trading_mode
      body.margin_mode = selectedExchange.margin_mode
    }
    return body
  }, [working, stakeCurrency, customExchange, selectedExchange])

  const payloadJson = useMemo(() => JSON.stringify(payload, null, 2), [payload])
  const whitelistJson = useMemo(() => JSON.stringify(whitelist, null, 2), [whitelist])

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      Toast.success(`${label}已复制到剪贴板`)
    } catch {
      Toast.error('复制失败，请手动选择文本')
    }
  }

  const evaluate = async () => {
    if (!valid || evaluating) return
    setEvaluating(true)
    try {
      const { job_id: jobId } = await pairlistApi.evaluate(api, payload)
      track(jobId, 'pairlist')
      const status = await waitFor(jobId)
      // null means the job was dismissed from the tracking panel.
      if (!status) return
      if (status.status === 'failed') {
        Toast.error(status.error || status.pollError || 'Pairlist 评估失败')
        return
      }
      const result = (await pairlistApi.evaluateResult(api, jobId)) as {
        status?: string
        error?: string
        result?: { whitelist?: string[]; length?: number }
      }
      if (result?.result?.whitelist) {
        setWhitelist(result.result.whitelist)
        setView('results')
        Toast.success(`评估完成：${result.result.whitelist.length} 个交易对`)
      } else if (result?.error) {
        Toast.error(result.error)
      } else {
        Toast.warning('评估已完成，但没有返回白名单')
      }
    } catch (err) {
      Toast.error(describeError(err as Error) ?? '评估失败')
    } finally {
      setEvaluating(false)
    }
  }

  const copyableConfigs = store.savedConfigs
    .filter((c) => c.name !== working.name)
    .map((c) => ({ value: c.name, label: c.name }))

  /* Render ---------------------------------------------------------------- */

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">Pairlist 配置</h1>
        <span className="ft-page-sub">构建 pairlist 处理链并评估白名单</span>
        <div style={{ marginLeft: 'auto' }} className="ft-row">
          <Button
            size="small"
            icon={<IconRefresh spin={loadingAvailable} />}
            onClick={() => setReloadNonce((n) => n + 1)}
          >
            重新加载处理器
          </Button>
        </div>
      </div>

      {wrongState && (
        <Banner
          type="warning"
          bordered
          icon={<IconAlertTriangle />}
          title="需要 webserver 模式"
          description="当前机器人不在 webserver 模式，/pairlists/available 与 /pairlists/evaluate 不可用。请以 webserver 模式启动机器人后再使用此页面。"
        />
      )}

      {availableError && !wrongState && (
        <Banner
          type="danger"
          bordered
          title="读取 pairlist 处理器失败"
          description={availableError}
        />
      )}

      {!valid && working.pairlists.length > 0 && (
        <Banner
          type="warning"
          bordered
          icon={<IconAlertTriangle />}
          title="配置无效"
          description="链中的第一个处理器必须是生成型 pairlist（例如 StaticPairList 或 VolumePairList）。"
        />
      )}

      {jobs.length > 0 && (
        <Panel title="后台任务" icon={<IconPlay />}>
          <BackgroundJobTracking jobs={jobs} onClear={clearFinished} onDismiss={dismiss} />
        </Panel>
      )}

      <div className="ft-panes-3">
        {/* Available handlers --------------------------------------------- */}
        <Panel
          title="可用处理器"
          icon={<IconList />}
          sub={`${available.length} 个`}
          flush
        >
          {available.length === 0 ? (
            <div className="ft-faint" style={{ padding: 'var(--ft-gap-5)', fontSize: 'var(--ft-font-sm)' }}>
              {loadingAvailable ? '加载中…' : '没有可用的 pairlist 处理器。'}
            </div>
          ) : (
            <div style={{ maxHeight: 620, overflowY: 'auto' }}>
              {available.map((info, index) => {
                const disabled = working.pairlists.length === 0 && !info.is_pairlist_generator
                return (
                  <div
                    // The backend can list a handler name more than once (the
                    // pairlist pipeline itself reports two PairInformationFilter
                    // entries), so the name alone is not a safe key.
                    key={`${info.name}-${index}`}
                    className="ft-row"
                    style={{
                      gap: 'var(--ft-gap-4)',
                      padding: 'var(--ft-gap-3) var(--ft-gap-4)',
                      borderBottom: '1px solid var(--ft-line)',
                      opacity: disabled ? 0.5 : 1,
                      alignItems: 'flex-start',
                    }}
                    title={info.description}
                  >
                    <div className="ft-col" style={{ gap: 1, minWidth: 0, flex: '1 1 auto' }}>
                      <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                        <span className="ft-mono-sm" style={{ fontWeight: 600 }}>
                          {info.name}
                        </span>
                        {info.is_pairlist_generator ? (
                          <Tag variant="solid" title="生成型 pairlist">
                            GEN
                          </Tag>
                        ) : (
                          <Tag variant="plain" title="过滤型 pairlist">
                            FILTER
                          </Tag>
                        )}
                      </span>
                      <span
                        className="ft-faint"
                        style={{
                          fontSize: 'var(--ft-font-xs)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {info.description}
                      </span>
                    </div>
                    <Tooltip
                      content={
                        disabled ? '链中第一个必须是生成型 pairlist' : `添加到链尾`
                      }
                    >
                      <Button
                        size="small"
                        theme="borderless"
                        type="tertiary"
                        icon={<IconPlus />}
                        disabled={disabled}
                        onClick={() => addToConfig(info, working.pairlists.length)}
                      />
                    </Tooltip>
                  </div>
                )
              })}
            </div>
          )}
        </Panel>

        {/* Chain ----------------------------------------------------------- */}
        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)', minWidth: 0 }}>
          <Panel
            title="配置"
            icon={<IconSave />}
            sub={`${working.pairlists.length} 个处理器`}
            actions={
              <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                <Select
                  size="small"
                  value={store.configName}
                  onChange={(value) => selectConfig(String(value ?? ''))}
                  optionList={store.savedConfigs.map((c) => ({ value: c.name, label: c.name }))}
                  style={{ width: 130 }}
                />
                <Input
                  size="small"
                  value={nameDraft}
                  placeholder="配置名称"
                  onChange={setNameDraft}
                  style={{ width: 130 }}
                />
                <Tooltip content="保存 / 重命名当前配置">
                  <Button size="small" icon={<IconSave />} onClick={saveConfig} />
                </Tooltip>
                <Tooltip content="复制当前配置">
                  <Button size="small" icon={<IconCopy />} onClick={duplicateConfig} />
                </Tooltip>
                <Tooltip content="删除当前配置">
                  <Button size="small" icon={<IconDelete />} onClick={deleteConfig} />
                </Tooltip>
              </div>
            }
          >
            <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
              <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-5)' }}>
                <div className="ft-col" style={{ gap: 2, width: 150 }}>
                  <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                    计价币
                  </span>
                  <Input size="small" value={stakeCurrency} onChange={setStakeCurrency} />
                </div>
                <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', paddingTop: 14 }}>
                  <Checkbox
                    checked={customExchange}
                    onChange={(e) => setCustomExchange(e.target.checked ?? false)}
                  >
                    <span style={{ fontSize: 'var(--ft-font-sm)' }}>自定义交易所</span>
                  </Checkbox>
                </div>
              </div>

              {customExchange && (
                <ExchangeSelect api={api} value={selectedExchange} onChange={setSelectedExchange} />
              )}

              {/* Blacklist editor ------------------------------------------ */}
              <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
                <div className="ft-rule">黑名单</div>
                <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
                  <Select
                    size="small"
                    value={copyFrom || undefined}
                    onChange={(value) => setCopyFrom(String(value ?? ''))}
                    optionList={copyableConfigs}
                    placeholder="从其他配置复制"
                    emptyContent="没有其他配置"
                    style={{ width: 180 }}
                  />
                  <Tooltip content="复制所选配置的黑名单">
                    <Button
                      size="small"
                      icon={<IconDownload />}
                      disabled={!copyFrom}
                      onClick={() => {
                        const source = store.savedConfigs.find((c) => c.name === copyFrom)
                        if (source) setBlacklist([...source.blacklist])
                      }}
                    >
                      复制
                    </Button>
                  </Tooltip>
                  <Button
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => setBlacklist([...working.blacklist, ''])}
                  >
                    添加
                  </Button>
                </div>

                {working.blacklist.length === 0 ? (
                  <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                    未设置黑名单，评估时不会排除任何交易对。
                  </span>
                ) : (
                  working.blacklist.map((entry, index) => (
                    <div className="ft-row" key={`blacklist-${index}`} style={{ gap: 'var(--ft-gap-3)' }}>
                      <Input
                        size="small"
                        value={entry}
                        placeholder="例如 BNB/USDT 或 .*UP/USDT"
                        onChange={(value) =>
                          setBlacklist(working.blacklist.map((v, i) => (i === index ? value : v)))
                        }
                        style={{ flex: '1 1 auto', minWidth: 0 }}
                      />
                      <Button
                        size="small"
                        theme="borderless"
                        type="tertiary"
                        icon={<IconClose />}
                        onClick={() => setBlacklist(working.blacklist.filter((_, i) => i !== index))}
                      />
                    </div>
                  ))
                )}
              </div>

              {/* Chain items ---------------------------------------------- */}
              <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
                <div className="ft-rule">处理链</div>

                {working.pairlists.length === 0 ? (
                  <div
                    className="ft-faint"
                    style={{
                      border: '1px dashed var(--ft-line-strong)',
                      borderRadius: 'var(--ft-radius)',
                      padding: 'var(--ft-gap-6)',
                      textAlign: 'center',
                      fontSize: 'var(--ft-font-sm)',
                    }}
                  >
                    从左侧添加生成型 pairlist（例如 StaticPairList）开始构建处理链。
                  </div>
                ) : (
                  working.pairlists.map((item, index) => {
                    const paramKeys = Object.keys(item.params)
                    return (
                      <div
                        key={item.id}
                        style={{
                          border: '1px solid var(--ft-line-strong)',
                          borderRadius: 'var(--ft-radius)',
                          overflow: 'hidden',
                        }}
                      >
                        <div
                          className="ft-row"
                          style={{
                            gap: 'var(--ft-gap-3)',
                            padding: 'var(--ft-gap-3) var(--ft-gap-4)',
                            background: 'var(--ft-paper-2)',
                            borderBottom: item.showParameters ? '1px solid var(--ft-line)' : 'none',
                          }}
                        >
                          <span className="ft-num ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                            {index + 1}
                          </span>
                          <div
                            className="ft-col"
                            style={{ gap: 0, minWidth: 0, flex: '1 1 auto', cursor: paramKeys.length ? 'pointer' : 'default' }}
                            onClick={() => paramKeys.length && toggleParameters(index)}
                          >
                            <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                              <span className="ft-mono-sm" style={{ fontWeight: 600 }}>
                                {item.name}
                              </span>
                              {item.is_pairlist_generator ? (
                                <Tag variant="solid">GEN</Tag>
                              ) : (
                                <Tag variant="plain">FILTER</Tag>
                              )}
                              {paramKeys.length > 0 && (
                                <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                                  {paramKeys.length} 个参数
                                </span>
                              )}
                            </span>
                            <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                              {item.description}
                            </span>
                          </div>

                          <Tooltip content="上移">
                            <Button
                              size="small"
                              theme="borderless"
                              type="tertiary"
                              icon={<IconArrowUp />}
                              disabled={index === 0}
                              onClick={() => moveItem(index, -1)}
                            />
                          </Tooltip>
                          <Tooltip content="下移">
                            <Button
                              size="small"
                              theme="borderless"
                              type="tertiary"
                              icon={<IconArrowDown />}
                              disabled={index === working.pairlists.length - 1}
                              onClick={() => moveItem(index, 1)}
                            />
                          </Tooltip>
                          <Tooltip content="移除">
                            <Button
                              size="small"
                              theme="borderless"
                              type="tertiary"
                              icon={<IconClose />}
                              onClick={() => removeFromConfig(index)}
                            />
                          </Tooltip>
                        </div>

                        {item.showParameters && (
                          <div
                            className="ft-col"
                            style={{ gap: 'var(--ft-gap-3)', padding: 'var(--ft-gap-4)' }}
                          >
                            {paramKeys.map((key) => (
                              <ParamEditor
                                key={key}
                                paramKey={key}
                                param={item.params[key]}
                                onChange={(value) => setParamValue(index, key, value)}
                              />
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })
                )}
              </div>
            </div>
          </Panel>
        </div>

        {/* Preview + results ---------------------------------------------- */}
        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)', minWidth: 0 }}>
          <Panel
            title="评估"
            icon={<IconPlay />}
            actions={
              <Button
                size="small"
                type="primary"
                icon={<IconPlay />}
                loading={evaluating}
                disabled={!valid || evaluating}
                onClick={evaluate}
              >
                评估
              </Button>
            }
          >
            <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
              <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                <IconInfoCircle className="ft-faint" />
                <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  评估在机器人后台运行，使用当前计价币与黑名单；结果仅供查看，不会修改机器人配置。
                </span>
              </div>
              <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                <Tag variant={valid ? 'up' : 'warn'}>{valid ? '配置有效' : '配置无效'}</Tag>
                <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  {working.pairlists.length} 个处理器
                </span>
              </div>
            </div>
          </Panel>

          <Panel title="配置预览" icon={<IconList />} flush>
            <Tabs
              type="line"
              size="small"
              activeKey={view}
              onChange={(key) => setView(key as 'config' | 'results')}
            >
              <TabPane
                itemKey="config"
                tab={
                  <span className="ft-row" style={{ gap: 4 }}>
                    配置 JSON
                  </span>
                }
              >
                <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', padding: 'var(--ft-gap-4)' }}>
                  <div className="ft-row">
                    <Button
                      size="small"
                      icon={<IconCopy />}
                      onClick={() => void copy(payloadJson, '配置')}
                    >
                      复制
                    </Button>
                  </div>
                  <pre className="ft-pre" style={{ maxHeight: 420, overflow: 'auto' }}>
                    {payloadJson}
                  </pre>
                </div>
              </TabPane>

              <TabPane
                itemKey="results"
                tab={<span>评估结果{whitelist.length ? ` (${whitelist.length})` : ''}</span>}
              >
                <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', padding: 'var(--ft-gap-4)' }}>
                  <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                    <Button
                      size="small"
                      icon={<IconCopy />}
                      disabled={!whitelist.length}
                      onClick={() => void copy(whitelistJson, '白名单')}
                    >
                      复制
                    </Button>
                    <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                      {whitelist.length} 个交易对
                    </span>
                  </div>
                  {whitelist.length === 0 ? (
                    <span className="ft-faint" style={{ fontSize: 'var(--ft-font-sm)' }}>
                      尚未评估，或评估结果为空。
                    </span>
                  ) : (
                    <>
                      <pre className="ft-pre" style={{ maxHeight: 300, overflow: 'auto' }}>
                        {whitelistJson}
                      </pre>
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
                          gap: 'var(--ft-gap-2)',
                        }}
                      >
                        {whitelist.map((pair) => (
                          <span className="ft-tag" key={pair} title={pair}>
                            {pair}
                          </span>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </TabPane>
            </Tabs>
          </Panel>
        </div>
      </div>
    </div>
  )
}
