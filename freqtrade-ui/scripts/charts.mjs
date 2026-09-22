#!/usr/bin/env node
/**
 * Per-chart detail captures.
 *
 * Crops each chart element on a page at 2x so axis labels, marker placement and
 * edge clipping can actually be inspected — at full-page scale those details are
 * a few pixels tall and impossible to judge.
 *
 * Usage: node scripts/charts.mjs <route> [theme]
 */

import { chromium } from 'playwright-core'
import { existsSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const ROUTE = process.argv[2] ?? 'dashboard'
const THEME = process.argv[3] ?? 'dark'
const ORIGIN = process.env.REVIEW_ORIGIN ?? 'http://127.0.0.1:5273'
const API_BASE = process.env.SMOKE_API_BASE ?? 'http://127.0.0.1:8081'
const OUT = `/tmp/ftui-charts/${THEME}-${ROUTE}`

const executablePath = [
  process.env.SMOKE_CHROME,
  join(homedir(), '.cache/ms-playwright/chromium-1228/chrome-linux64/chrome'),
  '/usr/bin/google-chrome',
]
  .filter(Boolean)
  .find((p) => existsSync(p))

const USER = process.env.SMOKE_USER
const PASS = process.env.SMOKE_PASSWORD
if (!USER || !PASS) {
  console.error('Set SMOKE_USER and SMOKE_PASSWORD before running this script.')
  process.exit(1)
}

const login = await fetch(`${API_BASE}/api/v1/token/login`, {
  method: 'POST',
  headers: {
    Authorization: 'Basic ' + Buffer.from(`${USER}:${PASS}`, 'utf8').toString('base64'),
    'Content-Type': 'application/json',
  },
  body: '{}',
})
const session = await login.json()

mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
})
const context = await browser.newContext({
  viewport: { width: 1680, height: 1200 },
  deviceScaleFactor: 2,
})
const page = await context.newPage()
await page.addInitScript(
  ([sess, t, id, user, pass]) => {
    localStorage.setItem(
      'ftui.bots',
      JSON.stringify([
        {
          id,
          name: 'main',
          baseUrl: window.location.origin,
          username: user,
          password: pass,
        },
      ]),
    )
    localStorage.setItem('ftui.activeBot', id)
    localStorage.setItem(
      `ftui.tokens.${id}`,
      JSON.stringify({ access: sess.access_token, refresh: sess.refresh_token }),
    )
    localStorage.setItem('ftui.theme', t)
  },
  [session, THEME, 'ftbot.0', USER, PASS],
)

await page.goto(`${ORIGIN}/${ROUTE}`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('.ft-shell', { timeout: 15000 })
let last = -1
for (let i = 0; i < 30; i += 1) {
  await page.waitForTimeout(700)
  const h = await page.evaluate(() => document.querySelector('.ft-main')?.scrollHeight ?? 0)
  if (h > 0 && h === last) break
  last = h
}
await page.waitForTimeout(1200)

// Each chart host, labelled by its enclosing panel so files are identifiable.
const targets = await page.evaluate(() => {
  const out = []
  document.querySelectorAll('.ft-chart').forEach((el, i) => {
    const panel = el.closest('.ft-panel')
    const title = panel?.querySelector('.ft-panel-title')?.textContent?.trim() ?? 'chart'
    const r = el.getBoundingClientRect()
    if (r.height < 20) return
    out.push({ i, title, w: Math.round(r.width), h: Math.round(r.height) })
  })
  return out
})

for (const t of targets) {
  const els = await page.$$('.ft-chart')
  const el = els[t.i]
  if (!el) continue
  const safe = t.title.replace(/[^\w\u4e00-\u9fa5-]+/g, '_')
  const file = join(OUT, `${String(t.i).padStart(2, '0')}-${safe}.png`)
  await el.screenshot({ path: file })
  console.log(`${file}  ${t.w}x${t.h}`)
}

await browser.close()
