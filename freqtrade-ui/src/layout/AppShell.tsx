/**
 * Application shell: brand block, grouped sidebar navigation, and a dense
 * topbar carrying bot identity, live state and global controls.
 */

import { useState, type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { Button, Dropdown, Select, Tooltip } from '@douyinfe/semi-ui'
import {
  IconBeaker,
  IconCandlestickChartStroked,
  IconChevronLeft,
  IconChevronRight,
  IconCoinMoney,
  IconConfigStroked,
  IconDownload,
  IconExit,
  IconHistory,
  IconHome,
  IconList,
  IconListView,
  IconLoopTextStroked,
  IconMoon,
  IconPulse,
  IconRefresh,
  IconSearch,
  IconSetting,
  IconSun,
  IconTerminal,
  IconUser,
} from '@douyinfe/semi-icons'

import { useBots } from '../state/bots'
import { useLive } from '../state/live'
import { useSnapshot } from '../state/snapshot'
import { useTheme } from '../state/theme'
import { DryRunTag, LiveDot, StateTag, Tag } from '../components/primitives'
import { formatPercent, formatPriceCurrency } from '../utils/format'

interface NavEntry {
  to: string
  label: string
  icon: ReactNode
  /** Show the open-trade count as a trailing badge. */
  badge?: 'trades' | 'pairs'
}

interface NavGroup {
  label: string
  items: NavEntry[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: '交易',
    items: [
      { to: '/dashboard', label: '总览', icon: <IconHome /> },
      { to: '/trade', label: '交易台', icon: <IconPulse />, badge: 'trades' },
      { to: '/open_trades', label: '持仓', icon: <IconListView />, badge: 'trades' },
      { to: '/trade_history', label: '历史成交', icon: <IconHistory /> },
      { to: '/balance', label: '资金', icon: <IconCoinMoney /> },
    ],
  },
  {
    label: '分析',
    items: [
      { to: '/chart', label: 'K 线图', icon: <IconCandlestickChartStroked /> },
      { to: '/pairlist', label: '交易对列表', icon: <IconList />, badge: 'pairs' },
      { to: '/pairlist_config', label: 'Pairlist 配置', icon: <IconConfigStroked /> },
    ],
  },
  {
    label: '工具',
    items: [
      { to: '/backtest', label: '回测', icon: <IconBeaker /> },
      { to: '/download_data', label: '下载数据', icon: <IconDownload /> },
      { to: '/lookahead_analysis', label: '未来函数分析', icon: <IconSearch /> },
      { to: '/recursive_analysis', label: '递归分析', icon: <IconLoopTextStroked /> },
    ],
  },
  {
    label: '系统',
    items: [
      { to: '/logs', label: '日志', icon: <IconTerminal /> },
      { to: '/settings', label: '设置', icon: <IconSetting /> },
    ],
  },
]

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)
  const { mode, toggle } = useTheme()
  const { bots, activeBotId, setActiveBotId, disconnect } = useBots()
  const { status: liveStatus, reconnect } = useLive()
  const { config, openTrades, profit, refresh, loading, whitelist } = useSnapshot()
  const navigate = useNavigate()

  const liveDotState = liveStatus === 'connected' ? 'on' : liveStatus === 'connecting' ? 'idle' : 'off'

  const botOptions = bots.map((bot) => ({
    value: bot.id,
    label: bot.name,
  }))

  return (
    <div className="ft-shell" data-collapsed={collapsed}>
      <div className="ft-brand">
        <span className="ft-brand-mark">FT</span>
        {!collapsed && <span className="ft-brand-name">Freqtrade Console</span>}
      </div>

      <header className="ft-topbar">
        <Tooltip content={collapsed ? '展开侧边栏' : '收起侧边栏'}>
          <Button
            theme="borderless"
            type="tertiary"
            size="small"
            icon={collapsed ? <IconChevronRight /> : <IconChevronLeft />}
            onClick={() => setCollapsed((c) => !c)}
          />
        </Tooltip>

        {bots.length > 0 && (
          <Select
            size="small"
            value={activeBotId ?? undefined}
            onChange={(v) => setActiveBotId(String(v))}
            optionList={botOptions}
            style={{ width: 168 }}
            prefix={<IconUser size="small" />}
          />
        )}

        {/* Bot identity at a glance: what it is, how it is running, how it is doing. */}
        <div className="ft-row" style={{ gap: 'var(--ft-gap-4)', minWidth: 0 }}>
          {config && (
            <>
              <StateTag state={config.state} />
              <DryRunTag dryRun={config.dry_run} />
              <Tag variant="plain" title="Trading mode">
                {config.trading_mode}
                {config.margin_mode ? ` · ${config.margin_mode}` : ''}
              </Tag>
              <Tag variant="plain" title="Exchange">
                {config.exchange}
              </Tag>
              <span className="ft-faint ft-mono-sm" title="Strategy / timeframe">
                {config.strategy} · {config.timeframe}
              </span>
            </>
          )}
        </div>

        <div className="ft-topbar-spacer" />

        {profit && (
          <div className="ft-row ft-num" style={{ gap: 'var(--ft-gap-5)' }}>
            <Tooltip content="未平仓交易">
              <span className="ft-row" style={{ gap: 4 }}>
                <span className="ft-muted" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  持仓
                </span>
                <strong>
                  {openTrades.length}
                  {config ? ` / ${config.max_open_trades}` : ''}
                </strong>
              </span>
            </Tooltip>
            <Tooltip content="总收益">
              <span
                className={`ft-row ${(profit.profit_all_ratio ?? 0) >= 0 ? 'ft-up' : 'ft-down'}`}
                style={{ gap: 4 }}
              >
                <span className="ft-muted" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  收益
                </span>
                <strong>{formatPercent(profit.profit_all_ratio, 2)}</strong>
                <span className="ft-muted">
                  {formatPriceCurrency(profit.profit_all_coin, config?.stake_currency ?? 'USDT', 2)}
                </span>
              </span>
            </Tooltip>
          </div>
        )}

        <Tooltip content={`实时连接：${liveStatus}`}>
          <span
            className="ft-row"
            style={{ gap: 5, cursor: 'pointer' }}
            onClick={() => reconnect()}
          >
            <LiveDot state={liveDotState} />
            <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
              WS
            </span>
          </span>
        </Tooltip>

        <Tooltip content="立即刷新">
          <Button
            theme="borderless"
            type="tertiary"
            size="small"
            icon={<IconRefresh spin={loading} />}
            onClick={refresh}
          />
        </Tooltip>

        <Tooltip content={mode === 'dark' ? '切换到浅色' : '切换到深色'}>
          <Button
            theme="borderless"
            type="tertiary"
            size="small"
            icon={mode === 'dark' ? <IconSun /> : <IconMoon />}
            onClick={toggle}
          />
        </Tooltip>

        <Dropdown
          trigger="click"
          position="bottomRight"
          render={
            <Dropdown.Menu>
              <Dropdown.Item
                icon={<IconExit />}
                type="danger"
                onClick={() => {
                  if (activeBotId) disconnect(activeBotId)
                  navigate('/login')
                }}
              >
                断开并退出登录
              </Dropdown.Item>
            </Dropdown.Menu>
          }
        >
          <Button theme="borderless" type="tertiary" size="small" icon={<IconUser />} />
        </Dropdown>
      </header>

      <nav className="ft-sidebar">
        {NAV_GROUPS.map((group) => (
          <div className="ft-navgroup" key={group.label}>
            <div className="ft-navgroup-label">{group.label}</div>
            {group.items.map((item) => {
              const badgeValue =
                item.badge === 'trades'
                  ? openTrades.length
                  : item.badge === 'pairs'
                    ? whitelist.length
                    : undefined
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `ft-navitem${isActive ? ' is-active' : ''}`}
                  data-active={undefined}
                  title={collapsed ? item.label : undefined}
                >
                  <span className="ft-navitem-icon">{item.icon}</span>
                  <span className="ft-navitem-label">{item.label}</span>
                  {badgeValue !== undefined && badgeValue > 0 && (
                    <span className="ft-navitem-badge">{badgeValue}</span>
                  )}
                </NavLink>
              )
            })}
          </div>
        ))}
      </nav>

      <main className="ft-main">{children}</main>
    </div>
  )
}
