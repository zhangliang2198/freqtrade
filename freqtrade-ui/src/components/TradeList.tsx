/**
 * The trade table.
 *
 * Used for open trades, closed trades and backtest trade lists. Open trades get
 * an actions column and show live figures; closed trades get close reason and
 * date. All rows are clickable and select the trade into the detail pane.
 */

import { useMemo, useState } from 'react'
import { Button, Dropdown, Input, Pagination, Space, Table } from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import {
  IconClose,
  IconDelete,
  IconExit,
  IconFilter,
  IconMore,
  IconPlus,
  IconRefresh,
  IconSearch,
} from '@douyinfe/semi-icons'

import type { Trade } from '../api/types'
import { DirectionTag, EmptyState, Tag } from './primitives'
import { TradeProfit } from './ProfitPill'
import { displayPair, formatPrice, formatTimestamp, parseTradeDate } from '../utils/format'

export interface TradeListProps {
  trades: Trade[]
  /** Open trades show current rate/profit and an actions column. */
  activeTrades?: boolean
  loading?: boolean
  /** Stake currency, for precision of stake columns. */
  stakeCurrency?: string
  stakeCurrencyDecimals?: number
  tradingMode?: string
  shortAllowed?: boolean
  forceEntryEnable?: boolean
  /** Enable the text filter. */
  showFilter?: boolean
  /** Server-side pagination for closed trade history. */
  pagination?: { page: number; pageSize: number; total: number; onChange: (page: number) => void }
  selectedTradeId?: number | null
  onSelectTrade?: (trade: Trade) => void
  /** Per-trade action handlers. Omit to hide the actions column. */
  onForceExit?: (trade: Trade, orderType?: string) => void
  onForceExitPartial?: (trade: Trade) => void
  onCancelOpenOrder?: (trade: Trade) => void
  onReloadTrade?: (trade: Trade) => void
  onDeleteTrade?: (trade: Trade) => void
  onIncreasePosition?: (trade: Trade) => void
  emptyText?: string
}

export function TradeList({
  trades,
  activeTrades = false,
  loading,
  stakeCurrency = 'USDT',
  stakeCurrencyDecimals = 3,
  tradingMode = 'spot',
  forceEntryEnable = false,
  showFilter = false,
  pagination,
  selectedTradeId,
  onSelectTrade,
  onForceExit,
  onForceExitPartial,
  onCancelOpenOrder,
  onReloadTrade,
  onDeleteTrade,
  onIncreasePosition,
  emptyText = 'No trades to show.',
}: TradeListProps) {
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(1)
  const isFutures = tradingMode !== 'spot'
  // Actions are shown whenever a handler exists — a closed trade can still be
  // reloaded or deleted, so gating on `activeTrades` would hide them.
  const hasActions = Boolean(
    onForceExit ||
      onForceExitPartial ||
      onCancelOpenOrder ||
      onReloadTrade ||
      onDeleteTrade ||
      onIncreasePosition,
  )

  const filtered = useMemo(() => {
    if (!filter.trim()) return trades
    const needle = filter.trim().toLowerCase()
    return trades.filter((t) =>
      [t.pair, t.exit_reason, t.enter_tag, String(t.trade_id)]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(needle)),
    )
  }, [trades, filter])

  // Client-side pagination when the caller does not paginate on the server.
  const pageSize = activeTrades ? 200 : 25
  const paged = useMemo(() => {
    if (pagination) return filtered
    if (activeTrades) return filtered
    const start = (page - 1) * pageSize
    return filtered.slice(start, start + pageSize)
  }, [filtered, page, pageSize, activeTrades, pagination])

  const leverageSuffix = (trade: Trade) =>
    isFutures && trade.leverage ? ` (${trade.leverage}x)` : ''

  const columns: ColumnProps<Trade>[] = useMemo(() => {
    const cols: ColumnProps<Trade>[] = [
      {
        title: 'ID',
        dataIndex: 'trade_id',
        width: 96,
        render: (_: unknown, trade: Trade) => (
          <span className="ft-row" style={{ gap: 6 }}>
            <span className="ft-num">{trade.trade_id}</span>
            {isFutures && <DirectionTag isShort={trade.is_short} />}
          </span>
        ),
      },
      {
        title: 'Pair',
        dataIndex: 'pair',
        width: 160,
        render: (pair: string, trade: Trade) => (
          <span className="ft-row" style={{ gap: 4 }}>
            <span style={{ fontWeight: 500 }}>{displayPair(pair)}</span>
            {trade.has_open_orders && (
              <Tag variant="plain" title="Has open orders">
                *
              </Tag>
            )}
          </span>
        ),
      },
      {
        title: 'Amount',
        dataIndex: 'amount',
        align: 'right',
        width: 110,
        render: (v: number) => <span className="ft-num">{formatPrice(v, 8)}</span>,
      },
      {
        title: activeTrades ? `Stake (${stakeCurrency})` : `Total stake (${stakeCurrency})`,
        dataIndex: activeTrades ? 'stake_amount' : 'max_stake_amount',
        align: 'right',
        width: 132,
        render: (_: unknown, trade: Trade) => {
          const value = activeTrades ? trade.stake_amount : (trade.max_stake_amount ?? trade.stake_amount)
          return (
            <span className="ft-num" title={`${formatPrice(value, stakeCurrencyDecimals)} ${stakeCurrency}`}>
              {formatPrice(value, stakeCurrencyDecimals)}
              {leverageSuffix(trade)}
            </span>
          )
        },
      },
      {
        title: 'Open rate',
        dataIndex: 'open_rate',
        align: 'right',
        width: 110,
        render: (v: number) => <span className="ft-num">{formatPrice(v, 8)}</span>,
      },
      {
        title: activeTrades ? 'Current' : 'Close rate',
        dataIndex: activeTrades ? 'current_rate' : 'close_rate',
        align: 'right',
        width: 110,
        render: (_: unknown, trade: Trade) => {
          const value = activeTrades
            ? (trade as Trade & { current_rate?: number }).current_rate
            : trade.close_rate
          return <span className="ft-num">{value == null ? '–' : formatPrice(value, 8)}</span>
        },
      },
      {
        title: 'Profit',
        dataIndex: 'profit_ratio',
        align: 'right',
        width: 150,
        render: (_: unknown, trade: Trade) => <TradeProfit trade={trade} />,
      },
      {
        title: 'Open date',
        dataIndex: 'open_timestamp',
        width: 150,
        render: (_: unknown, trade: Trade) => (
          <span className="ft-num ft-muted">
            {formatTimestamp(trade.open_timestamp ?? parseTradeDate(trade.open_date) ?? 0)}
          </span>
        ),
      },
    ]

    if (!activeTrades) {
      cols.push(
        {
          title: 'Close date',
          dataIndex: 'close_timestamp',
          width: 150,
          render: (_: unknown, trade: Trade) => (
            <span className="ft-num ft-muted">
              {formatTimestamp(trade.close_timestamp ?? parseTradeDate(trade.close_date) ?? 0)}
            </span>
          ),
        },
        {
          title: 'Exit reason',
          dataIndex: 'exit_reason',
          width: 150,
          render: (v: string | null) => (v ? <Tag variant="plain">{v}</Tag> : <span className="ft-faint">–</span>),
        },
      )
    }

    if (hasActions) {
      cols.push({
        title: '',
        dataIndex: 'actions',
        width: 48,
        align: 'center',
        render: (_: unknown, trade: Trade) => (
          <Dropdown
            trigger="click"
            position="bottomRight"
            clickToHide
            render={
              <Dropdown.Menu>
                {onForceExit && (
                  <>
                    <Dropdown.Item
                      icon={<IconExit />}
                      onClick={() => onForceExit(trade)}
                      type="tertiary"
                    >
                      Force exit
                    </Dropdown.Item>
                    <Dropdown.Item icon={<IconExit />} onClick={() => onForceExit(trade, 'limit')}>
                      Force exit — limit
                    </Dropdown.Item>
                    <Dropdown.Item icon={<IconExit />} onClick={() => onForceExit(trade, 'market')}>
                      Force exit — market
                    </Dropdown.Item>
                  </>
                )}
                {onForceExitPartial && (
                  <Dropdown.Item icon={<IconClose />} onClick={() => onForceExitPartial(trade)}>
                    Exit partial
                  </Dropdown.Item>
                )}
                {onCancelOpenOrder && trade.has_open_orders && (
                  <Dropdown.Item icon={<IconClose />} onClick={() => onCancelOpenOrder(trade)}>
                    Cancel open orders
                  </Dropdown.Item>
                )}
                {forceEntryEnable && onIncreasePosition && (
                  <Dropdown.Item icon={<IconPlus />} onClick={() => onIncreasePosition(trade)}>
                    Increase position
                  </Dropdown.Item>
                )}
                {onReloadTrade && (
                  <Dropdown.Item icon={<IconRefresh />} onClick={() => onReloadTrade(trade)}>
                    Reload
                  </Dropdown.Item>
                )}
                {onDeleteTrade && (
                  <Dropdown.Item
                    icon={<IconDelete />}
                    type="danger"
                    onClick={() => onDeleteTrade(trade)}
                  >
                    Delete trade
                  </Dropdown.Item>
                )}
              </Dropdown.Menu>
            }
          >
            <Button icon={<IconMore />} size="small" theme="borderless" type="tertiary" />
          </Dropdown>
        ),
      })
    }

    return cols
  }, [
    activeTrades,
    hasActions,
    isFutures,
    stakeCurrencyDecimals,
    forceEntryEnable,
    onForceExit,
    onForceExitPartial,
    onCancelOpenOrder,
    onReloadTrade,
    onDeleteTrade,
    onIncreasePosition,
  ])

  const total = pagination?.total ?? filtered.length

  return (
    <div className="ft-col" style={{ gap: 0 }}>
      {showFilter && (
        <div
          className="ft-row"
          style={{ padding: '8px 10px', borderBottom: '1px solid var(--ft-line)' }}
        >
          <Input
            size="small"
            prefix={<IconSearch />}
            placeholder="Filter by pair, tag or exit reason"
            value={filter}
            onChange={setFilter}
            showClear
            style={{ maxWidth: 320 }}
          />
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            <IconFilter /> {filtered.length} / {trades.length}
          </span>
        </div>
      )}

      <div className="ft-scroll-x ft-list-viewport">
        <Table<Trade>
          className="ft-table"
          columns={columns}
          dataSource={paged}
          loading={loading}
          rowKey="trade_id"
          size="small"
          pagination={false}
          empty={<EmptyState icon={<IconFilter />} title={emptyText} />}
          onRow={(trade) => ({
            // Semi types the callback argument as optional; skip rather than crash.
            onClick: () => trade && onSelectTrade?.(trade),
            style: {
              cursor: onSelectTrade ? 'pointer' : 'default',
              background:
                trade && selectedTradeId === trade.trade_id ? 'var(--ft-paper-3)' : undefined,
            },
          })}
        />
      </div>

      {/* The pager lives *outside* the scroll viewport. Inside it, reaching the
          next page meant scrolling to the bottom of a 25-row table first. */}
      {!activeTrades && total > pageSize && (
        <div
          className="ft-row"
          style={{
            padding: '8px 10px',
            justifyContent: 'flex-end',
            borderTop: '1px solid var(--ft-line)',
            flexShrink: 0,
          }}
        >
          <Space>
            <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
              每页 {pagination?.pageSize ?? pageSize} 笔 · 共 {total} 笔
            </span>
            <Pagination
              size="small"
              total={total}
              pageSize={pagination?.pageSize ?? pageSize}
              currentPage={pagination?.page ?? page}
              onPageChange={(p) => {
                if (pagination) pagination.onChange(p)
                else setPage(p)
              }}
            />
          </Space>
        </div>
      )}
    </div>
  )
}
