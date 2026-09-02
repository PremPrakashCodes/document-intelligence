import { Suspense } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { AlertCircle, ArrowLeft, ExternalLink, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { DocumentViewer, DocumentViewerSkeleton } from '@/components/extraction/DocumentViewer'
import { api } from '@/lib/api'
import { documentKeys, documentQuery } from '@/lib/queries'
import { formatRate } from '@/lib/utils'

export const Route = createFileRoute('/documents/$documentId')({
  loader: ({ context, params }) =>
    context.queryClient.ensureQueryData(documentQuery(params.documentId)),
  component: DocumentPage,
})

function DocumentPage() {
  const { documentId } = Route.useParams()
  const { data: document } = useSuspenseQuery(documentQuery(documentId))

  const { data: pages } = useQuery({
    queryKey: documentKeys.pages(documentId),
    queryFn: () => api.listPages(documentId),
    // Page geometry only exists once the PDF has been read.
    enabled: document.status !== 'pending' && document.status !== 'processing',
  })

  const matching = document.extraction?.matching

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-3 border-b bg-card px-3 py-1.5">
        <Button variant="ghost" size="icon" className="size-7 shrink-0" asChild>
          <Link to="/documents" aria-label="Back to documents">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>

        <h1 className="min-w-0 truncate text-sm font-medium">{document.filename}</h1>

        <span className="hidden shrink-0 font-mono text-[11px] text-muted-foreground sm:inline">
          {document.page_count} page{document.page_count === 1 ? '' : 's'} · {document.table_count}{' '}
          table{document.table_count === 1 ? '' : 's'}
        </span>

        {matching && matching.content_cells > 0 ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="hidden shrink-0 cursor-help items-center gap-1.5 rounded-md border border-confirmed/30 bg-confirmed-wash px-2 py-0.5 text-[11px] text-confirmed-strong md:inline-flex">
                <span
                  aria-hidden
                  className="h-2.5 w-1 rounded-sm"
                  style={{ background: 'var(--confirmed)' }}
                />
                <span className="font-mono">{formatRate(matching.match_rate)}</span> confirmed
              </span>
            </TooltipTrigger>
            <TooltipContent className="max-w-72">
              <p className="font-medium">
                {matching.matched_cells} of {matching.content_cells} populated cells match the
                PDF&rsquo;s own text layer
              </p>
              <p className="mt-1 text-xs opacity-90">
                {matching.empty_cells} further cells are blank and are not counted.
              </p>
            </TooltipContent>
          </Tooltip>
        ) : null}

        <Button variant="ghost" size="sm" className="ml-auto shrink-0 gap-1.5 text-xs" asChild>
          <a href={api.fileUrl(document.id)} target="_blank" rel="noreferrer">
            Original PDF
            <ExternalLink className="size-3" />
          </a>
        </Button>
      </header>

      {document.status === 'pending' || document.status === 'processing' ? (
        <Pending />
      ) : document.status === 'failed' ? (
        <Failed message={document.error?.message ?? 'This PDF could not be read.'} />
      ) : !pages ? (
        <DocumentViewerSkeleton />
      ) : (
        <Suspense fallback={<DocumentViewerSkeleton />}>
          <DocumentViewer document={document} pages={pages.items} />
        </Suspense>
      )}
    </div>
  )
}

function Pending() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-12 text-center">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
      <p className="text-sm font-medium">Extracting tables</p>
      <p className="max-w-sm text-xs text-muted-foreground">
        Reading the PDF&rsquo;s text and coordinates, then detecting the table structure. This
        updates on its own.
      </p>
    </div>
  )
}

function Failed({ message }: { message: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-12 text-center">
      <AlertCircle className="size-5 text-destructive" />
      <p className="text-sm font-medium">This PDF could not be read</p>
      <p className="max-w-prose text-xs text-muted-foreground">{message}</p>
      <Button variant="outline" size="sm" className="mt-2" asChild>
        <Link to="/documents">Back to documents</Link>
      </Button>
    </div>
  )
}
