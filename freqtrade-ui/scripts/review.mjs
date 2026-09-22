#!/usr/bin/env node
/**
 * Full-page review captures.
 *
 * The app scrolls inside `.ft-main`, so `fullPage: true` only ever yields the
 * viewport. This measures the real content height, resizes the viewport to fit,
 * and captures the whole page in one image — which is what makes a page-by-page
 * layout review possible at all.
 *
 * Usage:
 *   node scripts/review.mjs                 # all routes, dark
 *   node scripts/review.mjs dark light      # both themes
 *   node scripts/review.mjs dark dashboard trade
 */

import { chromium } from 'playwright-core'
import { existsSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const ORIGIN = process.env.REVIEW_ORIGIN ?? 'http://127.0.0.1:5273'
const API_BASE = process.env.SMOKE_API_BASE ?? 'http://127.0.0.1:8081'
const OUT = process.env.REVIEW_OUT ?? '/tmp/ftui-review'
const WIDTH = Number(process.env.REVIEW_WIDTH ?? 1680)

const ALL_ROUTES = [
  'dashboard',
  'trade',
  'open_trades',
  'trade_history',
  'balance',
  'chart',
  'pairlist',
  'pairlist_config',
  'backtest',
  'download_data',
  'lookahead_analysis',
  'recursive_analysis',
  'logs',
  'settings',
]

const argv = process.argv.slice(2)
const themes = argv.filter((a) => a === 'dark' || a === 'light')
const routes = argv.filter((a) => ALL_ROUTES.includes(a))
const THEMES = themes.length ? themes : ['dark']
const ROUTES = routes.length ? routes : ALL_ROUTES

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

for (const theme of THEMES) {
  for (const route of ROUTES) {
    const context = await browser.newContext({ viewport: { width: WIDTH, height: 1200 } })
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
      [session, theme, 'ftbot.0', USER, PASS],
    )

    await page.goto(`${ORIGIN}/${route}`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.ft-shell', { timeout: 15000 })

    // Wait for the content to stop growing rather than guessing a duration:
    // several pages fetch in two stages and a fixed sleep captures them half-drawn.
    let last = -1
    for (let i = 0; i < 30; i += 1) {
      await page.waitForTimeout(700)
      const h = await page.evaluate(
        () => document.querySelector('.ft-main')?.scrollHeight ?? 0,
      )
      if (h > 0 && h === last) break
      last = h
    }

    const contentH = await page.evaluate(
      () => document.querySelector('.ft-main')?.scrollHeight ?? 1200,
    )
    const height = Math.min(Math.max(contentH + 20, 900), 6000)
    await page.setViewportSize({ width: WIDTH, height })
    await page.waitForTimeout(900)

    const file = join(OUT, `${theme}-${route}.png`)
    await page.screenshot({ path: file })
    console.log(`${file}  ${WIDTH}x${Math.round(height)}`)
    await context.close()
  }
}

await browser.close()
