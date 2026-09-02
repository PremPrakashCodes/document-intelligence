import { describe, expect, it } from 'vitest'

import { makeCell, makeTable } from '@/test/fixtures'
import {
  buildGrid,
  columnGroups,
  findMatches,
  groupIndexByColumn,
  headerRowCount,
  rowValues,
  sortRowIndices,
  stubColumnCount,
  stubLayout,
  toNumber,
  toTsv,
  unverifiedCells,
} from '../tableGrid'

describe('buildGrid', () => {
  it('places each cell at its own row and column', () => {
    const grid = buildGrid(makeTable())
    expect(grid.rows).toBe(3)
    expect(grid.columns).toBe(3)
    expect(grid.origins[0][0]?.text).toBe('Particulars')
    expect(grid.origins[1][1]?.text).toBe('11,149')
  })

  it('marks the positions a span covers so they are not rendered twice', () => {
    // Azure emits only the origin cell and describes coverage with spans; the
    // covered positions have to be derived or the grid comes out with holes.
    const table = makeTable({
      row_count: 2,
      column_count: 3,
      cells: [
        makeCell({ row: 0, column: 0, column_span: 3, text: 'Fire' }),
        makeCell({ row: 1, column: 0, text: 'a' }),
        makeCell({ row: 1, column: 1, text: 'b' }),
        makeCell({ row: 1, column: 2, text: 'c' }),
      ],
    })
    const grid = buildGrid(table)
    expect(grid.origins[0][0]?.text).toBe('Fire')
    expect(grid.covered[0][1]).toBe(true)
    expect(grid.covered[0][2]).toBe(true)
    expect(grid.covered[1][0]).toBe(false)
  })

  it('handles a row span', () => {
    const table = makeTable({
      row_count: 3,
      column_count: 2,
      cells: [makeCell({ row: 0, column: 0, row_span: 2, text: 'tall' })],
    })
    const grid = buildGrid(table)
    expect(grid.covered[1][0]).toBe(true)
    expect(grid.covered[2][0]).toBe(false)
  })

  it('grows to fit a cell that overflows the declared counts', () => {
    const table = makeTable({
      row_count: 1,
      column_count: 1,
      cells: [makeCell({ row: 3, column: 4, text: 'far' })],
    })
    const grid = buildGrid(table)
    expect(grid.rows).toBe(4)
    expect(grid.columns).toBe(5)
  })

  it('copes with an empty table', () => {
    const grid = buildGrid({ cells: [], row_count: 0, column_count: 0 })
    expect(grid.rows).toBe(0)
    expect(grid.columns).toBe(0)
  })
})

describe('headerRowCount', () => {
  it('counts the leading run of header rows', () => {
    expect(headerRowCount(makeTable())).toBe(1)
  })

  it('is zero when Azure marked no headers', () => {
    const table = makeTable()
    expect(headerRowCount({ cells: table.cells.map((c) => ({ ...c, kind: 'content' })) })).toBe(0)
  })

  it('counts two stacked header rows', () => {
    const cells = [
      makeCell({ row: 0, column: 0, kind: 'columnHeader' }),
      makeCell({ row: 1, column: 0, kind: 'columnHeader' }),
      makeCell({ row: 2, column: 0 }),
    ]
    expect(headerRowCount({ cells })).toBe(2)
  })
})

describe('toNumber', () => {
  it.each([
    ['11,149', 11149],
    ['1,25,000', 125000],
    ['₹25,000', 25000],
    ['566,986', 566986],
    ['(1,234)', -1234],
    ['12.5', 12.5],
  ])('parses %s', (input, expected) => {
    expect(toNumber(input)).toBe(expected)
  })

  it.each(['-', '', '  ', 'Premiums earned (Net)', 'NL-4'])('rejects %s', (input) => {
    expect(toNumber(input)).toBeNull()
  })
})

describe('sortRowIndices', () => {
  const origins = [
    [makeCell({ text: 'header' })],
    [makeCell({ text: '11,149' })],
    [makeCell({ text: '1,25,000' })],
    [makeCell({ text: '-' })],
    [makeCell({ text: '566' })],
  ]

  it('sorts financial values numerically, not as strings', () => {
    // A string sort would put "1,25,000" before "566".
    const sorted = sortRowIndices([1, 2, 3, 4], origins, 0, 'asc')
    expect(sorted.slice(0, 3)).toEqual([4, 1, 2])
  })

  it('reverses on desc', () => {
    expect(sortRowIndices([1, 2, 4], origins, 0, 'desc')).toEqual([2, 1, 4])
  })

  it('sinks nil markers whichever way the column is sorted', () => {
    expect(sortRowIndices([1, 2, 3, 4], origins, 0, 'asc').at(-1)).toBe(3)
    expect(sortRowIndices([1, 2, 3, 4], origins, 0, 'desc').at(-1)).toBe(3)
  })

  it('does not mutate the input order', () => {
    const rows = [1, 2, 3, 4]
    sortRowIndices(rows, origins, 0, 'asc')
    expect(rows).toEqual([1, 2, 3, 4])
  })
})

describe('search', () => {
  it('finds cells case-insensitively, in grid order', () => {
    const matches = findMatches(makeTable().cells, 'q1')
    expect(matches.map((c) => c.text)).toEqual(['For Q1 2026-27', 'Upto Q1 2026-27'])
  })

  it('returns nothing for a blank query', () => {
    expect(findMatches(makeTable().cells, '   ')).toEqual([])
  })
})

describe('clipboard export', () => {
  it('renders rows as TSV', () => {
    const grid = buildGrid(makeTable())
    expect(rowValues(grid.origins, 1, 3)).toEqual(['Premiums earned (Net)', '11,149', '14,168'])
    expect(toTsv([['a', 'b'], ['c', 'd']])).toBe('a\tb\nc\td')
  })

  it('neutralises tabs and newlines inside a value', () => {
    // Otherwise one cell containing a tab would silently shift every column
    // to its right when pasted into a spreadsheet.
    expect(toTsv([['a\tb', 'c\nd']])).toBe('a b\tc d')
  })
})

describe('stubColumnCount', () => {
  it('takes the columns before the first group header span', () => {
    // How nl-1.pdf reads: [blank][Particulars][Schedule Ref.][Fire x4][Marine x4]
    const table = makeTable({
      row_count: 2,
      column_count: 7,
      cells: [
        makeCell({ row: 0, column: 0, text: '', kind: 'columnHeader' }),
        makeCell({ row: 0, column: 1, text: 'Particulars', kind: 'columnHeader' }),
        makeCell({ row: 0, column: 2, text: 'Schedule Ref.', kind: 'columnHeader' }),
        makeCell({ row: 0, column: 3, text: 'Fire', column_span: 2, kind: 'columnHeader' }),
        makeCell({ row: 0, column: 5, text: 'Marine', column_span: 2, kind: 'columnHeader' }),
      ],
    })
    expect(stubColumnCount(table)).toBe(3)
  })

  it('falls back to the leading non-numeric columns when there are no spans', () => {
    expect(stubColumnCount(makeTable())).toBe(1)
  })

  it('treats a column of nil dashes and figures as a measure column', () => {
    // Counting "-" as non-numeric would misfile the column as a row label and
    // wrongly pin it to the left edge.
    const table = makeTable({
      row_count: 3,
      column_count: 2,
      cells: [
        makeCell({ row: 0, column: 0, text: 'Particulars', kind: 'columnHeader' }),
        makeCell({ row: 0, column: 1, text: 'Amount', kind: 'columnHeader' }),
        makeCell({ row: 1, column: 0, text: 'Premiums' }),
        makeCell({ row: 1, column: 1, text: '-' }),
        makeCell({ row: 2, column: 0, text: 'Claims' }),
        makeCell({ row: 2, column: 1, text: '11,149' }),
      ],
    })
    expect(stubColumnCount(table)).toBe(1)
  })

  it('never pins the whole table', () => {
    const table = makeTable({
      row_count: 2,
      column_count: 2,
      cells: [
        makeCell({ row: 0, column: 0, text: 'a', kind: 'columnHeader' }),
        makeCell({ row: 1, column: 0, text: 'x' }),
        makeCell({ row: 1, column: 1, text: 'y' }),
      ],
    })
    expect(stubColumnCount(table)).toBeLessThan(2)
  })
})

describe('columnGroups', () => {
  const table = makeTable({
    row_count: 2,
    column_count: 7,
    cells: [
      makeCell({ row: 0, column: 0, text: '', kind: 'columnHeader' }),
      makeCell({ row: 0, column: 1, text: 'Particulars', kind: 'columnHeader' }),
      makeCell({ row: 0, column: 2, text: 'Schedule', kind: 'columnHeader' }),
      makeCell({ row: 0, column: 3, text: 'Fire', column_span: 2, kind: 'columnHeader' }),
      makeCell({ row: 0, column: 5, text: 'Marine', column_span: 2, kind: 'columnHeader' }),
    ],
  })

  it('reads the groups off the header spans', () => {
    expect(columnGroups(table, 3).map((g) => [g.label, g.start, g.end])).toEqual([
      ['Fire', 3, 5],
      ['Marine', 5, 7],
    ])
  })

  it('maps every column to its group, leaving the stub ungrouped', () => {
    const groups = columnGroups(table, 3)
    expect(groupIndexByColumn(groups, 7)).toEqual([-1, -1, -1, 0, 0, 1, 1])
  })
})

describe('stubLayout', () => {
  it('stacks the pinned columns left to right after the gutter', () => {
    const grid = buildGrid(makeTable())
    const layout = stubLayout(grid.origins, 2, 36)
    expect(layout[0].left).toBe(36)
    expect(layout[1].left).toBe(36 + layout[0].width)
  })

  it('keeps a long wrapping label from pinning a huge column', () => {
    const grid = buildGrid(
      makeTable({
        row_count: 2,
        column_count: 1,
        cells: [makeCell({ row: 1, column: 0, text: 'Profit/ Loss on sale of Investments etc' })],
      }),
    )
    expect(stubLayout(grid.origins, 1, 36)[0].width).toBeLessThanOrEqual(220)
  })
})

describe('unverifiedCells', () => {
  it('lists populated cells the PDF text layer could not confirm', () => {
    const azure = {
      source: 'azure_di' as const,
      matched: false,
      method: 'none' as const,
      containment: 0,
      iou: 0,
      bbox: null,
      word_count: 0,
    }
    const cells = [
      makeCell({ row: 0, column: 0, text: 'ok' }),
      makeCell({ row: 1, column: 0, text: ':unselected:', text_source: azure }),
      // Empty cells are not review work.
      makeCell({ row: 2, column: 0, text: '', text_source: azure }),
    ]
    expect(unverifiedCells(cells).map((c) => c.text)).toEqual([':unselected:'])
  })
})
