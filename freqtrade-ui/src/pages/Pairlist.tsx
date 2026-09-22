/**
 * Pairlist page.
 *
 * The bot's live pair universe: the methods that produced it, the whitelist
 * itself, and the blacklist with inline add/remove. Mutations go through the
 * REST API and are followed by a snapshot refresh; the API answers with a
 * per-pair `errors` map, which is surfaced as toasts rather than swallowed.
 */

import { useMemo, useState } from 'react'
import { Banner, Button, Input, Tooltip, Toast } from '@douyinfe/semi-ui'
import {
  IconAlertTriangle,
  IconClose,
  IconDelete,
  IconList,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconTick,
} from '@douyinfe/semi-icons'

import { pairlistApi } from '../api/endpoints'
import type { BlacklistResponse } from '../api/types'
import { Panel, Tag } from '../components/primitives'
import { describeError } from '../hooks/usePolling'
import { useApi } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import { displayPair } from '../utils/format'

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The backend returns `errors: { [pair]: { error_msg } }`. The shared type
 * describes it as `Record<string, string>`, so normalise defensively.
 */
function blacklistErrors(response: BlacklistResponse | undefined): [string, string][] {
  const raw = (response?.errors ?? {}) as Record<string, unknown>
  const entries: [string, string][] = []
  for (const [pair, value] of Object.entries(raw)) {
    if (typeof value === 'string') entries.push([pair, value])
    else if (value && typeof value === 'object') {
      const message = (value as { error_msg?: unknown }).error_msg
      entries.push([pair, typeof message === 'string' ? message : JSON.stringify(value)])
    }
  }
  return entries
}

function reportResult(response: BlacklistResponse | undefined, successText: string): void {
  const errors = blacklistErrors(response)
  if (!errors.length) {
    Toast.success(successText)
    return
  }
  for (const [pair, message] of errors) {
    Toast.error({ content: `${displayPair(pair)}: ${message}`, duration: 6 })
  }
}

/* -------------------------------------------------------------------------- */
/* Pair grid                                                                   */
/* -------------------------------------------------------------------------- */

function PairGrid({
  pairs,
  selected,
  onToggle,
  emptyText,
}: {
  pairs: string[]
  /** Only meaningful for the interactive blacklist grid. */
  selected?: string[]
  onToggle?: (pair: string) => void
  emptyText: string
}) {
  if (!pairs.length) {
    return (
      <div className="ft-faint" style={{ fontSize: 'var(--ft-font-sm)', padding: 'var(--ft-gap-4) 0' }}>
        {emptyText}
      </div>
    )
  }

  const selectedSet = new Set(selected ?? [])
  const interactive = Boolean(onToggle)

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(112px, 1fr))',
        gap: 'var(--ft-gap-2)',
      }}
    >
      {pairs.map((pair) => {
        const isSelected = selectedSet.has(pair)
        return (
          <div
            key={pair}
            title={pair}
            onClick={interactive ? () => onToggle?.(pair) : undefined}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '3px 6px',
              border: `1px solid ${isSelected ? 'var(--ft-ink-0)' : 'var(--ft-line-strong)'}`,
              borderRadius: 'var(--ft-radius-sm)',
              background: isSelected ? 'var(--ft-ink-0)' : 'var(--ft-paper-2)',
              color: isSelected ? 'var(--ft-paper-0)' : 'var(--ft-ink-1)',
              cursor: interactive ? 'pointer' : 'default',
              fontSize: 'var(--ft-font-xs)',
              fontFamily: 'var(--ft-mono)',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              userSelect: 'none',
            }}
          >
            {isSelected && <IconTick size="small" />}
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{displayPair(pair)}</span>
          </div>
        )
      })}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export function Pairlist() {
  const api = useApi()
  const { whitelist, pairlistMethods, blacklist, refresh, loading } = useSnapshot()

  const [newPair, setNewPair] = useState('')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string[]>([])
  const [filter, setFilter] = useState('')

  const blacklistPairs = blacklist?.blacklist ?? []
  const expandedCount = blacklist?.blacklist_expanded?.length ?? 0

  const filteredWhitelist = useMemo(() => {
    if (!filter.trim()) return whitelist
    const needle = filter.trim().toLowerCase()
    return whitelist.filter((pair) => pair.toLowerCase().includes(needle))
  }, [whitelist, filter])

  const toggleSelected = (pair: string) => {
    setSelected((prev) =>
      prev.includes(pair) ? prev.filter((p) => p !== pair) : [...prev, pair],
    )
  }

  const addPair = async () => {
    const pair = newPair.trim()
    if (!pair) return
    setBusy(true)
    try {
      const response = await pairlistApi.addBlacklist(api, [pair])
      reportResult(response, `已加入黑名单：${displayPair(pair)}`)
      setNewPair('')
      refresh()
    } catch (err) {
      Toast.error(describeError(err as Error) ?? '添加失败')
    } finally {
      setBusy(false)
    }
  }

  const deleteSelected = async () => {
    if (!selected.length) return
    setBusy(true)
    try {
      const response = await pairlistApi.deleteBlacklist(api, selected)
      reportResult(response, `已从黑名单移除 ${selected.length} 个交易对`)
      setSelected([])
      refresh()
    } catch (err) {
      Toast.error(describeError(err as Error) ?? '删除失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">交易对列表</h1>
        <span className="ft-page-sub">
          白名单 {whitelist.length} · 黑名单 {blacklistPairs.length}
          {expandedCount > blacklistPairs.length ? `（展开后 ${expandedCount}）` : ''}
        </span>
        <div style={{ marginLeft: 'auto' }} className="ft-row">
          <Button size="small" icon={<IconRefresh spin={loading} />} onClick={refresh}>
            刷新
          </Button>
        </div>
      </div>

      {blacklist?.method?.length ? (
        <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-2)' }}>
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            黑名单来源
          </span>
          {blacklist.method.map((method) => (
            <Tag key={method} variant="plain">
              {method}
            </Tag>
          ))}
        </div>
      ) : null}

      {/* Whitelist methods ------------------------------------------------- */}
      <Panel
        title="白名单方法"
        icon={<IconList />}
        sub={`${pairlistMethods.length} 个处理器`}
      >
        {pairlistMethods.length ? (
          <ol
            style={{
              margin: 0,
              padding: 0,
              listStyle: 'none',
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
              gap: 'var(--ft-gap-2)',
            }}
          >
            {pairlistMethods.map((method, index) => (
              <li
                key={`${method}-${index}`}
                className="ft-row"
                style={{
                  gap: 'var(--ft-gap-4)',
                  border: '1px solid var(--ft-line)',
                  borderRadius: 'var(--ft-radius-sm)',
                  padding: '3px 8px',
                  background: 'var(--ft-paper-2)',
                }}
              >
                <span className="ft-num ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  {index + 1}
                </span>
                <span className="ft-mono-sm">{method}</span>
              </li>
            ))}
          </ol>
        ) : (
          <div className="ft-faint" style={{ fontSize: 'var(--ft-font-sm)' }}>
            暂无 pairlist 处理器信息。
          </div>
        )}
      </Panel>

      {/* Whitelist -------------------------------------------------------- */}
      <Panel
        title="白名单"
        icon={<IconTick />}
        sub={`${filteredWhitelist.length} / ${whitelist.length}`}
        actions={
          <Input
            size="small"
            prefix={<IconSearch />}
            placeholder="筛选交易对"
            value={filter}
            onChange={setFilter}
            showClear
            style={{ width: 200 }}
          />
        }
      >
        {whitelist.length ? (
          <PairGrid pairs={filteredWhitelist} emptyText="没有匹配的交易对。" />
        ) : (
          <Banner
            type="info"
            bordered
            title="白名单为空"
            description="请确认机器人正在运行，且 pairlist 配置正确。"
          />
        )}
      </Panel>

      {/* Blacklist -------------------------------------------------------- */}
      <Panel
        title="黑名单"
        icon={<IconAlertTriangle />}
        sub={`${blacklistPairs.length} 个`}
        actions={
          <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
            <Input
              size="small"
              value={newPair}
              placeholder="例如 BTC/USDT"
              onChange={setNewPair}
              onEnterPress={addPair}
              style={{ width: 190 }}
            />
            <Tooltip content="加入黑名单">
              <Button
                size="small"
                icon={<IconPlus />}
                loading={busy}
                disabled={!newPair.trim()}
                onClick={addPair}
              >
                添加
              </Button>
            </Tooltip>
            <Tooltip content={selected.length ? `删除选中的 ${selected.length} 个` : '先点击交易对进行选择'}>
              <Button
                size="small"
                type="danger"
                icon={<IconDelete />}
                disabled={!selected.length || busy}
                onClick={deleteSelected}
              >
                删除{selected.length ? ` (${selected.length})` : ''}
              </Button>
            </Tooltip>
            {selected.length > 0 && (
              <Button
                size="small"
                theme="borderless"
                type="tertiary"
                icon={<IconClose />}
                onClick={() => setSelected([])}
              >
                取消选择
              </Button>
            )}
          </div>
        }
      >
        <PairGrid
          pairs={blacklistPairs}
          selected={selected}
          onToggle={toggleSelected}
          emptyText="黑名单为空。点击上方「添加」把交易对加入黑名单。"
        />
        {expandedCount > blacklistPairs.length && (
          <div className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)', marginTop: 'var(--ft-gap-4)' }}>
            通配符展开后共 {expandedCount} 个交易对。
          </div>
        )}
      </Panel>
    </div>
  )
}
