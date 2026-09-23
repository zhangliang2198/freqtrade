#!/usr/bin/env node
/**
 * Keyboard-focus audit.
 *
 * Tabs through a page and, for each focused element, compares its painted style
 * against the same element unfocused. An element that looks identical focused and
 * unfocused is unusable by keyboard — the user cannot tell where they are.
 *
 * The comparison is the point: a naive check that only looks for `outline-style`
 * reports false positives, because Semi draws focus on the border colour instead
 * (a Select goes from a transparent border to an ink one).
 *
 * Usage: node scripts/focus.mjs [dark|light]
 */

import { chromium } from 'playwright-core'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

const ORIGIN = process.env.REVIEW_ORIGIN ?? 'http://127.0.0.1:5273'
const API_BASE = process.env.SMOKE_API_BASE ?? 'http://127.0.0.1:8081'
const USER = process.env.SMOKE_USER
const PASS = process.env.SMOKE_PASSWORD
if (!USER || !PASS) {
  console.error('Set SMOKE_USER and SMOKE_PASSWORD before running this script.')
  process.exit(2)
}

const THEME = process.argv[2] === 'light' ? 'light' : 'dark'
const STEPS = Number(process.env.FOCUS_STEPS ?? 18)

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
    Authorization: 'Basic ' + Buffer.from(`${USER}:${PASS}`, 'utf8').toString('base64'),
    'Content-Type': 'application/json',
  },
  body: '{}',
})
const session = await login.json()

const ROUTES = [
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

/** The properties a focus style can plausibly change. */
const READ_STYLE = (el) => {
  const cs = getComputedStyle(el)
  return [
    cs.outlineStyle,
    cs.outlineWidth,
    cs.outlineColor,
    cs.boxShadow,
    cs.borderTopColor,
    cs.borderTopWidth,
    cs.backgroundColor,
    cs.color,
  ].join('|')
}

const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
})

let totalMissing = 0

for (const route of ROUTES) {
  const context = await browser.newContext({ viewport: { width: 1680, height: 1200 } })
  const page = await context.newPage()
  await page.addInitScript(
    ([sess, t, id, user, pass]) => {
      localStorage.setItem(
        'ftui.bots',
        JSON.stringify([
          { id, name: 'main', baseUrl: window.location.origin, username: user, password: pass },
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

  await page.goto(`${ORIGIN}/${route}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.ft-shell', { timeout: 15000 })
  await page
    .waitForFunction(
      () => {
        const main = document.querySelector('.ft-main')
        return !!main && !!document.querySelector('.ft-panel') && (main.innerText || '').trim().length > 120
      },
      { timeout: 25000 },
    )
    .catch(() => {})
  await page.waitForTimeout(2500)

  const missing = []
  for (let i = 0; i < STEPS; i += 1) {
    await page.keyboard.press('Tab')
    const result = await page.evaluate((readStyleSrc) => {
      const read = new Function('el', `return (${readStyleSrc})(el)`)
      const el = document.activeElement
      if (!el || el === document.body) return null
      const focused = read(el)
      // Blur-equivalent: read the same properties with focus moved to the body.
      const prev = el.getAttribute('tabindex')
      el.blur()
      const unfocused = read(el)
      el.focus()
      if (prev === null) el.removeAttribute('tabindex')
      return {
        tag: el.tagName,
        cls: (el.className || '').toString().slice(0, 40),
        changed: focused !== unfocused,
      }
    }, READ_STYLE.toString())

    if (result && !result.changed) missing.push(result)
  }

  if (missing.length) {
    totalMissing += missing.length
    console.log(`\n--- /${route}  ${missing.length} element(s) with no visible focus change`)
    for (const m of missing.slice(0, 6)) console.log(`    ${m.tag}  [${m.cls}]`)
  } else {
    console.log(`--- /${route}  ok (${STEPS} stops, every one visibly changed)`)
  }

  await context.close()
}

console.log(`\n${totalMissing} element(s) without a visible focus indicator in ${THEME} theme`)
await browser.close()
