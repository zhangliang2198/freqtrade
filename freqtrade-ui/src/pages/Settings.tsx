/**
 * Settings page.
 *
 * Everything here is a *client-side* preference: it changes how the console
 * renders, never the bot's own configuration. Values live in `useSettings()`
 * (localStorage `ftui.settings`), and the system section is read-only
 * diagnostics pulled from the active bot.
 */

import { useState, type ReactNode } from 'react'
import { Button, InputNumber, RadioGroup, Select, Slider, Toast } from '@douyinfe/semi-ui'
import {
  IconAlertTriangle,
  IconBellStroked,
  IconCandlestickChartStroked,
  IconConfigStroked,
  IconInfoCircle,
  IconList,
  IconMoon,
  IconPlay,
  IconRefresh,
  IconSetting,
  IconSun,
  IconTerminal,
} from '@douyinfe/semi-icons'

import { KeyValueList, Panel, Tag, ValuePair } from '../components/primitives'
import { SwitchRow } from '../components/selects'
import { useBots } from '../state/bots'
import { useSettings } from '../state/settings'
import { useSnapshot } from '../state/snapshot'
import { useTheme } from '../state/theme'
import type {
  ChartLabelSide,
  NotificationSettings,
  OpenTradesInTitle,
  TimeProfitPeriod,
  TimeProfitPreference,
} from '../state/settings'

/* -------------------------------------------------------------------------- */
/* Options                                                                     */
/* -------------------------------------------------------------------------- */

const OPEN_TRADES_OPTIONS: { value: OpenTradesInTitle; label: string }[] = [
  { value: 'showPill', label: '在图标上显示持仓胶囊' },
  { value: 'asTitle', label: '显示在标题中' },
  { value: 'noOpenTrades', label: '标题中不显示持仓' },
]

const CHART_SIDE_OPTIONS: { value: ChartLabelSide; label: string }[] = [
  { value: 'left', label: '左侧' },
  { value: 'right', label: '右侧' },
]

const PROFIT_BINS = [10, 15, 20, 25, 30, 40, 50]

/** Selectable extra columns for backtest result tables (freqUI parity). */
const BACKTEST_METRICS: { field: string; header: string }[] = [
  { field: 'sqn', header: 'SQN' },
  { field: 'cagr', header: 'CAGR' },
  { field: 'calmar', header: 'Calmar' },
  { field: 'p_value', header: '平均收益 p 值' },
  { field: 'expectancy', header: '期望值' },
  { field: 'profit_factor', header: '盈亏比' },
  { field: 'sharpe', header: 'Sharpe' },
  { field: 'sortino', header: 'Sortino' },
  { field: 'max_drawdown_account', header: '最大回撤' },
]

const NOTIFICATION_ROWS: { key: keyof NotificationSettings; label: string; help: string }[] = [
  { key: 'entry_fill', label: '入场成交通知', help: '开仓订单完全成交时提示' },
  { key: 'exit_fill', label: '离场成交通知', help: '平仓订单完全成交时提示' },
  { key: 'entry_cancel', label: '入场取消通知', help: '开仓订单被取消时提示' },
  { key: 'exit_cancel', label: '离场取消通知', help: '平仓订单被取消时提示' },
]

const TIME_PROFIT_PERIODS: { value: TimeProfitPeriod; label: string }[] = [
  { value: 'daily', label: '按日' },
  { value: 'weekly', label: '按周' },
  { value: 'monthly', label: '按月' },
]

const TIME_PROFIT_PREFERENCES: { value: TimeProfitPreference; label: string }[] = [
  { value: 'abs_profit', label: '绝对收益' },
  { value: 'rel_profit', label: '相对收益' },
]

/* -------------------------------------------------------------------------- */
/* Layout helpers                                                              */
/* -------------------------------------------------------------------------- */

/**
 * The four switches below only fire once the browser has granted notification
 * permission, which it will not do without a user gesture — so the panel has to
 * offer one. Hidden once permission is granted or denied.
 */
function NotificationPermissionRow() {
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(
    typeof Notification === 'undefined' ? 'unsupported' : Notification.permission,
  )

  if (permission === 'granted') {
    return (
      <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
        浏览器通知已授权
      </span>
    )
  }
  if (permission === 'unsupported') {
    return (
      <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
        当前浏览器不支持桌面通知，以下开关不会生效。
      </span>
    )
  }
  if (permission === 'denied') {
    return (
      <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
        通知已被拒绝，需在浏览器站点设置中重新允许。
      </span>
    )
  }
  return (
    <div className="ft-row" style={{ gap: 'var(--ft-gap-4)' }}>
      {/* Not `borderless`: this is the one action the panel needs the user to
          take, and a borderless button reads as a section heading. */}
      <Button
        size="small"
        theme="light"
        icon={<IconBellStroked />}
        onClick={() => {
          void Notification.requestPermission().then(setPermission)
        }}
      >
        允许桌面通知
      </Button>
      <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
        以下开关需要先授权
      </span>
    </div>
  )
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <div
      className="ft-row"
      style={{ gap: 'var(--ft-gap-5)', alignItems: 'flex-start', minHeight: 30 }}
    >
      <div className="ft-col" style={{ gap: 1, flex: '1 1 52%', minWidth: 0 }}>
        <span style={{ fontSize: 'var(--ft-font-sm)' }}>{label}</span>
        {hint !== undefined && (
          <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
            {hint}
          </span>
        )}
      </div>
      <div style={{ flex: '1 1 48%', minWidth: 0 }}>{children}</div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                        */
/* -------------------------------------------------------------------------- */

export function Settings() {
  const { settings, update, reset } = useSettings()
  const { config } = useSnapshot()
  const { activeBot } = useBots()
  const { mode, setMode } = useTheme()

  const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone

  const timezoneOptions = [
    { value: 'UTC', label: 'UTC（推荐，交易所通常使用 UTC）' },
    { value: 'local', label: `本地时区（${localZone}）` },
  ]

  const setNotification = (key: keyof NotificationSettings, checked: boolean) => {
    update({ notifications: { ...settings.notifications, [key]: checked } })
  }

  const onReset = () => {
    reset()
    Toast.success('已恢复默认设置')
  }

  return (
    <div className="ft-page">
      <div className="ft-page-head">
        <h1 className="ft-page-title">设置</h1>
        <span className="ft-page-sub">仅影响本控制台的显示方式，不会修改机器人配置</span>
      </div>

      <div className="ft-grid cols-2" style={{ alignItems: 'start' }}>
        {/* 界面 ----------------------------------------------------------- */}
        <Panel title="界面" icon={<IconSetting />} sub="顶部栏与交互">
          <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
            <SettingRow label="顶部栏持仓显示" hint="决定未平仓交易如何呈现">
              <Select
                size="small"
                value={settings.openTradesInTitle}
                onChange={(value) =>
                  update({ openTradesInTitle: (value as OpenTradesInTitle) ?? 'showPill' })
                }
                optionList={OPEN_TRADES_OPTIONS}
                style={{ width: '100%' }}
              />
            </SettingRow>

            <SettingRow label="时区" hint="影响所有时间戳的显示">
              <Select
                size="small"
                value={settings.timezone}
                onChange={(value) => update({ timezone: String(value ?? 'UTC') })}
                optionList={timezoneOptions}
                style={{ width: '100%' }}
              />
            </SettingRow>

            <SwitchRow
              label="平仓前显示确认对话框"
              help="强制平仓时弹出确认，避免误操作"
              checked={settings.confirmDialog}
              onChange={(checked) => update({ confirmDialog: checked })}
            />
          </div>
        </Panel>

        {/* 通知 ----------------------------------------------------------- */}
        <Panel title="通知" icon={<IconAlertTriangle />} sub="WebSocket 事件提示">
          <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
            <NotificationPermissionRow />
            {NOTIFICATION_ROWS.map((row) => (
              <SwitchRow
                key={row.key}
                label={row.label}
                help={row.help}
                checked={settings.notifications[row.key]}
                onChange={(checked) => setNotification(row.key, checked)}
              />
            ))}
          </div>
        </Panel>

        {/* 图表 ----------------------------------------------------------- */}
        <Panel title="图表" icon={<IconCandlestickChartStroked />} sub="K 线与指标">
          <div className="ft-col" style={{ gap: 'var(--ft-gap-5)' }}>
            <SettingRow label="价格轴位置" hint="坐标轴显示在左侧还是右侧">
              <RadioGroup
                type="button"
                buttonSize="small"
                value={settings.chartLabelSide}
                onChange={(e) =>
                  update({ chartLabelSide: (e.target.value as ChartLabelSide) ?? 'right' })
                }
                options={CHART_SIDE_OPTIONS}
              />
            </SettingRow>

            <SwitchRow
              label="使用 Heikin-Ashi K 线"
              help="以平均K线平滑趋势，牺牲精确价格"
              checked={settings.useHeikinAshiCandles}
              onChange={(checked) => update({ useHeikinAshiCandles: checked })}
            />

            <SwitchRow
              label="只请求必要的列"
              help="减小大数据集的传输量；绘图配置变化时可能需要额外请求"
              checked={settings.useReducedPairCalls}
              onChange={(checked) => update({ useReducedPairCalls: checked })}
            />

            <SettingRow label="默认显示K线数量" hint="新打开图表时请求的K线根数">
              <div className="ft-row" style={{ gap: 'var(--ft-gap-5)' }}>
                {/* Semi's Slider forwards `style` to its inner
                    `.semi-slider-wrapper`, not to the `.semi-slider` root that is
                    the real flex item. Putting the flex on the root therefore did
                    nothing and the wrapper collapsed to 0px — a floating handle
                    with no rail. The wrapper div carries the flex instead. */}
                <div style={{ flex: '1 1 auto', minWidth: 0 }}>
                  <Slider
                    min={100}
                    max={2000}
                    step={50}
                    value={settings.chartDefaultCandleCount}
                    onChange={(value) =>
                      update({
                        chartDefaultCandleCount: Array.isArray(value)
                          ? Number(value[0])
                          : Number(value),
                      })
                    }
                  />
                </div>
                <InputNumber
                  size="small"
                  min={100}
                  max={2000}
                  step={50}
                  value={settings.chartDefaultCandleCount}
                  onChange={(value) => update({ chartDefaultCandleCount: Number(value) || 250 })}
                  style={{ width: 88 }}
                />
              </div>
            </SettingRow>

            <SwitchRow
              label="显示图表标记区域"
              help="在图表上绘制信号/成交的标记区域"
              checked={settings.showMarkArea}
              onChange={(checked) => update({ showMarkArea: checked })}
            />

            <SettingRow label="收益分布分箱数" hint="收益分布图的直方柱数量">
              <Select
                size="small"
                value={settings.profitDistributionBins}
                onChange={(value) => update({ profitDistributionBins: Number(value) || 20 })}
                optionList={PROFIT_BINS.map((bin) => ({ value: bin, label: `${bin} 个分箱` }))}
                style={{ width: '100%' }}
              />
            </SettingRow>

            <SettingRow label="收益统计周期" hint="按日 / 周 / 月聚合收益">
              <Select
                size="small"
                value={settings.timeProfitPeriod}
                onChange={(value) =>
                  update({ timeProfitPeriod: (value as TimeProfitPeriod) ?? 'daily' })
                }
                optionList={TIME_PROFIT_PERIODS}
                style={{ width: '100%' }}
              />
            </SettingRow>

            <SettingRow label="收益统计口径" hint="绝对收益或相对收益率">
              <Select
                size="small"
                value={settings.timeProfitPreference}
                onChange={(value) =>
                  update({
                    timeProfitPreference: (value as TimeProfitPreference) ?? 'abs_profit',
                  })
                }
                optionList={TIME_PROFIT_PREFERENCES}
                style={{ width: '100%' }}
              />
            </SettingRow>
          </div>
        </Panel>

        {/* 回测 ----------------------------------------------------------- */}
        <Panel title="回测" icon={<IconPlay />} sub="结果表额外指标">
          <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
            <SettingRow
              label="附加指标"
              hint="选择在按交易对 / 按标签的结果中额外展示的指标"
            >
              <Select
                size="small"
                multiple
                value={settings.backtestAdditionalMetrics}
                onChange={(value) =>
                  update({
                    backtestAdditionalMetrics: Array.isArray(value) ? value.map(String) : [],
                  })
                }
                optionList={BACKTEST_METRICS.map((metric) => ({
                  value: metric.field,
                  label: metric.header,
                }))}
                placeholder="选择指标"
                maxTagCount={4}
                style={{ width: '100%' }}
              />
            </SettingRow>

            <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-2)' }}>
              {settings.backtestAdditionalMetrics.length === 0 ? (
                <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  未选择任何附加指标
                </span>
              ) : (
                settings.backtestAdditionalMetrics.map((field) => (
                  <Tag key={field} variant="plain">
                    {BACKTEST_METRICS.find((m) => m.field === field)?.header ?? field}
                  </Tag>
                ))
              )}
            </div>
          </div>
        </Panel>

        {/* 系统 ----------------------------------------------------------- */}
        <div style={{ gridColumn: '1 / -1' }}>
          <Panel
            title="系统"
            icon={<IconTerminal />}
            sub={activeBot?.name}
            actions={
              <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  当前主题：{mode === 'dark' ? '深色' : '浅色'}
                </span>
                <Button
                  size="small"
                  icon={mode === 'dark' ? <IconSun /> : <IconMoon />}
                  onClick={() => setMode(mode === 'dark' ? 'light' : 'dark')}
                >
                  {mode === 'dark' ? '切换到浅色' : '切换到深色'}
                </Button>
                <Button size="small" type="danger" icon={<IconRefresh />} onClick={onReset}>
                  恢复默认设置
                </Button>
              </div>
            }
          >
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                gap: 'var(--ft-gap-6)',
              }}
            >
              <KeyValueList>
                <ValuePair label="Freqtrade 版本">
                  <span className="ft-num">{config?.version ?? '未知'}</span>
                </ValuePair>
                <ValuePair label="API 版本">
                  <span className="ft-num">{config?.api_version ?? '未知'}</span>
                </ValuePair>
                <ValuePair label="运行模式">
                  <Tag variant="plain">{config?.runmode ?? '未知'}</Tag>
                </ValuePair>
                <ValuePair label="策略 / 周期">
                  <span className="ft-mono-sm">
                    {config?.strategy ?? '未知'} · {config?.timeframe ?? '–'}
                  </span>
                </ValuePair>
              </KeyValueList>

              <KeyValueList>
                <ValuePair label="API 地址">
                  <span className="ft-mono-sm" style={{ overflowWrap: 'anywhere' }}>
                    {activeBot?.baseUrl ?? '未连接'}
                  </span>
                </ValuePair>
                <ValuePair label="连接用户">
                  <span className="ft-mono-sm">{activeBot?.username ?? '–'}</span>
                </ValuePair>
                <ValuePair label="交易所">
                  <span className="ft-mono-sm">
                    {config?.exchange ?? '–'}
                    {config?.trading_mode ? ` · ${config.trading_mode}` : ''}
                  </span>
                </ValuePair>
                <ValuePair label="计价币">
                  <span className="ft-mono-sm">{config?.stake_currency ?? '–'}</span>
                </ValuePair>
              </KeyValueList>

              <div className="ft-col" style={{ gap: 'var(--ft-gap-4)' }}>
                <div className="ft-row" style={{ gap: 'var(--ft-gap-3)' }}>
                  <IconInfoCircle className="ft-faint" />
                  <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                    设置保存在浏览器 localStorage（ftui.settings），换浏览器后需要重新配置。
                  </span>
                </div>
                <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-2)' }}>
                  <Tag variant="plain">
                    <IconList size="small" /> 设置项 {Object.keys(settings).length}
                  </Tag>
                  <Tag variant="plain">
                    <IconConfigStroked size="small" /> 时区 {settings.timezone}
                  </Tag>
                </div>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
