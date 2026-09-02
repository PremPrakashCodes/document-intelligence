import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { makeCell, tableSummary } from '@/test/fixtures'
import { CellDetails } from '../CellDetails'
import { ConfidenceIndicator, confidenceTone } from '../ConfidenceIndicator'
import { ExtractionSourceBadge } from '../ExtractionSourceBadge'

const wrap = (ui: React.ReactNode) => render(<TooltipProvider>{ui}</TooltipProvider>)

describe('confidenceTone', () => {
  it.each([
    [null, 'none'],
    [0.99, 'good'],
    [0.9, 'good'],
    [0.85, 'low'],
    [0.5, 'poor'],
  ])('%s is %s', (confidence, expected) => {
    expect(confidenceTone(confidence as number | null)).toBe(expected)
  })
})

describe('ConfidenceIndicator', () => {
  it('shows a percentage when asked', () => {
    wrap(<ConfidenceIndicator confidence={0.973} showValue />)
    expect(screen.getByText('97%')).toBeInTheDocument()
  })

  it('says "not reported" rather than implying zero', () => {
    // Born-digital PDFs often carry no per-word confidence; reporting 0% would
    // be a lie about the extraction quality.
    wrap(<ConfidenceIndicator confidence={null} />)
    expect(screen.getByText('not reported')).toBeInTheDocument()
  })

  it('exposes the value to assistive technology', () => {
    wrap(<ConfidenceIndicator confidence={0.42} />)
    expect(screen.getByLabelText('Confidence 42%')).toBeInTheDocument()
  })
})

describe('ExtractionSourceBadge', () => {
  it('names PyMuPDF as the source when the text came from the PDF', () => {
    wrap(<ExtractionSourceBadge source="pymupdf" method="exact" />)
    expect(screen.getByText('PyMuPDF')).toBeInTheDocument()
    expect(screen.getByText('exact')).toBeInTheDocument()
  })

  it('names Azure when the PDF had no text there', () => {
    wrap(<ExtractionSourceBadge source="azure_di" method="none" />)
    expect(screen.getByText('Azure DI')).toBeInTheDocument()
    expect(screen.getByText('no text layer')).toBeInTheDocument()
  })
})

describe('CellDetails', () => {
  it('shows the full audit trail for a matched cell', () => {
    const cell = makeCell({ row: 1, column: 2, text: '₹25,000', confidence: 0.99 })
    wrap(<CellDetails cell={cell} table={tableSummary} />)

    // Once as the chosen value, then once per source reading below it — the
    // fixture has both sources agreeing.
    expect(screen.getAllByText('₹25,000')).toHaveLength(3)
    expect(screen.getByText('table_1 · row 2 · col 3')).toBeInTheDocument()
    expect(screen.getByText('100%')).toBeInTheDocument()   // containment
    expect(screen.getByText('0.400')).toBeInTheDocument()  // iou, diagnostic
    expect(screen.getByText(/of the text sits inside the cell/)).toBeInTheDocument()
  })

  it('flags a disagreement between the two sources and says which won', () => {
    const cell = makeCell({
      text: '₹25,000',
      pymupdf_text: '₹25,000',
      azure_text: '25,000',
      text_source: {
        source: 'pymupdf',
        matched: true,
        method: 'spatial',
        containment: 1,
        iou: 0.3,
        bbox: [1, 2, 3, 4],
        word_count: 1,
      },
    })
    wrap(<CellDetails cell={cell} table={tableSummary} />)
    expect(screen.getByText(/The sources disagree/)).toBeInTheDocument()
    expect(screen.getByText(/literal content of the file/)).toBeInTheDocument()
  })

  it('shows both readings, marking the one that was used', () => {
    const cell = makeCell({ text: 'a', pymupdf_text: 'a', azure_text: 'b' })
    wrap(<CellDetails cell={cell} table={tableSummary} />)
    // "PyMuPDF" appears on the provenance badge and again as a reading label.
    expect(screen.getAllByText('PyMuPDF').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('b')).toBeInTheDocument()   // Azure's reading, kept
    expect(screen.getByText('used')).toBeInTheDocument()
  })

  it('says when the PDF had no text for the cell', () => {
    const cell = makeCell({
      text: ':unselected:',
      pymupdf_text: null,
      azure_text: ':unselected:',
      confidence: null,
      text_source: {
        source: 'azure_di',
        matched: false,
        method: 'none',
        containment: 0,
        iou: 0,
        bbox: null,
        word_count: 0,
      },
    })
    wrap(<CellDetails cell={cell} table={tableSummary} />)
    expect(screen.getByText('not present')).toBeInTheDocument()
  })

  it('closes when asked', async () => {
    const onClose = vi.fn()
    const { default: userEvent } = await import('@testing-library/user-event')
    const user = userEvent.setup()
    wrap(<CellDetails cell={makeCell()} table={tableSummary} onClose={onClose} />)
    await user.click(screen.getByLabelText('Close details'))
    expect(onClose).toHaveBeenCalledOnce()
  })
})
