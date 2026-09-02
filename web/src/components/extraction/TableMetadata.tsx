import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { TableCell, TableSummary } from '@/lib/types'
import { cn, formatRate } from '@/lib/utils'
import { ConfidenceIndicator } from './ConfidenceIndicator'

/** The status line under a table: what it is, and how well it was resolved. */
export function TableMetadata({
  table,
  cells,
  className,
}: {
  table: TableSummary
  cells: TableCell[]
  className?: string
}) {
  const populated = cells.filter(
    (cell) => cell.text.trim() !== '' || (cell.pymupdf_text ?? '').trim() !== '',
  )
  const verified = populated.filter((cell) => cell.text_source.source === 'pymupdf')
  const rate = populated.length ? verified.length / populated.length : 0
  const [x0, y0, x1, y1] = table.bbox

  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-3 gap-y-1 border-t bg-card px-3 py-1.5 text-[11px] text-muted-foreground',
        className,
      )}
    >
      <span className="font-mono font-medium text-foreground">{table.id}</span>
      <span>Page {table.page_number}</span>
      <span className="font-mono">
        {table.row_count}×{table.column_count}
      </span>

      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help">
            Structure <span className="text-foreground">Azure DI</span>
          </span>
        </TooltipTrigger>
        <TooltipContent>
          Azure DI found the rows, columns, and cell boundaries.
        </TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <span className="flex cursor-help items-center gap-1.5">
            <span
              aria-hidden
              className="h-2.5 w-1 rounded-sm"
              style={{ background: 'var(--confirmed)' }}
            />
            <span className="font-mono text-foreground">
              {verified.length}/{populated.length}
            </span>
            confirmed ({formatRate(rate)})
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-72">
          Cells whose text was confirmed against the PDF&rsquo;s own text layer. The rest are
          Azure&rsquo;s reading — usually values only Azure reports, such as checkbox state.
        </TooltipContent>
      </Tooltip>

      <span className="flex items-center gap-1.5">
        Confidence <ConfidenceIndicator confidence={table.confidence} showValue />
      </span>

      <Tooltip>
        <TooltipTrigger asChild>
          <span className="ml-auto cursor-help font-mono opacity-70">
            {x0.toFixed(0)}, {y0.toFixed(0)} → {x1.toFixed(0)}, {y1.toFixed(0)}
          </span>
        </TooltipTrigger>
        <TooltipContent>Table bounding box in PDF points, top-left origin</TooltipContent>
      </Tooltip>
    </div>
  )
}
