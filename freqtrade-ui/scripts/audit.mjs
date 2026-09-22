#!/usr/bin/env node
/**
 * Rendered-style audit.
 *
 * Walks the live DOM and measures what actually reached the screen, to verify
 * the brief objectively:
 *   1. structure is greyscale — every painted colour is either achromatic or one
 *      of the four semantic tokens (up / down / warn / info);
 *   2. information density — row heights, font sizes, control sizes;
 *   3. icon blocks — panel headers and stat tiles carry a sized icon holder.
 *
 * Usage: node scripts/audit.mjs [origin]
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

const browser = await chromium.launch({
  executablePath,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
})

/** Distance from grey; >12 means the colour carries real hue. */
function chromaticity(rgb) {
  const [r, g, b] = rgb
  return Math.max(r, g, b) - Math.min(r, g, b)
}

const AUDIT = () => {
  const results = {
    unexpected: {},
    allowed: 0,
    fontSizes: {},
    rowHeights: {},
    iconBlocks: { panelIcons: 0, statIcons: 0, sized: 0 },
    nodeCount: 0,
  }

  const parse = (value) => {
    const m = /rgba?\(([^)]+)\)/.exec(value || '')
    if (!m) return null
    const parts = m[1].split(',').map((s) => parseFloat(s.trim()))
    if (parts.length < 3) return null
    const alpha = parts.length > 3 ? parts[3] : 1
    if (alpha === 0) return null
    return [parts[0], parts[1], parts[2]]
  }

  const parseHex = (hex) => {
    const h = (hex || '').trim().replace('#', '')
    if (h.length !== 6) return null
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
  }

  // The only hues the design allows: signed data and state.
  const bodyStyle = getComputedStyle(document.body)
  const allowed = new Set()
  for (const name of ['--ft-up', '--ft-down', '--ft-warn', '--ft-info', '--ft-up-bg', '--ft-down-bg', '--ft-warn-bg', '--ft-info-bg']) {
    const rgb = parseHex(bodyStyle.getPropertyValue(name))
    if (rgb) allowed.add(rgb.join(','))
  }

  const seen = new Set()
  for (const el of document.querySelectorAll('*')) {
    const style = getComputedStyle(el)
    const box = el.getBoundingClientRect()
    if (box.width === 0 || box.height === 0) continue
    results.nodeCount += 1

    for (const prop of ['color', 'backgroundColor', 'borderTopColor', 'borderBottomColor']) {
      const raw = style[prop]
      const rgb = parse(raw)
      if (!rgb) continue
      const key = `${prop}:${raw}`
      if (seen.has(key)) continue
      seen.add(key)

      const chroma = Math.max(...rgb) - Math.min(...rgb)
      if (chroma <= 12) continue
      if (allowed.has(rgb.join(','))) {
        results.allowed += 1
        continue
      }
      results.unexpected[key] = (results.unexpected[key] ?? 0) + 1
    }

    const text = el.textContent?.trim()
    if (text && el.children.length === 0) {
      const size = Math.round(parseFloat(style.fontSize))
      results.fontSizes[size] = (results.fontSizes[size] ?? 0) + 1
    }
  }

  // Density: measure typical table row heights.
  for (const tr of document.querySelectorAll('.ft-table tr, table tr')) {
    const h = Math.round(tr.getBoundingClientRect().height)
    if (h > 0) results.rowHeights[h] = (results.rowHeights[h] ?? 0) + 1
  }

  // Icon blocks in panel headers and stat tiles.
  const panels = document.querySelectorAll('.ft-panel')
  for (const panel of panels) {
    const icon = panel.querySelector('.ft-panel-icon, .ft-panel-head svg, .ft-panel-head i')
    if (icon) {
      results.iconBlocks.panelIcons += 1
      const r = icon.getBoundingClientRect()
      if (r.width >= 14 && r.width <= 28) results.iconBlocks.sized += 1
    }
  }
  for (const tile of document.querySelectorAll('.ft-stat')) {
    const icon = tile.querySelector('.ft-stat-icon, svg')
    if (icon) {
      results.iconBlocks.statIcons += 1
      const r = icon.getBoundingClientRect()
      if (r.width >= 14 && r.width <= 28) results.iconBlocks.sized += 1
    }
  }

  return results
}

const ROUTES = ['dashboard', 'trade', 'balance', 'logs', 'settings']

for (const theme of ['dark', 'light']) {
  console.log(`\n${'='.repeat(72)}\nTHEME: ${theme}\n${'='.repeat(72)}`)
  const context = await browser.newContext({ viewport: { width: 1680, height: 1050 } })
  const page = await context.newPage()
  await page.addInitScript(
    ([session, theme, id]) => {
      localStorage.setItem(
        'ftui.bots',
        JSON.stringify([
          {
            id,
            name: 'main',
            baseUrl: window.location.origin,
            username: USER,
            password: PASS,
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
    [session, theme, 'ftbot.0'],
  )

  for (const route of ROUTES) {
    await page.goto(`${ORIGIN}/${route}`, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('.ft-shell', { timeout: 15000 })
    await page.waitForTimeout(3000)

    const r = await page.evaluate(AUDIT)

    const bad = Object.entries(r.unexpected)
    const sizes = Object.entries(r.fontSizes)
      .map(([k, v]) => [Number(k), v])
      .sort((a, b) => a[0] - b[0])
    const rows = Object.entries(r.rowHeights)
      .map(([k, v]) => [Number(k), v])
      .sort((a, b) => a[0] - b[0])

    console.log(`\n--- /${route}  (${r.nodeCount} visible nodes)`)
    console.log(
      `  colour policy: ${bad.length === 0 ? 'PASS — greyscale + semantic tokens only' : `FAIL — ${bad.length} unexpected`}` +
        `  (${r.allowed} semantic usages)`,
    )
    for (const [k, v] of bad.slice(0, 8)) console.log(`      ${k}  ×${v}`)
    console.log(
      `  font sizes (px:count): ${sizes.map(([s, c]) => `${s}:${c}`).join('  ')}`,
    )
    console.log(
      `  row heights (px:count): ${rows.length ? rows.map(([h, c]) => `${h}:${c}`).join('  ') : 'no tables'}`,
    )
    console.log(
      `  icon blocks: panel=${r.iconBlocks.panelIcons} stat=${r.iconBlocks.statIcons} correctly-sized=${r.iconBlocks.sized}`,
    )
  }

  await context.close()
}

await browser.close()
