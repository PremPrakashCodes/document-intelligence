import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Crosshair, Loader2, Maximize, Minus, Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useElementSize } from '@/hooks/useElementSize'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { BBox, PageGeometry } from '@/lib/types'
import { BoundingBoxOverlay, type OverlayBox } from './BoundingBoxOverlay'
import {
  ZOOM_STEPS,
  centerOn,
  clampZoom,
  fitPageScale,
  followScale,
  snapRenderScale,
} from './pdfZoom'

/**
 * The rendered page, framed on whatever you have selected.
 *
 * The page image is produced by the same PyMuPDF page object that produced
 * every stored coordinate, in the same display space, so overlays need no
 * calibration and rotated pages need no handling here.
 *
 * **Why it follows the selection.** A landscape filing page fitted to half a
 * screen renders at 0.91 CSS px per point — below 72 dpi, where a 7pt figure is
 * about six pixels tall and unreadable. A viewer that shows the whole page by
 * default therefore fails at the one job it has: letting someone check a number
 * against the original. So `follow` is the default mode. Selecting a table
 * frames the table; selecting a cell zooms to that cell with its neighbours
 * still in view, at a magnification where the digits are legible.
 *
 * `Whole page` remains one click away for orientation.
 */

const PADDING = 16

type Mode = 'follow' | 'page' | 'manual'

export function PdfPageViewer({
  documentId,
  pageNumber,
  geometry,
  boxes,
  focusBox,
  className,
}: {
  documentId: string
  pageNumber: number
  geometry: PageGeometry
  boxes: OverlayBox[]
  /** The region to frame — the selected cell, or the selected table. */
  focusBox?: BBox | null
  className?: string
}) {
  const [scrollRef, pane] = useElementSize<HTMLDivElement>()
  const [mode, setMode] = useState<Mode>('follow')
  const [manualScale, setManualScale] = useState(1)
  const [loaded, setLoaded] = useState(false)
  const imageRef = useRef<HTMLDivElement>(null)

  const viewport = useMemo(
    () => ({ width: Math.max(pane.width - PADDING * 2, 0), height: Math.max(pane.height - PADDING * 2, 0) }),
    [pane.width, pane.height],
  )

  const displayScale = useMemo(() => {
    if (mode === 'manual') return manualScale
    if (mode === 'page' || !focusBox) return fitPageScale(geometry, viewport) || 1
    return followScale(focusBox, viewport)
  }, [mode, manualScale, focusBox, geometry, viewport])

  // Ask for a slightly sharper render than the display size so text stays crisp
  // on a high-density screen, snapped to the ladder so panning reuses the cache.
  const renderScale = useMemo(
    () => snapRenderScale(displayScale * Math.min(window.devicePixelRatio || 1, 2)),
    [displayScale],
  )

  const src = useMemo(
    () => api.pageImageUrl(documentId, pageNumber, renderScale),
    [documentId, pageNumber, renderScale],
  )

  useEffect(() => setLoaded(false), [src])

  const width = geometry.width * displayScale
  const height = geometry.height * displayScale

  // Keep the focused region centred as the selection or the zoom changes.
  useEffect(() => {
    const container = scrollRef.current
    if (!container || !focusBox || mode === 'page' || !viewport.width) return
    const { left, top } = centerOn(focusBox, geometry, displayScale, viewport, PADDING)
    container.scrollTo({ left, top, behavior: loaded ? 'smooth' : 'auto' })
  }, [focusBox, displayScale, mode, geometry, viewport, loaded, scrollRef])

  const stepZoom = useCallback(
    (delta: number) => {
      const current = displayScale
      const next =
        delta > 0
          ? ZOOM_STEPS.find((step) => step > current + 0.01)
          : [...ZOOM_STEPS].reverse().find((step) => step < current - 0.01)
      setManualScale(clampZoom(next ?? current))
      setMode('manual')
    },
    [displayScale],
  )

  const percent = Math.round(displayScale * 100)

  return (
    <div className={cn('flex min-h-0 flex-col bg-muted/30', className)}>
      <div className="flex items-center gap-2 border-b bg-card px-3 py-1.5">
        <span className="text-xs font-medium">Page {pageNumber}</span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {Math.round(geometry.width)}×{Math.round(geometry.height)} pt
          {geometry.rotation ? ` · ${geometry.rotation}°` : ''}
        </span>

        <div className="ml-auto flex items-center gap-1">
          <div className="flex items-center rounded-md border p-0.5">
            <ModeButton
              active={mode === 'follow'}
              onClick={() => setMode('follow')}
              label="Follow selection"
              hint="Zoom to whatever you select in the table, at readable size"
            >
              <Crosshair className="size-3.5" />
            </ModeButton>
            <ModeButton
              active={mode === 'page'}
              onClick={() => setMode('page')}
              label="Whole page"
              hint="Fit the entire page in view"
            >
              <Maximize className="size-3.5" />
            </ModeButton>
          </div>

          <div className="flex items-center">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Zoom out"
              disabled={displayScale <= ZOOM_STEPS[0] + 0.01}
              onClick={() => stepZoom(-1)}
            >
              <Minus className="size-3.5" />
            </Button>
            <span className="w-11 text-center font-mono text-[11px] text-muted-foreground">
              {percent}%
            </span>
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label="Zoom in"
              disabled={displayScale >= ZOOM_STEPS[ZOOM_STEPS.length - 1] - 0.01}
              onClick={() => stepZoom(1)}
            >
              <Plus className="size-3.5" />
            </Button>
          </div>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="relative min-h-0 flex-1 overflow-auto"
        style={{ padding: PADDING }}
      >
        {!loaded ? (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <Loader2 className="size-4 animate-spin text-muted-foreground" />
          </div>
        ) : null}

        <div
          ref={imageRef}
          className={cn(
            'page-surface relative transition-opacity duration-150',
            loaded ? 'opacity-100' : 'opacity-0',
            // Centre the page when it is smaller than the pane.
            'mx-auto',
          )}
          style={{ width, height }}
        >
          <img
            key={src}
            src={src}
            alt={`Page ${pageNumber} of the document`}
            className="block size-full select-none"
            draggable={false}
            onLoad={() => setLoaded(true)}
          />
          <BoundingBoxOverlay boxes={boxes} geometry={geometry} />
        </div>
      </div>
    </div>
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
