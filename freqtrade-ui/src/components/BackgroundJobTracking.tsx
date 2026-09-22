/**
 * Background-job tracker.
 *
 * freqtrade reports long-running work (backtest, data download, pairlist
 * evaluation, lookahead/recursive analysis) as a job that is polled by
 * `useJobPolling`. This widget renders whatever that hook is tracking: one
 * compact row per job with its category, status, overall progress and the
 * per-task breakdown the backend reports for downloads and backtests.
 *
 * It is deliberately presentational — jobs and the clear action arrive as
 * props, so every tool page can mount the same widget over its own poller.
 */

import { Button, Progress, Tooltip } from '@douyinfe/semi-ui'
import {
  IconCandlestickChartStroked,
  IconClose,
  IconDelete,
  IconDownload,
  IconList,
  IconSearch,
  IconTick,
} from '@douyinfe/semi-icons'

import type { TrackedJob } from '../hooks/useJobPolling'

/* -------------------------------------------------------------------------- */
/* Category presentation                                                       */
/* -------------------------------------------------------------------------- */

const CATEGORY_LABEL: Record<string, string> = {
  pairlist: 'Pairlist 评估',
  download_data: '数据下载',
  backtest: '回测',
  lookahead_analysis: '未来函数分析',
  recursive_analysis: '递归分析',
}

function categoryIcon(category: string) {
  switch (category) {
    case 'pairlist':
      return <IconList />
    case 'download_data':
      return <IconDownload />
    case 'backtest':
      return <IconCandlestickChartStroked />
    case 'lookahead_analysis':
      return <IconSearch />
    case 'recursive_analysis':
      return <IconSearch />
    default:
      return <IconList />
  }
}

function categoryLabel(category: string): string {
  return CATEGORY_LABEL[category] ?? category
}

/* -------------------------------------------------------------------------- */
/* Status                                                                      */
/* -------------------------------------------------------------------------- */

type JobState = 'running' | 'success' | 'failed'

function jobState(job: TrackedJob): JobState {
  if (job.status === 'success') return 'success'
  if (job.status === 'failed') return 'failed'
  return 'running'
}

const STATE_TEXT: Record<JobState, string> = {
  running: '运行中',
  success: '完成',
  failed: '失败',
}

function stateColor(state: JobState): string {
  if (state === 'success') return 'var(--ft-up)'
  if (state === 'failed') return 'var(--ft-down)'
  return 'var(--ft-ink-3)'
}

function StatusMark({ state }: { state: JobState }) {
  if (state === 'success') {
    return <IconTick style={{ color: 'var(--ft-up)' }} />
  }
  if (state === 'failed') {
    return <IconClose style={{ color: 'var(--ft-down)' }} />
  }
  return (
    <span
      className="ft-dot idle"
      style={{ background: 'var(--ft-ink-3)', flex: '0 0 7px' }}
      aria-hidden="true"
    />
  )
}

/* -------------------------------------------------------------------------- */
/* Progress                                                                    */
/* -------------------------------------------------------------------------- */

/** The backend reports `{progress, total}` per task; `description` is optional. */
interface ProgressTask {
  progress: number
  total: number
  description?: string
}

function taskPercent(task: ProgressTask): number {
  if (!task || !Number.isFinite(task.progress) || !Number.isFinite(task.total) || task.total <= 0) {
    return 0
  }
  return Math.min(100, Math.max(0, (task.progress / task.total) * 100))
}

function TaskBar({ name, task, state }: { name: string; task: ProgressTask; state: JobState }) {
  const percent = taskPercent(task)
  const label = task.description || name
  return (
    <div className="ft-col" style={{ gap: 2, minWidth: 0, flex: '1 1 140px' }}>
      <div className="ft-row" style={{ gap: 'var(--ft-gap-3)', minWidth: 0 }}>
        <span
          className="ft-mono-sm ft-muted ft-nowrap"
          style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}
          title={`${label} — ${task.progress}/${task.total}`}
        >
          {label}
        </span>
        <span className="ft-num ft-faint" style={{ marginLeft: 'auto', fontSize: 'var(--ft-font-xs)' }}>
          {percent.toFixed(0)}%
        </span>
      </div>
      <Progress
        percent={percent}
        showInfo={false}
        size="small"
        strokeWidth={4}
        stroke={state === 'failed' ? 'var(--ft-down)' : state === 'success' ? 'var(--ft-up)' : 'var(--ft-ink-3)'}
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Widget                                                                      */
/* -------------------------------------------------------------------------- */

export interface BackgroundJobTrackingProps {
  jobs: TrackedJob[]
  /** Forgets every finished job. */
  onClear: () => void
  /** Forgets a single job — omit to hide the per-row dismiss button. */
  onDismiss?: (jobId: string) => void
}

export function BackgroundJobTracking({ jobs, onClear, onDismiss }: BackgroundJobTrackingProps) {
  if (!jobs.length) return null

  const hasFinished = jobs.some((job) => !job.running)

  return (
    <div className="ft-col" style={{ gap: 'var(--ft-gap-3)', minWidth: 0 }}>
      {hasFinished && (
        <div className="ft-row" style={{ justifyContent: 'flex-end' }}>
          <Button size="small" theme="borderless" type="tertiary" icon={<IconDelete />} onClick={onClear}>
            清除已完成
          </Button>
        </div>
      )}

      {jobs.map((job) => {
        const state = jobState(job)
        const tasks = Object.entries(
          (job.progress_tasks ?? {}) as Record<string, ProgressTask>,
        )
        const percent =
          typeof job.progress === 'number' && Number.isFinite(job.progress)
            ? Math.min(100, Math.max(0, job.progress))
            : undefined
        const errorText = job.error || job.pollError

        return (
          <div
            key={job.job_id}
            className="ft-col"
            style={{
              gap: 'var(--ft-gap-3)',
              padding: 'var(--ft-gap-4)',
              border: '1px solid var(--ft-line)',
              borderRadius: 'var(--ft-radius)',
              background: 'var(--ft-paper-1)',
              minWidth: 0,
            }}
          >
            <div className="ft-row" style={{ gap: 'var(--ft-gap-4)', minWidth: 0 }}>
              <span
                className="ft-panel-icon"
                title={job.job_id}
                style={{ color: stateColor(state) }}
              >
                {categoryIcon(job.job_category)}
              </span>

              <span style={{ fontWeight: 600, fontSize: 'var(--ft-font-sm)' }}>
                {categoryLabel(job.job_category)}
              </span>

              <span className="ft-row" style={{ gap: 5 }}>
                <StatusMark state={state} />
                <span style={{ color: stateColor(state), fontSize: 'var(--ft-font-xs)' }}>
                  {STATE_TEXT[state]}
                </span>
              </span>

              <span className="ft-mono-sm ft-faint" style={{ marginLeft: 'auto' }} title="Job id">
                {job.job_id}
              </span>

              {onDismiss && (
                <Tooltip content="移除该任务">
                  <Button
                    size="small"
                    theme="borderless"
                    type="tertiary"
                    icon={<IconClose />}
                    onClick={() => onDismiss(job.job_id)}
                  />
                </Tooltip>
              )}
            </div>

            {errorText && (
              <div
                className="ft-mono-sm"
                style={{
                  color: 'var(--ft-down)',
                  background: 'var(--ft-down-bg)',
                  border: '1px solid var(--ft-line)',
                  borderRadius: 'var(--ft-radius-sm)',
                  padding: 'var(--ft-gap-3) var(--ft-gap-4)',
                  overflowWrap: 'anywhere',
                }}
              >
                {errorText}
              </div>
            )}

            {percent !== undefined && (
              <div className="ft-row" style={{ gap: 'var(--ft-gap-4)', minWidth: 0 }}>
                <Progress
                  percent={percent}
                  showInfo={false}
                  size="small"
                  strokeWidth={5}
                  stroke={state === 'failed' ? 'var(--ft-down)' : state === 'success' ? 'var(--ft-up)' : 'var(--ft-ink-3)'}
                  style={{ flex: '1 1 auto', minWidth: 0 }}
                />
                <span className="ft-num ft-muted" style={{ fontSize: 'var(--ft-font-xs)' }}>
                  {percent.toFixed(0)}%
                </span>
              </div>
            )}

            {tasks.length > 0 && (
              <div className="ft-row wrap" style={{ gap: 'var(--ft-gap-5)', minWidth: 0 }}>
                {tasks.map(([name, task]) => (
                  <TaskBar key={name} name={name} task={task} state={state} />
                ))}
              </div>
            )}

            {job.status_message && !errorText && (
              <div className="ft-faint" style={{ fontSize: 'var(--ft-font-xs)' }}>
                {job.status_message}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
