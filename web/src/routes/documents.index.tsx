import { useMemo, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, FileSearch, FileText, Search, SlidersHorizontal } from 'lucide-react'

import { DocumentStatusBadge } from '@/components/extraction/DocumentStatusBadge'
import { UploadDropzone } from '@/components/extraction/UploadDropzone'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { formatBytes, formatDocumentDate } from '@/lib/format'
import { documentsQuery } from '@/lib/queries'
import type { DocumentStatus } from '@/lib/types'

export const Route = createFileRoute('/documents/')({
  component: DocumentsPage,
})

function DocumentsPage() {
  const { data, isError, isLoading } = useQuery(documentsQuery())
  const documents = data?.items ?? []
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<DocumentStatus | 'all'>('all')
  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase()
    return documents.filter(
      (document) =>
        (status === 'all' || document.status === status) &&
        (!normalizedQuery || document.filename.toLocaleLowerCase().includes(normalizedQuery)),
    )
  }, [documents, query, status])

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <header className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Documents</h1>
          <Badge variant="secondary">{data?.total ?? 0}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Manage your PDFs, monitor extraction, and open any result for source-level review.
        </p>
      </header>

      <Card size="sm">
        <CardHeader>
          <CardTitle>Add a document</CardTitle>
          <CardDescription>Start a new table extraction from a scanned or digital PDF.</CardDescription>
        </CardHeader>
        <CardContent>
          <UploadDropzone compact />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Document library</CardTitle>
          <CardDescription>Search and filter every file in this workspace.</CardDescription>
        </CardHeader>
        <CardContent className="-mb-(--card-spacing)">
          <div className="mb-4 flex flex-col gap-2 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by filename..."
                className="pl-8"
                aria-label="Search documents by filename"
              />
            </div>
            <Select value={status} onValueChange={(value) => setStatus(value as DocumentStatus | 'all')}>
              <SelectTrigger className="w-full sm:w-44" aria-label="Filter documents by status">
                <SlidersHorizontal />
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="completed">Ready</SelectItem>
                  <SelectItem value="processing">Extracting</SelectItem>
                  <SelectItem value="pending">Queued</SelectItem>
                  <SelectItem value="partial">Text only</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </div>

          {isLoading ? (
            <div className="flex flex-col gap-2 border-t py-4">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : filtered.length ? (
            <div className="-mx-(--card-spacing) overflow-hidden border-t">
              <div className="hidden grid-cols-[2.25rem_minmax(0,1fr)_7rem_8rem_7rem_1.5rem] gap-4 bg-muted/45 px-5 py-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground md:grid">
                <span className="col-span-2">Document</span>
                <span>Size</span>
                <span>Uploaded</span>
                <span>Status</span>
                <span className="sr-only">Open</span>
              </div>
              <ul className="divide-y">
                {filtered.map((document) => (
                  <li key={document.id}>
                    <Link
                      to="/documents/$documentId"
                      params={{ documentId: document.id }}
                      className="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3.5 transition-colors hover:bg-muted/45 sm:px-5 md:grid-cols-[auto_minmax(0,1fr)_7rem_8rem_7rem_1.5rem] md:gap-4"
                    >
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background text-muted-foreground">
                        <FileText className="size-4" />
                      </span>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium group-hover:text-primary">{document.filename}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground md:hidden">
                          {document.page_count} page{document.page_count === 1 ? '' : 's'} · {formatBytes(document.file_size)}
                        </p>
                        <p className="hidden text-xs text-muted-foreground md:block">
                          {document.page_count} page{document.page_count === 1 ? '' : 's'}
                        </p>
                      </div>
                      <span className="hidden font-mono text-xs text-muted-foreground md:block">
                        {formatBytes(document.file_size)}
                      </span>
                      <span className="hidden text-xs text-muted-foreground md:block">
                        {formatDocumentDate(document.created_at)}
                      </span>
                      <DocumentStatusBadge status={document.status} />
                      <ArrowRight className="hidden size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 md:block" />
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <Empty className="min-h-64 border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileSearch />
                </EmptyMedia>
                <EmptyTitle>
                  {isError ? 'Could not load documents' : documents.length ? 'No documents found' : 'No documents yet'}
                </EmptyTitle>
                <EmptyDescription>
                  {isError
                    ? 'The document service is not responding. Check the API and try again.'
                    : documents.length
                    ? 'Try another filename or choose a different status filter.'
                    : 'Upload your first PDF above to start extracting traceable table data.'}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
