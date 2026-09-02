import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/**
 * Cell-level OCR confidence, shown as a bar rather than a number.
 *
 * Azure reports confidence per *word*, so a cell's value is the mean over the
 * words it contains; born-digital PDFs often carry none at all, which is
 * reported as "not reported" rather than silently as zero.
 *
 * The visual is deliberately quiet. On a 539-cell table a number in every cell
 * is noise; what a reviewer needs is to spot the handful of low ones.
 */

/** Below this, a value is worth a human check. */
export const LOW_CONFIDENCE = 0.9
/** Below this, treat it as unreliable. */
export const POOR_CONFIDENCE = 0.7

export function confidenceTone(confidence: number | null): 'none' | 'good' | 'low' | 'poor' {
  if (confidence === null) return 'none'
  if (confidence < POOR_CONFIDENCE) return 'poor'
  if (confidence < LOW_CONFIDENCE) return 'low'
  return 'good'
}

const TONE_COLOR: Record<'good' | 'low' | 'poor', string> = {
  good: 'var(--confirmed)',
  low: 'var(--reported)',
  poor: 'var(--destructive)',
}

export function ConfidenceIndicator({
  confidence,
  showValue = false,
  className,
}: {
  confidence: number | null
  showValue?: boolean
  className?: string
}) {
  const tone = confidenceTone(confidence)

  if (confidence === null) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn('cursor-help font-mono text-[11px] text-muted-foreground', className)}
            data-tone="none"
          >
            not reported
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-72">
          Azure reported no confidence here — usual for text embedded in the PDF rather than read
          from pixels.
        </TooltipContent>
      </Tooltip>
    )
  }

  const percent = Math.round(confidence * 100)

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn('inline-flex cursor-help items-center gap-1.5', className)}
          data-tone={tone}
          aria-label={`Confidence ${percent}%`}
        >
          <span className="h-1 w-7 overflow-hidden rounded-full bg-border">
            <span
              className="block h-full rounded-full"
              style={{
                width: `${Math.max(percent, 4)}%`,
                background: TONE_COLOR[tone as 'good' | 'low' | 'poor'],
              }}
            />
          </span>
          {showValue ? <span className="font-mono text-[11px]">{percent}%</span> : null}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {percent}% mean OCR confidence{tone !== 'good' ? ' — worth checking against the page' : ''}
      </TooltipContent>
    </Tooltip>
  )
}
