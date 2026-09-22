/**
 * Force-entry dialog.
 *
 * Also serves as the "increase position" dialog: freqtrade routes both through
 * POST /forceenter, and an existing open trade on the pair simply receives the
 * additional stake.
 */

import { useEffect, useMemo, useRef, useState, type FocusEvent } from 'react'
import { Banner, Button, Form, Modal, Toast } from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form'
import { IconClose, IconTick } from '@douyinfe/semi-icons'

import type { ForceEnterPayload } from '../api/types'
import { tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import { describeError } from '../hooks/usePolling'
import { formatPercent, formatPrice, formatPriceCurrency } from '../utils/format'
import { Tag } from './primitives'

type EntryValues = {
  pair: string
  side: 'long' | 'short'
  price?: number
  stakeamount?: number
  leverage?: number
  ordertype: string
  enter_tag?: string
}

const STAKE_RATIOS = [0.25, 0.5, 0.75, 1]

export interface ForceEntryFormProps {
  visible: boolean
  /** Pre-filled pair (e.g. the pair currently selected on the trading desk). */
  pair?: string
  /** True when adding to an existing position — the pair becomes read-only. */
  positionIncrease?: boolean
  onClose: () => void
  onSubmitted?: () => void
}

export function ForceEntryForm({
  visible,
  pair,
  positionIncrease = false,
  onClose,
  onSubmitted,
}: ForceEntryFormProps) {
  return (
    <Modal
      title={positionIncrease ? `加仓 ${pair ?? ''}` : '强制开仓'}
      visible={visible}
      onCancel={onClose}
      footer={null}
      width={520}
      maskClosable={false}
    >
      {/* Mounted only while open so the form always starts from fresh defaults. */}
      {visible ? (
        <EntryForm
          pair={pair}
          positionIncrease={positionIncrease}
          onClose={onClose}
          onSubmitted={onSubmitted}
        />
      ) : null}
    </Modal>
  )
}

function EntryForm({
  pair,
  positionIncrease,
  onClose,
  onSubmitted,
}: {
  pair?: string
  positionIncrease: boolean
  onClose: () => void
  onSubmitted?: () => void
}) {
  const api = useApi()
  const { config, balance, refresh } = useSnapshot()

  const stakeCurrency = config?.stake_currency ?? 'USDT'
  const decimals = config?.stake_currency_decimals ?? 3
  const shortAllowed = Boolean(config?.short_allowed)
  const isFutures = (config?.trading_mode ?? 'spot') !== 'spot'

  const formApiRef = useRef<FormApi<EntryValues> | null>(null)
  const [values, setValues] = useState<EntryValues>({
    pair: pair ?? '',
    side: 'long',
    ordertype: config?.order_types?.entry ?? 'limit',
    enter_tag: 'force_entry',
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

  // Make sure the available-stake hint is current.
  useEffect(() => {
    refresh()
  }, [refresh])

  const availableStake = useMemo(() => {
    const row = balance?.currencies?.find((c) => c.currency === stakeCurrency)
    if (!row) return undefined
    return row.bot_owned ?? row.free
  }, [balance, stakeCurrency])

  const roundStake = (value: number) => Number(value.toFixed(decimals))

  const applyRatio = (ratio: number) => {
    if (!availableStake) return
    formApiRef.current?.setValue('stakeamount', roundStake(availableStake * ratio))
  }

  const submit = async (formValues: EntryValues) => {
    setSubmitting(true)
    setError(undefined)
    try {
      // `pair` is the fallback for the read-only "increase position" case.
      const payload: ForceEnterPayload = {
        pair: String(formValues.pair ?? pair ?? '').trim(),
      }
      // Only set keys the user actually provided — the backend fills the rest.
      if (formValues.price) payload.price = Number(formValues.price)
      if (formValues.ordertype) payload.ordertype = formValues.ordertype
      if (formValues.stakeamount) payload.stakeamount = Number(formValues.stakeamount)
      if (shortAllowed && formValues.side) payload.side = formValues.side
      if (formValues.enter_tag) payload.enter_tag = formValues.enter_tag
      if (isFutures && formValues.leverage) payload.leverage = Number(formValues.leverage)

      const result = await tradingApi.forceEnter(api, payload)
      Toast.success({
        content: `已强制开仓 #${result?.trade_id ?? '?'} ${result?.pair ?? payload.pair}`,
        duration: 3,
      })
      refresh()
      onSubmitted?.()
      onClose()
    } catch (err) {
      setError(describeError(err as Error) ?? String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Form<EntryValues>
      getFormApi={(formApi) => {
        formApiRef.current = formApi
      }}
      initValues={values}
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

      {shortAllowed && (
        <Form.RadioGroup
          field="side"
          label="方向"
          type="button"
          buttonSize="small"
          options={[
            { label: '做多 Long', value: 'long' },
            { label: '做空 Short', value: 'short' },
          ]}
          style={{ marginBottom: 'var(--ft-gap-4)' }}
        />
      )}

      <Form.Input
        field="pair"
        label="交易对"
        placeholder="BTC/USDT"
        // `readonly` rather than `disabled`, so the required rule still sees the
        // prefilled pair when adding to an existing position.
        readonly={positionIncrease}
        rules={[{ required: true, message: '交易对必填' }]}
        onFocus={(e: FocusEvent<HTMLInputElement>) => e.target.select()}
      />

      <Form.InputNumber
        field="price"
        label="价格（可选）"
        placeholder="留空则按市价 / 配置定价"
        min={0}
        step={0.1}
        precision={8}
        style={{ width: '100%' }}
      />

      <Form.Slot label={{ text: `投入金额（${stakeCurrency}，可选）` }}>
        <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', width: '100%' }}>
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            {availableStake === undefined
              ? '可用余额未知'
              : `可用：${formatPriceCurrency(availableStake, stakeCurrency, decimals)}`}
          </span>
          <Form.InputNumber
            field="stakeamount"
            placeholder="留空则使用机器人配置的 stake_amount"
            min={0}
            step={stakeCurrency === 'USDT' || stakeCurrency === 'USDC' ? 10 : 1}
            precision={Math.max(decimals, 2)}
            style={{ width: '100%' }}
          />
          {availableStake ? (
            <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
              {STAKE_RATIOS.map((ratio) => (
                <Button
                  key={ratio}
                  size="small"
                  theme="borderless"
                  type="tertiary"
                  style={{ flex: '1 1 0', justifyContent: 'center' }}
                  onClick={() => applyRatio(ratio)}
                >
                  {formatPercent(ratio, 0)}
                </Button>
              ))}
              <Button
                size="small"
                theme="borderless"
                type="tertiary"
                icon={<IconClose />}
                title="清空，使用机器人配置的 stake_amount"
                disabled={values.stakeamount === undefined}
                onClick={() => formApiRef.current?.setValue('stakeamount', undefined)}
              />
            </div>
          ) : null}
        </div>
      </Form.Slot>

      {isFutures && (
        <Form.InputNumber
          field="leverage"
          label="杠杆（可选）"
          min={1}
          step={1}
          precision={1}
          style={{ width: '100%' }}
        />
      )}

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

      <Form.Input
        field="enter_tag"
        label="入场标签（可选）"
        placeholder="force_entry"
      />

      <div
        className="ft-row"
        style={{
          justifyContent: 'space-between',
          marginTop: 'var(--ft-gap-5)',
          paddingTop: 'var(--ft-gap-4)',
          borderTop: '1px solid var(--ft-line)',
        }}
      >
        <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
          {config?.dry_run ? <Tag variant="plain">DRY-RUN</Tag> : <Tag variant="warn">LIVE</Tag>}
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            {values.pair ? `${values.pair}` : '未选择交易对'}
            {values.price ? ` @ ${formatPrice(values.price, 8)}` : ''}
          </span>
        </span>
        <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
          <Button size="small" icon={<IconClose />} onClick={onClose}>
            取消
          </Button>
          <Button
            size="small"
            theme="solid"
            type="primary"
            icon={<IconTick />}
            htmlType="submit"
            loading={submitting}
          >
            {positionIncrease ? '加仓' : '开仓'}
          </Button>
        </span>
      </div>
    </Form>
  )
}
