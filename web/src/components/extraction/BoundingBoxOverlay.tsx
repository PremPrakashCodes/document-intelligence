import { cn } from '@/lib/utils'
import type { BBox, PageGeometry } from '@/lib/types'

/**
 * Positions boxes over a rendered page image.
 *
 * Coordinates are expressed as a **percentage of the page box**, not as pixels.
 * That is deliberate: PyMuPDF rounds a pixmap up to whole pixels (a 841.68pt
 * page at scale 2 renders 1684px wide, not 1683.36), so multiplying a
 * coordinate by the render scale drifts by up to a pixel at the right and
 * bottom edges. A fraction of the page box is exact at every zoom level and
 * survives the image being displayed at any CSS size.
 */

export type OverlayKind = 'table' | 'cell' | 'text'

export interface OverlayBox {
  id: string
  bbox: BBox
  kind: OverlayKind
  label?: string
  active?: boolean
}

export function toPercentRect(bbox: BBox, geometry: PageGeometry) {
  const [x0, y0, x1, y1] = bbox
  return {
    left: `${(x0 / geometry.width) * 100}%`,
    top: `${(y0 / geometry.height) * 100}%`,
    width: `${((x1 - x0) / geometry.width) * 100}%`,
    height: `${((y1 - y0) / geometry.height) * 100}%`,
  }
}

const KIND_STYLES: Record<OverlayKind, string> = {
  // The whole table region: a calm frame that does not fight the page.
  table: 'border-sky-500/70 bg-sky-500/5',
  // The selected cell as Azure bounded it.
  cell: 'border-violet-500 bg-violet-500/15',
  // The exact PyMuPDF words inside that cell - the tightest, truest box.
  text: 'border-emerald-500 bg-emerald-400/25',
}

export function BoundingBoxOverlay({
  boxes,
  geometry,
  className,
}: {
  boxes: OverlayBox[]
  geometry: PageGeometry
  className?: string
}) {
  return (
    <div className={cn('pointer-events-none absolute inset-0', className)} aria-hidden>
      {boxes.map((box) => (
        <div
          key={box.id}
          data-testid={`overlay-${box.kind}`}
          data-active={box.active ? 'true' : undefined}
          className={cn(
            'absolute rounded-[2px] border transition-[left,top,width,height] duration-200',
            KIND_STYLES[box.kind],
            box.active && 'ring-2 ring-offset-1 ring-offset-transparent',
            box.active && box.kind === 'text' && 'ring-emerald-400/60',
            box.active && box.kind === 'cell' && 'ring-violet-400/60',
          )}
          style={toPercentRect(box.bbox, geometry)}
        >
          {box.label ? (
            <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-sky-600 px-1.5 py-0.5 text-[10px] font-medium text-white shadow-sm">
              {box.label}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  )
}
