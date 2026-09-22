/**
 * Logs page.
 *
 * A dense monospace tail of the bot's log: level colouring, level and text
 * filters, optional 5-second auto-refresh, and a jump-to-bottom control. The
 * view sticks to the bottom while new lines arrive unless the user scrolls up.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Banner, Button, Input, Select, Switch, Tooltip } from '@douyinfe/semi-ui'
import { IconArrowDown, IconRefresh, IconSearch, IconTerminal } from '@douyinfe/semi-icons'

import { infoApi } from '../api/endpoints'
import type { LogEntry, LogLevel } from '../api/types'
import { Panel, Tag } from '../components/primitives'
import { describeError, usePolling } from '../hooks/usePolling'
import { useApi } from '../state/bots'
import { useSettings } from '../state/settings'
import { formatTimestamp } from '../utils/format'

const LIMITS = [100, 200, 500, 1000, 2000]
const LEVELS: LogLevel[] = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

function levelColor(level: LogLevel): string {
  if (level === 'ERROR' || level === 'CRITICAL') return 'var(--ft-down)'
  if (level === 'WARNING') return 'var(--ft-warn)'
  return 'var(--ft-ink-4)'
}

function levelBackground(level: LogLevel): string | undefined {
  if (level === 'ERROR' || level === 'CRITICAL') return 'var(--ft-down-bg)'
  if (level === 'WARNING') return 'var(--ft-warn-bg)'
  return undefined
}

export function Logs() {
  const api = useApi()
  const { settings } = useSettings()

  const [limit, setLimit] = useState(500)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [level, setLevel] = useState<LogLevel | 'ALL'>('ALL')
  const [text, setText] = useState('')

  const containerRef = useRef<HTMLDivElement | null>(null)
  // True while the view should follow new lines; released when the user scrolls up.
  const stickRef = useRef(true)

  const { data, error, loading, refreshing, refresh } = usePolling(
    (signal) => infoApi.logs(api, limit, signal),
    [api, limit],
    { intervalMs: autoRefresh ? 5_000 : 0, enabled: Boolean(api) },
  )

  const entries: LogEntry[] = useMemo(() => data ?? [], [data])

  const filtered = useMemo(() => {
    let list = entries
    if (level !== 'ALL') list = list.filter((entry) => entry.level === level)
    const needle = text.trim().toLowerCase()
    if (needle) {
      list = list.filter(
        (entry) =>
          entry.message.toLowerCase().includes(needle) ||
          entry.logger.toLowerCase().includes(needle),
      )
    }
    return list
  }, [entries, level, text])

  const counts = useMemo(() => {
    let errors = 0
    let warnings = 0
    for (const entry of entries) {
      if (entry.level === 'ERROR' || entry.level === 'CRITICAL') errors += 1
      else if (entry.level === 'WARNING') warnings += 1
    }
    return { errors, warnings }
  }, [entries])

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    stickRef.current = true
    el.scrollTop = el.scrollHeight
  }, [])

  // Follow the tail as new lines arrive.
  useEffect(() => {
    const el = containerRef.current
    if (!el || !stickRef.current) return
    el.scrollTop = el.scrollHeight
  }, [data])

  const onScroll = () => {
    const el = containerRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }

  const levelOptions = [
    { value: 'ALL', label: '全部级别' },
    ...LEVELS.map((item) => ({ value: item, label: item })),
  ]

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">日志</h1>
        <span className="ft-page-sub">
          {filtered.length} / {entries.length} 行
          {counts.errors > 0 ? ` · ${counts.errors} 错误` : ''}
          {counts.warnings > 0 ? ` · ${counts.warnings} 警告` : ''}
        </span>
        <div style={{ marginLeft: 'auto' }} className="ft-row">
          <Tooltip content="立即刷新">
            <Button size="small" icon={<IconRefresh spin={refreshing || loading} />} onClick={refresh} />
          </Tooltip>
        </div>
      </div>

      {error && (
        <Banner
          type="danger"
          bordered
          title="读取日志失败"
          description={describeError(error) ?? error.message}
        />
      )}

      <Panel
        title="日志输出"
        icon={<IconTerminal />}
        sub={autoRefresh ? '每 5 秒自动刷新' : '自动刷新已关闭'}
        flush
        bodyClassName="ft-scroll-x ft-list-viewport"
        actions={
          <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
            <Select
              size="small"
              value={level}
              onChange={(value) => setLevel((value as LogLevel | 'ALL') ?? 'ALL')}
              optionList={levelOptions}
              style={{ width: 118 }}
            />
            <Input
              size="small"
              prefix={<IconSearch />}
              placeholder="过滤消息 / logger"
              value={text}
              onChange={setText}
              showClear
              style={{ width: 220 }}
            />
            <Select
              size="small"
              value={limit}
              onChange={(value) => setLimit(Number(value) || 500)}
              optionList={LIMITS.map((item) => ({ value: item, label: `最近 ${item} 行` }))}
              style={{ width: 118 }}
            />
            <label className="ft-row" style={{ gap: 6, fontSize: 'var(--ft-font-sm)' }}>
              <Switch size="small" checked={autoRefresh} onChange={setAutoRefresh} />
              自动刷新
            </label>
            <Tooltip content="滚动到底部">
              <Button size="small" icon={<IconArrowDown />} onClick={scrollToBottom} />
            </Tooltip>
          </div>
        }
      >
        <div
          ref={containerRef}
          onScroll={onScroll}
          style={{
            height: 'calc(100vh - 230px)',
            minHeight: 320,
            overflowY: 'auto',
            overflowX: 'hidden',
            padding: 'var(--ft-gap-3) var(--ft-gap-4)',
            background: 'var(--ft-paper-0)',
          }}
        >
          {filtered.length === 0 ? (
            <div className="ft-empty">
              <span className="ft-empty-icon">
                <IconTerminal />
              </span>
              <div>{entries.length ? '没有匹配的日志行' : '暂无日志'}</div>
              <div className="ft-faint">
                {entries.length
                  ? '尝试调整级别或关键词过滤。'
                  : '机器人尚未输出日志，或日志接口不可用。'}
              </div>
            </div>
          ) : (
            filtered.map((entry, index) => (
              <div
                key={`${entry.timestamp}-${index}`}
                className="ft-mono-sm"
                style={{
                  display: 'flex',
                  gap: 'var(--ft-gap-4)',
                  alignItems: 'baseline',
                  padding: '1px 4px',
                  borderRadius: 'var(--ft-radius-sm)',
                  background: levelBackground(entry.level),
                  lineHeight: 1.45,
                }}
              >
                <span className="ft-faint ft-nowrap" style={{ flex: '0 0 auto' }}>
                  {formatTimestamp(entry.timestamp, { timezone: settings.timezone })}
                </span>
                <span
                  className="ft-nowrap"
                  style={{
                    flex: '0 0 76px',
                    color: levelColor(entry.level),
                    fontWeight: entry.level === 'ERROR' || entry.level === 'CRITICAL' ? 600 : 500,
                  }}
                >
                  {entry.level.padEnd(8, ' ')}
                </span>
                <span
                  className="ft-muted ft-nowrap"
                  style={{
                    flex: '0 1 190px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                  title={entry.logger}
                >
                  {entry.logger}
                </span>
                <span style={{ flex: '1 1 auto', minWidth: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                  {entry.message}
                </span>
              </div>
            ))
          )}
        </div>
      </Panel>

      <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-2)' }}>
        <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
          级别图例
        </span>
        {LEVELS.map((item) => (
          <Tag key={item} variant="plain" title={`${item} 颜色`}>
            <span style={{ color: levelColor(item) }}>{item}</span>
          </Tag>
        ))}
      </div>
    </div>
  )
}
