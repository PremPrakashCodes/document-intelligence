import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { MatchMethod, Source } from '@/lib/types'

/**
 * Where a value came from, and how sure the join is.
 *
 * The distinction the whole pipeline exists to preserve: `pymupdf` means the
 * characters are literally what the PDF contains; `azure_di` means they are the
 * service's reading of the pixels.
 */

const METHOD_COPY: Record<MatchMethod, { label: string; detail: string }> = {
  exact: {
    label: 'exact',
    detail: 'The PDF text layer and Azure agree on this value character for character.',
  },
  spatial: {
    label: 'spatial',
    detail:
      'The PDF text sits squarely inside the cell but reads differently from Azure. The PDF is the literal content of the file, so it wins.',
  },
  weak: {
    label: 'weak',
    detail:
      'PDF words were found but they hang outside the cell, so Azure’s reading was kept instead.',
  },
  none: {
    label: 'no text layer',
    detail:
      'No PDF text inside this cell — a scanned page, an empty cell, or a value only Azure reports.',
  },
}

export function ExtractionSourceBadge({
  source,
  method,
  className,
  showMethod = true,
}: {
  source: Source
  method?: MatchMethod
  className?: string
  showMethod?: boolean
}) {
  const copy = method ? METHOD_COPY[method] : undefined
  const confirmed = source === 'pymupdf'

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'inline-flex cursor-help items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-[11px]',
            confirmed
              ? 'border-confirmed/35 bg-confirmed-wash text-confirmed-strong'
              : 'border-reported/40 bg-reported-wash text-reported-strong',
            className,
          )}
        >
          <span
            aria-hidden
            className="h-2.5 w-1 rounded-sm"
            style={{ background: confirmed ? 'var(--confirmed)' : 'var(--reported)' }}
          />
          <span className="font-medium">{confirmed ? 'PyMuPDF' : 'Azure DI'}</span>
          {showMethod && copy ? <span className="font-mono opacity-75">{copy.label}</span> : null}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-medium">
          {confirmed ? 'Confirmed against the PDF text layer' : 'From Azure DI'}
        </p>
        {copy ? <p className="mt-1 text-xs opacity-90">{copy.detail}</p> : null}
      </TooltipContent>
    </Tooltip>
  )
}
