import { Check, Copy, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { TableCell, TableSummary } from '@/lib/types'
import { ConfidenceIndicator } from './ConfidenceIndicator'
import { ExtractionSourceBadge } from './ExtractionSourceBadge'

/**
 * The audit trail for one cell.
 *
 * This panel is the point of the whole system: the chosen value, what each
 * extractor independently read, the geometry that joined them, and the numbers
 * behind that decision — so a figure can be trusted, or challenged, on evidence.
 *
 * It sits under the page viewer rather than under the table, because it
 * explains what the highlight on the page is showing.
 */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2 py-0.5">
      <dt className="w-24 shrink-0 text-[11px] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-xs">{children}</dd>
    </div>
  )
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-6 shrink-0"
      aria-label={label}
      onClick={() => {
        void navigator.clipboard?.writeText(value)
        setCopied(true)
        setTimeout(() => setCopied(false), 1200)
      }}
    >
      {copied ? <Check className="size-3 text-confirmed" /> : <Copy className="size-3" />}
    </Button>
  )
}

export function CellDetails({
  cell,
  table,
  onClose,
  className,
}: {
  cell: TableCell
  table: TableSummary
  onClose?: () => void
  className?: string
}) {
  const source = cell.text_source
  const [x0, y0, x1, y1] = cell.bbox
  const disagrees =
    cell.pymupdf_text !== null && cell.pymupdf_text.trim() !== cell.azure_text.trim()

  return (
    <aside className={cn('flex flex-col gap-2.5 p-3', className)} aria-label="Cell details">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[11px] text-muted-foreground">
            {table.id} · row {cell.row + 1} · col {cell.column + 1}
          </p>
          <p className="mt-0.5 break-words font-mono text-base font-medium">
            {cell.text || <span className="font-sans text-muted-foreground">(empty)</span>}
          </p>
        </div>
        <div className="flex shrink-0 items-center">
          <CopyButton value={cell.text} label="Copy cell value" />
          {onClose ? (
            <Button
              variant="ghost"
              size="icon"
              className="size-6"
              aria-label="Close details"
              onClick={onClose}
            >
              <X className="size-3" />
            </Button>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <ExtractionSourceBadge source={source.source} method={source.method} />
        <ConfidenceIndicator confidence={cell.confidence} showValue />
      </div>

      {/* What each source read. The two rows are the evidence; the highlight on
          the page above is the same claim, drawn. */}
      <div className="space-y-1">
        <Reading
          label="PyMuPDF"
          value={cell.pymupdf_text}
          used={source.source === 'pymupdf'}
          hint="the PDF’s own text"
        />
        <Reading
          label="Azure DI"
          value={cell.azure_text}
          used={source.source === 'azure_di'}
          hint="read from the page"
        />
      </div>

      {disagrees ? (
        <p className="rounded-md border border-reported/30 bg-reported-wash px-2 py-1.5 text-[11px] text-reported-strong">
          The sources disagree. The PDF’s own text was kept: it is the literal content of the file
          rather than a reading of it.
        </p>
      ) : null}

      <dl className="border-t pt-2">
        <Field label="Page">{table.page_number}</Field>
        <Field label="Structure">
          Azure DI
          {cell.kind !== 'content' ? ` · ${cell.kind}` : ''}
          {cell.row_span > 1 || cell.column_span > 1
            ? ` · spans ${cell.row_span}×${cell.column_span}`
            : ''}
        </Field>
        <Field label="Matched">
          <span className="font-mono">{(source.containment * 100).toFixed(0)}%</span>
          <span className="ml-1 text-muted-foreground">
            of the text sits inside the cell
            {source.word_count ? ` · ${source.word_count} word${source.word_count === 1 ? '' : 's'}` : ''}
          </span>
        </Field>
        <Field label="IoU">
          <span className="font-mono text-muted-foreground">{source.iou.toFixed(3)}</span>
          <span className="ml-1 text-muted-foreground">diagnostic only, never decides a match</span>
        </Field>
        <Field label="Cell box">
          <span className="font-mono text-[11px]">
            {x0.toFixed(1)}, {y0.toFixed(1)} → {x1.toFixed(1)}, {y1.toFixed(1)}
          </span>
        </Field>
        {source.bbox ? (
          <Field label="Text box">
            <span className="font-mono text-[11px] text-confirmed-strong">
              {source.bbox[0].toFixed(1)}, {source.bbox[1].toFixed(1)} →{' '}
              {source.bbox[2].toFixed(1)}, {source.bbox[3].toFixed(1)}
            </span>
          </Field>
        ) : null}
      </dl>
    </aside>
  )
}

function Reading({
  label,
  value,
  used,
  hint,
}: {
  label: string
  value: string | null
  used: boolean
  hint: string
}) {
  return (
    <div
      className={cn(
        'flex items-baseline gap-2 rounded-md border px-2 py-1',
        used ? 'border-confirmed/35 bg-confirmed-wash' : 'border-border/60',
      )}
    >
      <span className="w-16 shrink-0 text-[11px] text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1 break-words font-mono text-xs">
        {value === null ? (
          <span className="font-sans text-muted-foreground">not present</span>
        ) : value === '' ? (
          <span className="font-sans text-muted-foreground">(empty)</span>
        ) : (
          value
        )}
      </span>
      {used ? (
        <span className="shrink-0 text-[10px] font-medium text-confirmed-strong">used</span>
      ) : (
        <span className="shrink-0 text-[10px] text-muted-foreground">{hint}</span>
      )}
    </div>
  )
}
