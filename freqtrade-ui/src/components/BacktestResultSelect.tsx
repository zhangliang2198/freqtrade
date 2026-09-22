/**
 * Sidebar list of the backtest results currently held in memory.
 *
 * Each entry can be selected (drives every analysis/visualisation tab), have
 * its notes edited inline (persisted to disk via the API) or be unloaded from
 * the UI without touching the stored result.
 */

import { useState } from 'react'
import { Button, TextArea, Toast, Tooltip } from '@douyinfe/semi-ui'
import { IconClose, IconEdit, IconTick } from '@douyinfe/semi-icons'

import { EmptyState, Panel } from './primitives'
import { backtestApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { formatPercent } from '../utils/format'
import type { BacktestResultInMemory } from '../utils/backtestMetrics'

export interface BacktestResultSelectProps {
  results: Record<string, BacktestResultInMemory>
  selectedKey: string
  onSelect: (key: string) => void
  onRemove: (key: string) => void
  /** Fired after a note was persisted so the parent can refresh its copy. */
  onNotesSaved: (key: string, notes: string) => void
}

export function BacktestResultSelect({
  results,
  selectedKey,
  onSelect,
  onRemove,
  onNotesSaved,
}: BacktestResultSelectProps) {
  const api = useApi()
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)

  const entries = Object.entries(results)

  const beginEdit = (key: string, result: BacktestResultInMemory) => {
    setEditingKey(key)
    setDraft(result.metadata.notes ?? '')
  }

  const confirmEdit = async (key: string, result: BacktestResultInMemory) => {
    const filename = result.metadata.filename
    if (!filename) {
      Toast.warning('该结果没有可写入的文件')
      setEditingKey(null)
      return
    }
    setSaving(true)
    try {
      await backtestApi.saveNotes(api, {
        run_id: result.metadata.run_id ?? key,
        filename,
        notes: draft,
        strategy: result.metadata.strategyName,
      })
      Toast.success('备注已保存')
      setEditingKey(null)
      onNotesSaved(key, draft)
    } catch (err) {
      Toast.error(err instanceof Error ? err.message : '备注保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel title="已加载结果" sub={`${entries.length}`} flush>
      {entries.length === 0 ? (
        <EmptyState title="暂无已加载结果" hint="运行回测或从历史记录载入" />
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {entries.map(([key, result]) => {
            const selected = key === selectedKey
            const editing = editingKey === key
            const strategy = result.strategy
            return (
              <li
                key={key}
                onClick={() => !editing && onSelect(key)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 'var(--ft-gap-3)',
                  padding: '6px 10px',
                  borderBottom: '1px solid var(--ft-line)',
                  cursor: editing ? 'default' : 'pointer',
                  background: selected ? 'var(--ft-ink-0)' : undefined,
                  color: selected ? 'var(--ft-paper-0)' : undefined,
                }}
              >
                {editing ? (
                  <>
                    <TextArea
                      rows={2}
                      autosize
                      value={draft}
                      placeholder="备注"
                      onChange={setDraft}
                      style={{ flex: '1 1 auto', minWidth: 0 }}
                    />
                    <Button
                      size="small"
                      theme="borderless"
                      type="tertiary"
                      icon={<IconTick />}
                      loading={saving}
                      title="保存备注"
                      onClick={(e) => {
                        e.stopPropagation()
                        void confirmEdit(key, result)
                      }}
                      style={{ color: 'inherit' }}
                    />
                    <Button
                      size="small"
                      theme="borderless"
                      type="tertiary"
                      icon={<IconClose />}
                      title="取消"
                      onClick={(e) => {
                        e.stopPropagation()
                        setEditingKey(null)
                      }}
                      style={{ color: 'inherit' }}
                    />
                  </>
                ) : (
                  <>
                    <div className="ft-col" style={{ gap: 0, minWidth: 0, flex: '1 1 auto' }}>
                      <span
                        className="ft-nowrap"
                        style={{ fontWeight: 600, fontSize: 'var(--ft-font-sm)' }}
                      >
                        {result.metadata.strategyName} · {strategy.timeframe ?? '–'}
                      </span>
                      <span
                        className="ft-num"
                        style={{ fontSize: 'var(--ft-font-xs)', opacity: selected ? 0.8 : 0.65 }}
                      >
                        {strategy.total_trades ?? 0} 笔 · {formatPercent(strategy.profit_total, 2)}
                      </span>
                      {result.metadata.notes ? (
                        <span
                          style={{
                            fontSize: 'var(--ft-font-xs)',
                            whiteSpace: 'pre-wrap',
                            opacity: 0.75,
                          }}
                        >
                          {result.metadata.notes}
                        </span>
                      ) : null}
                    </div>

                    {result.metadata.filename ? (
                      <Tooltip content="编辑备注">
                        <Button
                          size="small"
                          theme="borderless"
                          type="tertiary"
                          icon={<IconEdit />}
                          style={{ color: 'inherit' }}
                          onClick={(e) => {
                            e.stopPropagation()
                            beginEdit(key, result)
                          }}
                        />
                      </Tooltip>
                    ) : null}

                    <Tooltip content="从界面卸载（磁盘文件保留）">
                      <Button
                        size="small"
                        theme="borderless"
                        type="tertiary"
                        icon={<IconClose />}
                        style={{ color: 'inherit' }}
                        onClick={(e) => {
                          e.stopPropagation()
                          onRemove(key)
                        }}
                      />
                    </Tooltip>
                  </>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}
