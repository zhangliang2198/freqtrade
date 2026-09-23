#!/usr/bin/env node
/**
 * Structural audit.
 *
 * Reports, for every route, the things that make a dense console feel wrong:
 *
 *   * how wide the page container runs relative to the viewport, and how much of
 *     each panel's width its content actually occupies;
 *   * each panel's rendered height against its content's natural height, which
 *     is where dead space shows up;
 *   * panels whose content is so tall they stretch the page (unbounded tables);
 *   * horizontal overflow inside panels.
 *
 * Usage: node scripts/structure.mjs [origin]
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
// The app has breakpoints at 1280 and 1100 that a single wide-viewport sweep
// never exercises, so the width and theme are configurable.
const WIDTHS = (process.env.STRUCTURE_WIDTHS ?? '2040,1440,1100')
  .split(',')
  .map((n) => Number(n.trim()))
  .filter((n) => Number.isFinite(n) && n > 0)
const THEMES = (process.env.STRUCTURE_THEMES ?? 'dark,light').split(',').map((t) => t.trim())
const HEIGHT = Number(process.env.STRUCTURE_HEIGHT ?? 1200)

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

const PROBE = () => {
  const px = (n) => Math.round(n)
  const page = document.querySelector('.ft-page')
  const panels = [...document.querySelectorAll('.ft-panel')].map((panel) => {
    const body = panel.querySelector('.ft-panel-body')
    const rect = panel.getBoundingClientRect()
    const bodyRect = body?.getBoundingClientRect()
    // Natural content height: scrollHeight ignores any max-height clamp, so the
    // difference against the laid-out height is the dead space.
    const contentH = body ? body.scrollHeight : 0
    const laidOutH = bodyRect ? bodyRect.height : 0

    // Widest descendant vs panel width — a sparse table shows up as a low ratio.
    let widest = 0
    if (body) {
      for (const el of body.querySelectorAll('table, .ft-table, .ft-list, ul, ol')) {
        widest = Math.max(widest, el.getBoundingClientRect().width)
      }
    }

    return {
      title: panel.querySelector('.ft-panel-title')?.textContent?.trim() ?? '(no title)',
      w: px(rect.width),
      h: px(rect.height),
      laidOutH: px(laidOutH),
      contentH: px(contentH),
      dead: px(Math.max(0, laidOutH - contentH)),
      rows: body ? body.querySelectorAll('tr').length : 0,
      overflowX: body ? body.scrollWidth - body.clientWidth : 0,
      widest: px(widest),
    }
  })

  // Text that is silently cut off. An element that clips its own overflow
  // without an ellipsis hides content with no cue at all — the classic failure
  // mode of a dense table (a wrapped timestamp, a truncated pair name). Elements
  // inside a scroll container are skipped: there the clipping is reachable.
  const clipped = []
  const inScroller = (el) => {
    let n = el.parentElement
    while (n && n !== document.body) {
      const ox = getComputedStyle(n).overflowX
      if (ox === 'auto' || ox === 'scroll') return true
      n = n.parentElement
    }
    return false
  }
  for (const el of document.querySelectorAll('.ft-main *')) {
    const own = [...el.childNodes]
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent.trim())
      .join('')
    if (!own) continue
    const cs = getComputedStyle(el)
    if (cs.textOverflow === 'ellipsis') continue
    if (cs.overflowX !== 'hidden' && cs.overflowX !== 'clip') continue
    if (el.clientWidth === 0 || el.scrollWidth <= el.clientWidth + 1) continue
    if (inScroller(el)) continue
    clipped.push({
      text: own.slice(0, 28),
      cls: (el.className || '').toString().slice(0, 34),
      cut: px(el.scrollWidth - el.clientWidth),
    })
  }

  return {
    viewportW: window.innerWidth,
    pageW: page ? px(page.getBoundingClientRect().width) : 0,
    docScrollW: document.documentElement.scrollWidth,
    clipped: clipped.slice(0, 6),
    // `.ft-page.fill` deliberately stretches its list panel into the leftover
    // height, so a tall panel there is the design, not a defect.
    fill: page ? page.classList.contains('fill') : false,
    panels,
  }
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

async function makePage(theme, width) {
    const context = await browser.newContext({ viewport: { width, height: HEIGHT } })
    const page = await context.newPage()
    await page.addInitScript(
    ([sess, id, user, pass, t]) => {
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
    [session, 'ftbot.0', USER, PASS, theme],
    )
    return { context, page }
}

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    console.log(`\n${'='.repeat(70)}\nTHEME ${theme}  ·  viewport ${width}px\n${'='.repeat(70)}`)
    const { context, page } = await makePage(theme, width)
    await sweep(page)
    await context.close()
  }
}

async function sweep(page) {
for (const route of ROUTES) {
  await page.goto(`${ORIGIN}/${route}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.ft-shell', { timeout: 15000 })
  await page.waitForTimeout(6000)

  const r = await page.evaluate(PROBE)
  const waste = r.pageW / r.viewportW
  console.log(
    `--- /${route}   page=${r.pageW}px (${Math.round(waste * 100)}% of viewport)  doc=${r.docScrollW}px  panels=${r.panels.length}${r.fill ? '  [fill]' : ''}`,
  )

  // A page that rendered no panels must never read as "ok" — that is how a
  // broken route would silently pass this audit.
  if (r.panels.length === 0) {
    console.log('    FAIL — no panels rendered (route is blank or still loading)')
    continue
  }

  for (const c of r.clipped) {
    console.log(`    CLIPPED ${c.cut}px  "${c.text}"  [${c.cls}]`)
  }

  const interesting = r.panels
    .filter((p) => p.dead > 40 || (!r.fill && p.h > 700) || p.overflowX > 0)
    .sort((a, b) => b.dead - a.dead)

  if (interesting.length === 0) {
    console.log('    ok — no dead space, no oversized panels, no overflow')
  }
  for (const p of interesting.slice(0, 8)) {
    const bits = [`w=${p.w}`, `h=${p.h}`]
    if (p.dead > 40) bits.push(`DEAD=${p.dead}px`)
    if (!r.fill && p.h > 700) bits.push('OVERSIZED')
    if (p.rows) bits.push(`rows=${p.rows}`)
    if (p.overflowX > 0) bits.push(`overflowX=${p.overflowX}`)
    console.log(`    ${p.title.padEnd(18)} ${bits.join('  ')}`)
  }
}
}

await browser.close()
