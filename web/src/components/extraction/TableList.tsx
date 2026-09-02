import { cn } from '@/lib/utils'
import type { TableSummary } from '@/lib/types'

/**
 * The table selector.
 *
 * Deliberately a compact strip rather than a row of cards: a document has a
 * handful of tables, and the earlier card list spent 79px of vertical space —
 * a tenth of a laptop viewport — to say "Table 1, Table 2". The page and the
 * grid are what deserve that space.
 */
export function TableList({
  tables,
  selectedId,
  onSelect,
  className,
}: {
  tables: TableSummary[]
  selectedId: string | null
  onSelect: (table: TableSummary) => void
  className?: string
}) {
  if (tables.length <= 1) return null

  return (
    <div
      className={cn('flex items-center gap-1 overflow-x-auto', className)}
      role="tablist"
      aria-label="Extracted tables"
    >
      {tables.map((table) => {
        const selected = table.id === selectedId
        return (
          <button
            key={table.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onSelect(table)}
            className={cn(
              'flex shrink-0 items-baseline gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors',
              'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring',
              selected
                ? 'border-selected/50 bg-selected-wash text-foreground'
                : 'border-transparent text-muted-foreground hover:border-border hover:text-foreground',
            )}
          >
            <span className="font-medium">
              {table.caption ?? table.id.replace('table_', 'Table ')}
            </span>
            <span className="font-mono text-[10px] opacity-70">
              {table.row_count}×{table.column_count}
            </span>
          </button>
        )
      })}
    </div>
  )
}
