/**
 * Force-exit dialog.
 *
 * Handles both the full-exit and partial-exit flows: leaving the amount at the
 * trade's full size exits everything, lowering it (or dragging the slider)
 * exits only part of the position.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Banner, Button, Form, Modal, Toast } from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form'
import { IconClose, IconTick } from '@douyinfe/semi-icons'

import type { ForceExitPayload, Trade } from '../api/types'
import { tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import { describeError } from '../hooks/usePolling'
import { formatPrice, formatPriceCurrency } from '../utils/format'
import { DirectionTag, Tag } from './primitives'

type ExitValues = {
  amount?: number
  price?: number
  ordertype: string
}

export interface ForceExitFormProps {
  visible: boolean
  /** Null while nothing is selected; the modal stays closed in that case. */
  trade: Trade | null
  onClose: () => void
  onSubmitted?: () => void
}

export function ForceExitForm({ visible, trade, onClose, onSubmitted }: ForceExitFormProps) {
  return (
    <Modal
      title={trade ? `强制平仓 #${trade.trade_id} · ${trade.pair}` : '强制平仓'}
      visible={visible && trade !== null}
      onCancel={onClose}
      footer={null}
      width={520}
      maskClosable={false}
    >
      {visible && trade ? (
        <ExitForm trade={trade} onClose={onClose} onSubmitted={onSubmitted} />
      ) : null}
    </Modal>
  )
}

function ExitForm({
  trade,
  onClose,
  onSubmitted,
}: {
  trade: Trade
  onClose: () => void
  onSubmitted?: () => void
}) {
  const api = useApi()
  const { config, refresh } = useSnapshot()

  const formApiRef = useRef<FormApi<ExitValues> | null>(null)
  const step = trade.amount_precision ?? 1e-6

  const initial = useMemo<ExitValues>(
    () => ({
      amount: trade.amount,
      ordertype: config?.order_types?.exit ?? 'limit',
    }),
    [trade.amount, config?.order_types?.exit],
  )

  const [values, setValues] = useState<ExitValues>(initial)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

  useEffect(() => {
    refresh()
  }, [refresh])

  const estimatedValue = useMemo(() => {
    const rate = (trade as Trade & { current_rate?: number }).current_rate
    if (!values.amount || !rate) return undefined
    return values.amount * rate
  }, [values.amount, trade])

  const isLimit = values.ordertype === 'limit'

  const submit = async (formValues: ExitValues) => {
    setSubmitting(true)
    setError(undefined)
    try {
      const payload: ForceExitPayload = { tradeid: String(trade.trade_id) }
      if (formValues.ordertype) payload.ordertype = formValues.ordertype
      if (formValues.amount) payload.amount = Number(formValues.amount)
      if (formValues.price && formValues.ordertype === 'limit') {
        payload.price = Number(formValues.price)
      }

      const result = await tradingApi.forceExit(api, payload)
      Toast.success({ content: `已发送平仓指令：${result?.result ?? 'ok'}`, duration: 3 })
      refresh()
      onSubmitted?.()
      onClose()
    } catch (err) {
      setError(describeError(err as Error) ?? String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const partial = values.amount !== undefined && values.amount < trade.amount

  return (
    <Form<ExitValues>
      getFormApi={(formApi) => {
        formApiRef.current = formApi
      }}
      initValues={initial}
      labelPosition="top"
      onSubmit={(formValues) => void submit(formValues)}
      onValueChange={(next) => setValues(next)}
      style={{ width: '100%' }}
    >
      {error ? (
        <Banner
          type="danger"
          description={error}
          closeIcon={null}
          style={{ marginBottom: 'var(--ft-gap-5)' }}
        />
      ) : null}

      <div className="ft-row" style={{ gap: 'var(--ft-gap-3)', marginBottom: 'var(--ft-gap-5)' }}>
        <Tag variant="plain">#{trade.trade_id}</Tag>
        <span>{trade.pair}</span>
        {trade.trading_mode !== 'spot' && <DirectionTag isShort={trade.is_short} />}
        <span className="ft-num ft-muted">
          持有 {formatPrice(trade.amount, 8)} {trade.base_currency}
        </span>
      </div>

      <Form.Slot label={{ text: `平仓数量（${trade.base_currency}）` }}>
        <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', width: '100%' }}>
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            {estimatedValue === undefined
              ? '估算价值：—'
              : `估算价值：~${formatPriceCurrency(estimatedValue, trade.quote_currency, 2)}`}
            {partial ? ' · 部分平仓' : ' · 全部平仓'}
          </span>
          <Form.InputNumber
            field="amount"
            min={0}
            max={trade.amount}
            step={step}
            precision={8}
            style={{ width: '100%' }}
          />
          <Form.Slider field="amount" min={0} max={trade.amount} step={step} />
          <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
            {[0.25, 0.5, 0.75, 1].map((ratio) => (
              <Button
                key={ratio}
                size="small"
                theme="borderless"
                type="tertiary"
                style={{ flex: '1 1 0', justifyContent: 'center' }}
                onClick={() =>
                  formApiRef.current?.setValue(
                    'amount',
                    Number((trade.amount * ratio).toFixed(8)),
                  )
                }
              >
                {ratio * 100}%
              </Button>
            ))}
          </div>
        </div>
      </Form.Slot>

      <Form.InputNumber
        field="price"
        label="价格（仅限价单）"
        disabled={!isLimit}
        min={0}
        step={trade.price_precision ?? 1e-6}
        precision={8}
        placeholder={isLimit ? '留空则由交易所决定' : '市价单无需价格'}
        style={{ width: '100%' }}
      />

      <Form.RadioGroup
        field="ordertype"
        label="订单类型"
        type="button"
        buttonSize="small"
        options={[
          { label: '市价 Market', value: 'market' },
          { label: '限价 Limit', value: 'limit' },
        ]}
      />

      <div
        className="ft-row"
        style={{
          justifyContent: 'flex-end',
          gap: 'var(--ft-gap-3)',
          marginTop: 'var(--ft-gap-5)',
          paddingTop: 'var(--ft-gap-4)',
          borderTop: '1px solid var(--ft-line)',
        }}
      >
        <Button size="small" icon={<IconClose />} onClick={onClose}>
          取消
        </Button>
        <Button
          size="small"
          theme="solid"
          type="danger"
          icon={<IconTick />}
          htmlType="submit"
          loading={submitting}
        >
          {partial ? '部分平仓' : '全部平仓'}
        </Button>
      </div>
    </Form>
  )
}
