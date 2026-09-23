/**
 * Small presentational primitives shared by every page.
 *
 * These deliberately wrap plain markup rather than Semi components wherever the
 * monochrome styling would have to fight Semi's defaults — the icon-block
 * panels and stat tiles are the app's own visual language.
 */

import { forwardRef, type ReactNode } from 'react'

/* -------------------------------------------------------------------------- */
/* Panel                                                                       */
/* -------------------------------------------------------------------------- */

export interface PanelProps {
  title?: ReactNode
  /** Small icon rendered in the leading block. */
  icon?: ReactNode
  sub?: ReactNode
  actions?: ReactNode
  /** Remove body padding — for tables that manage their own spacing. */
  flush?: boolean
  className?: string
  bodyClassName?: string
  children: ReactNode
}

/**
 * `ref` is forwarded so a page can scroll a panel into view — selecting a row in
 * a table above the fold otherwise updates a panel the user cannot see.
 */
export const Panel = forwardRef<HTMLElement, PanelProps>(function Panel(
  { title, icon, sub, actions, flush, className, bodyClassName, children },
  ref,
) {
  const hasHead = title !== undefined || actions !== undefined || icon !== undefined
  return (
    <section ref={ref} className={`ft-panel${className ? ` ${className}` : ''}`}>
      {hasHead && (
        <header className="ft-panel-head">
          {icon !== undefined && <span className="ft-panel-icon">{icon}</span>}
          {title !== undefined && <span className="ft-panel-title">{title}</span>}
          {sub !== undefined && <span className="ft-panel-sub">{sub}</span>}
          {actions !== undefined && <div className="ft-panel-actions">{actions}</div>}
        </header>
      )}
      <div className={`ft-panel-body${flush ? ' flush' : ''}${bodyClassName ? ` ${bodyClassName}` : ''}`}>
        {children}
      </div>
    </section>
  )
})

/* -------------------------------------------------------------------------- */
/* Stat tile                                                                   */
/* -------------------------------------------------------------------------- */

export type Tone = 'neutral' | 'up' | 'down' | 'warn' | 'info'

const toneClass: Record<Tone, string> = {
  neutral: '',
  up: 'ft-up',
  down: 'ft-down',
  warn: '',
  info: '',
}

export interface StatTileProps {
  icon?: ReactNode
  label: ReactNode
  value: ReactNode
  /** Secondary line: deltas, counts, captions. */
  meta?: ReactNode
  tone?: Tone
  /** Use the smaller value size — for long numeric strings. */
  compact?: boolean
  title?: string
}

export function StatTile({
  icon,
  label,
  value,
  meta,
  tone = 'neutral',
  compact,
  title,
}: StatTileProps) {
  return (
    <div className="ft-stat" title={title}>
      {icon !== undefined && <span className="ft-stat-icon">{icon}</span>}
      <div className="ft-stat-body">
        <div className="ft-stat-label">{label}</div>
        <div className={`ft-stat-value${compact ? ' sm' : ''} ft-num ${toneClass[tone]}`}>
          {value}
        </div>
        {meta !== undefined && <div className="ft-stat-meta">{meta}</div>}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Key/value                                                                   */
/* -------------------------------------------------------------------------- */

export function ValuePair({
  label,
  children,
  title,
}: {
  label: ReactNode
  children: ReactNode
  title?: string
}) {
  return (
    <>
      <dt title={title}>{label}</dt>
      <dd title={title}>{children}</dd>
    </>
  )
}

export function KeyValueList({ children }: { children: ReactNode }) {
  return <dl className="ft-kv">{children}</dl>
}

/* -------------------------------------------------------------------------- */
/* Tags                                                                        */
/* -------------------------------------------------------------------------- */

export function Tag({
  children,
  variant = 'default',
  title,
}: {
  children: ReactNode
  variant?: 'default' | 'solid' | 'up' | 'down' | 'warn' | 'plain'
  title?: string
}) {
  const cls = variant === 'default' ? '' : ` ${variant}`
  return (
    <span className={`ft-tag${cls}`} title={title}>
      {children}
    </span>
  )
}

/** Long/short badge — only meaningful in futures mode. */
export function DirectionTag({ isShort }: { isShort: boolean }) {
  return (
    <Tag variant={isShort ? 'down' : 'up'} title={isShort ? 'Short position' : 'Long position'}>
      {isShort ? 'SHORT' : 'LONG'}
    </Tag>
  )
}

export function StateTag({ state }: { state: string }) {
  const variant =
    state === 'running' ? 'up' : state === 'paused' ? 'warn' : state === 'stopped' ? 'down' : 'plain'
  return <Tag variant={variant}>{state.toUpperCase()}</Tag>
}

export function DryRunTag({ dryRun }: { dryRun: boolean }) {
  return (
    <Tag variant={dryRun ? 'plain' : 'warn'} title={dryRun ? 'Simulated trading' : 'Real funds'}>
      {dryRun ? 'DRY-RUN' : 'LIVE'}
    </Tag>
  )
}

/** Connection indicator used in the topbar and bot lists. */
export function LiveDot({ state }: { state: 'on' | 'off' | 'idle' }) {
  return <span className={`ft-dot ${state}`} />
}

/* -------------------------------------------------------------------------- */
/* Misc                                                                        */
/* -------------------------------------------------------------------------- */

export function SectionRule({ children }: { children: ReactNode }) {
  return <div className="ft-rule">{children}</div>
}

export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon?: ReactNode
  title: ReactNode
  hint?: ReactNode
}) {
  return (
    <div className="ft-empty">
      {icon !== undefined && <span className="ft-empty-icon">{icon}</span>}
      <div>{title}</div>
      {hint !== undefined && <div className="ft-faint">{hint}</div>}
    </div>
  )
}
