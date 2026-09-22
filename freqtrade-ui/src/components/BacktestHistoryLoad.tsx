/**
 * Loads stored backtest results from disk.
 *
 * The list is fetched from `/backtest/history`; clicking a row (or the load
 * button) reads that result into the UI, and the delete action removes the
 * file from disk after a confirmation.
 */

import { useMemo, useState } from 'react'
import { Banner, Button, Input, Modal, Table, Toast, Tooltip } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import {
  IconClose,
  IconDelete,
  IconDownload,
  IconInfoCircle,
  IconRefresh,
  IconSearch,
} from '@douyinfe/semi-icons'

import { Panel } from './primitives'
import { backtestApi } from '../api/endpoints'
import { ApiError, type BotApi } from '../api/client'
import type { BacktestHistoryEntry, BacktestResponse } from '../api/types'
import { usePolling } from '../hooks/usePolling'
import { formatTimestamp, timeAgo } from '../utils/format'

/**
 * The backend's history entry also carries `run_id`, which the foundation's
 * `BacktestHistoryEntry` does not declare (the API type predates it).
 */
interface HistoryEntry extends BacktestHistoryEntry {
  run_id?: string
}

export interface BacktestHistoryLoadProps {
  api: BotApi
  /** Hands a freshly loaded result (and its raw response) to the page. */
  onLoad: (entry: BacktestHistoryEntry, response: BacktestResponse) => void
  /** `run_id`s already held in memory — those rows are marked as loaded. */
  loadedRunIds?: string[]
  onUnload?: (runId: string) => void
}

/** freqUI's `timestampToTimeRangeString`: compact "20260101" / "20260101T1200". */
function timeRangeString(ms: number): string {
  const full = formatTimestamp(ms, { timezone: 'UTC' })
  if (full === 'N/A') return 'N/A'
  const [date, time = '00:00:00'] = full.split(' ')
  const compact = date.replace(/-/g, '')
  if (time === '00:00:00') return compact
  const [hh, mm, ss] = time.split(':')
  return ss === '00' ? `${compact}T${hh}${mm}` : `${compact}T${hh}${mm}${ss}`
}

export function BacktestHistoryLoad({
  api,
  onLoad,
  loadedRunIds = [],
  onUnload,
}: BacktestHistoryLoadProps) {
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const { data, error, loading, refresh } = usePolling<HistoryEntry[]>(
    (signal) => backtestApi.history(api, signal),
    [api],
  )

  const entries = useMemo(() => (Array.isArray(data) ? data : []), [data])

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return entries
    return entries.filter(
      (entry) =>
        entry.filename.toLowerCase().includes(needle) ||
        entry.strategy.toLowerCase().includes(needle),
    )
  }, [entries, filter])

  const isLoaded = (entry: HistoryEntry) =>
    loadedRunIds.includes(entry.run_id ?? '') || loadedRunIds.includes(entry.filename)

  const loadResult = async (entry: HistoryEntry) => {
    if (isLoaded(entry)) return
    setBusy(entry.filename)
    try {
      const response = await backtestApi.historyResult(api, {
        filename: entry.filename,
        strategy: entry.strategy,
      })
      if (response?.backtest_result) {
        onLoad(entry, response)
        Toast.success(`已载入 ${entry.strategy}`)
      } else {
        Toast.warning('结果文件为空')
      }
    } catch (err) {
      Toast.error(err instanceof Error ? err.message : '载入失败')
    } finally {
      setBusy(null)
    }
  }

  const deleteResult = (entry: HistoryEntry) => {
    Modal.confirm({
      title: '删除回测结果',
      content: `确定从磁盘删除 ${entry.filename}？`,
      okText: '删除',
      cancelText: '取消',
      onOk: async () => {
        try {
          await backtestApi.deleteHistory(api, entry.filename)
          Toast.success('已删除')
          refresh()
        } catch (err) {
          Toast.error(err instanceof Error ? err.message : '删除失败')
        }
      },
    })
  }

  const wrongState = error instanceof ApiError && error.isWrongState

  const columns: ColumnProps<HistoryEntry>[] = [
    {
      key: 'strategy',
      title: 'Strategy',
      width: 180,
      render: (_: unknown, entry: HistoryEntry) => (
        <span style={{ fontWeight: 500 }}>{entry.strategy}</span>
      ),
    },
    {
      key: 'details',
      title: 'Details',
      render: (_: unknown, entry: HistoryEntry) => (
        <span className="ft-row ft-nowrap" style={{ gap: 'var(--ft-gap-3)' }}>
          <span className="ft-mono-sm" style={{ color: 'var(--ft-ink-0)' }}>
            {entry.timeframe ?? '–'}
          </span>
          {entry.backtest_start_ts && entry.backtest_end_ts ? (
            <span className="ft-mono-sm ft-faint">
              {timeRangeString(entry.backtest_start_ts * 1000)}-
              {timeRangeString(entry.backtest_end_ts * 1000)}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: 'backtest_start_time',
      title: 'Backtest Time',
      width: 190,
      render: (_: unknown, entry: HistoryEntry) => (
        <Tooltip content={timeAgo(entry.backtest_start_time * 1000)}>
          <span className="ft-num ft-muted">
            {formatTimestamp(entry.backtest_start_time * 1000)}
          </span>
        </Tooltip>
      ),
    },
    {
      key: 'filename',
      title: 'Filename',
      render: (_: unknown, entry: HistoryEntry) => (
        <span className="ft-mono-sm ft-faint" title={entry.filename}>
          {entry.filename}
        </span>
      ),
    },
    {
      key: 'actions',
      title: 'Actions',
      width: 140,
      align: 'right',
      render: (_: unknown, entry: HistoryEntry) => {
        const loaded = isLoaded(entry)
        return (
          <span
            className="ft-row"
            style={{ gap: 2, justifyContent: 'flex-end' }}
            onClick={(e) => e.stopPropagation()}
          >
            {entry.notes ? (
              <Tooltip content={entry.notes}>
                <span className="ft-faint" style={{ display: 'grid', placeItems: 'center' }}>
                  <IconInfoCircle />
                </span>
              </Tooltip>
            ) : null}
            {loaded ? (
              <Tooltip content="从界面卸载（磁盘文件保留）">
                <Button
                  size="small"
                  theme="borderless"
                  type="tertiary"
                  icon={<IconClose />}
                  onClick={() => onUnload?.(entry.run_id ?? entry.filename)}
                />
              </Tooltip>
            ) : (
              <Tooltip content="载入该结果">
                <Button
                  size="small"
                  theme="borderless"
                  type="tertiary"
                  icon={<IconDownload />}
                  loading={busy === entry.filename}
                  onClick={() => void loadResult(entry)}
                />
              </Tooltip>
            )}
            <Tooltip content="从磁盘删除">
              <Button
                size="small"
                theme="borderless"
                type="danger"
                icon={<IconDelete />}
                disabled={loaded}
                onClick={() => deleteResult(entry)}
              />
            </Tooltip>
          </span>
        )
      },
    },
  ]

  return (
    <Panel
      title="载入历史结果"
      icon={<IconDownload />}
      sub="点击行可载入，可同时载入多个结果"
      flush
      actions={
        <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
          <Input
            size="small"
            prefix={<IconSearch />}
            placeholder="过滤文件名或策略"
            value={filter}
            onChange={setFilter}
            showClear
            style={{ width: 220 }}
          />
          <Tooltip content="刷新列表">
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconRefresh />}
              onClick={refresh}
              loading={loading}
            />
          </Tooltip>
        </span>
      }
    >
      {wrongState && (
        <div style={{ padding: 'var(--ft-gap-4)' }}>
          <Banner
            type="info"
            bordered
            title="需要 webserver 模式"
            description="载入历史回测结果需要机器人以 webserver 模式运行。"
          />
        </div>
      )}

      {error && !wrongState && (
        <div style={{ padding: 'var(--ft-gap-4)' }}>
          <Banner type="danger" bordered title="无法读取历史结果" description={error.message} />
        </div>
      )}

      <Table<HistoryEntry>
        className="ft-table"
        columns={columns}
        dataSource={filtered}
        rowKey="filename"
        size="small"
        loading={loading}
        pagination={false}
        empty="没有历史回测结果"
        onRow={(entry?: HistoryEntry) => ({
          onClick: () => {
            if (entry) void loadResult(entry)
          },
          style: {
            cursor: entry && isLoaded(entry) ? 'not-allowed' : 'pointer',
            opacity: entry && isLoaded(entry) ? 0.6 : 1,
          },
        })}
      />
    </Panel>
  )
}
