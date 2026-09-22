/**
 * Open trades — the full-width, action-capable view of the bot's positions.
 *
 * Selecting a row opens the trade detail in a side sheet; every mutation asks
 * for confirmation and then refreshes the shared snapshot.
 */

import { useCallback, useState } from 'react'
import { Button, Modal, SideSheet, Toast, Tooltip } from '@douyinfe/semi-ui'
import {
  IconActivity,
  IconDelete,
  IconExit,
  IconRefresh,
  IconTemplate,
} from '@douyinfe/semi-icons'

import type { Trade } from '../api/types'
import { tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import { describeError } from '../hooks/usePolling'
import { ForceEntryForm } from '../components/ForceEntryForm'
import { ForceExitForm } from '../components/ForceExitForm'
import { TradeDetail } from '../components/TradeDetail'
import { TradeList } from '../components/TradeList'
import { DryRunTag, Panel, StateTag } from '../components/primitives'
import { displayPair, formatTimestamp } from '../utils/format'

export function OpenTrades() {
  const api = useApi()
  const { config, openTrades, loading, lastUpdated, refresh } = useSnapshot()

  const [selected, setSelected] = useState<Trade | null>(null)
  const [exitTarget, setExitTarget] = useState<Trade | null>(null)
  const [entryTarget, setEntryTarget] = useState<{ pair: string; increase: boolean } | null>(null)

  const stakeCurrency = config?.stake_currency ?? 'USDT'
  const stakeDecimals = config?.stake_currency_decimals ?? 3
  const tradingMode = config?.trading_mode ?? 'spot'

  const afterMutation = useCallback(() => {
    refresh()
    setSelected(null)
  }, [refresh])

  const confirmAction = useCallback(
    (title: string, content: string, action: () => Promise<unknown>, success: string) => {
      Modal.confirm({
        title,
        content,
        okText: '确认',
        cancelText: '取消',
        onOk: async () => {
          try {
            await action()
            Toast.success({ content: success, duration: 2 })
            afterMutation()
          } catch (err) {
            Toast.error({ content: describeError(err as Error) ?? String(err) })
          }
        },
      })
    },
    [afterMutation],
  )

  const handleForceExit = useCallback(
    (trade: Trade, orderType?: string) => {
      confirmAction(
        '强制平仓',
        `确定强制平掉 #${trade.trade_id} ${displayPair(trade.pair)}${
          orderType ? `（${orderType}）` : ''
        } 吗？`,
        () =>
          tradingApi.forceExit(api, {
            tradeid: String(trade.trade_id),
            ...(orderType ? { ordertype: orderType } : {}),
          }),
        '平仓指令已发送',
      )
    },
    [api, confirmAction],
  )

  const handleCancelOpenOrder = useCallback(
    (trade: Trade) => {
      confirmAction(
        '取消挂单',
        `取消 #${trade.trade_id} ${displayPair(trade.pair)} 的所有未成交挂单？`,
        () => tradingApi.cancelOpenOrder(api, trade.trade_id),
        '已取消挂单',
      )
    },
    [api, confirmAction],
  )

  const handleReloadTrade = useCallback(
    (trade: Trade) => {
      confirmAction(
        '重新加载交易',
        `从交易所重新同步 #${trade.trade_id} ${displayPair(trade.pair)} 的状态？`,
        () => tradingApi.reloadTrade(api, trade.trade_id),
        '交易已重新加载',
      )
    },
    [api, confirmAction],
  )

  const handleDeleteTrade = useCallback(
    (trade: Trade) => {
      confirmAction(
        '删除交易',
        `永久删除 #${trade.trade_id} ${displayPair(trade.pair)}？未平仓交易会被同时取消挂单。`,
        () => tradingApi.deleteTrade(api, trade.trade_id),
        '交易已删除',
      )
    },
    [api, confirmAction],
  )

  return (
    <div className="ft-page">
      <header className="ft-page-head">
        <h1 className="ft-page-title">未平仓交易</h1>
        <span className="ft-page-sub">
          {openTrades.length} 笔 · {config?.exchange ?? '—'} · {config?.strategy ?? '—'}
        </span>
        <span className="ft-row" style={{ marginLeft: 'auto', gap: 'var(--ft-gap-4)' }}>
          {config && <StateTag state={config.state} />}
          {config && <DryRunTag dryRun={config.dry_run} />}
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            更新于 {lastUpdated ? formatTimestamp(lastUpdated, { seconds: false }) : '—'}
          </span>
          <Tooltip content="立即刷新">
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconRefresh />}
              onClick={refresh}
            />
          </Tooltip>
        </span>
      </header>

      <Panel title="持仓列表" icon={<IconActivity />} flush bodyClassName="ft-scroll-x">
        <TradeList
          trades={openTrades}
          activeTrades
          loading={loading}
          stakeCurrency={stakeCurrency}
          stakeCurrencyDecimals={stakeDecimals}
          tradingMode={tradingMode}
          forceEntryEnable={config?.force_entry_enable}
          selectedTradeId={selected?.trade_id ?? null}
          onSelectTrade={setSelected}
          onForceExit={handleForceExit}
          onForceExitPartial={setExitTarget}
          onCancelOpenOrder={handleCancelOpenOrder}
          onReloadTrade={handleReloadTrade}
          onDeleteTrade={handleDeleteTrade}
          onIncreasePosition={(trade) => setEntryTarget({ pair: trade.pair, increase: true })}
          emptyText="当前没有未平仓交易。"
        />
      </Panel>

      <SideSheet
        title={selected ? `交易详情 #${selected.trade_id} · ${displayPair(selected.pair)}` : '交易详情'}
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
              <Button
                size="small"
                theme="solid"
                type="danger"
                icon={<IconExit />}
                onClick={() => setExitTarget(selected)}
              >
                强制平仓
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

      <ForceExitForm
        visible={exitTarget !== null}
        trade={exitTarget}
        onClose={() => setExitTarget(null)}
        onSubmitted={afterMutation}
      />

      <ForceEntryForm
        visible={entryTarget !== null}
        pair={entryTarget?.pair}
        positionIncrease={entryTarget?.increase ?? false}
        onClose={() => setEntryTarget(null)}
        onSubmitted={afterMutation}
      />
    </div>
  )
}
