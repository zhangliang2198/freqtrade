#!/usr/bin/env node
/**
 * End-to-end smoke test.
 *
 * Seeds a bot connection into localStorage (so we skip form typing), then walks
 * every route in a real Chromium and reports console errors, page exceptions and
 * failed requests. This is the check that catches "it compiles but the page is
 * blank" regressions.
 *
 * Usage:
 *   node scripts/smoke.mjs                       # against http://127.0.0.1:5273
 *   node scripts/smoke.mjs http://127.0.0.1:4173  # against a built preview
 */

import { chromium } from 'playwright-core'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const ORIGIN = process.argv[2] ?? 'http://127.0.0.1:5273'
const API_BASE = process.env.SMOKE_API_BASE ?? 'http://127.0.0.1:8081'
const USER = process.env.SMOKE_USER
const PASS = process.env.SMOKE_PASSWORD
if (!USER || !PASS) {
  console.error('Set SMOKE_USER and SMOKE_PASSWORD before running this script.')
  process.exit(2)
}

// The bot URL the browser should use. Pointing it at ORIGIN keeps every request
// same-origin and routes them through the Vite dev proxy, which is how the app
// is meant to run against a live bot without restarting it for CORS.
const BOT_URL = process.env.SMOKE_BOT_URL ?? ORIGIN

const CANDIDATE_BROWSERS = [
  process.env.SMOKE_CHROME,
  join(homedir(), '.cache/ms-playwright/chromium-1228/chrome-linux64/chrome'),
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].filter(Boolean)

const executablePath = CANDIDATE_BROWSERS.find((p) => existsSync(p))
if (!executablePath) {
  console.error('No Chromium found. Set SMOKE_CHROME to a browser binary.')
  process.exit(2)
}

const ROUTES = [
  '/dashboard',
  '/trade',
  '/open_trades',
  '/trade_history',
  '/balance',
  '/chart',
  '/pairlist',
  '/pairlist_config',
  '/backtest',
  '/download_data',
  '/lookahead_analysis',
  '/recursive_analysis',
  '/logs',
  '/settings',
  '/definitely-not-a-route',
]

// Noise that is never the app's fault.
const IGNORE = [
  /favicon/i,
  /Download the React DevTools/i,
  /ResizeObserver loop/i,
  /net::ERR_ABORTED/i,
  // freqtrade answers webserver-only endpoints with 503 "Bot is not in the
  // correct state." when the bot runs in trade mode. The UI degrades on
  // purpose; the browser still logs the response as a console error.
  /status of 503/i,
]

const logins = await fetch(`${API_BASE}/api/v1/token/login`, {
  method: 'POST',
  headers: {
    Authorization:
      'Basic ' + Buffer.from(`${USER}:${PASS}`, 'utf8').toString('base64'),
    'Content-Type': 'application/json',
  },
  body: '{}',
})
const session = await logins.json()
if (!session.access_token) {
  console.error('Login failed:', JSON.stringify(session).slice(0, 200))
  process.exit(2)
}

const botId = 'ftbot.0'
const bot = { id: botId, name: 'smoke', baseUrl: BOT_URL, username: USER, password: PASS }
const tokens = { access: session.access_token, refresh: session.refresh_token }

const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
})

const results = []

for (const route of ROUTES) {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
  const page = await context.newPage()

  const problems = []

  page.on('console', (msg) => {
    if (msg.type() !== 'error' && msg.type() !== 'warning') return
    const text = msg.text()
    if (IGNORE.some((re) => re.test(text))) return
    // React key/AntD-style warnings still matter; keep them but label severity.
    problems.push(`${msg.type()}: ${text}`)
  })
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`))
  page.on('requestfailed', (req) => {
    const text = `${req.method()} ${req.url()} ${req.failure()?.errorText ?? ''}`
    if (IGNORE.some((re) => re.test(text))) return
    problems.push(`requestfailed: ${text}`)
  })

  await page.addInitScript(
    ([id, botJson, tokenJson, theme]) => {
      localStorage.setItem('ftui.bots', botJson)
      localStorage.setItem('ftui.activeBot', id)
      localStorage.setItem(`ftui.tokens.${id}`, tokenJson)
      localStorage.setItem('ftui.theme', theme)
    },
    [botId, JSON.stringify([bot]), JSON.stringify(tokens), 'dark'],
  )

  let navigationError
  try {
    // `networkidle` can resolve before React's effects kick off their fetches,
    // so wait for the app shell to exist and then let the first data land.
    await page.goto(`${ORIGIN}${route}`, { waitUntil: 'domcontentloaded', timeout: 30000 })
    await page.waitForSelector('.ft-shell, .ft-login', { timeout: 15000 })
  } catch (err) {
    navigationError = err.message
  }

  // Let the initial snapshot requests settle, then wait for the text to stop
  // growing so we measure the rendered page rather than a loading state.
  await page.waitForTimeout(1500)
  let previous = -1
  for (let i = 0; i < 10; i += 1) {
    const current = await page
      .evaluate(() => document.body.innerText.trim().length)
      .catch(() => 0)
    if (current === previous) break
    previous = current
    await page.waitForTimeout(700)
  }

  const bodyText = await page.evaluate(() => document.body.innerText).catch(() => '')
  const rootChildren = await page
    .evaluate(() => document.getElementById('root')?.childElementCount ?? 0)
    .catch(() => 0)

  results.push({
    route,
    blank: rootChildren === 0 || bodyText.trim().length < 20,
    textLength: bodyText.trim().length,
    navigationError,
    problems: [...new Set(problems)],
  })

  await context.close()
}

await browser.close()

let failures = 0
for (const r of results) {
  const bad = r.blank || r.navigationError || r.problems.length > 0
  if (bad) failures += 1
  console.log(
    `${bad ? 'FAIL' : ' ok '}  ${r.route.padEnd(24)} text=${String(r.textLength).padStart(6)}` +
      (r.blank ? '  <BLANK/EMPTY>' : '') +
      (r.navigationError ? `  nav: ${r.navigationError}` : ''),
  )
  for (const p of r.problems.slice(0, 6)) {
    console.log(`        ${p.slice(0, 220)}`)
  }
  if (r.problems.length > 6) console.log(`        … ${r.problems.length - 6} more`)
}

console.log(`\n${results.length - failures}/${results.length} routes clean`)
process.exit(failures > 0 ? 1 : 0)
