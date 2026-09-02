import { useEffect, useState } from 'react'

/**
 * Tracks a media query in JS.
 *
 * Used instead of rendering both layouts and hiding one with CSS: the table
 * pane mounts hundreds of cells and issues its own query, so a `hidden lg:flex`
 * pair would build and fetch the whole grid twice on every view.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(query).matches,
  )

  useEffect(() => {
    const list = window.matchMedia(query)
    const onChange = () => setMatches(list.matches)
    onChange()
    list.addEventListener('change', onChange)
    return () => list.removeEventListener('change', onChange)
  }, [query])

  return matches
}
