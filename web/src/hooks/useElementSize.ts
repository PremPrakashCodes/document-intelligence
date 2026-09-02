import { useLayoutEffect, useRef, useState } from 'react'

/** Tracks an element's content-box size. Returns zeroes until first measure. */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return

    const observer = new ResizeObserver(([entry]) => {
      const box = entry.contentRect
      // Round to whole pixels: sub-pixel jitter would otherwise re-request a
      // page render every time a scrollbar appears.
      setSize({ width: Math.round(box.width), height: Math.round(box.height) })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return [ref, size] as const
}
