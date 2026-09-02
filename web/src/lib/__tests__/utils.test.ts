import { describe, expect, it } from 'vitest'

import { formatRate } from '../utils'

describe('formatRate', () => {
  it('never rounds an imperfect result up to 100%', () => {
    // 519/521 on the real sample. Reporting "100%" here would claim a flawless
    // extraction when two cells did not match.
    expect(formatRate(519 / 521)).toBe('99.6%')
    expect(formatRate(0.9999)).toBe('99.9%')
  })

  it('prints a genuine whole as 100%', () => {
    expect(formatRate(1)).toBe('100%')
  })

  it('drops a trailing zero', () => {
    expect(formatRate(0.9)).toBe('90%')
    expect(formatRate(0.5)).toBe('50%')
  })

  it('handles zero', () => {
    expect(formatRate(0)).toBe('0%')
  })
})
