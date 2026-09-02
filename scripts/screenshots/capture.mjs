// Regenerates the README screenshots. Needs `serve_sample.py` and a vite dev
// server already running - see the header of serve_sample.py for the three
// commands - plus playwright available to node:
//
//     npm i playwright && npx playwright install chromium
//     node scripts/screenshots/capture.mjs
import { chromium } from 'playwright'

const BASE = 'http://localhost:5199'
const DOC = 'doc_sample0000demo'
const OUT = new URL('../../docs/images', import.meta.url).pathname

// The router/query devtools float over both corners of the viewport.
const HIDE = `
  .tsqd-parent-container, [class*="tsqd"], [class*="TanStackRouterDevtools"],
  button[aria-label*="devtools" i], button[aria-label*="Open Tanstack" i],
  #tsr-devtools, .TanStackRouterDevtools { display: none !important; }
`

const browser = await chromium.launch()
const page = await browser.newPage({
  viewport: { width: 1680, height: 1000 },
  deviceScaleFactor: 2,
  colorScheme: 'light',
})

const errors = []
page.on('pageerror', (e) => errors.push(String(e)))
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

async function open(path) {
  await page.goto(BASE + path, { waitUntil: 'networkidle' })
  await page.addStyleTag({ content: HIDE })
  await page.waitForTimeout(1200)
}

async function selectCell(sel) {
  await page.waitForSelector('[data-testid="table-cell"]')
  await page.locator(`[data-cell="${sel}"]`).first().click()
  await page.waitForTimeout(2200)  // the page pane animates its zoom
}

// 1. The whole workspace, with a matched cell selected: PDF on the left
//    zoomed to the cell, the extracted table on the right, provenance below.
await open(`/documents/${DOC}`)
await selectCell('2:3')
await page.screenshot({ path: `${OUT}/document-viewer.png` })

// 2. The differentiator, close up: a nil dash Azure dropped and PyMuPDF
//    recovered. Cropped to the page pane, measured off the split's own
//    separator so the crop follows the layout instead of a guessed constant.
await selectCell('2:4')
const split = await page.locator('[role="separator"]').first().boundingBox()
await page.screenshot({
  path: `${OUT}/cell-provenance.png`,
  clip: { x: 0, y: 56, width: Math.round(split.x), height: 944 },
})

// 3. The library view, trimmed to where the content actually ends.
await open('/documents')
const row = await page.getByText('sample-revenue-account.pdf').first().boundingBox()
await page.screenshot({
  path: `${OUT}/documents-list.png`,
  clip: { x: 0, y: 0, width: 1680, height: Math.round(row.y + row.height + 56) },
})

if (errors.length) console.log('CONSOLE ERRORS:', errors.slice(0, 6))
console.log('wrote document-viewer.png, cell-provenance.png, documents-list.png')
await browser.close()
