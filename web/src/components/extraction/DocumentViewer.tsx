import { useEffect, useState } from 'react'
import { useSuspenseQuery } from '@tanstack/react-query'
import { AlertTriangle, FileWarning, PanelsTopLeft, Table2 } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { tableQuery, tablesQuery } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { DocumentDetail, PageGeometry, TableCell, TableSummary } from '@/lib/types'
import type { OverlayBox } from './BoundingBoxOverlay'
import { CellDetails } from './CellDetails'
import { PdfPageViewer } from './PdfPageViewer'
import { ResizableSplit } from './ResizableSplit'
import { TableList } from './TableList'
import { TableViewer } from './TableViewer'

/**
 * Page and table, side by side.
 *
 * The evidence and its explanation are kept together: the page viewer and the
 * cell inspector share the left column, so the highlighted region and the
 * account of how it was matched are read in one glance — and the table keeps
 * the full height of the right column instead of losing a third of it to a
 * panel that opens underneath.
 *
 * Below `lg` the two panes cannot coexist usefully, so they become a pair of
 * tabs rather than two cramped halves. The breakpoint is read in JS rather than
 * expressed as `hidden lg:flex` on both layouts, because the table pane mounts
 * hundreds of cells and runs its own query — rendering it twice and hiding one
 * copy costs the whole grid twice over.
 */
export function DocumentViewer({
  document,
  pages,
}: {
  document: DocumentDetail
  pages: { page_number: number; geometry: PageGeometry }[]
}) {
  const { data: tableList } = useSuspenseQuery(tablesQuery(document.id))
  const tables = tableList.items
  const [selectedTableId, setSelectedTableId] = useState<string | null>(tables[0]?.id ?? null)
  const [selectedCell, setSelectedCell] = useState<TableCell | null>(null)
  const [mobilePane, setMobilePane] = useState<'table' | 'page'>('table')
  const wide = useMediaQuery('(min-width: 1024px)')

  const selectedTable = tables.find((table) => table.id === selectedTableId) ?? null

  useEffect(() => setSelectedCell(null), [selectedTableId])

  const pageNumber = selectedTable?.page_number ?? pages[0]?.page_number ?? 1
  const geometry = pages.find((page) => page.page_number === pageNumber)?.geometry

  if (!geometry) {
    return <EmptyState message="This document has no renderable pages." />
  }

  const pagePane = (
    <>
      <PdfPageViewer
        documentId={document.id}
        pageNumber={pageNumber}
        geometry={geometry}
        boxes={overlayBoxes(selectedTable, selectedCell)}
        focusBox={selectedCell?.bbox ?? selectedTable?.bbox ?? null}
        className="min-h-0 flex-1"
      />
      {selectedCell && selectedTable ? (
        <CellDetails
          cell={selectedCell}
          table={selectedTable}
          onClose={() => setSelectedCell(null)}
          className="max-h-[38%] shrink-0 overflow-auto border-t bg-card"
        />
      ) : (
        <SelectionHint className="shrink-0 border-t bg-card" />
      )}
    </>
  )

  const tablePane = selectedTable ? (
    <TablePane
      documentId={document.id}
      table={selectedTable}
      selectedCell={selectedCell}
      onSelectCell={setSelectedCell}
    />
  ) : (
    <EmptyState message="No tables were detected in this document." />
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {document.status === 'partial' ? <PartialBanner document={document} /> : null}

      {tables.length > 1 ? (
        <TableList
          tables={tables}
          selectedId={selectedTableId}
          onSelect={(table: TableSummary) => setSelectedTableId(table.id)}
          className="border-b bg-card px-2 py-1"
        />
      ) : null}

      {wide ? (
        <ResizableSplit storageKey="gi:viewer-split" first={pagePane} second={tablePane} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex gap-1 border-b bg-card p-1" role="tablist" aria-label="View">
            <PaneTab active={mobilePane === 'table'} onClick={() => setMobilePane('table')}>
              <Table2 className="size-3.5" /> Table
            </PaneTab>
            <PaneTab active={mobilePane === 'page'} onClick={() => setMobilePane('page')}>
              <PanelsTopLeft className="size-3.5" /> Page
              {selectedCell ? <span className="size-1.5 rounded-full bg-selected" /> : null}
            </PaneTab>
          </div>
          <div className="flex min-h-0 flex-1 flex-col">
            {mobilePane === 'table' ? tablePane : pagePane}
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
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        'flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring',
        active ? 'bg-secondary text-secondary-foreground' : 'text-muted-foreground hover:text-foreground',
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
        <span className="font-medium">Tables are unavailable for this document.</span> Azure
        Azure DI failed{error ? ` (${error.code})` : ''}, so table structure could not
        be extracted. Everything PyMuPDF produced — text, coordinates, page geometry, metadata — is
        intact.
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
