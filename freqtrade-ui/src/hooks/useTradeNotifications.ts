/**
 * Browser notifications for trade events.
 *
 * The settings page offers four switches for these; without a consumer they were
 * pure decoration. The live provider already keeps the newest messages in a
 * bounded ring, so this only has to watch that ring and fire once per event id.
 */

import { useEffect, useRef } from 'react'

import { useLive } from '../state/live'
import { useSettings, type NotificationSettings } from '../state/settings'

/** Settings key → the WS topic it listens to, and the notification title. */
const TOPICS: Record<keyof NotificationSettings, string> = {
  entry_fill: '入场成交',
  exit_fill: '离场成交',
  entry_cancel: '入场取消',
  exit_cancel: '离场取消',
}

/** Enough history to survive a burst without growing without bound. */
const MAX_REMEMBERED = 200

function describe(data: unknown): string {
  if (!data || typeof data !== 'object') return ''
  const trade = data as { pair?: string; trade_id?: number; amount?: number; open_rate?: number }
  const bits: string[] = []
  if (trade.trade_id !== undefined) bits.push(`#${trade.trade_id}`)
  if (trade.amount !== undefined) bits.push(`${trade.amount}`)
  return bits.join(' · ')
}

export function useTradeNotifications(): void {
  const { events } = useLive()
  const { settings } = useSettings()
  const notified = useRef<Set<number>>(new Set())

  useEffect(() => {
    // Nothing to do until the user has granted permission — the settings panel
    // surfaces a button for that.
    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return

    const enabled = settings.notifications
    for (const event of events) {
      if (notified.current.has(event.id)) continue
      const key = event.type as keyof NotificationSettings
      if (!(key in TOPICS)) continue
      // Mark every recognised event as seen, enabled or not, so turning a
      // switch on does not replay the backlog.
      notified.current.add(event.id)
      if (!enabled[key]) continue

      const pair = (event.data as { pair?: string } | null)?.pair ?? ''
      try {
        new Notification(`${TOPICS[key]}${pair ? ` · ${pair}` : ''}`, {
          body: describe(event.data),
          tag: `${key}-${event.id}`,
        })
      } catch {
        /* Some browsers refuse to construct a notification outside a user gesture. */
      }
    }

    if (notified.current.size > MAX_REMEMBERED) {
      notified.current = new Set([...notified.current].slice(-MAX_REMEMBERED))
    }
  }, [events, settings.notifications])
}
