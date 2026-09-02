import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(cleanup)

// jsdom implements neither, and both are used by the table viewer's
// scroll-to-match and by Radix's popper positioning.
Element.prototype.scrollIntoView = vi.fn()
window.HTMLElement.prototype.scrollTo = vi.fn()

// Radix's popper measures with ResizeObserver, which jsdom does not implement.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver

// navigator.clipboard is getter-only in jsdom, so it cannot be assigned per
// test. Defined once here as a configurable mock; tests read the calls off
// `navigator.clipboard.writeText` and clear it in their own setup.
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
  configurable: true,
  writable: true,
})
