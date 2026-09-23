#!/usr/bin/env node
/**
 * Text contrast audit.
 *
 * For every visible text node it resolves the effective background by walking up
 * the ancestor chain to the first non-transparent colour, then computes the WCAG
 * contrast ratio. This catches the readability problems a monochrome theme is
 * most prone to — grey-on-grey captions, dimmed values, placeholder text — which
 * are tedious to spot by eye across 15 pages and two themes.
 *
 * Thresholds: 3.0 for large/bold text (>=18.66px, or >=14px bold), 4.5 otherwise.
 *
 * Usage: node scripts/contrast.mjs [dark|light]
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
const VIEWPORT = { width: 1680, height: 1200 }

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

const PROBE = () => {
  const parse = (value) => {
    const m = /rgba?\(([^)]+)\)/.exec(value || '')
    if (!m) return null
    const p = m[1].split(',').map((s) => parseFloat(s.trim()))
    if (p.length < 3) return null
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }
  }
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  })
  const lum = (c) => {
    const f = (v) => {
      const s = v / 255
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
    }
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b)
  }
  const ratio = (a, b) => {
    const l1 = lum(a)
    const l2 = lum(b)
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05)
  }

  const bgOf = (el) => {
    let node = el
    let acc = null
    while (node && node !== document.documentElement.parentElement) {
      const c = parse(getComputedStyle(node).backgroundColor)
      if (c && c.a > 0) {
        acc = acc ? over(acc, c) : c
        if (acc.a >= 1) return acc
      }
      node = node.parentElement
    }
    return acc ?? { r: 255, g: 255, b: 255, a: 1 }
  }

  const out = []
  for (const el of document.querySelectorAll('body *')) {
    const box = el.getBoundingClientRect()
    if (box.width < 4 || box.height < 4) continue
    const style = getComputedStyle(el)
    if (style.visibility === 'hidden' || style.display === 'none') continue
    if (Number(style.opacity) < 0.15) continue

    // WCAG exempts disabled controls from contrast minimums, and Semi renders
    // them at 35% alpha by design. Reporting them buries the real findings.
    if (
      el.closest(
        '[disabled],[aria-disabled="true"],.semi-button-disabled,.semi-tabs-tab-disabled,.semi-select-disabled,.semi-input-disabled,.semi-switch-disabled,.semi-checkbox-disabled,.semi-radio-disabled,.semi-slider-disabled',
      )
    ) {
      continue
    }

    // Only elements that directly own text.
    const own = [...el.childNodes]
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent.trim())
      .join('')
    if (!own) continue

    const fgRaw = parse(style.color)
    if (!fgRaw) continue
    const bg = bgOf(el)
    const fg = fgRaw.a < 1 ? over(fgRaw, bg) : fgRaw

    const size = parseFloat(style.fontSize)
    const weight = Number(style.fontWeight) || 400
    const large = size >= 18.66 || (size >= 14 && weight >= 700)
    const need = large ? 3 : 4.5
    const r = ratio(fg, bg)
    if (r < need) {
      out.push({
        text: own.slice(0, 34),
        cls: (el.className || '').toString().slice(0, 44),
        size: Math.round(size),
        weight,
        color: style.color,
        bg: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`,
        ratio: Math.round(r * 100) / 100,
        need,
      })
    }
  }
  return out
}

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

const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
})

let total = 0
for (const route of ROUTES) {
  const context = await browser.newContext({ viewport: VIEWPORT })
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

  const bad = await page.evaluate(PROBE)
  // Collapse duplicates: the same style problem usually repeats per row.
  const seen = new Map()
  for (const b of bad) {
    const key = `${b.cls}|${b.color}|${b.bg}|${b.size}`
    if (!seen.has(key)) seen.set(key, { ...b, count: 1 })
    else seen.get(key).count += 1
  }
  const uniq = [...seen.values()].sort((a, b) => a.ratio - b.ratio)

  if (uniq.length) {
    console.log(`\n--- /${route}  (${uniq.length} distinct low-contrast styles, ${bad.length} nodes)`)
    for (const u of uniq.slice(0, 5)) {
      console.log(
        `    ${u.ratio.toFixed(2)}:1 (need ${u.need})  ${u.size}px/${u.weight}  ${u.color} on ${u.bg}  ×${u.count}  "${u.text}"  [${u.cls}]`,
      )
    }
    total += uniq.length
  } else {
    console.log(`--- /${route}  ok`)
  }
  await context.close()
}

console.log(`\n${total} distinct low-contrast styles in ${THEME} theme`)
await browser.close()
