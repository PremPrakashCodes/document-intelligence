/**
 * Composing a whole page: text blocks and extracted tables in one sequence.
 *
 * The table viewer answers "what does this table say". This answers the
 * question a reviewer asks either side of it — "what does the page say" — by
 * putting PyMuPDF's text back together with Azure's table structure in the
 * order the page reads.
 *
 * Two things have to be got right, and both live here rather than in the
 * component so they can be tested without a DOM:
 *
 * 1. **Not saying everything twice.** A table's text is also present as
 *    ordinary text blocks, because PyMuPDF sees characters, not tables. The
 *    reflowed view therefore drops every block that sits inside a table's
 *    footprint and renders the grid instead; the faithful layout keeps the
 *    blocks and draws the grid as an overlay on top of them.
 * 2. **Reading order.** PyMuPDF's block order follows the content stream,
 *    which on a two-column page can run down one column and back up the other.
 *    Blocks are banded by vertical overlap and read left to right within a
 *    band, with a table always taking a band of its own.
 */

import type { BBox, PageBlock, PageLine, PageSpan, TableDetail } from '@/lib/types'

/** PyMuPDF's packed span style bits. */
export const SPAN_FLAG = {
  superscript: 1,
  italic: 2,
  serif: 4,
  mono: 8,
  bold: 16,
} as const

export type FlowNode =
  | { kind: 'text'; id: string; bbox: BBox; block: PageBlock }
  | { kind: 'image'; id: string; bbox: BBox; block: PageBlock }
  | { kind: 'table'; id: string; bbox: BBox; table: TableDetail }

/** Fraction of a block that must fall inside a table before it is the table's. */
const TABLE_CONTAINMENT = 0.55

/** Vertical slack, in points, before two blocks stop counting as one line. */
const BAND_SLACK = 2

export function area(bbox: BBox): number {
  return Math.max(bbox[2] - bbox[0], 0) * Math.max(bbox[3] - bbox[1], 0)
}

/** Fraction of `inner`'s area that falls inside `outer`. */
export function containment(inner: BBox, outer: BBox): number {
  const width = Math.min(inner[2], outer[2]) - Math.max(inner[0], outer[0])
  const height = Math.min(inner[3], outer[3]) - Math.max(inner[1], outer[1])
  const innerArea = area(inner)
  // A degenerate block - an empty line, a hairline rule - has no area to
  // apportion, so it counts as the table's if it falls within it at all. This
  // is checked before the overlap test, which a zero-area box always fails.
  if (innerArea <= 0) return width >= 0 && height >= 0 ? 1 : 0
  if (width <= 0 || height <= 0) return 0
  return (width * height) / innerArea
}

/** Does this block's text belong to one of the tables rather than to the page? */
export function isInsideTable(
  bbox: BBox,
  tables: { bbox: BBox }[],
  threshold = TABLE_CONTAINMENT,
): boolean {
  return tables.some((table) => containment(bbox, table.bbox) >= threshold)
}

/**
 * Order nodes the way the page reads.
 *
 * Blocks are grouped into horizontal bands: a block joins the open band while
 * it starts before that band's shallowest bottom edge, which keeps captions
 * beside a figure together and still breaks between stacked paragraphs. Within
 * a band, order is left to right. A table opens and closes a band of its own —
 * it is block-level by nature, and letting a full-width grid absorb the
 * paragraphs that follow it would scramble everything after it.
 */
export function readingOrder(nodes: FlowNode[]): FlowNode[] {
  const sorted = [...nodes].sort((a, b) => a.bbox[1] - b.bbox[1] || a.bbox[0] - b.bbox[0])

  const bands: FlowNode[][] = []
  let open: { nodes: FlowNode[]; bottom: number } | null = null

  for (const node of sorted) {
    const blockLevel = node.kind === 'table'
    if (!blockLevel && open && node.bbox[1] < open.bottom - BAND_SLACK) {
      open.nodes.push(node)
      // The band ends where its shallowest member ends, so one tall block
      // cannot swallow the rows below it.
      open.bottom = Math.min(open.bottom, node.bbox[3])
      continue
    }
    const band = [node]
    bands.push(band)
    open = blockLevel ? null : { nodes: band, bottom: node.bbox[3] }
  }

  return bands.flatMap((band) =>
    band.length === 1 ? band : [...band].sort((a, b) => a.bbox[0] - b.bbox[0]),
  )
}

/**
 * The page as an ordered sequence of paragraphs, figures, and tables.
 *
 * `keepTableText` is what separates the two views: the reflowed reading view
 * replaces a table's blocks with the grid, while the faithful layout keeps
 * every block where the PDF drew it and overlays the grid on top.
 */
export function buildPageFlow(
  blocks: PageBlock[],
  tables: TableDetail[],
  { keepTableText = false }: { keepTableText?: boolean } = {},
): FlowNode[] {
  const nodes: FlowNode[] = []

  for (const block of blocks) {
    if (!keepTableText && isInsideTable(block.bbox, tables)) continue
    if (block.type === 'image') {
      nodes.push({ kind: 'image', id: `image-${block.number}`, bbox: block.bbox, block })
      continue
    }
    // A block of nothing but whitespace is structure, not content.
    if (!blockText(block).trim()) continue
    nodes.push({ kind: 'text', id: `block-${block.number}`, bbox: block.bbox, block })
  }

  for (const table of tables) {
    nodes.push({ kind: 'table', id: table.id, bbox: table.bbox, table })
  }

  return readingOrder(nodes)
}

// --- text -------------------------------------------------------------------

export function lineText(line: PageLine): string {
  return line.spans.map((span) => span.text).join('')
}

export function blockText(block: PageBlock): string {
  return (block.lines ?? []).map(lineText).join('\n')
}

export function flowText(nodes: FlowNode[]): string {
  return nodes
    .map((node) => {
      if (node.kind === 'text') return blockText(node.block)
      if (node.kind === 'image') return '[image]'
      return tableTsv(node.table)
    })
    .join('\n\n')
}

/** One table as tab-separated rows — what a spreadsheet expects. */
function tableTsv(table: TableDetail): string {
  const rows: string[][] = Array.from({ length: table.row_count }, () =>
    Array.from({ length: table.column_count }, () => ''),
  )
  for (const cell of table.cells) {
    if (rows[cell.row]) rows[cell.row][cell.column] = cell.text.replace(/[\t\n\r]/g, ' ')
  }
  return rows.map((row) => row.join('\t')).join('\n')
}

export interface TextStyle {
  size: number
  bold: boolean
  italic: boolean
  mono: boolean
}

export function spanStyle(span: PageSpan): TextStyle {
  return {
    size: span.size,
    bold: Boolean(span.flags & SPAN_FLAG.bold),
    italic: Boolean(span.flags & SPAN_FLAG.italic),
    mono: Boolean(span.flags & SPAN_FLAG.mono),
  }
}

/** The span that carries most of a line — what sets the line's own size. */
export function dominantSpan(line: PageLine): PageSpan | null {
  let best: PageSpan | null = null
  for (const span of line.spans) {
    if (!best || span.text.length > best.text.length) best = span
  }
  return best
}

export function lineStyle(line: PageLine): TextStyle {
  const span = dominantSpan(line)
  return span ? spanStyle(span) : { size: 0, bold: false, italic: false, mono: false }
}

/**
 * The page's body text size, weighted by how many characters are set in it.
 *
 * Every relative size decision in the reflowed view is made against this, so a
 * heading is "larger than this page's prose" rather than "larger than 10pt" —
 * the latter would call every line on a 7pt filing schedule a heading.
 */
export function bodyFontSize(blocks: PageBlock[]): number {
  const weight = new Map<number, number>()
  for (const block of blocks) {
    for (const line of block.lines ?? []) {
      for (const span of line.spans) {
        const size = Math.round(span.size * 2) / 2
        const characters = span.text.trim().length
        if (characters) weight.set(size, (weight.get(size) ?? 0) + characters)
      }
    }
  }
  if (!weight.size) return 10

  let common = 10
  let most = -1
  // Ascending, so an exact tie resolves to the smaller size: body text is
  // never the larger of two equally common sizes on a page.
  for (const [size, characters] of [...weight].sort((a, b) => a[0] - b[0])) {
    if (characters > most) {
      most = characters
      common = size
    }
  }
  return common
}

/** Heading levels: 0 is body text, 1 the largest. */
export function headingLevel(block: PageBlock, bodySize: number): 0 | 1 | 2 | 3 {
  const lines = block.lines ?? []
  if (!lines.length || lines.length > 3) return 0
  const style = lineStyle(lines[0])
  const ratio = bodySize > 0 ? style.size / bodySize : 1
  if (ratio >= 1.45) return 1
  if (ratio >= 1.18) return 2
  if (style.bold && ratio >= 0.98) return 3
  return 0
}

export type Alignment = 'left' | 'center' | 'right'

/**
 * How a block sits on the page, from its margins.
 *
 * Only worth reading for a block narrow enough to have been placed: a
 * full-width paragraph is justified by its container, and calling it "centred"
 * because both margins happen to match would centre the page's body text.
 */
export function blockAlignment(bbox: BBox, pageWidth: number, contentBox?: BBox): Alignment {
  const left = contentBox?.[0] ?? 0
  const right = contentBox?.[2] ?? pageWidth
  const width = Math.max(right - left, 1)
  const leftGap = bbox[0] - left
  const rightGap = right - bbox[2]
  if ((bbox[2] - bbox[0]) / width > 0.75) return 'left'

  const skew = (leftGap - rightGap) / width
  if (Math.abs(skew) < 0.05 && leftGap / width > 0.08) return 'center'
  if (skew > 0.25) return 'right'
  return 'left'
}

/** The union of every block's box — the page's own margins, as drawn. */
export function contentBox(blocks: PageBlock[]): BBox | undefined {
  if (!blocks.length) return undefined
  const box: BBox = [Infinity, Infinity, -Infinity, -Infinity]
  for (const block of blocks) {
    box[0] = Math.min(box[0], block.bbox[0])
    box[1] = Math.min(box[1], block.bbox[1])
    box[2] = Math.max(box[2], block.bbox[2])
    box[3] = Math.max(box[3], block.bbox[3])
  }
  return box
}
