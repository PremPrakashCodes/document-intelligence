/**
 * Zoom arithmetic for the page viewer.
 *
 * Split out from the component because the follow-the-selection maths is the
 * part worth testing: it decides whether a reviewer can actually read the
 * figure they are checking.
 */

import type { BBox, PageGeometry } from '@/lib/types'

/**
 * Render scales the server will be asked for.
 *
 * A fixed ladder rather than a continuous value, so panning between cells
 * reuses a cached page image instead of fetching a fresh render for every
 * fractional zoom. The API clamps at 6.
 */
export const RENDER_STEPS = [1, 1.5, 2, 3, 4, 6] as const

/** Display zoom steps offered by the − / + controls. */
export const ZOOM_STEPS = [0.75, 1, 1.5, 2, 3, 4, 6] as const

/**
 * How much of the page to show around the focused region, as a multiple of its
 * size. Framing a cell edge-to-edge would magnify it hugely and strand the
 * reader with no idea which row or column they are looking at; roughly five
 * times its width keeps the neighbouring labels and figures in view, which is
 * what makes the value checkable rather than merely large.
 */
const CONTEXT_FACTOR = 5

/**
 * The smallest window to show, in PDF points. Without a floor, a one-character
 * cell like a nil dash would zoom past the API's limit and past usefulness.
 */
const MIN_WINDOW_POINTS = 165

export function snapRenderScale(scale: number): number {
  const first = RENDER_STEPS.find((step) => step >= scale)
  return first ?? RENDER_STEPS[RENDER_STEPS.length - 1]
}

export function clampZoom(scale: number): number {
  return Math.min(Math.max(scale, ZOOM_STEPS[0]), ZOOM_STEPS[ZOOM_STEPS.length - 1])
}

/** Display scale that fits the whole page inside `pane`. */
export function fitPageScale(geometry: PageGeometry, pane: { width: number; height: number }): number {
  if (!pane.width || !pane.height) return 1
  return Math.min(pane.width / geometry.width, pane.height / geometry.height)
}

/**
 * Display scale that frames `focus` with enough context to be read.
 *
 * Returns a scale in CSS px per PDF point, so 4 means a 7pt figure renders 28px
 * tall — comfortably readable, which a fit-to-width page never is: this
 * document's landscape page fits a half-pane at 0.91, below 72 dpi.
 */
export function followScale(
  focus: BBox,
  pane: { width: number; height: number },
  { contextFactor = CONTEXT_FACTOR, minWindow = MIN_WINDOW_POINTS } = {},
): number {
  if (!pane.width || !pane.height) return 1

  const focusWidth = Math.max(focus[2] - focus[0], 1)
  const focusHeight = Math.max(focus[3] - focus[1], 1)
  const aspect = pane.height / pane.width

  const windowWidth = Math.max(focusWidth * contextFactor, minWindow)
  const windowHeight = Math.max(focusHeight * contextFactor, minWindow * aspect)

  return clampZoom(Math.min(pane.width / windowWidth, pane.height / windowHeight))
}

/**
 * Scroll offsets that put `focus` in the middle of the pane.
 *
 * Clamped to the scrollable range so a region near an edge still lands as close
 * to centre as the page allows, rather than being pushed off it.
 */
export function centerOn(
  focus: BBox,
  geometry: PageGeometry,
  displayScale: number,
  pane: { width: number; height: number },
  padding = 0,
) {
  const centerX = ((focus[0] + focus[2]) / 2) * displayScale + padding
  const centerY = ((focus[1] + focus[3]) / 2) * displayScale + padding
  const contentWidth = geometry.width * displayScale + padding * 2
  const contentHeight = geometry.height * displayScale + padding * 2

  return {
    left: Math.max(0, Math.min(centerX - pane.width / 2, contentWidth - pane.width)),
    top: Math.max(0, Math.min(centerY - pane.height / 2, contentHeight - pane.height)),
  }
}
