/**
 * Turning a flat cell list into a grid, and the copy/search helpers over it.
 *
 * Kept out of the component so the logic that matters — span expansion,
 * search, and TSV export — is testable without rendering anything.
 */

import type { TableCell, TableDetail } from '@/lib/types'

/** A grid position, which may be covered by a span from above or to the left. */
export type GridSlot = { cell: TableCell; rowIndex: number } | null

/**
 * Lay cells out on a dense `row_count × column_count` grid.
 *
 * Azure emits one entry per *origin* cell and describes coverage with
 * `row_span`/`column_span`; it does not emit the covered positions. Rendering
 * straight from the list would leave holes, so spans are expanded here and the
 * covered slots marked, letting the renderer skip them while the browser's own
 * `rowSpan`/`colSpan` does the visual work.
 */
export function buildGrid(table: Pick<TableDetail, 'cells' | 'row_count' | 'column_count'>) {
  const rows = Math.max(table.row_count, ...table.cells.map((c) => c.row + c.row_span), 0)
  const columns = Math.max(table.column_count, ...table.cells.map((c) => c.column + c.column_span), 0)

  const origins: (TableCell | null)[][] = Array.from({ length: rows }, () =>
    Array.from({ length: columns }, () => null),
  )
  const covered: boolean[][] = Array.from({ length: rows }, () =>
    Array.from({ length: columns }, () => false),
  )

  for (const cell of table.cells) {
    if (cell.row >= rows || cell.column >= columns) continue
    origins[cell.row][cell.column] = cell
    for (let r = cell.row; r < Math.min(cell.row + cell.row_span, rows); r++) {
      for (let c = cell.column; c < Math.min(cell.column + cell.column_span, columns); c++) {
        if (r !== cell.row || c !== cell.column) covered[r][c] = true
      }
    }
  }

  return { rows, columns, origins, covered }
}

/** Rows Azure marked as headers — always the leading run, if any. */
export function headerRowCount(table: Pick<TableDetail, 'cells'>): number {
  const headerRows = new Set(
    table.cells.filter((cell) => cell.kind === 'columnHeader').map((cell) => cell.row),
  )
  let count = 0
  while (headerRows.has(count)) count += 1
  return count
}

export function cellKey(cell: Pick<TableCell, 'row' | 'column'>): string {
  return `${cell.row}:${cell.column}`
}

/** Case-insensitive substring match over the chosen text. */
export function matchesQuery(cell: TableCell, query: string): boolean {
  if (!query) return false
  return cell.text.toLowerCase().includes(query.toLowerCase())
}

export function findMatches(cells: TableCell[], query: string): TableCell[] {
  if (!query.trim()) return []
  return cells
    .filter((cell) => matchesQuery(cell, query))
    .sort((a, b) => a.row - b.row || a.column - b.column)
}

export function toNumber(text: string): number | null {
  const trimmed = text.trim()
  if (!trimmed || trimmed === '-' || trimmed === '—') return null
  // Strip currency symbols, digit grouping, and surrounding parentheses, which
  // filings use for negatives.
  const negative = /^\(.*\)$/.test(trimmed)
  const cleaned = trimmed.replace(/[()]/g, '').replace(/[₹$€£,\s]/g, '')
  if (!/^-?\d*\.?\d+$/.test(cleaned)) return null
  const parsed = Number(cleaned)
  if (Number.isNaN(parsed)) return null
  return negative ? -parsed : parsed
}

/** Tab-separated text — what spreadsheets expect on the clipboard. */
export function toTsv(rows: string[][]): string {
  return rows
    .map((row) => row.map((value) => value.replace(/[\t\n\r]/g, ' ')).join('\t'))
    .join('\n')
}

export function rowValues(origins: (TableCell | null)[][], rowIndex: number, columns: number): string[] {
  return Array.from({ length: columns }, (_, column) => origins[rowIndex]?.[column]?.text ?? '')
}

export function tableValues(
  origins: (TableCell | null)[][],
  rows: number,
  columns: number,
): string[][] {
  return Array.from({ length: rows }, (_, row) => rowValues(origins, row, columns))
}

/**
 * How many leading columns are the table's stub — the labels that identify a
 * row rather than measure it.
 *
 * Derived from Azure's own structure rather than guessed from the values: the
 * stub is everything to the left of the first *spanning* group header. In
 * In the sample document the header row reads `[blank] [Particulars] [Schedule Ref.] [Fire
 * ×4] [Marine ×4] …`, so the first span sits at column 3 and the stub is three
 * columns wide — exactly the columns that must stay pinned when you scroll
 * nineteen columns to the right.
 *
 * Falls back to the leading run of non-numeric columns when a table has no
 * spanning headers, and never claims more than half the table.
 */
export function stubColumnCount(
  table: Pick<TableDetail, 'cells' | 'row_count' | 'column_count'>,
): number {
  const columns = Math.max(table.column_count, 1)
  const ceiling = Math.max(0, Math.min(3, columns - 1))

  const firstSpan = table.cells
    .filter((cell) => cell.row === 0 && cell.column_span > 1)
    .sort((a, b) => a.column - b.column)[0]
  if (firstSpan && firstSpan.column > 0) return Math.min(firstSpan.column, ceiling)

  // No group headers: take the leading columns whose body values are not
  // figures, which is what a stub is in practice.
  let count = 0
  while (count < ceiling && !isMeasureColumn(table.cells, count)) count += 1
  return count
}

/** Nil markers stand in for a figure, so they are not evidence of a label. */
const NIL_MARKERS = new Set(['', '-', '\u2014', '\u2013', 'nil', 'NIL'])

function isMeasureColumn(cells: TableCell[], column: number): boolean {
  // Blanks and nil markers are excluded from the sample rather than counted
  // against it: a column that is mostly dashes with a few figures is still a
  // measure column, and counting the dashes as non-numeric would misfile it as
  // a row label and wrongly pin it.
  const body = cells.filter(
    (cell) =>
      cell.column === column &&
      cell.kind !== 'columnHeader' &&
      !NIL_MARKERS.has(cell.text.trim()),
  )
  if (!body.length) return false
  const numeric = body.filter((cell) => toNumber(cell.text) !== null).length
  return numeric / body.length > 0.6
}

export interface ColumnGroup {
  label: string
  start: number
  /** Exclusive. */
  end: number
  index: number
}

/**
 * The column groups Azure found, from the spans in the first header row.
 *
 * These are real structure — `Fire`, `Marine`, `Miscellaneous`, `Total`, each
 * covering four period columns — so banding them apart is encoding the
 * table's own shape, not decorating it. Without the banding, nineteen columns
 * of near-identical figures read as one undifferentiated wall.
 */
export function columnGroups(
  table: Pick<TableDetail, 'cells' | 'column_count'>,
  stubColumns: number,
): ColumnGroup[] {
  return table.cells
    .filter((cell) => cell.row === 0 && cell.column >= stubColumns && cell.text.trim() !== '')
    .sort((a, b) => a.column - b.column)
    .map((cell, index) => ({
      label: cell.text,
      start: cell.column,
      end: cell.column + Math.max(cell.column_span, 1),
      index,
    }))
}

/** Group index for each column, or -1 for stub and ungrouped columns. */
export function groupIndexByColumn(groups: ColumnGroup[], columns: number): number[] {
  const result = Array.from({ length: columns }, () => -1)
  for (const group of groups) {
    for (let column = group.start; column < Math.min(group.end, columns); column++) {
      result[column] = group.index
    }
  }
  return result
}

/**
 * Fixed widths and left offsets for the pinned stub columns.
 *
 * Sticky positioning needs each pinned column's offset up front, and offsets
 * can only be summed if the widths are known, so stub widths are computed from
 * their content instead of left to the browser's auto layout.
 */
export function stubLayout(
  origins: (TableCell | null)[][],
  stubColumns: number,
  gutterWidth: number,
): { column: number; width: number; left: number }[] {
  const layout: { column: number; width: number; left: number }[] = []
  let left = gutterWidth

  for (let column = 0; column < stubColumns; column++) {
    const longest = origins.reduce((max, row) => {
      const text = row?.[column]?.text ?? ''
      // Long labels wrap, so width tracks the longest *word*, not the whole
      // string — otherwise "Profit/ Loss on sale/redemption of Investments"
      // would pin a 400px column.
      const word = text.split(/\s+/).reduce((a, b) => (b.length > a.length ? b : a), '')
      return Math.max(max, Math.min(text.length, word.length + 6))
    }, 0)
    const width = Math.round(Math.min(Math.max(longest * 7 + 20, 52), 220))
    layout.push({ column, width, left })
    left += width
  }
  return layout
}

/** Populated cells whose text was not confirmed against the PDF text layer. */
export function unverifiedCells(cells: TableCell[]): TableCell[] {
  return cells
    .filter(
      (cell) =>
        cell.text.trim() !== '' && cell.text_source.source === 'azure_di',
    )
    .sort((a, b) => a.row - b.row || a.column - b.column)
}
