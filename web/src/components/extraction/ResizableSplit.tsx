import { useCallback, useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

/**
 * A two-pane split with a draggable divider.
 *
 * Hand-rolled rather than pulled in: it is a pointer listener and a percentage.
 * The ratio persists per storage key, because the right balance between page
 * and table is a personal, stable preference — someone checking a wide table
 * wants a narrow page pane and should not have to say so on every visit.
 *
 * The divider is a real focusable separator with arrow-key support, so the
 * layout is adjustable without a pointer.
 */
export function ResizableSplit({
  first,
  second,
  storageKey,
  initial = 46,
  min = 22,
  max = 74,
  className,
}: {
  first: React.ReactNode
  second: React.ReactNode
  storageKey: string
  initial?: number
  min?: number
  max?: number
  className?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [percent, setPercent] = useState(() => readStored(storageKey) ?? initial)
  const [dragging, setDragging] = useState(false)

  const clamp = useCallback(
    (value: number) => Math.min(Math.max(value, min), max),
    [min, max],
  )

  useEffect(() => {
    if (!dragging) return

    const onMove = (event: PointerEvent) => {
      const box = containerRef.current?.getBoundingClientRect()
      if (!box) return
      setPercent(clamp(((event.clientX - box.left) / box.width) * 100))
    }
    const onUp = () => setDragging(false)

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    // Stop the drag selecting text across the whole page.
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
  }, [dragging, clamp])

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, String(Math.round(percent)))
    } catch {
      // Private windows and blocked site data: the layout just won't persist.
    }
  }, [percent, storageKey])

  return (
    <div ref={containerRef} className={cn('flex min-h-0 flex-1', className)}>
      <div className="flex min-w-0 flex-col" style={{ width: `${percent}%` }}>
        {first}
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize the page and table panes"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={min}
        aria-valuemax={max}
        tabIndex={0}
        onPointerDown={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') setPercent((value) => clamp(value - 2))
          if (event.key === 'ArrowRight') setPercent((value) => clamp(value + 2))
        }}
        className={cn(
          'group relative w-px shrink-0 cursor-col-resize bg-border',
          'focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring',
        )}
      >
        {/* A one-pixel rule is the right visual weight but an impossible
            pointer target, so the grab area is widened invisibly. */}
        <span className="absolute inset-y-0 -left-1.5 -right-1.5 block" />
        <span
          className={cn(
            'absolute inset-y-0 -left-px -right-px block transition-colors',
            dragging ? 'bg-ring' : 'group-hover:bg-ring/60',
          )}
        />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">{second}</div>
    </div>
  )
}

function readStored(key: string): number | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const value = Number(raw)
    return Number.isFinite(value) ? value : null
  } catch {
    return null
  }
}
