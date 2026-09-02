import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { makeCell, makeTable } from '@/test/fixtures'
import type { TableCell } from '@/lib/types'
import { TableViewer } from '../TableViewer'

type ViewerProps = React.ComponentProps<typeof TableViewer>

function renderViewer(props: Partial<Omit<ViewerProps, 'onSelectCell'>> = {}) {
  // Always the local mock, so the returned handle is typed as a spy rather
  // than as a union with the component's plain callback signature.
  const onSelectCell = vi.fn<(cell: TableCell | null) => void>()
  const utils = render(
    <TooltipProvider>
      <TableViewer
        table={props.table ?? makeTable()}
        selectedCell={props.selectedCell ?? null}
        onSelectCell={onSelectCell}
      />
    </TooltipProvider>,
  )
  return { ...utils, onSelectCell }
}

describe('TableViewer', () => {
  it('renders every cell in a grid', () => {
    renderViewer()
    expect(screen.getByText('Particulars')).toBeInTheDocument()
    expect(screen.getByText('11,149')).toBeInTheDocument()
    expect(screen.getAllByTestId('table-cell')).toHaveLength(9)
  })

  it('renders the header row as th so it can stick', () => {
    renderViewer()
    expect(screen.getByText('Particulars').closest('th')).not.toBeNull()
    expect(screen.getByText('11,149').closest('td')).not.toBeNull()
  })

  it('reports the clicked cell with its full provenance', async () => {
    const user = userEvent.setup()
    const { onSelectCell } = renderViewer()
    await user.click(screen.getByText('11,149'))
    expect(onSelectCell).toHaveBeenCalledOnce()
    const cell = onSelectCell.mock.calls[0][0] as TableCell
    expect(cell.row).toBe(1)
    expect(cell.column).toBe(1)
    expect(cell.text_source.bbox).not.toBeNull()
  })

  it('marks the selected cell', () => {
    const table = makeTable()
    const selected = table.cells.find((c) => c.text === '11,149')!
    renderViewer({ selectedCell: selected })
    expect(screen.getByText('11,149').closest('td')).toHaveClass('outline-selected')
  })

  it('does not render a covered span position twice', () => {
    const table = makeTable({
      row_count: 2,
      column_count: 3,
      cells: [
        makeCell({ row: 0, column: 0, column_span: 3, text: 'Fire', kind: 'columnHeader' }),
        makeCell({ row: 1, column: 0, text: 'a' }),
        makeCell({ row: 1, column: 1, text: 'b' }),
        makeCell({ row: 1, column: 2, text: 'c' }),
      ],
    })
    renderViewer({ table })
    expect(screen.getAllByText('Fire')).toHaveLength(1)
    expect(screen.getByText('Fire').closest('th')).toHaveAttribute('colspan', '3')
  })

  describe('search', () => {
    it('highlights matches and reports the count', async () => {
      const user = userEvent.setup()
      renderViewer()
      await user.type(screen.getByLabelText('Search this table'), 'Q1')
      expect(screen.getByText('1/2')).toBeInTheDocument()
    })

    it('selects the first match so the PDF highlight follows', async () => {
      const user = userEvent.setup()
      const { onSelectCell } = renderViewer()
      await user.type(screen.getByLabelText('Search this table'), '11,149')
      expect(onSelectCell).toHaveBeenCalled()
      const last = onSelectCell.mock.calls.at(-1)![0] as TableCell
      expect(last.text).toBe('11,149')
    })

    it('steps through matches', async () => {
      const user = userEvent.setup()
      renderViewer()
      await user.type(screen.getByLabelText('Search this table'), 'Q1')
      await user.click(screen.getByLabelText('Next match'))
      expect(screen.getByText('2/2')).toBeInTheDocument()
      // Wraps around.
      await user.click(screen.getByLabelText('Next match'))
      expect(screen.getByText('1/2')).toBeInTheDocument()
    })

    it('reports no matches for a miss', async () => {
      const user = userEvent.setup()
      renderViewer()
      await user.type(screen.getByLabelText('Search this table'), 'zzz')
      expect(screen.getByText('none')).toBeInTheDocument()
    })

    it('clears with the button', async () => {
      const user = userEvent.setup()
      renderViewer()
      const input = screen.getByLabelText('Search this table')
      await user.type(input, 'Q1')
      await user.click(screen.getByLabelText('Clear search'))
      expect(input).toHaveValue('')
    })
  })

  describe('copy', () => {
    // userEvent.setup() installs its own clipboard stub, so the spy has to go
    // on after it rather than being defined once up front.
    const spyOnClipboard = () =>
      vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)

    it('copies the whole table as TSV', async () => {
      const user = userEvent.setup()
      const writeText = spyOnClipboard()
      renderViewer()

      await user.click(screen.getByRole('button', { name: /copy table/i }))
      expect(writeText).toHaveBeenCalledOnce()
      const text = writeText.mock.calls[0][0] as string
      expect(text.split('\n')).toHaveLength(3)
      expect(text.split('\n')[0]).toBe('Particulars\tFor Q1 2026-27\tUpto Q1 2026-27')
    })

    it('copies a single row', async () => {
      const user = userEvent.setup()
      const writeText = spyOnClipboard()
      renderViewer()

      await user.click(screen.getByLabelText('Copy row 2'))
      expect(writeText).toHaveBeenCalledWith('Premiums earned (Net)\t11,149\t14,168')
    })
  })

  describe('provenance marks', () => {
    it('marks a cell that came from Azure rather than the PDF', () => {
      const table = makeTable({
        cells: [
          makeCell({
            row: 0,
            column: 0,
            text: '1,25,000',
            pymupdf_text: null,
            text_source: {
              source: 'azure_di',
              matched: false,
              method: 'none',
              containment: 0,
              iou: 0,
              bbox: null,
              word_count: 0,
            },
          }),
        ],
        row_count: 1,
        column_count: 1,
      })
      renderViewer({ table })
      expect(screen.getByTestId('mark-unverified')).toBeInTheDocument()
    })

    it('leaves a verified, confident cell unmarked', () => {
      renderViewer()
      expect(screen.queryByTestId('mark-unverified')).not.toBeInTheDocument()
      expect(screen.queryByTestId('mark-low-confidence')).not.toBeInTheDocument()
    })

    it('marks a low-confidence cell', () => {
      const table = makeTable({
        cells: [makeCell({ row: 0, column: 0, confidence: 0.55 })],
        row_count: 1,
        column_count: 1,
      })
      renderViewer({ table })
      expect(screen.getByTestId('mark-low-confidence')).toBeInTheDocument()
    })
  })

  it('shows the table metadata line', () => {
    renderViewer()
    expect(screen.getByText('table_1')).toBeInTheDocument()
    expect(screen.getByText('3×3')).toBeInTheDocument()
    expect(screen.getByText('Azure DI')).toBeInTheDocument()
  })
})
