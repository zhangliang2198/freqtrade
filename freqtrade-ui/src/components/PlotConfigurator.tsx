/**
 * Plot-configurator.
 *
 * freqtrade strategies declare a `plot_config` mapping indicator columns to the
 * main plot and to named subplots. This panel lets the user curate that mapping
 * for the chart page — which columns are drawn on the price pane, which ones get
 * their own pane — and keeps the result in `localStorage` under `ftui.plotConfig`.
 *
 * Two dense checkbox pickers (main plot / one selected subplot) rather than the
 * drag-and-drop indicator editor the Vue UI grew: the same decisions, a fraction
 * of the surface.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Checkbox, Empty, Input, Select, Switch, Tooltip } from '@douyinfe/semi-ui'
import {
  IconClose,
  IconDelete,
  IconPlus,
  IconSave,
  IconSearch,
} from '@douyinfe/semi-icons'

import type { PlotConfig } from '../api/types'

/* -------------------------------------------------------------------------- */
/* Shape                                                                       */
/* -------------------------------------------------------------------------- */

export interface PlotConfigOptions {
  showTags?: boolean
  markAreaZIndex?: number
}

export interface PlotConfigShape {
  main_plot: Record<string, unknown>
  subplots: Record<string, Record<string, unknown>>
  options?: PlotConfigOptions
}

export const EMPTY_PLOT_CONFIG: PlotConfigShape = { main_plot: {}, subplots: {} }

/** A fresh, independently mutable empty config. */
function emptyConfig(): PlotConfigShape {
  return { main_plot: {}, subplots: {} }
}

const STORAGE_KEY = 'ftui.plotConfig'
const DEFAULT_NAME = 'default'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Coerces anything that reached us from the API or storage into the strict shape. */
export function coercePlotConfig(value: unknown): PlotConfigShape {
  const input = isRecord(value) ? value : {}
  const mainPlot = isRecord(input.main_plot) ? { ...input.main_plot } : {}

  const subplots: Record<string, Record<string, unknown>> = {}
  if (isRecord(input.subplots)) {
    for (const [name, sub] of Object.entries(input.subplots)) {
      subplots[name] = isRecord(sub) ? { ...sub } : {}
    }
  }

  let options: PlotConfigOptions | undefined
  if (isRecord(input.options)) {
    options = {}
    if (typeof input.options.showTags === 'boolean') options.showTags = input.options.showTags
    if (typeof input.options.markAreaZIndex === 'number') {
      options.markAreaZIndex = input.options.markAreaZIndex
    }
  }

  return options ? { main_plot: mainPlot, subplots, options } : { main_plot: mainPlot, subplots }
}

/**
 * Every column a plot config asks the backend for: main-plot keys, every subplot
 * key, plus the tag columns unless tags are explicitly disabled.
 */
export function plotConfigColumns(plotConfig: PlotConfig | PlotConfigShape | undefined): string[] {
  const config = coercePlotConfig(plotConfig)
  const columns: string[] = []

  for (const key of Object.keys(config.main_plot)) columns.push(key)
  for (const subplot of Object.values(config.subplots)) {
    for (const key of Object.keys(subplot)) columns.push(key)
  }
  if (config.options?.showTags !== false) columns.push('enter_tag', 'exit_tag')

  return [...new Set(columns)].sort()
}

/* -------------------------------------------------------------------------- */
/* Storage                                                                     */
/* -------------------------------------------------------------------------- */

interface PlotConfigStoreShape {
  plotConfigName: string
  customPlotConfigs: Record<string, PlotConfigShape>
}

function readStore(): PlotConfigStoreShape {
  const fallback: PlotConfigStoreShape = {
    plotConfigName: DEFAULT_NAME,
    customPlotConfigs: { [DEFAULT_NAME]: emptyConfig() },
  }
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as unknown
    if (!isRecord(parsed)) return fallback

    const configs: Record<string, PlotConfigShape> = {}
    if (isRecord(parsed.customPlotConfigs)) {
      for (const [name, config] of Object.entries(parsed.customPlotConfigs)) {
        configs[name] = coercePlotConfig(config)
      }
    }
    if (!Object.keys(configs).length) configs[DEFAULT_NAME] = emptyConfig()

    const name =
      typeof parsed.plotConfigName === 'string' && configs[parsed.plotConfigName]
        ? parsed.plotConfigName
        : Object.keys(configs)[0]

    return { plotConfigName: name, customPlotConfigs: configs }
  } catch {
    return fallback
  }
}

function writeStore(store: PlotConfigStoreShape): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    /* storage unavailable — the in-memory value still drives the chart */
  }
}

/** The active plot config as persisted, for callers that only need the columns. */
export function loadActivePlotConfig(): PlotConfigShape {
  const store = readStore()
  return store.customPlotConfigs[store.plotConfigName] ?? emptyConfig()
}

/* -------------------------------------------------------------------------- */
/* Column picker                                                               */
/* -------------------------------------------------------------------------- */

function ColumnPicker({
  columns,
  selected,
  onToggle,
  onSelectAll,
  onClear,
}: {
  /** Columns offered by the loaded dataset. */
  columns: string[]
  selected: string[]
  onToggle: (column: string, checked: boolean) => void
  onSelectAll: () => void
  onClear: () => void
}) {
  const [filter, setFilter] = useState('')

  // Selected keys the current dataset does not expose stay visible (and
  // removable) rather than silently disappearing from the editor.
  const extra = useMemo(
    () => selected.filter((column) => !columns.includes(column)).sort(),
    [selected, columns],
  )

  const entries = useMemo(() => {
    const all = [...columns, ...extra]
    if (!filter.trim()) return all
    const needle = filter.trim().toLowerCase()
    return all.filter((column) => column.toLowerCase().includes(needle))
  }, [columns, extra, filter])

  const selectedSet = useMemo(() => new Set(selected), [selected])

  return (
    <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', minWidth: 0 }}>
      <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
        <Input
          size="small"
          prefix={<IconSearch />}
          placeholder="筛选列"
          value={filter}
          onChange={setFilter}
          showClear
          style={{ flex: '1 1 auto', minWidth: 0 }}
        />
        <Tooltip content="选中全部可用列">
          <Button size="small" theme="borderless" type="tertiary" onClick={onSelectAll}>
            全选
          </Button>
        </Tooltip>
        <Tooltip content="清空该绘图区">
          <Button size="small" theme="borderless" type="tertiary" onClick={onClear}>
            清空
          </Button>
        </Tooltip>
      </div>

      {entries.length === 0 ? (
        <Empty description="没有可用列" style={{ padding: 'var(--ft-gap-5)' }} />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
            gap: '2px var(--ft-gap-4)',
            maxHeight: 260,
            overflowY: 'auto',
            border: '1px solid var(--ft-line)',
            borderRadius: 'var(--ft-radius-sm)',
            padding: 'var(--ft-gap-3)',
          }}
        >
          {entries.map((column) => {
            const unavailable = !columns.includes(column)
            return (
              <Checkbox
                key={column}
                checked={selectedSet.has(column)}
                onChange={(e) => onToggle(column, e.target.checked ?? false)}
              >
                <span className="ft-mono-sm" title={unavailable ? '当前图表不可用' : column}>
                  {column}
                  {unavailable && <span className="ft-faint"> · 不可用</span>}
                </span>
              </Checkbox>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Configurator                                                                */
/* -------------------------------------------------------------------------- */

export interface PlotConfiguratorProps {
  /** Columns the loaded dataset exposes. */
  columns: string[]
  /** Fires after every edit with the new active config. */
  onChange?: (config: PlotConfigShape) => void
}

export function PlotConfigurator({ columns, onChange }: PlotConfiguratorProps) {
  const [store, setStore] = useState<PlotConfigStoreShape>(() => readStore())
  const [newName, setNewName] = useState('')
  const [selectedSubplot, setSelectedSubplot] = useState('')

  const config = store.customPlotConfigs[store.plotConfigName] ?? emptyConfig()
  const subplotNames = useMemo(() => Object.keys(config.subplots), [config.subplots])

  // Keep the subplot selection pointing at something that exists.
  useEffect(() => {
    if (subplotNames.length === 0) {
      if (selectedSubplot) setSelectedSubplot('')
      return
    }
    if (!subplotNames.includes(selectedSubplot)) setSelectedSubplot(subplotNames[0])
  }, [subplotNames, selectedSubplot])

  const commit = useCallback(
    (next: PlotConfigShape) => {
      setStore((prev) => {
        const updated: PlotConfigStoreShape = {
          ...prev,
          customPlotConfigs: { ...prev.customPlotConfigs, [prev.plotConfigName]: next },
        }
        writeStore(updated)
        return updated
      })
      onChange?.(next)
    },
    [onChange],
  )

  const toggleMain = (column: string, checked: boolean) => {
    const mainPlot = { ...config.main_plot }
    if (checked) mainPlot[column] = mainPlot[column] ?? {}
    else delete mainPlot[column]
    commit({ ...config, main_plot: mainPlot })
  }

  const toggleSubplot = (column: string, checked: boolean) => {
    if (!selectedSubplot) return
    const subplot = { ...(config.subplots[selectedSubplot] ?? {}) }
    if (checked) subplot[column] = subplot[column] ?? {}
    else delete subplot[column]
    commit({ ...config, subplots: { ...config.subplots, [selectedSubplot]: subplot } })
  }

  const setSubplot = (columns_: string[]) => {
    if (!selectedSubplot) return
    const subplot: Record<string, unknown> = {}
    for (const column of columns_) subplot[column] = {}
    commit({ ...config, subplots: { ...config.subplots, [selectedSubplot]: subplot } })
  }

  const addSubplot = () => {
    const base = 'subplot'
    let index = Object.keys(config.subplots).length + 1
    let name = `${base}${index}`
    while (config.subplots[name]) {
      index += 1
      name = `${base}${index}`
    }
    commit({ ...config, subplots: { ...config.subplots, [name]: {} } })
    setSelectedSubplot(name)
  }

  const removeSubplot = () => {
    if (!selectedSubplot) return
    const subplots = { ...config.subplots }
    delete subplots[selectedSubplot]
    commit({ ...config, subplots })
  }

  const setShowTags = (showTags: boolean) => {
    commit({ ...config, options: { ...config.options, showTags } })
  }

  const selectConfig = (name: string) => {
    setStore((prev) => {
      const updated = { ...prev, plotConfigName: name }
      writeStore(updated)
      return updated
    })
    const next = store.customPlotConfigs[name]
    if (next) onChange?.(next)
  }

  const createConfig = () => {
    const name = newName.trim()
    if (!name) return
    const next: PlotConfigShape = emptyConfig()
    setStore((prev) => {
      const updated: PlotConfigStoreShape = {
        plotConfigName: name,
        customPlotConfigs: { ...prev.customPlotConfigs, [name]: next },
      }
      writeStore(updated)
      return updated
    })
    setNewName('')
    onChange?.(next)
  }

  const deleteConfig = () => {
    const name = store.plotConfigName
    const names = Object.keys(store.customPlotConfigs)
    if (names.length <= 1) return
    const remaining = { ...store.customPlotConfigs }
    delete remaining[name]
    const fallbackName = Object.keys(remaining)[0]
    const updated: PlotConfigStoreShape = {
      plotConfigName: fallbackName,
      customPlotConfigs: remaining,
    }
    setStore(updated)
    writeStore(updated)
    onChange?.(remaining[fallbackName])
  }

  const usedColumns = plotConfigColumns(config)
  const nameOptions = Object.keys(store.customPlotConfigs).map((name) => ({
    value: name,
    label: name,
  }))

  return (
    <div className="ft-col" style={{ gap: 'var(--ft-gap-5)', minWidth: 0 }}>
      {/* Config identity -------------------------------------------------- */}
      <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
        <Select
          size="small"
          value={store.plotConfigName}
          onChange={(value) => selectConfig(String(value ?? ''))}
          optionList={nameOptions}
          style={{ minWidth: 140, flex: '1 1 140px' }}
          prefix={<IconSave size="small" />}
        />
        <Input
          size="small"
          value={newName}
          placeholder="新配置名称"
          onChange={setNewName}
          style={{ width: 130 }}
        />
        <Tooltip content="以当前名称另存为新配置">
          <Button size="small" icon={<IconPlus />} onClick={createConfig} disabled={!newName.trim()}>
            新建
          </Button>
        </Tooltip>
        <Tooltip content="删除当前配置">
          <Button
            size="small"
            icon={<IconDelete />}
            onClick={deleteConfig}
            disabled={Object.keys(store.customPlotConfigs).length <= 1}
          />
        </Tooltip>
      </div>

      <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
        <Switch size="small" checked={config.options?.showTags !== false} onChange={setShowTags} />
        <span style={{ fontSize: 'var(--ft-font-sm)' }}>在提示中显示 enter/exit 标签</span>
      </div>

      {/* Main plot -------------------------------------------------------- */}
      <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
        <div className="ft-rule">主图</div>
        <ColumnPicker
          columns={columns}
          selected={Object.keys(config.main_plot)}
          onToggle={toggleMain}
          onSelectAll={() => {
            const mainPlot: Record<string, unknown> = {}
            for (const column of columns) mainPlot[column] = {}
            commit({ ...config, main_plot: mainPlot })
          }}
          onClear={() => commit({ ...config, main_plot: {} })}
        />
      </div>

      {/* Subplots --------------------------------------------------------- */}
      <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
        <div className="ft-rule">子图</div>

        <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
          <Select
            size="small"
            value={selectedSubplot || undefined}
            onChange={(value) => setSelectedSubplot(String(value ?? ''))}
            optionList={subplotNames.map((name) => ({ value: name, label: name }))}
            placeholder="选择子图"
            emptyContent="尚未创建子图"
            style={{ minWidth: 130, flex: '1 1 130px' }}
          />
          <Button size="small" icon={<IconPlus />} onClick={addSubplot}>
            添加子图
          </Button>
          <Tooltip content="删除当前子图">
            <Button
              size="small"
              icon={<IconClose />}
              onClick={removeSubplot}
              disabled={!selectedSubplot}
            />
          </Tooltip>
        </div>

        {selectedSubplot ? (
          <ColumnPicker
            columns={columns}
            selected={Object.keys(config.subplots[selectedSubplot] ?? {})}
            onToggle={toggleSubplot}
            onSelectAll={() => setSubplot(columns)}
            onClear={() => setSubplot([])}
          />
        ) : (
          <div className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            子图用于把振荡类指标（RSI、MACD 等）放到独立坐标轴。点击「添加子图」创建。
          </div>
        )}
      </div>

      {/* Result ----------------------------------------------------------- */}
      <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
        <div className="ft-rule">请求列（{usedColumns.length}）</div>
        <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-2)' }}>
          {usedColumns.length === 0 ? (
            <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
              未选择任何指标列
            </span>
          ) : (
            usedColumns.map((column) => (
              <span className="ft-tag" key={column}>
                {column}
              </span>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
