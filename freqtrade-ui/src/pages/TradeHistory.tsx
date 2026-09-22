/**
 * Trade history — closed trades with server-side pagination.
 *
 * `/trades` is paginated by the backend, so the page requests a window at a
 * time and feeds the total back into the table's pagination control. Selecting
 * a row opens the detail side sheet, which also carries the delete action
 * (closed-trade rows have no inline actions column).
 */

import { useCallback, useState } from 'react'
import { Button, Modal, SideSheet, Toast, Tooltip } from '@douyinfe/semi-ui'
import { IconDelete, IconHistory, IconRefresh, IconTemplate } from '@douyinfe/semi-icons'

import type { Trade } from '../api/types'
import { tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import { describeError, usePolling } from '../hooks/usePolling'
import { TradeDetail } from '../components/TradeDetail'
import { TradeList } from '../components/TradeList'
import { DryRunTag, Panel } from '../components/primitives'
import { displayPair, formatPriceCurrency } from '../utils/format'

const PAGE_SIZE = 25

export function TradeHistory() {
  const api = useApi()
  const { config, refresh } = useSnapshot()

  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Trade | null>(null)

  const stakeCurrency = config?.stake_currency ?? 'USDT'
  const stakeDecimals = config?.stake_currency_decimals ?? 3
  const tradingMode = config?.trading_mode ?? 'spot'

  const state = usePolling(
    (signal) =>
      tradingApi.trades(
        api,
        { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE },
        signal,
      ),
    [api, page],
    { intervalMs: 60_000 },
  )

  const trades = state.data?.trades ?? []
  const total = state.data?.total_trades ?? 0
  const refreshTrades = state.refresh

  const afterMutation = useCallback(() => {
    refresh()
    refreshTrades()
    setSelected(null)
  }, [refresh, refreshTrades])

  const handleDeleteTrade = useCallback(
    (trade: Trade) => {
      Modal.confirm({
        title: '删除交易',
        content: `永久删除 #${trade.trade_id} ${displayPair(trade.pair)}？该操作不可撤销。`,
        okText: '确认',
        cancelText: '取消',
        onOk: async () => {
          try {
            await tradingApi.deleteTrade(api, trade.trade_id)
            Toast.success({ content: '交易已删除', duration: 2 })
            afterMutation()
          } catch (err) {
            Toast.error({ content: describeError(err as Error) ?? String(err) })
          }
        },
      })
    },
    [api, afterMutation],
  )

  const handleReloadTrade = useCallback(
    (trade: Trade) => {
      Modal.confirm({
        title: '重新加载交易',
        content: `从交易所重新同步 #${trade.trade_id} ${displayPair(trade.pair)} 的状态？`,
        okText: '确认',
        cancelText: '取消',
        onOk: async () => {
          try {
            await tradingApi.reloadTrade(api, trade.trade_id)
            Toast.success({ content: '交易已重新加载', duration: 2 })
            afterMutation()
          } catch (err) {
            Toast.error({ content: describeError(err as Error) ?? String(err) })
          }
        },
      })
    },
    [api, afterMutation],
  )

  const handleForceExit = useCallback(
    (trade: Trade, orderType?: string) => {
      Modal.confirm({
        title: '强制平仓',
        content: `确定强制平掉 #${trade.trade_id} ${displayPair(trade.pair)}${
          orderType ? `（${orderType}）` : ''
        } 吗？`,
        okText: '确认',
        cancelText: '取消',
        onOk: async () => {
          try {
            await tradingApi.forceExit(api, {
              tradeid: String(trade.trade_id),
              ...(orderType ? { ordertype: orderType } : {}),
            })
            Toast.success({ content: '平仓指令已发送', duration: 2 })
            afterMutation()
          } catch (err) {
            Toast.error({ content: describeError(err as Error) ?? String(err) })
          }
        },
      })
    },
    [api, afterMutation],
  )

  const pageProfit = trades.reduce((sum, trade) => sum + (trade.profit_abs ?? 0), 0)

  return (
    <div className="ft-page fill">
      <header className="ft-page-head">
        <h1 className="ft-page-title">交易历史</h1>
        <span className="ft-page-sub">
          共 {total} 笔 · 第 {page} 页
        </span>
        <span className="ft-row" style={{ marginLeft: 'auto', gap: 'var(--ft-gap-4)' }}>
          {config && <DryRunTag dryRun={config.dry_run} />}
          <span className="ft-faint ft-num" style={{ fontSize: 'var(--ft-font-xs)' }}>
            本页盈亏{' '}
            <span
              className={
                pageProfit > 0 ? 'ft-up' : pageProfit < 0 ? 'ft-down' : 'ft-flat'
              }
            >
              {formatPriceCurrency(pageProfit, stakeCurrency, stakeDecimals)}
            </span>
          </span>
          <Tooltip content="立即刷新">
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconRefresh />}
              onClick={refreshTrades}
            />
          </Tooltip>
        </span>
      </header>

      <Panel
        title="已平仓交易"
        icon={<IconHistory />}
        flush
      >
        <TradeList
          trades={trades}
          activeTrades={false}
          loading={state.loading}
          showFilter
          stakeCurrency={stakeCurrency}
          stakeCurrencyDecimals={stakeDecimals}
          tradingMode={tradingMode}
          selectedTradeId={selected?.trade_id ?? null}
          onSelectTrade={setSelected}
          // Closed-trade rows have no inline actions column in TradeList; these
          // handlers are still wired so the component can surface them if that
          // changes, and the side sheet below exposes the actions today.
          onForceExit={handleForceExit}
          onReloadTrade={handleReloadTrade}
          onDeleteTrade={handleDeleteTrade}
          pagination={{
            page,
            pageSize: PAGE_SIZE,
            total,
            onChange: setPage,
          }}
          emptyText="暂无已平仓交易。"
        />
      </Panel>

      <SideSheet
        title={
          selected ? `交易详情 #${selected.trade_id} · ${displayPair(selected.pair)}` : '交易详情'
        }
        visible={selected !== null}
        onCancel={() => setSelected(null)}
        width={760}
        placement="right"
        footer={
          selected ? (
            <div className="ft-row" style={{ justifyContent: 'flex-end', gap: 'var(--ft-gap-3)' }}>
              <Button
                size="small"
                theme="borderless"
                type="tertiary"
                icon={<IconRefresh />}
                onClick={() => handleReloadTrade(selected)}
              >
                重新加载
              </Button>
              <Button
                size="small"
                theme="light"
                type="danger"
                icon={<IconDelete />}
                onClick={() => handleDeleteTrade(selected)}
              >
                删除交易
              </Button>
            </div>
          ) : undefined
        }
      >
        {selected ? (
          <TradeDetail
            trade={selected}
            stakeCurrency={stakeCurrency}
            stakeCurrencyDecimals={stakeDecimals}
          />
        ) : (
          <div className="ft-empty">
            <span className="ft-empty-icon">
              <IconTemplate />
            </span>
            <div>未选择交易</div>
          </div>
        )}
      </SideSheet>
    </div>
  )
}
