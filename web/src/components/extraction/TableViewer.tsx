import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Copy } from 'lucide-react'

import { cn } from '@/lib/utils'
import type { TableCell as CellType, TableDetail } from '@/lib/types'
import { LOW_CONFIDENCE, confidenceTone } from './ConfidenceIndicator'
import { TableMetadata } from './TableMetadata'
import { TableToolbar } from './TableToolbar'
import {
  buildGrid,
  cellKey,
  columnGroups,
  findMatches,
  groupIndexByColumn,
  headerRowCount,
  matchesQuery,
  rowValues,
  sortRowIndices,
  stubColumnCount,
  stubLayout,
  toNumber,
  toTsv,
  unverifiedCells,
  type SortDirection,
} from './tableGrid'

/**
 * A spreadsheet-like view of one extracted table.
 *
 * The grid scrolls as one piece: no frozen header row and no pinned label
 * column, so what you see is the table exactly as the document lays it out.
 *
 * **Columns are banded by group.** `Fire`, `Marine`, `Miscellaneous` and `Total`
 * each cover several period columns, and the banding comes from Azure's own
 * header spans — real structure, not decoration. With nineteen columns of
 * similar figures it is what keeps the grid from reading as one wall, and it
 * does the orienting work that a pinned column otherwise would.
 */

const GUTTER_WIDTH = 26

export function TableViewer({
  table,
  selectedCell,
  onSelectCell,
  className,
}: {
  table: TableDetail
  selectedCell: CellType | null
  onSelectCell: (cell: CellType | null) => void
  className?: string
}) {
  const [query, setQuery] = useState('')
  const [activeMatch, setActiveMatch] = useState(0)
  const [sort, setSort] = useState<{ column: number; direction: SortDirection } | null>(null)
  const [copied, setCopied] = useState(false)
  const [copiedRow, setCopiedRow] = useState<number | null>(null)
  const [reviewIndex, setReviewIndex] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)

  const grid = useMemo(() => buildGrid(table), [table])
  const headerRows = useMemo(() => headerRowCount(table), [table])
  const stubColumns = useMemo(() => stubColumnCount(table), [table])
  const groups = useMemo(() => columnGroups(table, stubColumns), [table, stubColumns])
  const groupOf = useMemo(
    () => groupIndexByColumn(groups, grid.columns),
    [groups, grid.columns],
  )
  const stubs = useMemo(
    () => stubLayout(grid.origins, stubColumns, GUTTER_WIDTH),
    [grid.origins, stubColumns],
  )
  const matches = useMemo(() => findMatches(table.cells, query), [table.cells, query])
  const unverified = useMemo(() => unverifiedCells(table.cells), [table.cells])

  const rowOrder = useMemo(() => {
    const header = Array.from({ length: headerRows }, (_, i) => i)
    const body = Array.from({ length: grid.rows - headerRows }, (_, i) => i + headerRows)
    if (!sort) return [...header, ...body]
    return [...header, ...sortRowIndices(body, grid.origins, sort.column, sort.direction)]
  }, [grid, headerRows, sort])

  const scrollTo = useCallback((cell: CellType) => {
    scrollRef.current
      ?.querySelector<HTMLElement>(`[data-cell="${cellKey(cell)}"]`)
      ?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
  }, [])

  useEffect(() => setActiveMatch(0), [query])

  useEffect(() => {
    const match = matches[activeMatch]
    if (!match) return
    onSelectCell(match)
    scrollTo(match)
  }, [matches, activeMatch, onSelectCell, scrollTo])

  const stepMatch = useCallback(
    (delta: number) => {
      if (!matches.length) return
      setActiveMatch((current) => (current + delta + matches.length) % matches.length)
    },
    [matches.length],
  )

  /** Walk the cells that were not confirmed against the PDF — the review queue. */
  const stepReview = useCallback(
    (delta: number) => {
      if (!unverified.length) return
      const next = (reviewIndex + delta + unverified.length) % unverified.length
      setReviewIndex(next)
      onSelectCell(unverified[next])
      scrollTo(unverified[next])
    },
    [unverified, reviewIndex, onSelectCell, scrollTo],
  )

  const copy = useCallback((text: string) => {
    void navigator.clipboard?.writeText(text)
  }, [])

  const copyTable = useCallback(() => {
    copy(toTsv(rowOrder.map((row) => rowValues(grid.origins, row, grid.columns))))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [copy, grid, rowOrder])

  const copyRow = useCallback(
    (rowIndex: number) => {
      copy(toTsv([rowValues(grid.origins, rowIndex, grid.columns)]))
      setCopiedRow(rowIndex)
      setTimeout(() => setCopiedRow(null), 1200)
    },
    [copy, grid],
  )

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (!selectedCell) return
      const deltas: Record<string, [number, number]> = {
        ArrowUp: [-1, 0],
        ArrowDown: [1, 0],
        ArrowLeft: [0, -1],
        ArrowRight: [0, 1],
      }
      const delta = deltas[event.key]
      if (delta) {
        event.preventDefault()
        const row = Math.min(Math.max(selectedCell.row + delta[0], 0), grid.rows - 1)
        const column = Math.min(Math.max(selectedCell.column + delta[1], 0), grid.columns - 1)
        const next = grid.origins[row]?.[column]
        if (next) {
          onSelectCell(next)
          scrollTo(next)
        }
      }
      if (event.key === 'c' && (event.metaKey || event.ctrlKey)) copy(selectedCell.text)
      if (event.key === 'Escape') onSelectCell(null)
    },
    [selectedCell, grid, onSelectCell, copy, scrollTo],
  )

  return (
    <div className={cn('flex min-h-0 flex-col bg-card', className)}>
      <TableToolbar
        query={query}
        onQueryChange={setQuery}
        matchCount={matches.length}
        activeMatch={activeMatch}
        onStepMatch={stepMatch}
        onCopyTable={copyTable}
        copied={copied}
        unverifiedCount={unverified.length}
        onStepReview={stepReview}
      />

      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-auto focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
        tabIndex={0}
        onKeyDown={onKeyDown}
        role="region"
        aria-label={`Table ${table.id}. Use the arrow keys to move between cells.`}
      >
        <table className="w-max border-separate border-spacing-0 text-[13px]">
          <colgroup>
            <col style={{ width: GUTTER_WIDTH }} />
            {stubs.map((stub) => (
              <col key={stub.column} style={{ width: stub.width }} />
            ))}
          </colgroup>
          <tbody>
            {rowOrder.map((rowIndex, displayIndex) => {
              const isHeader = displayIndex < headerRows
              const isLastHeader = displayIndex === headerRows - 1
              return (
                <tr key={rowIndex} className={cn(!isHeader && 'group/row hover:bg-accent/40')}>
                  {/* A row handle, not a row number. Many of these tables
                      carry their own serial column, and a second count beside
                      it reads as data — "4" in the gutter next to "2" in the
                      document is a contradiction the reader has to resolve.
                      The handle stays blank until hovered, then offers copy. */}
                  <th
                    scope="row"
                    className={cn(
                      'border-b border-r-2 border-b-grid-rule border-r-border bg-card',
                      'px-0 text-center align-middle font-normal',
                    )}
                  >
                    {isHeader ? null : (
                      <button
                        type="button"
                        title={`Copy row ${rowIndex + 1}`}
                        aria-label={`Copy row ${rowIndex + 1}`}
                        onClick={() => copyRow(rowIndex)}
                        className="rounded p-0.5 text-muted-foreground opacity-0 hover:text-foreground focus-visible:opacity-100 focus-visible:outline-1 focus-visible:outline-ring group-hover/row:opacity-100"
                      >
                        <Copy
                          className={cn('size-3', copiedRow === rowIndex && 'text-confirmed')}
                        />
                      </button>
                    )}
                  </th>

                  {Array.from({ length: grid.columns }, (_, column) => {
                    if (grid.covered[rowIndex]?.[column]) return null
                    const cell = grid.origins[rowIndex]?.[column]
                    const stub = stubs.find((entry) => entry.column === column)
                    const group = groupOf[column]
                    const banded = group >= 0 && group % 2 === 1

                    if (!cell) {
                      return (
                        <td
                          key={column}
                          className={cn(
                            'min-w-[5.5rem] border-b border-r border-grid-rule',
                            banded && 'bg-group-wash',
                          )}
                        />
                      )
                    }

                    return (
                      <TableCellView
                        key={column}
                        cell={cell}
                        isHeader={isHeader}
                        isLastHeader={isLastHeader}
                        isStub={Boolean(stub)}
                        banded={banded}
                        isGroupStart={groups.some((entry) => entry.start === column)}
                        selected={
                          selectedCell?.row === cell.row && selectedCell?.column === cell.column
                        }
                        isMatch={matchesQuery(cell, query)}
                        isActiveMatch={matches[activeMatch] === cell}
                        sortDirection={
                          isHeader && sort?.column === cell.column ? sort.direction : undefined
                        }
                        onSelect={() => onSelectCell(cell)}
                        onSort={
                          isHeader
                            ? () =>
                                setSort((current) =>
                                  current?.column === cell.column && current.direction === 'asc'
                                    ? { column: cell.column, direction: 'desc' }
                                    : current?.column === cell.column
                                      ? null
                                      : { column: cell.column, direction: 'asc' },
                                )
                            : undefined
                        }
                      />
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <TableMetadata table={table} cells={table.cells} />
    </div>
  )
}

function TableCellView({
  cell,
  isHeader,
  isLastHeader,
  isStub,
  banded,
  isGroupStart,
  selected,
  isMatch,
  isActiveMatch,
  sortDirection,
  onSelect,
  onSort,
}: {
  cell: CellType
  isHeader: boolean
  isLastHeader: boolean
  isStub: boolean
  banded: boolean
  isGroupStart: boolean
  selected: boolean
  isMatch: boolean
  isActiveMatch: boolean
  sortDirection?: SortDirection
  onSelect: () => void
  onSort?: () => void
}) {
  const numeric = toNumber(cell.text) !== null
  const unverified = cell.text.trim() !== '' && cell.text_source.source === 'azure_di'
  const lowConfidence = cell.confidence !== null && cell.confidence < LOW_CONFIDENCE
  const tone = confidenceTone(cell.confidence)
  const Tag = isHeader ? 'th' : 'td'

  return (
    <Tag
      data-cell={`${cell.row}:${cell.column}`}
      data-testid="table-cell"
      scope={isHeader ? 'col' : undefined}
      rowSpan={cell.row_span > 1 ? cell.row_span : undefined}
      colSpan={cell.column_span > 1 ? cell.column_span : undefined}
      onClick={onSelect}
      className={cn(
        'relative min-w-[5.5rem] cursor-pointer border-b border-r border-grid-rule px-2 py-1 align-top',
        // A heavier rule where a new column group begins, so the four-column
        // blocks Azure found are legible as blocks.
        isGroupStart && 'border-l border-l-border',
        banded && !selected && 'bg-group-wash',
        isHeader
          ? cn(
              'bg-card text-left text-[11px] font-medium leading-tight tracking-tight',
              isLastHeader && 'border-b-2 border-b-border',
            )
          : 'font-normal',
        isStub && 'bg-card',
        numeric && !isHeader && 'text-right font-mono tabular-nums',
        // Selection is the loudest state: it is what the page overlay is
        // currently framing.
        selected && 'bg-selected-wash outline outline-2 -outline-offset-2 outline-selected',
        isMatch && !isActiveMatch && !selected && 'bg-hit',
        isActiveMatch && !selected && 'bg-hit-active',
      )}
    >
      <div className={cn('flex items-start gap-1', numeric && !isHeader && 'justify-end')}>
        <span className="min-w-0 break-words">{cell.text}</span>
        {isHeader && onSort ? (
          <button
            type="button"
            aria-label={`Sort by ${cell.text || `column ${cell.column + 1}`}`}
            className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground opacity-0 transition-opacity hover:bg-accent focus-visible:opacity-100 focus-visible:outline-1 focus-visible:outline-ring [th:hover_&]:opacity-100"
            onClick={(event) => {
              event.stopPropagation()
              onSort()
            }}
          >
            {sortDirection === 'desc' ? (
              <ArrowDown className="size-3" />
            ) : (
              <ArrowUp className={cn('size-3', sortDirection === undefined && 'opacity-50')} />
            )}
          </button>
        ) : null}
      </div>

      {/* Provenance marks: only the exceptions are marked. Decorating all 539
          cells would hide the handful that need a human. */}
      {(unverified || lowConfidence) && !isHeader ? (
        <span className="pointer-events-none absolute right-0 top-0 flex">
          {unverified ? (
            <span
              data-testid="mark-unverified"
              title="Azure's reading — not confirmed against the PDF text layer"
              className="size-0 border-l-[6px] border-t-[6px] border-l-transparent border-t-reported"
            />
          ) : null}
          {lowConfidence && !unverified ? (
            <span
              data-testid="mark-low-confidence"
              title={`Low confidence: ${Math.round((cell.confidence ?? 0) * 100)}%`}
              className={cn(
                'size-0 border-l-[6px] border-t-[6px] border-l-transparent',
                tone === 'poor' ? 'border-t-destructive' : 'border-t-reported',
              )}
            />
          ) : null}
        </span>
      ) : null}
    </Tag>
  )
}
