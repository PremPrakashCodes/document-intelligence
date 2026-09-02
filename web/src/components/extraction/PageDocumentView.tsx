import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import {
  AlignLeft,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  ImageIcon,
  LayoutTemplate,
  Loader2,
  Minus,
  Plus,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useElementSize } from '@/hooks/useElementSize'
import { pageBlocksQuery, tableQuery } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type {
  BBox,
  PageBlock,
  PageGeometry,
  PageLine,
  TableCell,
  TableDetail,
  TableSummary,
} from '@/lib/types'
import { LOW_CONFIDENCE, confidenceTone } from './ConfidenceIndicator'
import {
  type Alignment,
  type FlowNode,
  blockAlignment,
  bodyFontSize,
  buildPageFlow,
  contentBox,
  dominantSpan,
  flowText,
  headingLevel,
  lineStyle,
  lineText,
  spanStyle,
} from './pageFlow'
import { buildGrid, headerRowCount, toNumber } from './tableGrid'

/**
 * The whole page: its prose and its tables, not one table in isolation.
 *
 * The table viewer shows a grid stripped of everything around it, which is the
 * right tool for checking a figure and the wrong one for the question a
 * reviewer asks first — *which* schedule is this, what does the note under it
 * say, whose signature is at the foot. Both answers now live behind a pair of
 * tabs over the same page.
 *
 * Two renderings, because "show me the page" means two different things:
 *
 * - **Layout** rebuilds the page at its own coordinates. Every line is placed
 *   where the PDF drew it and scaled horizontally to the width it occupies
 *   there, so the result reads as the document rather than as an extract — but
 *   made of real, selectable text with the extracted cells drawn over it as a
 *   clickable grid. Cells whose value came from Azure alone are the ones with
 *   no characters in the PDF underneath, so those are the only ones this view
 *   has to write in itself.
 * - **Reflow** drops the coordinates and reads top to bottom at a comfortable
 *   size: paragraphs as paragraphs, tables as tables. This is the one that
 *   survives a narrow pane, and the one you can copy out of.
 */

/** Reflowed body text size, in px, that `bodyFontSize` maps onto. */
const REFLOW_BODY_PX = 13

const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2, 3] as const

type Mode = 'layout' | 'reflow'

export interface PageSelection {
  cell: TableCell
  table: TableSummary
}

// --- container ---------------------------------------------------------------

export function PageDocumentPane({
  documentId,
  pageNumber,
  pageCount,
  geometry,
  tables,
  selection,
  onSelectCell,
  onPageChange,
  className,
}: {
  documentId: string
  pageNumber: number
  pageCount: number
  geometry: PageGeometry
  /** The tables on this page, from the document listing. */
  tables: TableSummary[]
  /** The open cell *and* the table it belongs to - a page can hold several. */
  selection: PageSelection | null
  onSelectCell: (selection: PageSelection | null) => void
  onPageChange: (pageNumber: number) => void
  className?: string
}) {
  const { data: page, isPending, isError } = useQuery(pageBlocksQuery(documentId, pageNumber))

  // One request per table, each immutable and cached for the session, so
  // switching back to the table tab reuses exactly what this view fetched.
  const details = useQueries({
    queries: tables.map((table) => tableQuery(documentId, table.id)),
  })
  const loaded = details.every((query) => query.data)

  if (isError) {
    return (
      <Placeholder className={className}>This page&rsquo;s text could not be loaded.</Placeholder>
    )
  }
  if (isPending || !loaded) {
    return (
      <div className={cn('flex min-h-0 flex-1 flex-col gap-2 bg-card p-4', className)}>
        <Skeleton className="h-5 w-2/5" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-11/12" />
        <Skeleton className="mt-3 h-40 w-full" />
      </div>
    )
  }

  return (
    <PageDocumentView
      geometry={geometry}
      pageNumber={pageNumber}
      pageCount={pageCount}
      blocks={page.content.blocks ?? []}
      tables={details.map((query) => query.data as TableDetail)}
      hasTextLayer={page.has_text_layer}
      selection={selection}
      onSelectCell={onSelectCell}
      onPageChange={onPageChange}
      className={className}
    />
  )
}

// --- view --------------------------------------------------------------------

export function PageDocumentView({
  geometry,
  pageNumber,
  pageCount,
  blocks,
  tables,
  hasTextLayer,
  selection,
  onSelectCell,
  onPageChange,
  className,
}: {
  geometry: PageGeometry
  pageNumber: number
  pageCount: number
  blocks: PageBlock[]
  tables: TableDetail[]
  hasTextLayer: boolean
  selection: PageSelection | null
  onSelectCell: (selection: PageSelection | null) => void
  onPageChange: (pageNumber: number) => void
  className?: string
}) {
  const [mode, setMode] = useState<Mode>('layout')
  const [zoom, setZoom] = useState(1)
  const [copied, setCopied] = useState(false)
  const [scrollRef, pane] = useElementSize<HTMLDivElement>()

  const bodySize = useMemo(() => bodyFontSize(blocks), [blocks])
  const margins = useMemo(() => contentBox(blocks), [blocks])
  const layoutNodes = useMemo(
    () => buildPageFlow(blocks, tables, { keepTableText: true }),
    [blocks, tables],
  )
  const reflowNodes = useMemo(() => buildPageFlow(blocks, tables), [blocks, tables])

  // Fit to the pane's width, then let the zoom control take it from there. A
  // filing page fitted to half a laptop screen lands near 7px body text, which
  // is the same unreadability the PDF viewer's follow mode exists to avoid.
  const fitScale = pane.width ? Math.max((pane.width - 32) / geometry.width, 0.1) : 1
  const scale = fitScale * zoom

  const select = useCallback(
    (cell: TableCell, table: TableDetail) => {
      const { cells: _cells, ...summary } = table
      onSelectCell({ cell, table: summary })
    },
    [onSelectCell],
  )

  const copyPage = useCallback(() => {
    void navigator.clipboard?.writeText(flowText(reflowNodes))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [reflowNodes])

  const stepZoom = (delta: number) => {
    const next =
      delta > 0
        ? ZOOM_STEPS.find((step) => step > zoom + 0.01)
        : [...ZOOM_STEPS].reverse().find((step) => step < zoom - 0.01)
    if (next) setZoom(next)
  }

  return (
    <div className={cn('flex min-h-0 flex-col bg-card', className)}>
      <div className="flex flex-wrap items-center gap-1.5 border-b px-2 py-1.5">
        <div className="flex items-center">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label="Previous page"
            disabled={pageNumber <= 1}
            onClick={() => onPageChange(pageNumber - 1)}
          >
            <ChevronLeft className="size-3.5" />
          </Button>
          <span className="min-w-16 text-center font-mono text-[11px] text-muted-foreground">
            {pageNumber} / {pageCount}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-label="Next page"
            disabled={pageNumber >= pageCount}
            onClick={() => onPageChange(pageNumber + 1)}
          >
            <ChevronRight className="size-3.5" />
          </Button>
        </div>

        <div className="flex items-center rounded-md border p-0.5">
          <ModeButton
            active={mode === 'layout'}
            onClick={() => setMode('layout')}
            label="Page layout"
            hint="The page rebuilt at its own coordinates, with the extracted cells drawn over it"
          >
            <LayoutTemplate className="size-3.5" />
          </ModeButton>
          <ModeButton
            active={mode === 'reflow'}
            onClick={() => setMode('reflow')}
            label="Reading order"
            hint="Paragraphs and tables top to bottom, at a readable size"
          >
            <AlignLeft className="size-3.5" />
          </ModeButton>
        </div>

        {mode === 'layout' ? (
          <div className="flex items-center">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Zoom out"
              disabled={zoom <= ZOOM_STEPS[0] + 0.01}
              onClick={() => stepZoom(-1)}
            >
              <Minus className="size-3.5" />
            </Button>
            <span className="w-10 text-center font-mono text-[11px] text-muted-foreground">
              {Math.round(zoom * 100)}%
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Zoom in"
              disabled={zoom >= ZOOM_STEPS[ZOOM_STEPS.length - 1] - 0.01}
              onClick={() => stepZoom(1)}
            >
              <Plus className="size-3.5" />
            </Button>
          </div>
        ) : null}

        <Button variant="ghost" size="sm" className="ml-auto h-7" onClick={copyPage}>
          {copied ? <Check className="size-3.5 text-confirmed" /> : <Copy className="size-3.5" />}
          Copy page
        </Button>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto bg-muted/30 p-4">
        {!hasTextLayer ? (
          <p className="mb-3 rounded-md border border-reported/30 bg-reported-wash px-3 py-2 text-xs text-reported-strong">
            This page has no text layer — it is a scan. Only the table structure below was
            recovered.
          </p>
        ) : null}

        {mode === 'layout' ? (
          <LayoutPage
            geometry={geometry}
            nodes={layoutNodes}
            scale={scale}
            bodySize={bodySize}
            selection={selection}
            onSelectCell={select}
          />
        ) : (
          <ReflowPage
            nodes={reflowNodes}
            bodySize={bodySize}
            pageWidth={geometry.width}
            margins={margins}
            selection={selection}
            onSelectCell={select}
          />
        )}
      </div>
    </div>
  )
}

/**
 * The open cell, but only for the table it actually belongs to.
 *
 * A page can carry several tables, and row 1 column 1 exists in every one of
 * them, so a bare row/column comparison would light up the same coordinate in
 * each. The selection carries its table for exactly this reason.
 */
function cellIn(selection: PageSelection | null, table: TableDetail): TableCell | null {
  return selection && selection.table.id === table.id ? selection.cell : null
}

// --- layout: the page at its own coordinates ---------------------------------

function LayoutPage({
  geometry,
  nodes,
  scale,
  bodySize,
  selection,
  onSelectCell,
}: {
  geometry: PageGeometry
  nodes: FlowNode[]
  scale: number
  bodySize: number
  selection: PageSelection | null
  onSelectCell: (cell: TableCell, table: TableDetail) => void
}) {
  const ref = useFitText([nodes, scale])

  return (
    <div
      ref={ref}
      className="page-ink page-surface relative mx-auto"
      style={{ width: geometry.width * scale, height: geometry.height * scale }}
    >
      {nodes.map((node) => {
        if (node.kind === 'image') {
          return <LayoutImage key={node.id} bbox={node.bbox} scale={scale} />
        }
        if (node.kind === 'text') {
          return (
            <LayoutBlock key={node.id} block={node.block} scale={scale} />
          )
        }
        return (
          <LayoutTable
            key={node.id}
            table={node.table}
            scale={scale}
            bodySize={bodySize}
            selectedCell={cellIn(selection, node.table)}
            onSelectCell={onSelectCell}
          />
        )
      })}
    </div>
  )
}

function LayoutBlock({ block, scale }: { block: PageBlock; scale: number }) {
  return (
    <>
      {(block.lines ?? []).map((line, index) => (
        <LayoutLine key={index} line={line} scale={scale} />
      ))}
    </>
  )
}

/**
 * One line of the PDF, placed where it was drawn.
 *
 * The font is never the document's own, so the natural width of the same
 * characters is off by a few percent — enough to run a table row's label into
 * the figure beside it. `data-fit-width` hands the drawn width to the fitting
 * pass, which scales the line horizontally to land exactly on it.
 */
function LayoutLine({ line, scale }: { line: PageLine; scale: number }) {
  const text = lineText(line)
  if (!text.trim()) return null

  const style = lineStyle(line)
  const width = (line.bbox[2] - line.bbox[0]) * scale
  // The box is the glyphs' extent, so the baseline sits at its foot; anchoring
  // the text to the bottom keeps it on the rule it was drawn on.
  const height = (line.bbox[3] - line.bbox[1]) * scale

  return (
    <span
      data-fit-width={width}
      style={{
        position: 'absolute',
        left: line.bbox[0] * scale,
        top: line.bbox[1] * scale,
        height,
        fontSize: Math.max(style.size * scale, 1),
        lineHeight: `${height}px`,
        transformOrigin: '0 0',
        whiteSpace: 'pre',
      }}
    >
      {line.spans.map((span, index) => {
        const spanStyles = spanStyle(span)
        return (
          <span
            key={index}
            style={{
              fontSize:
                spanStyles.size === style.size ? undefined : Math.max(spanStyles.size * scale, 1),
              fontWeight: spanStyles.bold ? 600 : undefined,
              fontStyle: spanStyles.italic ? 'italic' : undefined,
              fontFamily: spanStyles.mono ? 'var(--font-mono)' : undefined,
            }}
          >
            {span.text}
          </span>
        )
      })}
    </span>
  )
}

function LayoutImage({ bbox, scale }: { bbox: BBox; scale: number }) {
  return (
    <div
      style={{
        position: 'absolute',
        left: bbox[0] * scale,
        top: bbox[1] * scale,
        width: (bbox[2] - bbox[0]) * scale,
        height: (bbox[3] - bbox[1]) * scale,
      }}
      className="flex items-center justify-center rounded-sm border border-dashed border-border/70 bg-muted/40"
    >
      <ImageIcon className="size-3.5 text-muted-foreground/60" />
    </div>
  )
}

/**
 * The extracted grid, drawn over the page's own characters.
 *
 * The cells are transparent: the text under them is the PDF's, at the PDF's
 * coordinates, which is a truer rendering than anything this view could
 * re-typeset. What it adds is the structure Azure found — where one cell ends
 * and the next begins, and which values nobody could confirm — plus a click
 * target that ties each cell back to the viewer and the page overlay.
 */
function LayoutTable({
  table,
  scale,
  bodySize,
  selectedCell,
  onSelectCell,
}: {
  table: TableDetail
  scale: number
  bodySize: number
  selectedCell: TableCell | null
  onSelectCell: (cell: TableCell, table: TableDetail) => void
}) {
  const [x0, y0, x1, y1] = table.bbox
  return (
    <div
      data-testid="layout-table"
      style={{
        position: 'absolute',
        left: x0 * scale,
        top: y0 * scale,
        width: (x1 - x0) * scale,
        height: (y1 - y0) * scale,
      }}
      className="cell-rule border"
    >
      {table.cells.map((cell) => {
        const selected = selectedCell?.row === cell.row && selectedCell?.column === cell.column
        // Azure read it but the PDF has no characters there, so nothing
        // underneath this rectangle says what the cell contains.
        const orphan = cell.text.trim() !== '' && cell.text_source.source === 'azure_di'
        const lowConfidence = cell.confidence !== null && cell.confidence < LOW_CONFIDENCE

        return (
          <button
            key={`${cell.row}:${cell.column}`}
            type="button"
            data-testid="layout-cell"
            title={cell.text}
            onClick={() => onSelectCell(cell, table)}
            style={{
              position: 'absolute',
              left: (cell.bbox[0] - x0) * scale,
              top: (cell.bbox[1] - y0) * scale,
              width: (cell.bbox[2] - cell.bbox[0]) * scale,
              height: (cell.bbox[3] - cell.bbox[1]) * scale,
            }}
            className={cn(
              'cell-rule overflow-hidden border-b border-r text-left leading-tight',
              'hover:bg-selected-wash/60 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring',
              orphan && 'bg-reported-wash',
              lowConfidence && !orphan && 'bg-reported-wash/50',
              selected && 'bg-selected-wash outline outline-2 -outline-offset-2 outline-selected',
            )}
          >
            {orphan ? (
              <span
                data-testid="layout-cell-text"
                className="block truncate px-0.5 text-reported-strong"
                style={{ fontSize: writtenSize(cell.bbox, bodySize, scale) }}
              >
                {cell.text}
              </span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

/**
 * Type size for a value this view has to write in itself.
 *
 * It matches the page's own prose, so a filled-in cell does not announce
 * itself as a different document - but never exceeds what the cell can hold. A
 * fixed size cannot do this: the same 7pt at a 4x zoom is 28px, which spills a
 * long token clean across the neighbouring columns.
 */
function writtenSize(bbox: BBox, bodySize: number, scale: number): number {
  const height = (bbox[3] - bbox[1]) * scale
  return Math.max(Math.min(bodySize * scale, height * 0.8), 5)
}

/**
 * Scale every fitted line horizontally onto the width the PDF drew it at.
 *
 * Runs on layout so the correction lands in the same frame as the text, and
 * again once webfonts settle — the first pass measures fallback metrics, which
 * are not the ones the reader ends up seeing.
 */
function useFitText(deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const root = ref.current
    if (!root) return

    const fit = () => {
      for (const element of root.querySelectorAll<HTMLElement>('[data-fit-width]')) {
        const target = Number(element.dataset.fitWidth)
        // offsetWidth is the untransformed width, so this stays correct on a
        // re-run without having to clear the transform first.
        const natural = element.offsetWidth
        element.style.transform =
          natural > 0 && target > 0 ? `scaleX(${target / natural})` : ''
      }
    }

    fit()
    let cancelled = false
    void document.fonts?.ready.then(() => {
      if (!cancelled) fit()
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return ref
}

// --- reflow: reading order at a readable size --------------------------------

function ReflowPage({
  nodes,
  bodySize,
  pageWidth,
  margins,
  selection,
  onSelectCell,
}: {
  nodes: FlowNode[]
  bodySize: number
  pageWidth: number
  margins?: BBox
  selection: PageSelection | null
  onSelectCell: (cell: TableCell, table: TableDetail) => void
}) {
  if (!nodes.length) {
    return <Placeholder>This page is blank.</Placeholder>
  }

  return (
    <article className="mx-auto max-w-4xl space-y-3 rounded-md border bg-background p-6 shadow-sm">
      {nodes.map((node) => {
        if (node.kind === 'image') {
          return (
            <div
              key={node.id}
              className="flex items-center gap-2 rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground"
            >
              <ImageIcon className="size-4" /> Image
            </div>
          )
        }
        if (node.kind === 'text') {
          return (
            <ReflowBlock
              key={node.id}
              block={node.block}
              bodySize={bodySize}
              alignment={blockAlignment(node.bbox, pageWidth, margins)}
            />
          )
        }
        return (
          <ReflowTable
            key={node.id}
            table={node.table}
            selectedCell={cellIn(selection, node.table)}
            onSelectCell={onSelectCell}
          />
        )
      })}
    </article>
  )
}

function ReflowBlock({
  block,
  bodySize,
  alignment,
}: {
  block: PageBlock
  bodySize: number
  alignment: Alignment
}) {
  const level = headingLevel(block, bodySize)
  const lines = block.lines ?? []

  return (
    <div
      className={cn(
        'whitespace-pre-wrap break-words',
        alignment === 'center' && 'text-center',
        alignment === 'right' && 'text-right',
        level > 0 && 'font-semibold tracking-tight',
        level === 1 && 'mt-4',
        level === 2 && 'mt-3',
      )}
    >
      {lines.map((line, index) => {
        const style = lineStyle(line)
        const span = dominantSpan(line)
        return (
          <p
            key={index}
            style={{
              fontSize: reflowSize(style.size, bodySize),
              fontWeight: style.bold ? 600 : undefined,
              fontStyle: style.italic ? 'italic' : undefined,
              fontFamily: style.mono ? 'var(--font-mono)' : undefined,
            }}
            className="leading-snug"
          >
            {span && line.spans.length === 1
              ? span.text
              : line.spans.map((part, partIndex) => {
                  const partStyle = spanStyle(part)
                  return (
                    <span
                      key={partIndex}
                      style={{
                        fontSize:
                          partStyle.size === style.size
                            ? undefined
                            : reflowSize(partStyle.size, bodySize),
                        fontWeight: partStyle.bold ? 600 : undefined,
                        fontStyle: partStyle.italic ? 'italic' : undefined,
                      }}
                    >
                      {part.text}
                    </span>
                  )
                })}
          </p>
        )
      })}
    </div>
  )
}

/** Point sizes mapped onto readable pixels, keeping the page's own hierarchy. */
export function reflowSize(size: number, bodySize: number): number {
  if (bodySize <= 0) return REFLOW_BODY_PX
  const scaled = (size / bodySize) * REFLOW_BODY_PX
  return Math.round(Math.min(Math.max(scaled, 11), 30) * 10) / 10
}

function ReflowTable({
  table,
  selectedCell,
  onSelectCell,
}: {
  table: TableDetail
  selectedCell: TableCell | null
  onSelectCell: (cell: TableCell, table: TableDetail) => void
}) {
  const grid = useMemo(() => buildGrid(table), [table])
  const headerRows = useMemo(() => headerRowCount(table), [table])

  return (
    <figure className="my-4 overflow-x-auto rounded-md border">
      <table className="w-full border-collapse text-[12px]">
        <tbody>
          {Array.from({ length: grid.rows }, (_, row) => (
            <tr key={row} className={row >= headerRows ? 'hover:bg-accent/40' : undefined}>
              {Array.from({ length: grid.columns }, (_, column) => {
                if (grid.covered[row]?.[column]) return null
                const cell = grid.origins[row]?.[column]
                const isHeader = row < headerRows
                const Tag = isHeader ? 'th' : 'td'
                if (!cell) {
                  return <Tag key={column} className="border-b border-r border-grid-rule" />
                }
                const numeric = !isHeader && toNumber(cell.text) !== null
                const selected =
                  selectedCell?.row === cell.row && selectedCell?.column === cell.column
                const orphan = cell.text.trim() !== '' && cell.text_source.source === 'azure_di'
                const tone = confidenceTone(cell.confidence)

                return (
                  <Tag
                    key={column}
                    data-testid="reflow-cell"
                    scope={isHeader ? 'col' : undefined}
                    rowSpan={cell.row_span > 1 ? cell.row_span : undefined}
                    colSpan={cell.column_span > 1 ? cell.column_span : undefined}
                    onClick={() => onSelectCell(cell, table)}
                    className={cn(
                      'cursor-pointer border-b border-r border-grid-rule px-1.5 py-1 align-top',
                      isHeader
                        ? 'bg-muted/50 text-left text-[11px] font-medium leading-tight'
                        : 'font-normal',
                      numeric && 'text-right font-mono tabular-nums',
                      orphan && !selected && 'text-reported-strong',
                      tone === 'poor' && !selected && 'underline decoration-destructive/60',
                      selected &&
                        'bg-selected-wash outline outline-2 -outline-offset-2 outline-selected',
                    )}
                  >
                    {cell.text}
                  </Tag>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <figcaption className="border-t bg-card px-2 py-1 font-mono text-[10px] text-muted-foreground">
        {table.caption ?? table.id} · {table.row_count}×{table.column_count}
      </figcaption>
    </figure>
  )
}

function ModeButton({
  active,
  onClick,
  label,
  hint,
  children,
}: {
  active: boolean
  onClick: () => void
  label: string
  hint: string
  children: React.ReactNode
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          aria-pressed={active}
          onClick={onClick}
          className={cn(
            'rounded p-1 transition-colors',
            'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring',
            active
              ? 'bg-secondary text-secondary-foreground'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-medium">{label}</p>
        <p className="text-xs opacity-90">{hint}</p>
      </TooltipContent>
    </Tooltip>
  )
}

function Placeholder({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn('flex flex-1 items-center justify-center p-8 text-center', className)}
    >
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  )
}

export function PageDocumentSkeleton() {
  return (
    <div className="flex flex-1 items-center justify-center">
      <Loader2 className="size-4 animate-spin text-muted-foreground" />
    </div>
  )
}
