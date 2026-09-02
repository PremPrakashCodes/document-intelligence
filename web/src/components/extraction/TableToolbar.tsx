import { ChevronDown, ChevronUp, Check, Copy, Search, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/**
 * Search, the review queue, and copy.
 *
 * The review queue is the piece that matters. Reading 539 cells to find the two
 * the extractor could not confirm is not a task anyone will actually do, so the
 * toolbar counts them and steps through them. When the count is zero it says so
 * plainly, which is the more common and more reassuring case.
 */
export function TableToolbar({
  query,
  onQueryChange,
  matchCount,
  activeMatch,
  onStepMatch,
  onCopyTable,
  copied,
  unverifiedCount,
  onStepReview,
}: {
  query: string
  onQueryChange: (value: string) => void
  matchCount: number
  activeMatch: number
  onStepMatch: (delta: number) => void
  onCopyTable: () => void
  copied: boolean
  unverifiedCount: number
  onStepReview: (delta: number) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b bg-card px-2 py-1.5">
      <div className="relative min-w-44 flex-1">
        <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search this table"
          aria-label="Search this table"
          className="h-7 pl-7 pr-20 text-[13px]"
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              onStepMatch(event.shiftKey ? -1 : 1)
            }
            if (event.key === 'Escape') onQueryChange('')
          }}
        />
        {query ? (
          <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-0.5">
            <span className="font-mono text-[11px] text-muted-foreground">
              {matchCount ? `${activeMatch + 1}/${matchCount}` : 'none'}
            </span>
            {matchCount > 1 ? (
              <>
                <button
                  type="button"
                  aria-label="Previous match"
                  onClick={() => onStepMatch(-1)}
                  className="rounded p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring"
                >
                  <ChevronUp className="size-3" />
                </button>
                <button
                  type="button"
                  aria-label="Next match"
                  onClick={() => onStepMatch(1)}
                  className="rounded p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring"
                >
                  <ChevronDown className="size-3" />
                </button>
              </>
            ) : null}
            <Button
              variant="ghost"
              size="icon"
              className="size-5"
              aria-label="Clear search"
              onClick={() => onQueryChange('')}
            >
              <X className="size-3" />
            </Button>
          </div>
        ) : null}
      </div>

      <Separator orientation="vertical" className="h-5" />

      <ReviewQueue count={unverifiedCount} onStep={onStepReview} />

      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="sm" className="h-7 gap-1.5 px-2 text-xs" onClick={onCopyTable}>
            {copied ? <Check className="size-3.5 text-confirmed" /> : <Copy className="size-3.5" />}
            {copied ? 'Copied' : 'Copy table'}
          </Button>
        </TooltipTrigger>
        <TooltipContent>Copy the whole table as TSV, ready to paste into a spreadsheet</TooltipContent>
      </Tooltip>
    </div>
  )
}

function ReviewQueue({ count, onStep }: { count: number; onStep: (delta: number) => void }) {
  if (count === 0) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              'flex cursor-help items-center gap-1.5 rounded-md border border-confirmed/30',
              'bg-confirmed-wash px-2 py-1 text-xs text-confirmed-strong',
            )}
          >
            <Check className="size-3.5" />
            All values confirmed
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-72">
          Every populated cell in this table matches the PDF&rsquo;s own text layer.
        </TooltipContent>
      </Tooltip>
    )
  }

  return (
    <div className="flex items-center rounded-md border border-reported/40 bg-reported-wash">
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => onStep(1)}
            className="flex items-center gap-1.5 rounded-l-md px-2 py-1 text-xs text-reported-strong hover:bg-reported/15 focus-visible:outline-1 focus-visible:outline-ring"
          >
            <span className="font-mono font-medium">{count}</span>
            {count === 1 ? 'needs review' : 'need review'}
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-72">
          <p className="font-medium">Cells the PDF text layer could not confirm</p>
          <p className="mt-1 text-xs opacity-90">
            Click to step through them. Usually values only Azure reports, such as checkbox state.
          </p>
        </TooltipContent>
      </Tooltip>
      <div className="flex flex-col border-l border-reported/30">
        <button
          type="button"
          aria-label="Previous cell needing review"
          onClick={() => onStep(-1)}
          className="px-1 text-reported-strong hover:bg-reported/15 focus-visible:outline-1 focus-visible:outline-ring"
        >
          <ChevronUp className="size-3" />
        </button>
        <button
          type="button"
          aria-label="Next cell needing review"
          onClick={() => onStep(1)}
          className="px-1 text-reported-strong hover:bg-reported/15 focus-visible:outline-1 focus-visible:outline-ring"
        >
          <ChevronDown className="size-3" />
        </button>
      </div>
    </div>
  )
}
