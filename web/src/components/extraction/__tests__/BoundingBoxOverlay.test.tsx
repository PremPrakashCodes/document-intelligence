import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { geometry } from '@/test/fixtures'
import { BoundingBoxOverlay, toPercentRect } from '../BoundingBoxOverlay'

describe('toPercentRect', () => {
  it('expresses a box as a fraction of the page, not in pixels', () => {
    // Percentages are exact at any zoom. Multiplying by the render scale would
    // drift, because PyMuPDF rounds pixmap dimensions up to whole pixels.
    const rect = toPercentRect([0, 0, 420.84, 297.6], geometry)
    expect(rect).toEqual({ left: '0%', top: '0%', width: '50%', height: '50%' })
  })

  it('places a box at the far corner without overflowing', () => {
    const rect = toPercentRect([841.68, 595.2, 841.68, 595.2], geometry)
    expect(rect.left).toBe('100%')
    expect(rect.top).toBe('100%')
  })

  it('is independent of the display size of the image', () => {
    const box: [number, number, number, number] = [100, 50, 200, 100]
    expect(toPercentRect(box, geometry)).toEqual(
      toPercentRect(box, { ...geometry }),
    )
  })
})

describe('BoundingBoxOverlay', () => {
  it('renders one element per box, keyed by kind', () => {
    render(
      <BoundingBoxOverlay
        geometry={geometry}
        boxes={[
          { id: 't', bbox: [0, 0, 100, 100], kind: 'table', label: 'table_1' },
          { id: 'c', bbox: [10, 10, 50, 30], kind: 'cell', active: true },
          { id: 'x', bbox: [12, 12, 40, 25], kind: 'text', active: true },
        ]}
      />,
    )
    expect(screen.getByTestId('overlay-table')).toBeInTheDocument()
    expect(screen.getByTestId('overlay-cell')).toHaveAttribute('data-active', 'true')
    expect(screen.getByTestId('overlay-text')).toBeInTheDocument()
    expect(screen.getByText('table_1')).toBeInTheDocument()
  })

  it('renders nothing when there is nothing to highlight', () => {
    const { container } = render(<BoundingBoxOverlay geometry={geometry} boxes={[]} />)
    expect(container.querySelectorAll('[data-testid^="overlay-"]')).toHaveLength(0)
  })

  it('positions a box from its bbox', () => {
    render(
      <BoundingBoxOverlay
        geometry={geometry}
        boxes={[{ id: 'c', bbox: [420.84, 0, 841.68, 297.6], kind: 'cell' }]}
      />,
    )
    expect(screen.getByTestId('overlay-cell')).toHaveStyle({ left: '50%', width: '50%' })
  })
})
