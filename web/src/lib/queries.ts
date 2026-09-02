/** Query options shared by route loaders and components. */

import { queryOptions } from '@tanstack/react-query'

import { api } from './api'

export const documentKeys = {
  all: ['documents'] as const,
  list: () => [...documentKeys.all, 'list'] as const,
  detail: (id: string) => [...documentKeys.all, id] as const,
  pages: (id: string) => [...documentKeys.detail(id), 'pages'] as const,
  page: (id: string, n: number) => [...documentKeys.pages(id), n] as const,
  tables: (id: string) => [...documentKeys.detail(id), 'tables'] as const,
  table: (id: string, tableId: string) => [...documentKeys.tables(id), tableId] as const,
}

export const documentsQuery = () =>
  queryOptions({ queryKey: documentKeys.list(), queryFn: () => api.listDocuments() })

export const documentQuery = (id: string) =>
  queryOptions({
    queryKey: documentKeys.detail(id),
    queryFn: () => api.getDocument(id),
    // While extraction runs the status changes without user action.
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'processing' ? 2000 : false
    },
  })

export const tablesQuery = (id: string) =>
  queryOptions({ queryKey: documentKeys.tables(id), queryFn: () => api.listTables(id) })

export const tableQuery = (documentId: string, tableId: string) =>
  queryOptions({
    queryKey: documentKeys.table(documentId, tableId),
    queryFn: () => api.getTable(documentId, tableId),
    // A table's cells never change once extracted.
    staleTime: Infinity,
  })

/** Only the word list: the rest of a page's content is not needed for overlays. */
export const pageWordsQuery = (documentId: string, pageNumber: number) =>
  queryOptions({
    queryKey: [...documentKeys.page(documentId, pageNumber), 'words'],
    queryFn: () => api.getPage(documentId, pageNumber, ['words']),
    staleTime: Infinity,
  })

/**
 * Text blocks with their lines, spans, and coordinates - what the full-page
 * view rebuilds the page from. `words` is deliberately left out: the block
 * tree already carries every character, and asking for both would double the
 * largest part of the response.
 *
 * `include` filters the *content* blob only; the page's plain text is its own
 * column and comes back either way, so asking for it here is an error.
 */
export const pageBlocksQuery = (documentId: string, pageNumber: number) =>
  queryOptions({
    queryKey: [...documentKeys.page(documentId, pageNumber), 'blocks'],
    queryFn: () => api.getPage(documentId, pageNumber, ['blocks']),
    staleTime: Infinity,
  })
