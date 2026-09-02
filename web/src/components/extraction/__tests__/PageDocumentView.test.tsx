import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { BOLD, geometry, makeBlock, makeCell, makeTable } from '@/test/fixtures'
import type { PageBlock, TableCell, TableDetail } from '@/lib/types'
import { PageDocumentView } from '../PageDocumentView'

/** A page shaped like a filing: a title, a table, and a note under it. */
const table = makeTable({ bbox: [50, 200, 350, 260] })

const blocks: PageBlock[] = [
  makeBlock(0, 'Schedule 1 — Premiums', [200, 40, 400, 62], { size: 16, flags: BOLD }),
  makeBlock(1, 'Particulars', [55, 205, 145, 218]),
  makeBlock(2, 'Figures are in thousands.', [50, 300, 260, 313]),
]

type ViewProps = React.ComponentProps<typeof PageDocumentView>

function renderView(props: Partial<ViewProps> = {}) {
  const onSelectCell = vi.fn<ViewProps['onSelectCell']>()
  const onPageChange = vi.fn<ViewProps['onPageChange']>()
  const utils = render(
    <TooltipProvider>
      <PageDocumentView
        geometry={geometry}
        pageNumber={props.pageNumber ?? 2}
        pageCount={props.pageCount ?? 5}
        blocks={props.blocks ?? blocks}
        tables={props.tables ?? [table]}
        hasTextLayer={props.hasTextLayer ?? true}
        selection={props.selection ?? null}
        onSelectCell={onSelectCell}
        onPageChange={onPageChange}
      />
    </TooltipProvider>,
  )
  return { ...utils, onSelectCell, onPageChange }
}

describe('PageDocumentView', () => {
  it('opens on the faithful layout', () => {
    renderView()
    expect(screen.getByLabelText('Page layout')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('Schedule 1 — Premiums')).toBeInTheDocument()
  })

  describe('layout', () => {
    it('keeps the text the table covers, and draws the grid over it', () => {
      renderView()
      // The block inside the table's footprint is still drawn: in this view
      // the PDF's own characters are what the cells sit on top of.
      expect(screen.getByText('Particulars')).toBeInTheDocument()
      expect(screen.getByTestId('layout-table')).toBeInTheDocument()
      expect(screen.getAllByTestId('layout-cell')).toHaveLength(9)
    })

    it('places a line where the PDF drew it', () => {
      renderView()
      // The text sits in a styled run inside the positioned line.
      const line = screen
        .getByText('Figures are in thousands.')
        .closest<HTMLElement>('[data-fit-width]')!
      const title = screen
        .getByText('Schedule 1 — Premiums')
        .closest<HTMLElement>('[data-fit-width]')!

      expect(line).toHaveStyle({ position: 'absolute' })
      // Scaled, but proportional: the note is drawn below the title, and the
      // width it has to fill is handed to the fitting pass.
      expect(parseFloat(line.style.top)).toBeGreaterThan(parseFloat(title.style.top))
      expect(Number(line.dataset.fitWidth)).toBeGreaterThan(0)
    })

    it('writes in only the cells the PDF has no characters for', () => {
      const orphan = makeCell({
        row: 1,
        column: 1,
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
      })
      const withOrphan: TableDetail = {
        ...table,
        cells: [...table.cells.filter((cell) => !(cell.row === 1 && cell.column === 1)), orphan],
      }
      renderView({ tables: [withOrphan] })

      const written = screen.getAllByTestId('layout-cell-text')
      expect(written).toHaveLength(1)
      expect(written[0]).toHaveTextContent('1,25,000')
    })

    it('reports the clicked cell with the table it came from', async () => {
      const user = userEvent.setup()
      const { onSelectCell } = renderView()
      await user.click(screen.getByTitle('11,149'))
      expect(onSelectCell).toHaveBeenCalledOnce()
      const selection = onSelectCell.mock.calls[0][0]!
      expect(selection.cell.text).toBe('11,149')
      expect(selection.table.id).toBe('table_1')
      // The summary the inspector wants — never the whole cell list.
      expect(selection.table).not.toHaveProperty('cells')
    })
  })

  describe('reading order', () => {
    it('replaces the table’s own text with the grid', async () => {
      const user = userEvent.setup()
      renderView()
      await user.click(screen.getByLabelText('Reading order'))

      const cells = screen.getAllByTestId('reflow-cell')
      expect(cells).toHaveLength(9)
      // 'Particulars' now appears once, as a header cell, rather than twice.
      expect(screen.getAllByText('Particulars')).toHaveLength(1)
      expect(screen.getByText('Particulars').closest('th')).not.toBeNull()
    })

    it('keeps the page’s prose around the table', async () => {
      const user = userEvent.setup()
      renderView()
      await user.click(screen.getByLabelText('Reading order'))
      expect(screen.getByText('Schedule 1 — Premiums')).toBeInTheDocument()
      expect(screen.getByText('Figures are in thousands.')).toBeInTheDocument()
    })

    it('sizes a heading above the page’s body text', async () => {
      const user = userEvent.setup()
      renderView()
      await user.click(screen.getByLabelText('Reading order'))
      const heading = screen.getByText('Schedule 1 — Premiums')
      const body = screen.getByText('Figures are in thousands.')
      expect(parseFloat(heading.style.fontSize)).toBeGreaterThan(parseFloat(body.style.fontSize))
    })

    it('reports a clicked cell the same way the layout does', async () => {
      const user = userEvent.setup()
      const { onSelectCell } = renderView()
      await user.click(screen.getByLabelText('Reading order'))
      await user.click(screen.getByText('14,168'))
      expect(onSelectCell.mock.calls.at(-1)![0]!.cell.text).toBe('14,168')
    })

    it('marks the selected cell', async () => {
      const user = userEvent.setup()
      const cell = table.cells.find((entry) => entry.text === '11,149') as TableCell
      renderView({ selection: { cell, table } })
      await user.click(screen.getByLabelText('Reading order'))
      expect(screen.getByText('11,149').closest('td')).toHaveClass('outline-selected')
    })

    it('leaves the same coordinate in another table unmarked', async () => {
      const user = userEvent.setup()
      const cell = table.cells.find((entry) => entry.text === '11,149') as TableCell
      const second = makeTable({ id: 'table_2', bbox: [400, 200, 700, 260] })
      // Row 1, column 1 exists in both tables and holds the same figure; only
      // the table the selection names should light up.
      renderView({ tables: [table, second], selection: { cell, table: second } })
      await user.click(screen.getByLabelText('Reading order'))

      const [first, duplicate] = screen.getAllByText('11,149').map((node) => node.closest('td'))
      expect(first).not.toHaveClass('outline-selected')
      expect(duplicate).toHaveClass('outline-selected')
    })
  })

  describe('page navigation', () => {
    it('steps through the document', async () => {
      const user = userEvent.setup()
      const { onPageChange } = renderView({ pageNumber: 2, pageCount: 5 })
      expect(screen.getByText('2 / 5')).toBeInTheDocument()
      await user.click(screen.getByLabelText('Next page'))
      expect(onPageChange).toHaveBeenCalledWith(3)
      await user.click(screen.getByLabelText('Previous page'))
      expect(onPageChange).toHaveBeenLastCalledWith(1)
    })

    it('stops at both ends', () => {
      renderView({ pageNumber: 1, pageCount: 1 })
      expect(screen.getByLabelText('Previous page')).toBeDisabled()
      expect(screen.getByLabelText('Next page')).toBeDisabled()
    })
  })

  it('copies the page as text, with the table tabbed out', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
    renderView()

    await user.click(screen.getByRole('button', { name: /copy page/i }))
    const text = writeText.mock.calls[0][0] as string
    expect(text.startsWith('Schedule 1 — Premiums')).toBe(true)
    expect(text).toContain('Premiums earned (Net)\t11,149\t14,168')
    expect(text.trimEnd().endsWith('Figures are in thousands.')).toBe(true)
  })

  it('says so when the page is a scan', () => {
    renderView({ hasTextLayer: false, blocks: [] })
    expect(screen.getByText(/no text layer/i)).toBeInTheDocument()
  })

  it('says so when the page is blank', async () => {
    const user = userEvent.setup()
    renderView({ blocks: [], tables: [] })
    await user.click(screen.getByLabelText('Reading order'))
    expect(screen.getByText('This page is blank.')).toBeInTheDocument()
  })

  it('renders a page with no tables at all', async () => {
    const user = userEvent.setup()
    renderView({ tables: [] })
    await user.click(screen.getByLabelText('Reading order'))
    expect(screen.queryByTestId('reflow-cell')).not.toBeInTheDocument()
    const article = screen.getByRole('article')
    expect(within(article).getByText('Particulars')).toBeInTheDocument()
  })
})
