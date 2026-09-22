#!/usr/bin/env node
/**
 * Screenshot sweep — captures key pages in both themes for visual review.
 *
 * Usage: node scripts/shots.mjs [origin] [outDir]
 */

import { chromium } from 'playwright-core'
import { existsSync, mkdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const ORIGIN = process.argv[2] ?? 'http://127.0.0.1:5273'
const OUT = process.argv[3] ?? '/tmp/ftui-shots'
const API_BASE = process.env.SMOKE_API_BASE ?? 'http://127.0.0.1:8081'
const USER = process.env.SMOKE_USER
const PASS = process.env.SMOKE_PASSWORD
if (!USER || !PASS) {
  console.error('Set SMOKE_USER and SMOKE_PASSWORD before running this script.')
  process.exit(2)
}

const executablePath = [
  process.env.SMOKE_CHROME,
  join(homedir(), '.cache/ms-playwright/chromium-1228/chrome-linux64/chrome'),
  '/usr/bin/google-chrome',
]
  .filter(Boolean)
  .find((p) => existsSync(p))

const login = await fetch(`${API_BASE}/api/v1/token/login`, {
  method: 'POST',
  headers: {
    Authorization:
      'Basic ' + Buffer.from(`${USER}:${PASS}`, 'utf8').toString('base64'),
    'Content-Type': 'application/json',
  },
  body: '{}',
})
const session = await login.json()

const PAGES = ['dashboard', 'trade', 'chart', 'balance', 'backtest', 'pairlist_config', 'logs', 'settings']

mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
})

for (const theme of ['dark', 'light']) {
  const context = await browser.newContext({
    viewport: { width: 1680, height: 1050 },
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  await page.addInitScript(
    ([session, theme, id, user, pass]) => {
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
        JSON.stringify({ access: session.access_token, refresh: session.refresh_token }),
      )
      localStorage.setItem('ftui.theme', theme)
    },
    [session, theme, 'ftbot.0', USER, PASS],
  )

  for (const route of PAGES) {
    await page.goto(`${ORIGIN}/${route}`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.ft-shell', { timeout: 15000 })
    // Let charts paint and the snapshot settle.
    await page.waitForTimeout(9000)
    const file = join(OUT, `${theme}-${route}.png`)
    await page.screenshot({ path: file })
    console.log(file)
  }

  await context.close()
}

await browser.close()
