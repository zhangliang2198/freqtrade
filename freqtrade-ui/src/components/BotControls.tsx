/**
 * Bot control bar.
 *
 * A single row of icon buttons mirroring freqUI's BotControls. Every
 * destructive action goes through a confirm dialog; the row disables itself
 * according to the bot's state and runmode.
 */

import { useState } from 'react'
import { Button, Modal, Tooltip, Toast } from '@douyinfe/semi-ui'
import {
  IconClose,
  IconExit,
  IconPause,
  IconPlay,
  IconPlus,
  IconRefresh,
  IconStop,
} from '@douyinfe/semi-icons'

import { controlApi, tradingApi } from '../api/endpoints'
import { useApi } from '../state/bots'
import { useSnapshot } from '../state/snapshot'
import { describeError } from '../hooks/usePolling'
import { ForceEntryForm } from './ForceEntryForm'

/** Runmodes in which the trading endpoints actually do something. */
const TRADING_RUNMODES = ['live', 'dry_run']

export interface BotControlsProps {
  /** Called after any successful mutation, in addition to the snapshot refresh. */
  onChanged?: () => void
}

export function BotControls({ onChanged }: BotControlsProps) {
  const api = useApi()
  const { config, refresh } = useSnapshot()
  const [busy, setBusy] = useState<string | null>(null)
  const [entryOpen, setEntryOpen] = useState(false)

  const state = config?.state
  const runmode = config?.runmode ?? ''
  const isTrading = TRADING_RUNMODES.includes(runmode)
  const isRunning = state === 'running'
  const locked = busy !== null

  const done = (label: string, detail?: string) => {
    Toast.success({ content: detail ? `${label}：${detail}` : `${label} 已发送`, duration: 2 })
    refresh()
    onChanged?.()
  }

  const run = async (key: string, label: string, action: () => Promise<unknown>) => {
    setBusy(key)
    try {
      const result = await action()
      const detail =
        result && typeof result === 'object' && 'status' in result
          ? String((result as { status: unknown }).status)
          : undefined
      done(label, detail)
    } catch (err) {
      Toast.error({ content: `${label} 失败：${describeError(err as Error) ?? String(err)}` })
    } finally {
      setBusy(null)
    }
  }

  const confirmThen = (key: string, label: string, content: string, action: () => Promise<unknown>) => {
    Modal.confirm({
      title: label,
      content,
      okText: '确认',
      cancelText: '取消',
      onOk: () => run(key, label, action),
    })
  }

  const disabledStart = !isTrading || isRunning
  const disabledStop = !isTrading || !isRunning

  return (
    <>
      <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-3)' }}>
        <Tooltip content="启动交易循环">
          <Button
            size="small"
            theme="light"
            type="primary"
            icon={<IconPlay />}
            loading={busy === 'start'}
            disabled={disabledStart || (locked && busy !== 'start')}
            onClick={() => void run('start', '启动', () => controlApi.start(api))}
          />
        </Tooltip>

        <Tooltip content="停止交易循环（同时停止管理未平仓交易）">
          <Button
            size="small"
            theme="light"
            type="tertiary"
            icon={<IconStop />}
            loading={busy === 'stop'}
            disabled={disabledStop || (locked && busy !== 'stop')}
            onClick={() =>
              confirmThen('stop', '停止机器人', '确定停止机器人循环吗？未平仓交易将不再被管理。', () =>
                controlApi.stop(api),
              )
            }
          />
        </Tooltip>

        <Tooltip content="暂停（停止买入）— 继续管理未平仓交易，但不再开新仓或加仓">
          <Button
            size="small"
            theme="light"
            type="tertiary"
            icon={<IconPause />}
            loading={busy === 'stopentry'}
            disabled={disabledStop || (locked && busy !== 'stopentry')}
            onClick={() =>
              confirmThen(
                'stopentry',
                '暂停开仓',
                '机器人将继续管理未平仓交易，但不会开新仓或加仓。确定停止开仓吗？',
                () => controlApi.stopEntry(api),
              )
            }
          />
        </Tooltip>

        <Tooltip content="重新加载配置（含策略），会重置运行时修改的设置">
          <Button
            size="small"
            theme="light"
            type="tertiary"
            icon={<IconRefresh />}
            loading={busy === 'reload'}
            disabled={!isTrading || (locked && busy !== 'reload')}
            onClick={() =>
              confirmThen('reload', '重新加载配置', '重新加载配置（含策略）？运行时修改的设置将丢失。', () =>
                controlApi.reloadConfig(api),
              )
            }
          />
        </Tooltip>

        <Tooltip content="强制平掉所有持仓">
          <Button
            size="small"
            theme="light"
            type="danger"
            icon={<IconExit />}
            loading={busy === 'forceexit'}
            disabled={!isTrading || (locked && busy !== 'forceexit')}
            onClick={() =>
              confirmThen('forceexit', '强制平仓（全部）', '确定强制平掉全部持仓吗？该操作不可撤销。', () =>
                tradingApi.forceExit(api, { tradeid: 'all' }),
              )
            }
          />
        </Tooltip>

        {config?.force_entry_enable && (
          <Tooltip content="强制开仓 — 立即按指定价格开仓，出场仍由策略规则管理">
            <Button
              size="small"
              theme="light"
              type="tertiary"
              icon={<IconPlus />}
              disabled={!isTrading || !isRunning || locked}
              onClick={() => setEntryOpen(true)}
            />
          </Tooltip>
        )}

        {!isTrading && config && (
          <Tooltip content={`当前运行模式为 ${runmode || '未知'}，交易控制不可用`}>
            <span className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
              <IconClose /> 非交易模式
            </span>
          </Tooltip>
        )}
      </div>

      <ForceEntryForm
        visible={entryOpen}
        onClose={() => setEntryOpen(false)}
        onSubmitted={() => {
          refresh()
          onChanged?.()
        }}
      />
    </>
  )
}
