/**
 * Dense, two-column detail panel for a single trade.
 *
 * Mirrors freqUI's TradeDetail: general fields on the left, stoploss / futures /
 * orders on the right, with the trade's custom-data blob behind a modal so the
 * panel itself stays scannable.
 */

import { useCallback, useMemo, useState } from 'react'
import { Banner, Button, Modal, Spin, Tooltip } from '@douyinfe/semi-ui'
import { IconLayers, IconRefresh, IconSearch } from '@douyinfe/semi-icons'

import type { ListCustomData, Trade, TradeOrder } from '../api/types'
import { tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { describeError } from '../hooks/usePolling'
import {
  formatDecimal,
  formatPercent,
  formatPrice,
  formatPriceCurrency,
  formatTimestamp,
} from '../utils/format'
import { KeyValueList, SectionRule, Tag, ValuePair } from './primitives'
import { TradeProfit } from './ProfitPill'

/**
 * Fields the API returns on open trades (and futures trades) that are not part
 * of the base `Trade` type.
 */
type TradeExtras = Trade & {
  current_rate?: number
  total_profit_abs?: number
  total_profit_ratio?: number
  stoploss_current_dist?: number
  stoploss_current_dist_ratio?: number
}

function renderCustomValue(value: unknown): string {
  if (value === null || value === undefined) return '–'
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

function OrderRow({ order, index }: { order: TradeOrder; index: number }) {
  const isBuy = order.ft_order_side === 'buy'
  const price = order.average ?? order.price
  return (
    <div
      className="ft-row"
      style={{ gap: 'var(--ft-gap-3)', fontSize: 'var(--ft-font-xs)', padding: '2px 0' }}
      title={`${order.ft_order_side} ${order.order_type} · ${order.status}`}
    >
      <span className="ft-faint ft-num">#{index + 1}</span>
      <Tag variant={isBuy ? 'up' : 'down'}>{order.ft_order_side}</Tag>
      <span className="ft-muted">{order.order_type}</span>
      <span className="ft-num ft-muted">
        {formatTimestamp(order.order_timestamp, { seconds: false })}
      </span>
      <span className="ft-num">{formatPrice(price, 8)}</span>
      <span className="ft-num ft-muted">
        {order.remaining ? `${formatPrice(order.remaining, 8)} / ` : ''}
        {formatPrice(order.filled ?? order.amount, 8)}
      </span>
      <span className="ft-faint" style={{ marginLeft: 'auto' }}>
        {order.status}
      </span>
    </div>
  )
}

export interface TradeDetailProps {
  trade: Trade
  stakeCurrency?: string
  stakeCurrencyDecimals?: number
}

export function TradeDetail({
  trade,
  stakeCurrency,
  stakeCurrencyDecimals = 3,
}: TradeDetailProps) {
  const api = useApi()
  const t = trade as TradeExtras
  const currency = stakeCurrency ?? trade.quote_currency ?? 'USDT'
  const isFutures = (trade.trading_mode ?? 'spot') !== 'spot'

  const [customOpen, setCustomOpen] = useState(false)
  const [customRows, setCustomRows] = useState<ListCustomData[] | null>(null)
  const [customError, setCustomError] = useState<string | undefined>(undefined)
  const [customLoading, setCustomLoading] = useState(false)

  const loadCustomData = useCallback(async () => {
    setCustomLoading(true)
    setCustomError(undefined)
    try {
      const rows = await tradingApi.customData(api, trade.trade_id)
      setCustomRows(Array.isArray(rows) ? rows : [])
    } catch (err) {
      setCustomError(describeError(err as Error) ?? String(err))
      setCustomRows([])
    } finally {
      setCustomLoading(false)
    }
  }, [api, trade.trade_id])

  // Fetched on demand — the modal is the only consumer.
  const openCustomData = () => {
    setCustomOpen(true)
    void loadCustomData()
  }

  const orders = trade.orders ?? trade.open_orders ?? []
  const stakeValue = trade.is_open
    ? trade.stake_amount
    : (trade.max_stake_amount ?? trade.stake_amount)

  /**
   * Capital at risk if the stoploss triggers. Derived from the stop price when
   * available (which accounts for leverage), else from the stop ratio.
   */
  const atRisk = useMemo(() => {
    if (trade.stop_loss_abs && trade.open_rate && trade.amount) {
      return Math.abs(trade.open_rate - trade.stop_loss_abs) * trade.amount
    }
    return trade.stake_amount * Math.abs(trade.stop_loss_ratio ?? 0)
  }, [trade.stop_loss_abs, trade.open_rate, trade.amount, trade.stake_amount, trade.stop_loss_ratio])

  return (
    <div className="ft-grid cols-2">
      {/* ---------------------------------------------------------------- */}
      {/* Left: general + details                                           */}
      {/* ---------------------------------------------------------------- */}
      <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
        <div className="ft-row">
          <SectionRule>概况</SectionRule>
          <Tooltip content="加载该交易的自定义数据">
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconLayers />}
              onClick={openCustomData}
            >
              自定义数据
            </Button>
          </Tooltip>
        </div>

        <KeyValueList>
          <ValuePair label="交易 ID">
            <span className="ft-num">{trade.trade_id}</span>
          </ValuePair>
          <ValuePair label="交易对">
            <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
              <span>{trade.pair}</span>
              {isFutures && (
                <Tag variant={trade.is_short ? 'down' : 'up'}>
                  {trade.is_short ? 'SHORT' : 'LONG'}
                </Tag>
              )}
            </span>
          </ValuePair>
          <ValuePair label="开仓时间">
            <span className="ft-num">{formatTimestamp(trade.open_timestamp)}</span>
          </ValuePair>
          {trade.open_fill_timestamp ? (
            <ValuePair label="成交时间">
              <span className="ft-num">{formatTimestamp(trade.open_fill_timestamp)}</span>
            </ValuePair>
          ) : null}
          {trade.enter_tag ? (
            <ValuePair label="入场标签">
              <Tag variant="plain">{trade.enter_tag}</Tag>
            </ValuePair>
          ) : null}

          <ValuePair label={trade.is_open ? '投入' : '总投入'}>
            <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
              <span className="ft-num">
                {formatPriceCurrency(stakeValue, currency, stakeCurrencyDecimals)}
              </span>
              {isFutures && (
                <>
                  <Tag variant="plain">{trade.leverage}x</Tag>
                  <span className="ft-num ft-muted" title="仓位价值">
                    {formatPriceCurrency(trade.amount * trade.open_rate, currency, 2)}
                  </span>
                </>
              )}
            </span>
          </ValuePair>

          <ValuePair label="数量">
            <span className="ft-num">{formatPrice(trade.amount, 8)}</span>
          </ValuePair>
          <ValuePair label="开仓价">
            <span className="ft-num">{formatPrice(trade.open_rate, 8)}</span>
          </ValuePair>

          {trade.is_open && t.current_rate !== undefined ? (
            <ValuePair label="当前价">
              <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                <span className="ft-num">{formatPrice(t.current_rate, 8)}</span>
                <span className="ft-num ft-muted" title="当前价值（合约：保证金 + 盈亏）">
                  ({formatPriceCurrency(trade.stake_amount + (trade.profit_abs ?? 0), currency, 2)})
                </span>
              </span>
            </ValuePair>
          ) : null}

          {!trade.is_open && trade.close_rate !== null ? (
            <ValuePair label="平仓价">
              <span className="ft-num">{formatPrice(trade.close_rate, 8)}</span>
            </ValuePair>
          ) : null}

          {trade.close_timestamp ? (
            <ValuePair label="平仓时间">
              <span className="ft-num">{formatTimestamp(trade.close_timestamp)}</span>
            </ValuePair>
          ) : null}

          {trade.is_open && trade.realized_profit && !t.total_profit_abs ? (
            <ValuePair label="已实现盈亏">
              <TradeProfit trade={trade} mode="realized" />
            </ValuePair>
          ) : null}
          {trade.is_open && t.total_profit_abs ? (
            <ValuePair label="总盈亏">
              <TradeProfit trade={trade} mode="total" />
            </ValuePair>
          ) : null}
          <ValuePair label={trade.is_open ? '当前盈亏' : '平仓盈亏'}>
            <TradeProfit trade={trade} />
          </ValuePair>
          {trade.trade_duration_s ? (
            <ValuePair label="持仓时长">
              <span className="ft-num">{trade.trade_duration}</span>
            </ValuePair>
          ) : null}
        </KeyValueList>

        <div className="ft-subhead">更多明细</div>
        <KeyValueList>
          {trade.min_rate !== null ? (
            <ValuePair label="最低价">
              <span className="ft-num">{formatPrice(trade.min_rate, 8)}</span>
            </ValuePair>
          ) : null}
          {trade.max_rate !== null ? (
            <ValuePair label="最高价">
              <span className="ft-num">{formatPrice(trade.max_rate, 8)}</span>
            </ValuePair>
          ) : null}
          <ValuePair label="开仓手续费">
            <span className="ft-num">
              {trade.fee_open_cost === null
                ? '–'
                : formatPriceCurrency(trade.fee_open_cost, trade.fee_open_currency, 8)}
              {trade.fee_open_currency && trade.fee_open_currency !== trade.quote_currency
                ? ` (${trade.fee_open_currency})`
                : ''}
              {` · ${formatPercent(trade.fee_open)}`}
            </span>
          </ValuePair>
          {trade.fee_close_cost !== null ? (
            <ValuePair label="平仓手续费">
              <span className="ft-num">
                {formatPriceCurrency(trade.fee_close_cost, trade.fee_close_currency, 8)}
                {` · ${formatPercent(trade.fee_close)}`}
              </span>
            </ValuePair>
          ) : null}
          <ValuePair label="入场次数">
            <span className="ft-num">{trade.nr_of_successful_entries ?? '–'}</span>
          </ValuePair>
          <ValuePair label="出场次数">
            <span className="ft-num">{trade.nr_of_successful_exits ?? '–'}</span>
          </ValuePair>
        </KeyValueList>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Right: stoploss, futures, orders                                  */}
      {/* ---------------------------------------------------------------- */}
      <div className="ft-col" style={{ gap: 'var(--ft-gap-3)' }}>
        <SectionRule>止损</SectionRule>
        <KeyValueList>
          <ValuePair label="止损">
            <span className="ft-num">
              {formatPercent(trade.stop_loss_ratio)} | {formatPrice(trade.stop_loss_abs, 8)}
            </span>
          </ValuePair>
          <ValuePair
            label="风险敞口"
            title="按投入金额计算：触发止损时的预估亏损"
          >
            <span className="ft-num ft-down">
              {formatPriceCurrency(atRisk, currency, stakeCurrencyDecimals)}
            </span>
          </ValuePair>
          {trade.is_open &&
          t.stoploss_current_dist_ratio !== undefined &&
          t.stoploss_current_dist !== undefined ? (
            <ValuePair label="距止损">
              <span className="ft-num">
                {formatPercent(t.stoploss_current_dist_ratio)} |{' '}
                {formatPrice(t.stoploss_current_dist, 8)}
              </span>
            </ValuePair>
          ) : null}
          {trade.initial_stop_loss_pct !== null && trade.initial_stop_loss_abs ? (
            <ValuePair label="初始止损">
              <span className="ft-num">
                {formatPercent(trade.initial_stop_loss_pct / 100)} |{' '}
                {formatPrice(trade.initial_stop_loss_abs, 8)}
              </span>
            </ValuePair>
          ) : null}
          {trade.stoploss_last_update_timestamp ? (
            <ValuePair label="止损更新">
              <span className="ft-num">{formatTimestamp(trade.stoploss_last_update_timestamp)}</span>
            </ValuePair>
          ) : null}
        </KeyValueList>

        {isFutures && (
          <>
            <SectionRule>合约 / 杠杆</SectionRule>
            <KeyValueList>
              <ValuePair label="方向">
                <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                  <Tag variant={trade.is_short ? 'down' : 'up'}>
                    {trade.is_short ? 'SHORT' : 'LONG'}
                  </Tag>
                  <span className="ft-num">{trade.leverage}x</span>
                </span>
              </ValuePair>
              <ValuePair
                label="资金费"
                title="正数表示交易赚取资金费，负数表示支付资金费"
              >
                <span className="ft-num">{formatDecimal(trade.funding_fees)}</span>
              </ValuePair>
              <ValuePair label="利率">
                <span className="ft-num">{formatDecimal(trade.interest_rate)}</span>
              </ValuePair>
              {trade.liquidation_price !== null ? (
                <ValuePair label="强平价">
                  <span className="ft-num ft-down">{formatPrice(trade.liquidation_price, 8)}</span>
                </ValuePair>
              ) : null}
            </KeyValueList>
          </>
        )}

        <div className="ft-subhead">
          订单{orders.length > 1 ? ` [${orders.length}]` : ''}
        </div>
        {orders.length === 0 ? (
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            暂无订单记录
          </span>
        ) : (
          <div className="ft-col" style={{ gap: 0 }}>
            {orders.map((order, index) => (
              <OrderRow key={order.order_id || index} order={order} index={index} />
            ))}
          </div>
        )}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Custom data modal                                                 */}
      {/* ---------------------------------------------------------------- */}
      <Modal
        title={`自定义数据 · #${trade.trade_id}`}
        visible={customOpen}
        onCancel={() => setCustomOpen(false)}
        footer={
          <div className="ft-row" style={{ justifyContent: 'flex-end' }}>
            <Button
              size="small"
              theme="borderless"
              type="tertiary"
              icon={<IconRefresh />}
              loading={customLoading}
              onClick={() => void loadCustomData()}
            >
              重新加载
            </Button>
            <Button size="small" onClick={() => setCustomOpen(false)}>
              关闭
            </Button>
          </div>
        }
        width={520}
      >
        {customError ? (
          <Banner
            type="warning"
            description={customError}
            closeIcon={null}
            style={{ marginBottom: 'var(--ft-gap-4)' }}
          />
        ) : null}
        {customLoading && !customRows ? (
          <div style={{ padding: 'var(--ft-gap-6)', textAlign: 'center' }}>
            <Spin size="middle" />
          </div>
        ) : !customRows || customRows.length === 0 ? (
          <div className="ft-empty">
            <span className="ft-empty-icon">
              <IconSearch />
            </span>
            <div>该交易没有自定义数据</div>
          </div>
        ) : (
          <KeyValueList>
            {customRows.map((row) => (
              <ValuePair
                key={row.key}
                label={row.key}
                title={row.value_type ?? row.type}
              >
                <span className="ft-num">{renderCustomValue(row.value)}</span>
                <span className="ft-faint" style={{ marginLeft: 'var(--ft-gap-3)' }}>
                  {row.value_type ?? row.type}
                </span>
              </ValuePair>
            ))}
          </KeyValueList>
        )}
      </Modal>
    </div>
  )
}
