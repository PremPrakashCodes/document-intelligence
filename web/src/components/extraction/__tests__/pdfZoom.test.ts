import { describe, expect, it } from 'vitest'

import { geometry } from '@/test/fixtures'
import { centerOn, fitPageScale, followScale, snapRenderScale } from '../pdfZoom'

// The half-screen pane the viewer actually gets on a laptop.
const PANE = { width: 740, height: 620 }

describe('fitPageScale', () => {
  it('reproduces the unreadable scale that motivated follow mode', () => {
    // 842pt landscape page in a half pane renders below 72 dpi: a 7pt figure
    // lands about six pixels tall.
    expect(fitPageScale(geometry, PANE)).toBeCloseTo(0.879, 2)
  })

  it('is bounded by whichever axis runs out first', () => {
    expect(fitPageScale(geometry, { width: 10_000, height: 595 })).toBeCloseTo(1, 1)
  })

  it('survives a pane that has not been measured yet', () => {
    expect(fitPageScale(geometry, { width: 0, height: 0 })).toBe(1)
  })
})

describe('followScale', () => {
  it('makes a small numeric cell genuinely readable', () => {
    // A real cell from nl-1.pdf: 31pt wide, 7pt tall.
    const scale = followScale([265.3, 154.5, 296.3, 161.9], PANE)
    expect(scale).toBeGreaterThanOrEqual(3)
    // 7pt of type at this scale is >20 CSS px.
    expect(7 * scale).toBeGreaterThan(20)
  })

  it('is far more magnified than fitting the whole page', () => {
    const cell: [number, number, number, number] = [265.3, 154.5, 296.3, 161.9]
    expect(followScale(cell, PANE)).toBeGreaterThan(fitPageScale(geometry, PANE) * 3)
  })

  it('keeps context around the cell rather than filling the pane with it', () => {
    // Framing a 31pt cell edge to edge would be ~24x and strand the reader with
    // no neighbouring row or column labels.
    expect(followScale([265.3, 154.5, 296.3, 161.9], PANE)).toBeLessThan(8)
  })

  it('does not zoom past the ceiling for a one-character cell', () => {
    const dash = followScale([397.9, 200.4, 399.9, 207.5], PANE)
    expect(dash).toBeLessThanOrEqual(6)
    expect(dash).toBeGreaterThan(1)
  })

  it('zooms out for a whole table rather than in', () => {
    const table = followScale([28.8, 111.3, 810.9, 370.5], PANE)
    const cell = followScale([265.3, 154.5, 296.3, 161.9], PANE)
    expect(table).toBeLessThan(cell)
  })

  it('survives an unmeasured pane', () => {
    expect(followScale([0, 0, 10, 10], { width: 0, height: 0 })).toBe(1)
  })
})

describe('snapRenderScale', () => {
  it('rounds up to a ladder step so renders are cacheable', () => {
    expect(snapRenderScale(1.2)).toBe(1.5)
    expect(snapRenderScale(2.0)).toBe(2)
    expect(snapRenderScale(3.4)).toBe(4)
  })

  it('never exceeds what the API accepts', () => {
    expect(snapRenderScale(99)).toBe(6)
  })
})

describe('centerOn', () => {
  it('centres the region in the pane', () => {
    const { left, top } = centerOn([400, 300, 440, 320], geometry, 2, PANE)
    // Centre of the box is (420, 310) in points, so (840, 620) at scale 2.
    expect(left).toBeCloseTo(840 - PANE.width / 2, 0)
    expect(top).toBeCloseTo(620 - PANE.height / 2, 0)
  })

  it('never scrolls past the start of the page', () => {
    const { left, top } = centerOn([0, 0, 10, 10], geometry, 2, PANE)
    expect(left).toBe(0)
    expect(top).toBe(0)
  })

  it('never scrolls past the end of the page', () => {
    const { left } = centerOn([830, 580, 842, 595], geometry, 2, PANE)
    expect(left).toBeLessThanOrEqual(geometry.width * 2 - PANE.width)
  })
})
