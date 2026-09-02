import { describe, expect, it } from 'vitest'

import { BOLD, makeBlock, makeSpan, makeTable } from '@/test/fixtures'
import type { PageBlock } from '@/lib/types'
import {
  blockAlignment,
  blockText,
  bodyFontSize,
  buildPageFlow,
  containment,
  contentBox,
  flowText,
  headingLevel,
  isInsideTable,
  lineStyle,
  readingOrder,
} from '../pageFlow'

/** A table across the middle of the page, matching `makeTable`'s footprint. */
const table = makeTable({ bbox: [50, 200, 550, 400] })

describe('containment', () => {
  it('reports the fraction of the inner box that falls inside the outer one', () => {
    expect(containment([0, 0, 10, 10], [0, 0, 20, 20])).toBe(1)
    expect(containment([0, 0, 10, 10], [5, 0, 20, 20])).toBeCloseTo(0.5)
    expect(containment([0, 0, 10, 10], [50, 50, 60, 60])).toBe(0)
  })

  it('treats a zero-area box as contained when it touches', () => {
    expect(containment([5, 5, 5, 5], [0, 0, 20, 20])).toBe(1)
  })
})

describe('isInsideTable', () => {
  it('claims a block that sits within the table', () => {
    expect(isInsideTable([60, 210, 200, 225], [table])).toBe(true)
  })

  it('leaves a caption just above the table alone', () => {
    expect(isInsideTable([50, 180, 300, 196], [table])).toBe(false)
  })

  it('leaves a block that only clips the table edge alone', () => {
    // Three quarters of this block is above the table's top edge.
    expect(isInsideTable([60, 185, 200, 205], [table])).toBe(false)
  })
})

describe('buildPageFlow', () => {
  const heading = makeBlock(0, 'Schedule 1', [50, 40, 300, 60])
  const insideTable = makeBlock(1, 'Premiums earned (Net)', [60, 210, 200, 225])
  const footnote = makeBlock(2, 'Figures in thousands', [50, 420, 300, 435])

  it('replaces a table’s own text blocks with the table', () => {
    const nodes = buildPageFlow([heading, insideTable, footnote], [table])
    expect(nodes.map((node) => node.kind)).toEqual(['text', 'table', 'text'])
    expect(nodes.map((node) => node.id)).toEqual(['block-0', 'table_1', 'block-2'])
  })

  it('keeps the text under the table for the faithful layout', () => {
    const nodes = buildPageFlow([heading, insideTable, footnote], [table], {
      keepTableText: true,
    })
    expect(nodes.map((node) => node.id)).toContain('block-1')
  })

  it('drops a block that holds only whitespace', () => {
    const blank = makeBlock(3, '   ', [50, 500, 300, 515])
    const nodes = buildPageFlow([heading, blank], [])
    expect(nodes).toHaveLength(1)
  })

  it('keeps an image block as a placeholder', () => {
    const image: PageBlock = { number: 4, type: 'image', bbox: [400, 40, 500, 120] }
    const nodes = buildPageFlow([image], [])
    expect(nodes[0].kind).toBe('image')
  })

  it('renders the page as text with the table tabbed out', () => {
    const text = flowText(buildPageFlow([heading, insideTable, footnote], [table]))
    expect(text.startsWith('Schedule 1')).toBe(true)
    expect(text).toContain('Particulars\tFor Q1 2026-27\tUpto Q1 2026-27')
    expect(text.endsWith('Figures in thousands')).toBe(true)
  })
})

describe('readingOrder', () => {
  it('reads two columns of the same line left to right', () => {
    // PyMuPDF emitted the right-hand block first.
    const right = makeBlock(0, 'right', [400, 100, 500, 115])
    const left = makeBlock(1, 'left', [50, 101, 150, 116])
    const nodes = readingOrder(buildPageFlow([right, left], []))
    expect(nodes.map((node) => blockText((node as { block: PageBlock }).block))).toEqual([
      'left',
      'right',
    ])
  })

  it('does not let a tall block swallow the rows beneath it', () => {
    const tall = makeBlock(0, 'tall', [50, 100, 150, 400])
    const beside = makeBlock(1, 'beside', [200, 105, 300, 120])
    const below = makeBlock(2, 'below', [200, 300, 300, 315])
    const nodes = readingOrder(buildPageFlow([tall, beside, below], []))
    expect(nodes.map((node) => blockText((node as { block: PageBlock }).block))).toEqual([
      'tall',
      'beside',
      'below',
    ])
  })

  it('gives a table a band of its own', () => {
    // This note starts just above the table and overlaps it vertically, so a
    // plain band would absorb the table and then sort it ahead of the note on
    // x - putting a 500pt-wide grid before the line that introduces it.
    const note = makeBlock(0, 'note', [600, 190, 700, 205])
    const after = makeBlock(1, 'after', [50, 420, 300, 435])
    const nodes = buildPageFlow([note, after], [table])
    expect(nodes.map((node) => node.id)).toEqual(['block-0', 'table_1', 'block-1'])
  })
})

describe('bodyFontSize', () => {
  it('takes the size most of the characters are set in, not the largest', () => {
    const title = makeBlock(0, 'TITLE', [50, 40, 300, 70], { size: 22 })
    const body = [
      makeBlock(1, 'a paragraph of ordinary prose', [50, 100, 400, 112], { size: 9 }),
      makeBlock(2, 'and a second one just like it', [50, 120, 400, 132], { size: 9 }),
    ]
    expect(bodyFontSize([title, ...body])).toBe(9)
  })

  it('falls back to 10pt for a page with no text', () => {
    expect(bodyFontSize([])).toBe(10)
  })
})

describe('headingLevel', () => {
  const body = 9

  it('grades by size against the page’s own body text', () => {
    expect(headingLevel(makeBlock(0, 'Big', [0, 0, 10, 10], { size: 20 }), body)).toBe(1)
    expect(headingLevel(makeBlock(0, 'Medium', [0, 0, 10, 10], { size: 11 }), body)).toBe(2)
  })

  it('treats body-size bold as the lightest heading', () => {
    expect(headingLevel(makeBlock(0, 'Bold', [0, 0, 10, 10], { flags: BOLD }), body)).toBe(3)
  })

  it('leaves ordinary prose as body text', () => {
    expect(headingLevel(makeBlock(0, 'prose', [0, 0, 10, 10]), body)).toBe(0)
  })

  it('never calls a long passage a heading', () => {
    const long: PageBlock = {
      number: 0,
      type: 'text',
      bbox: [0, 0, 100, 100],
      lines: Array.from({ length: 6 }, (_, index) => ({
        bbox: [0, index * 12, 100, index * 12 + 10] as [number, number, number, number],
        direction: [1, 0] as [number, number],
        spans: [makeSpan('a line of prose', { size: 20 })],
      })),
    }
    expect(headingLevel(long, body)).toBe(0)
  })
})

describe('lineStyle', () => {
  it('takes its size from the span carrying most of the line', () => {
    const line = {
      bbox: [0, 0, 100, 12] as [number, number, number, number],
      direction: [1, 0] as [number, number],
      spans: [makeSpan('1', { size: 6 }), makeSpan('a much longer run', { size: 11, flags: BOLD })],
    }
    expect(lineStyle(line)).toMatchObject({ size: 11, bold: true })
  })
})

describe('blockAlignment', () => {
  const margins = contentBox([makeBlock(0, 'x', [50, 0, 550, 10])])

  it('centres a narrow block with matching margins', () => {
    expect(blockAlignment([230, 40, 370, 60], 600, margins)).toBe('center')
  })

  it('leaves a full-width paragraph alone', () => {
    // Its margins match too, but it fills the measure - it was not placed.
    expect(blockAlignment([50, 40, 550, 60], 600, margins)).toBe('left')
  })

  it('reads a block pushed to the right margin as right-aligned', () => {
    expect(blockAlignment([460, 40, 550, 60], 600, margins)).toBe('right')
  })
})

describe('contentBox', () => {
  it('is the union of every block', () => {
    expect(
      contentBox([makeBlock(0, 'a', [50, 40, 300, 60]), makeBlock(1, 'b', [80, 500, 560, 520])]),
    ).toEqual([50, 40, 560, 520])
  })

  it('is undefined for a blank page', () => {
    expect(contentBox([])).toBeUndefined()
  })
})
