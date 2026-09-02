/**
 * Typed client for the documents API.
 *
 * Vite proxies `/api/*` to the FastAPI server in development, so the default
 * base URL is relative; `VITE_API_URL` points at a deployed API instead.
 */

import type {
  DocumentDetail,
  DocumentSummary,
  PageDetail,
  PageSummary,
  Paginated,
  TableDetail,
  TableSummary,
  UploadResponse,
} from './types'

const BASE = import.meta.env.VITE_API_URL ?? '/api'

export class ApiError extends Error {
  // Declared rather than a constructor parameter property: the tsconfig sets
  // `erasableSyntaxOnly`, which forbids syntax that emits runtime code.
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return (await response.json()) as T
}

/** FastAPI puts the reason in `detail`; fall back to the status text. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  } catch {
    // Not JSON - an upstream proxy error, most likely.
  }
  return response.statusText || `Request failed with ${response.status}`
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value))
  }
  const rendered = search.toString()
  return rendered ? `?${rendered}` : ''
}

export const api = {
  listDocuments: (limit = 50, offset = 0) =>
    request<Paginated<DocumentSummary>>(`/documents${query({ limit, offset })}`),

  getDocument: (id: string) => request<DocumentDetail>(`/documents/${id}`),

  deleteDocument: (id: string) =>
    request<void>(`/documents/${id}`, { method: 'DELETE' }).catch((error) => {
      // 204 has no body, so the JSON parse above throws on success.
      if (error instanceof SyntaxError) return
      throw error
    }),

  listPages: (id: string, limit = 200, offset = 0) =>
    request<Paginated<PageSummary>>(`/documents/${id}/pages${query({ limit, offset })}`),

  /** `include` trims the response; the overlay only ever needs `words`. */
  getPage: (id: string, pageNumber: number, include?: string[]) =>
    request<PageDetail>(
      `/documents/${id}/pages/${pageNumber}${include ? `?${include.map((k) => `include=${k}`).join('&')}` : ''}`,
    ),

  listTables: (id: string, pageNumber?: number) =>
    request<Paginated<TableSummary>>(
      `/documents/${id}/tables${query({ limit: 200, page_number: pageNumber })}`,
    ),

  getTable: (id: string, tableId: string) =>
    request<TableDetail>(`/documents/${id}/tables/${tableId}`),

  upload: async (file: File): Promise<UploadResponse> => {
    const body = new FormData()
    body.append('file', file)
    const response = await fetch(`${BASE}/documents`, { method: 'POST', body })
    if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
    return (await response.json()) as UploadResponse
  },

  reextract: (id: string) =>
    request<UploadResponse>(`/documents/${id}/extract`, { method: 'POST' }),

  /** URL of the rendered page image - used as an <img src>, not fetched. */
  pageImageUrl: (id: string, pageNumber: number, scale: number) =>
    `${BASE}/documents/${id}/pages/${pageNumber}/render${query({ scale })}`,

  fileUrl: (id: string) => `${BASE}/documents/${id}/file`,
}
