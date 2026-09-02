/** Fixtures shaped like the real nl-1.pdf extraction. */

import type { PageGeometry, TableCell, TableDetail, TableSummary } from '@/lib/types'

export const geometry: PageGeometry = {
  width: 841.68,
  height: 595.2,
  rotation: 0,
  mediabox: [0, 0, 841.68, 595.2],
}

export function makeCell(overrides: Partial<TableCell> = {}): TableCell {
  const text = overrides.text ?? 'value'
  return {
    row: 0,
    column: 0,
    row_span: 1,
    column_span: 1,
    kind: 'content',
    text,
    azure_text: text,
    pymupdf_text: text,
    bbox: [10, 10, 60, 25],
    confidence: 0.99,
    text_source: {
      source: 'pymupdf',
      matched: true,
      method: 'exact',
      containment: 1,
      iou: 0.4,
      bbox: [12, 12, 55, 22],
      word_count: 1,
    },
    ...overrides,
  }
}

/** A 3x3 table: one header row, then two body rows of financial values. */
export function makeTable(overrides: Partial<TableDetail> = {}): TableDetail {
  const headers = ['Particulars', 'For Q1 2026-27', 'Upto Q1 2026-27']
  const rows = [
    ['Premiums earned (Net)', '11,149', '14,168'],
    ['Investment income', '-', '1,25,000'],
  ]

  const cells: TableCell[] = [
    ...headers.map((text, column) =>
      makeCell({
        row: 0,
        column,
        text,
        kind: 'columnHeader',
        bbox: [column * 100, 0, (column + 1) * 100, 20],
      }),
    ),
    ...rows.flatMap((row, rowIndex) =>
      row.map((text, column) =>
        makeCell({
          row: rowIndex + 1,
          column,
          text,
          bbox: [column * 100, (rowIndex + 1) * 20, (column + 1) * 100, (rowIndex + 2) * 20],
        }),
      ),
    ),
  ]

  return {
    id: 'table_1',
    page_number: 1,
    source: 'azure_di',
    bbox: [0, 0, 300, 60],
    row_count: 3,
    column_count: 3,
    caption: null,
    confidence: 0.99,
    continues_table_id: null,
    cell_count: cells.length,
    cells,
    ...overrides,
  }
}

export const tableSummary: TableSummary = {
  id: 'table_1',
  page_number: 4,
  source: 'azure_di',
  bbox: [50, 200, 550, 500],
  row_count: 3,
  column_count: 3,
  caption: null,
  confidence: 0.99,
  continues_table_id: null,
  cell_count: 9,
}
