/**
 * Balance — the account composition view.
 *
 * Shows the bot's view of the wallet by default (falling back to the account
 * view when the backend does not report per-bot balances), with toggles for
 * small balances and bot-managed currencies.
 */

import { useMemo, useState } from 'react'
import {
  Banner,
  Button,
  Checkbox,
  Progress,
  Table,
  Tooltip,
  Typography,
} from '@douyinfe/semi-ui'
import type { ColumnProps } from '@douyinfe/semi-ui/lib/es/table'
import { IconCoinMoney, IconPieChartStroked, IconRefresh } from '@douyinfe/semi-icons'

import type { BalanceCurrency } from '../api/types'
import { useSnapshot } from '../state/snapshot'
import { DonutChart } from '../components/charts'
import { DryRunTag, EmptyState, Panel, StatTile, Tag } from '../components/primitives'
import {
  formatNumber,
  formatPercent,
  formatPrice,
  formatPriceCurrency,
  formatTimestamp,
  signClass,
} from '../utils/format'

/** One currency row as rendered in the table. */
interface BalanceRow {
  currency: string
  available: number | null
  inStake: number | null
  used: number
  position: number
  isPosition: boolean
  side: string
  raw: BalanceCurrency
}

export function Balance() {
  const { config, balance, loading, lastUpdated, refresh } = useSnapshot()

  const [showBotOnly, setShowBotOnly] = useState(true)
  const [hideSmall, setHideSmall] = useState(true)

  const stakeCurrency = config?.stake_currency ?? balance?.stake ?? 'USDT'
  const stakeDecimals = config?.stake_currency_decimals ?? 3

  /** True when the backend reports per-bot balances for at least one currency. */
  const canUseBotBalance = useMemo(
    () =>
      (balance?.currencies ?? []).some(
        (c) => c.bot_owned !== null && c.bot_owned !== undefined,
      ),
    [balance],
  )

  const botOnly = canUseBotBalance && showBotOnly

  // Mirrors freqUI: anything below 1.1^decimals is considered dust.
  const smallBalance = useMemo(
    () => Number((1.1 ** stakeDecimals).toFixed(8)),
    [stakeDecimals],
  )

  const rows = useMemo<BalanceRow[]>(() => {
    return (balance?.currencies ?? [])
      .filter(
        (c) =>
          (!hideSmall || c.est_stake >= smallBalance) &&
          (!canUseBotBalance || !showBotOnly || (c.is_bot_managed ?? true) === true),
      )
      .map((c) => ({
        currency: c.currency,
        available: botOnly ? (c.bot_owned ?? c.free) : c.free,
        inStake: botOnly ? (c.est_stake_bot ?? c.est_stake) : c.est_stake,
        used: c.used,
        position: c.position,
        isPosition: c.is_position,
        side: c.side,
        raw: c,
      }))
      .sort((a, b) => (b.inStake ?? 0) - (a.inStake ?? 0))
  }, [balance, botOnly, canUseBotBalance, hideSmall, showBotOnly, smallBalance])

  const hiddenCount = (balance?.currencies?.length ?? 0) - rows.length

  const totalStake = botOnly ? (balance?.total_bot ?? balance?.total) : balance?.total
  const totalValue = botOnly ? (balance?.value_bot ?? balance?.value) : balance?.value
  const startingRatio = botOnly
    ? (balance?.starting_capital_ratio_bot ?? balance?.starting_capital_ratio)
    : balance?.starting_capital_ratio

  const botSharePercent = useMemo(() => {
    if (!balance || !balance.total) return 0
    return Math.max(0, Math.min(100, (balance.total_bot / balance.total) * 100))
  }, [balance])

  const slices = useMemo(
    () =>
      rows
        .filter((r) => (r.inStake ?? 0) > 0)
        .map((r) => ({ label: r.currency, value: r.inStake ?? 0 })),
    [rows],
  )

  const columns = useMemo<ColumnProps<BalanceRow>[]>(
    () => [
      {
        title: '币种',
        dataIndex: 'currency',
        width: 110,
        render: (currency: string, row: BalanceRow) => (
          <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
            <span style={{ fontWeight: 500 }}>{currency}</span>
            {row.isPosition && <Tag variant={row.side === 'short' ? 'down' : 'up'}>{row.side || 'pos'}</Tag>}
          </span>
        ),
      },
      {
        title: '可用',
        dataIndex: 'available',
        align: 'right',
        render: (value: number | null) => (
          <span className="ft-num">{value === null ? '–' : formatPrice(value, 8)}</span>
        ),
      },
      {
        title: `折算 ${stakeCurrency}`,
        dataIndex: 'inStake',
        align: 'right',
        render: (value: number | null) => (
          <span className="ft-num">
            {value === null ? '–' : formatPrice(value, stakeDecimals)}
          </span>
        ),
      },
      {
        title: '占用',
        dataIndex: 'used',
        align: 'right',
        render: (value: number) => (
          <span className="ft-num ft-muted">{formatPrice(value, 8)}</span>
        ),
      },
      {
        title: '持仓',
        dataIndex: 'position',
        align: 'right',
        render: (value: number, row: BalanceRow) =>
          row.isPosition ? (
            <span className="ft-num">{formatPrice(value, 8)}</span>
          ) : (
            <span className="ft-faint">–</span>
          ),
      },
    ],
    [stakeCurrency, stakeDecimals],
  )

  return (
    <div className="ft-page">
      <header className="ft-page-head">
        <h1 className="ft-page-title">资金</h1>
        <span className="ft-page-sub">
          {showBotOnly && canUseBotBalance ? '机器人余额' : '账户余额'} · {stakeCurrency}
        </span>
        <span className="ft-row" style={{ marginLeft: 'auto', gap: 'var(--ft-gap-4)' }}>
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

      {balance?.note ? <Banner type="info" description={balance.note} closeIcon={null} /> : null}

      <div className="ft-grid cols-4">
        <StatTile
          icon={<IconCoinMoney />}
          label={botOnly ? '机器人总余额' : '账户总余额'}
          value={formatPriceCurrency(totalStake, stakeCurrency, stakeDecimals)}
          meta={`起始 ${formatPriceCurrency(balance?.starting_capital, stakeCurrency, stakeDecimals)}`}
        />
        <StatTile
          icon={<IconPieChartStroked />}
          label="总价值"
          value={formatPriceCurrency(totalValue, stakeCurrency, stakeDecimals)}
          meta={balance?.symbol ? `计价货币 ${balance.symbol}` : undefined}
        />
        <StatTile
          label="较起始资金"
          value={formatPercent(startingRatio)}
          tone={
            startingRatio === undefined || startingRatio === 0
              ? 'neutral'
              : startingRatio > 0
                ? 'up'
                : 'down'
          }
          meta={
            balance
              ? `${formatPriceCurrency(
                  botOnly ? balance.starting_capital_fiat_bot : balance.starting_capital_fiat,
                  stakeCurrency,
                  2,
                )} 折算`
              : undefined
          }
        />
        <StatTile
          label="持仓币种"
          value={`${rows.length}`}
          meta={
            hiddenCount > 0
              ? `已隐藏 ${hiddenCount} 项`
              : canUseBotBalance
                ? '机器人托管'
                : '后端未区分机器人余额'
          }
        />
      </div>

      <div className="ft-grid cols-2">
        <Panel
          title="余额明细"
          icon={<IconCoinMoney />}
          sub={`${rows.length} 种货币`}
          flush
          actions={
            <div className="ft-row" style={{ gap: 'var(--ft-gap-5)' }}>
              <Checkbox
                checked={showBotOnly}
                disabled={!canUseBotBalance}
                onChange={(e) => setShowBotOnly(Boolean(e.target.checked))}
              >
                <span style={{ fontSize: 'var(--ft-font-sm)' }}>只看机器人持仓</span>
              </Checkbox>
              <Checkbox
                checked={hideSmall}
                onChange={(e) => setHideSmall(Boolean(e.target.checked))}
              >
                <span style={{ fontSize: 'var(--ft-font-sm)' }}>隐藏小额</span>
              </Checkbox>
            </div>
          }
        >
          <Table<BalanceRow>
            className="ft-table"
            columns={columns}
            dataSource={rows}
            rowKey="currency"
            size="small"
            pagination={false}
            loading={loading}
            empty={<EmptyState icon={<IconCoinMoney />} title="没有余额记录" />}
            footer={() => (
              <div
                className="ft-row wrap"
                style={{
                  gap: 'var(--ft-gap-6)',
                  padding: '6px 10px',
                  background: 'var(--ft-paper-2)',
                  fontSize: 'var(--ft-font-sm)',
                }}
              >
                <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                  <span className="ft-faint">总计</span>
                  <span className="ft-num" style={{ fontWeight: 600 }}>
                    {formatPriceCurrency(totalStake, stakeCurrency, stakeDecimals)}
                  </span>
                </span>
                <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                  <span className="ft-faint">起始资金比例</span>
                  <span className={`ft-num ${signClass(startingRatio)}`}>
                    {formatPercent(startingRatio)}
                  </span>
                </span>
                <span className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                  <span className="ft-faint">总价值</span>
                  <span className="ft-num" style={{ fontWeight: 600 }}>
                    {formatPriceCurrency(totalValue, stakeCurrency, stakeDecimals)}
                  </span>
                </span>
                <span className="ft-row" style={{ gap: 'var(--ft-gap-3)', marginLeft: 'auto' }}>
                  <span className="ft-faint">小额阈值</span>
                  <span className="ft-num">
                    {formatNumber(smallBalance, 8)} {stakeCurrency}
                  </span>
                </span>
              </div>
            )}
          />
        </Panel>

        <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
          <Panel title="资金构成" icon={<IconPieChartStroked />} sub={stakeCurrency}>
            <DonutChart slices={slices} />
          </Panel>

          <Panel title="机器人占比" icon={<IconCoinMoney />}>
            {canUseBotBalance ? (
              <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
                <div className="ft-row">
                  <Typography.Text type="tertiary" size="small">
                    机器人托管余额占账户总额
                  </Typography.Text>
                  <span className="ft-num" style={{ marginLeft: 'auto', fontWeight: 600 }}>
                    {formatPercent(botSharePercent / 100)}
                  </span>
                </div>
                <Progress percent={botSharePercent} size="small" showInfo={false} />
                <div className="ft-row ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  <span>
                    机器人 {formatPriceCurrency(balance?.total_bot, stakeCurrency, stakeDecimals)}
                  </span>
                  <span style={{ marginLeft: 'auto' }}>
                    账户 {formatPriceCurrency(balance?.total, stakeCurrency, stakeDecimals)}
                  </span>
                </div>
              </div>
            ) : (
              <EmptyState
                icon={<IconCoinMoney />}
                title="后端未提供机器人余额"
                hint="该 freqtrade 版本 / 模式下不区分机器人托管资金，仅显示账户余额。"
              />
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}
