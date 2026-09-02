import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Format a 0..1 rate as a percentage that never overstates the result.
 *
 * `Math.round` would turn 519/521 into "100%", claiming a flawless extraction
 * when two cells did not match. For an audit surface that is the wrong
 * direction to round, so anything short of the whole is floored and given a
 * decimal; only a genuine 1.0 prints as "100%".
 */
export function formatRate(rate: number): string {
  if (rate >= 1) return '100%'
  const floored = Math.floor(rate * 1000) / 10
  return `${Number.isInteger(floored) ? floored : floored.toFixed(1)}%`
}
