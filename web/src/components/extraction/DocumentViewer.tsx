import { useCallback, useState } from 'react'
import { useSuspenseQuery } from '@tanstack/react-query'
import { AlertTriangle, FileText, FileWarning, PanelsTopLeft, Table2 } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { tableQuery, tablesQuery } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { DocumentDetail, PageGeometry, TableCell, TableSummary } from '@/lib/types'
import type { OverlayBox } from './BoundingBoxOverlay'
import { CellDetails } from './CellDetails'
import { PageDocumentPane, type PageSelection } from './PageDocumentView'
import { PdfPageViewer } from './PdfPageViewer'
import { ResizableSplit } from './ResizableSplit'
import { TableList } from './TableList'
import { TableViewer } from './TableViewer'

/**
 * Page and extraction, side by side.
 *
 * The evidence and its explanation are kept together: the page viewer and the
 * cell inspector share the left column, so the highlighted region and the
 * account of how it was matched are read in one glance — and the extraction
 * keeps the full height of the right column instead of losing a third of it to
 * a panel that opens underneath.
 *
 * **Two readings of the extraction, behind tabs.** A grid on its own answers
 * "is this figure right"; it cannot answer "which schedule is this" or "what
 * does the note under the table say", because it has thrown away everything
 * that was not a cell. So the right column offers both: `Tables` is the
 * spreadsheet view of one table, `Full page` rebuilds the whole page — prose,
 * figures, and every table on it — from the same extraction. Both drive the
 * same selection, so a cell clicked in either one lights up on the PDF.
 *
 * Below `lg` the two columns cannot coexist usefully, so they become tabs
 * rather than two cramped halves. The breakpoint is read in JS rather than
 * expressed as `hidden lg:flex` on both layouts, because the table pane mounts
 * hundreds of cells and runs its own query — rendering it twice and hiding one
 * copy costs the whole grid twice over.
 */

type View = 'tables' | 'page'

export function DocumentViewer({
  document,
  pages,
}: {
  document: DocumentDetail
  pages: { page_number: number; geometry: PageGeometry }[]
}) {
  const { data: tableList } = useSuspenseQuery(tablesQuery(document.id))
  const tables = tableList.items

  const firstPage = tables[0]?.page_number ?? pages[0]?.page_number ?? 1
  const [pageNumber, setPageNumber] = useState(firstPage)
  const [selectedTableId, setSelectedTableId] = useState<string | null>(tables[0]?.id ?? null)
  // The table travels with the cell: in the full-page view a click can land in
  // any table on the page, and the inspector needs the one it actually came
  // from rather than whatever the table tab happens to have open.
  const [selection, setSelection] = useState<PageSelection | null>(null)
  const [view, setView] = useState<View>(tables.length ? 'tables' : 'page')
  const [showPdf, setShowPdf] = useState(false)
  const wide = useMediaQuery('(min-width: 1024px)')

  const selectedCell = selection?.cell ?? null
  const activeTable = tables.find((table) => table.id === selectedTableId) ?? null

  const selectTable = useCallback((table: TableSummary) => {
    setSelectedTableId(table.id)
    setPageNumber(table.page_number)
    setSelection(null)
  }, [])

  const selectFromPage = useCallback((next: PageSelection | null) => {
    setSelection(next)
    // Keep the table tab pointed at whatever was last inspected, so switching
    // back opens the grid the cell belongs to.
    if (next) setSelectedTableId(next.table.id)
  }, [])

  const selectFromTable = useCallback(
    (cell: TableCell | null) => {
      setSelection(cell && activeTable ? { cell, table: activeTable } : null)
    },
    [activeTable],
  )

  const changePage = useCallback((next: number) => {
    setPageNumber(next)
    setSelection(null)
  }, [])

  const geometry = pages.find((page) => page.page_number === pageNumber)?.geometry
  const pageTables = tables.filter((table) => table.page_number === pageNumber)
  // Whichever table the highlight belongs to: the open one in the table tab,
  // the clicked one in the full-page view.
  const overlayTable = view === 'page' ? (selection?.table ?? null) : activeTable

  if (!geometry) {
    return <EmptyState message="This document has no renderable pages." />
  }

  const pdfPane = (
    <>
      <PdfPageViewer
        documentId={document.id}
        pageNumber={pageNumber}
        geometry={geometry}
        boxes={overlayBoxes(overlayTable, selectedCell)}
        focusBox={selectedCell?.bbox ?? overlayTable?.bbox ?? null}
        className="min-h-0 flex-1"
      />
      {selection ? (
        <CellDetails
          cell={selection.cell}
          table={selection.table}
          onClose={() => setSelection(null)}
          className="max-h-[38%] shrink-0 overflow-auto border-t bg-card"
        />
      ) : (
        <SelectionHint className="shrink-0 border-t bg-card" />
      )}
    </>
  )

  const tablesPane = activeTable ? (
    <div className="flex min-h-0 flex-1 flex-col">
      <TableList
        tables={tables}
        selectedId={selectedTableId}
        onSelect={selectTable}
        className="border-b bg-card"
      />
      <TablePane
        documentId={document.id}
        table={activeTable}
        selectedCell={selectedCell}
        onSelectCell={selectFromTable}
      />
    </div>
  ) : (
    <EmptyState message="No tables were detected in this document." />
  )

  const fullPagePane = (
    <PageDocumentPane
      documentId={document.id}
      pageNumber={pageNumber}
      // What the page listing returned, not the document's page count: only
      // these pages have the geometry this view needs to draw anything.
      pageCount={pages.length}
      geometry={geometry}
      tables={pageTables}
      selection={selection}
      onSelectCell={selectFromPage}
      onPageChange={changePage}
      className="min-h-0 flex-1"
    />
  )

  const extractionPane = (
    <div className="flex min-h-0 flex-1 flex-col bg-card">
      <div className="flex gap-1 border-b p-1" role="tablist" aria-label="Extraction view">
        <PaneTab
          active={view === 'tables'}
          onClick={() => setView('tables')}
          disabled={!tables.length}
        >
          <Table2 className="size-3.5" /> Tables
          {tables.length ? (
            <span className="font-mono text-[10px] opacity-70">{tables.length}</span>
          ) : null}
        </PaneTab>
        <PaneTab active={view === 'page'} onClick={() => setView('page')}>
          <FileText className="size-3.5" /> Full page
        </PaneTab>
      </div>
      {view === 'tables' ? tablesPane : fullPagePane}
    </div>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {document.status === 'partial' ? <PartialBanner document={document} /> : null}

      {wide ? (
        <ResizableSplit storageKey="gi:viewer-split" first={pdfPane} second={extractionPane} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex gap-1 border-b bg-card p-1" role="tablist" aria-label="View">
            <PaneTab
              active={!showPdf && view === 'tables'}
              onClick={() => {
                setShowPdf(false)
                setView('tables')
              }}
              disabled={!tables.length}
            >
              <Table2 className="size-3.5" /> Tables
            </PaneTab>
            <PaneTab
              active={!showPdf && view === 'page'}
              onClick={() => {
                setShowPdf(false)
                setView('page')
              }}
            >
              <FileText className="size-3.5" /> Full page
            </PaneTab>
            <PaneTab active={showPdf} onClick={() => setShowPdf(true)}>
              <PanelsTopLeft className="size-3.5" /> PDF
              {selectedCell ? <span className="size-1.5 rounded-full bg-selected" /> : null}
            </PaneTab>
          </div>
          <div className="flex min-h-0 flex-1 flex-col">
            {showPdf ? pdfPane : view === 'tables' ? tablesPane : fullPagePane}
          </div>
        </div>
      )}
    </div>
  )
}

function overlayBoxes(table: TableSummary | null, cell: TableCell | null): OverlayBox[] {
  const boxes: OverlayBox[] = []
  if (table) boxes.push({ id: table.id, bbox: table.bbox, kind: 'table' })
  if (cell) {
    boxes.push({ id: 'cell', bbox: cell.bbox, kind: 'cell', active: true })
    // The tightest, truest box: where the characters actually are.
    if (cell.text_source.bbox) {
      boxes.push({ id: 'text', bbox: cell.text_source.bbox, kind: 'text', active: true })
    }
  }
  return boxes
}

function TablePane({
  documentId,
  table,
  selectedCell,
  onSelectCell,
}: {
  documentId: string
  table: TableSummary
  selectedCell: TableCell | null
  onSelectCell: (cell: TableCell | null) => void
}) {
  const { data: detail } = useSuspenseQuery(tableQuery(documentId, table.id))
  return (
    <TableViewer
      table={detail}
      selectedCell={selectedCell}
      onSelectCell={onSelectCell}
      className="min-h-0 flex-1"
    />
  )
}

function PaneTab({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean
  onClick: () => void
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring',
        'disabled:pointer-events-none disabled:opacity-40',
        active
          ? 'bg-secondary text-secondary-foreground'
          : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

function SelectionHint({ className }: { className?: string }) {
  return (
    <div className={cn('px-3 py-2.5', className)}>
      <p className="text-xs text-muted-foreground">
        Select a cell to zoom to it on the page and see where its value came from.
        <span className="ml-1.5 hidden font-mono text-[10px] opacity-70 sm:inline">
          ↑ ↓ ← → to move
        </span>
      </p>
    </div>
  )
}

function PartialBanner({ document }: { document: DocumentDetail }) {
  const error = document.extraction?.azure_di.error
  return (
    <div className="flex items-start gap-2 border-b border-reported/30 bg-reported-wash px-4 py-2 text-xs text-reported-strong">
      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
      <p>
        <span className="font-medium">Tables are unavailable for this document.</span> Azure DI
        failed{error ? ` (${error.code})` : ''}, so table structure could not be extracted.
        Everything PyMuPDF produced — text, coordinates, page geometry, metadata — is intact, and
        the full-page view reads from it.
      </p>
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center">
      <FileWarning className="size-5 text-muted-foreground" />
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  )
}

export function DocumentViewerSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn('grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 lg:grid-cols-2', className)}>
      <Skeleton className="min-h-96 w-full" />
      <Skeleton className="min-h-96 w-full" />
    </div>
  )
}
