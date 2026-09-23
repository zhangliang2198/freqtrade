/**
 * Background-job polling.
 *
 * freqtrade long-running actions (backtest, download, pairlist evaluation,
 * lookahead/recursive analysis) all follow the same contract: the POST returns
 * a `job_id`, and `GET /background/{job_id}` reports progress until
 * `running === false`.
 *
 * This hook owns that loop, deduplicates concurrent polls of the same job, and
 * resumes jobs already running on the server (so a page refresh does not lose
 * sight of an in-flight backtest).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { backgroundApi } from '../api/endpoints'
import type { BackgroundTaskStatus } from '../api/types'
import type { BotApi } from '../api/client'

export type JobCategory =
  | 'pairlist'
  | 'download_data'
  | 'backtest'
  | 'lookahead_analysis'
  | 'recursive_analysis'

const POLL_MS = 1000

export interface TrackedJob extends BackgroundTaskStatus {
  /** Set when the poll loop itself failed, as opposed to the job failing. */
  pollError?: string
}

export interface UseJobPolling {
  jobs: TrackedJob[]
  /** Begins tracking a job id returned by a POST. */
  track: (jobId: string, category: JobCategory) => void
  /** Stops tracking and forgets a job. */
  dismiss: (jobId: string) => void
  /** Forgets every finished job. */
  clearFinished: () => void
  /** Resolves with the final status once the job settles. */
  waitFor: (jobId: string) => Promise<TrackedJob | null>
}

export function useJobPolling(api: BotApi | null, enabled = true): UseJobPolling {
  const [jobs, setJobs] = useState<TrackedJob[]>([])

  const timers = useRef(new Map<string, number>())
  // `null` means the job was dismissed before it settled, so an awaiting
  // caller can stop rather than hang forever.
  const waiters = useRef(new Map<string, (job: TrackedJob | null) => void>())
  // Guards against starting two loops for the same job id.
  const polling = useRef(new Set<string>())

  const upsert = useCallback((job: TrackedJob) => {
    setJobs((prev) => {
      const index = prev.findIndex((j) => j.job_id === job.job_id)
      if (index === -1) return [job, ...prev]
      const next = [...prev]
      next[index] = { ...next[index], ...job }
      return next
    })
  }, [])

  const stopPolling = useCallback((jobId: string) => {
    const timer = timers.current.get(jobId)
    if (timer !== undefined) {
      window.clearInterval(timer)
      timers.current.delete(jobId)
    }
    polling.current.delete(jobId)
  }, [])

  const track = useCallback(
    (jobId: string, category: JobCategory) => {
      if (!api || polling.current.has(jobId)) return
      polling.current.add(jobId)

      // Seed a placeholder so the UI shows the job immediately. The backend's
      // first status word is not known yet, so `running` is the honest value.
      upsert({ job_id: jobId, job_category: category, status: 'running', running: true })

      const tick = async () => {
        try {
          const status = await backgroundApi.get(api, jobId)
          const next: TrackedJob = { ...status, job_category: status.job_category ?? category }
          upsert(next)
          if (!next.running) {
            stopPolling(jobId)
            waiters.current.get(jobId)?.(next)
            waiters.current.delete(jobId)
          }
        } catch (err) {
          stopPolling(jobId)
          const failed: TrackedJob = {
            job_id: jobId,
            job_category: category,
            status: 'failed',
            running: false,
            pollError: err instanceof Error ? err.message : String(err),
          }
          upsert(failed)
          waiters.current.get(jobId)?.(failed)
          waiters.current.delete(jobId)
        }
      }

      void tick()
      timers.current.set(jobId, window.setInterval(tick, POLL_MS))
    },
    [api, stopPolling, upsert],
  )

  const waitFor = useCallback(
    (jobId: string) =>
      new Promise<TrackedJob | null>((resolve) => {
        const existing = jobs.find((j) => j.job_id === jobId)
        if (existing && !existing.running) {
          resolve(existing)
          return
        }
        waiters.current.set(jobId, resolve)
      }),
    [jobs],
  )

  const dismiss = useCallback(
    (jobId: string) => {
      stopPolling(jobId)
      // Resolve any waiter, otherwise `await waitFor(id)` never settles and the
      // caller's `finally` never runs — the action button stayed disabled.
      waiters.current.get(jobId)?.(null)
      waiters.current.delete(jobId)
      setJobs((prev) => prev.filter((j) => j.job_id !== jobId))
    },
    [stopPolling],
  )

  const clearFinished = useCallback(() => {
    setJobs((prev) => prev.filter((j) => j.running))
  }, [])

  // On mount (and when the bot changes), adopt jobs the server already knows
  // about — this is what makes a page reload mid-backtest survive.
  useEffect(() => {
    if (!api || !enabled) return
    let cancelled = false

    void (async () => {
      try {
        const running = await backgroundApi.list(api)
        if (cancelled || !Array.isArray(running)) return
        for (const job of running) {
          if (job?.running) {
            track(job.job_id, (job.job_category as JobCategory) ?? 'backtest')
          }
        }
      } catch {
        /* webserver-mode only; ignore when unavailable */
      }
    })()

    return () => {
      cancelled = true
    }
    // `track` is stable per api; re-running on every job change would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, enabled])

  // Tear every loop down on unmount / bot switch.
  useEffect(() => {
    const timersRef = timers.current
    return () => {
      for (const timer of timersRef.values()) window.clearInterval(timer)
      timersRef.clear()
      polling.current.clear()
    }
  }, [api])

  return { jobs, track, dismiss, clearFinished, waitFor }
}
