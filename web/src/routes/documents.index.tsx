import { createFileRoute, Link } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { FileText } from 'lucide-react'

import { UploadDropzone } from '@/components/extraction/UploadDropzone'
import { documentsQuery } from '@/lib/queries'
import { cn } from '@/lib/utils'
import type { DocumentStatus } from '@/lib/types'

export const Route = createFileRoute('/documents/')({
  loader: ({ context }) => context.queryClient.ensureQueryData(documentsQuery()),
  component: DocumentsPage,
})

const STATUS: Record<DocumentStatus, { label: string; className: string }> = {
  pending: { label: 'Queued', className: 'text-muted-foreground' },
  processing: { label: 'Extracting', className: 'text-foreground' },
  completed: { label: 'Extracted', className: 'text-confirmed-strong' },
  partial: { label: 'Text only', className: 'text-reported-strong' },
  failed: { label: 'Failed', className: 'text-destructive' },
}

function DocumentsPage() {
  const { data } = useSuspenseQuery(documentsQuery())

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold tracking-tight">Documents</h1>
        <p className="text-sm text-muted-foreground">
          Every table found in each PDF, with each value traceable to where it sits on the page.
        </p>
      </div>

      <UploadDropzone />

      {data.items.length === 0 ? (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Nothing extracted yet. Upload a PDF to see its tables.
        </p>
      ) : (
        <ul className="divide-y overflow-hidden rounded-lg border bg-card">
          {data.items.map((document) => {
            const status = STATUS[document.status]
            return (
              <li key={document.id}>
                <Link
                  to="/documents/$documentId"
                  params={{ documentId: document.id }}
                  className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-accent/50"
                >
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{document.filename}</p>
                    <p className="font-mono text-[11px] text-muted-foreground">
                      {document.page_count} page{document.page_count === 1 ? '' : 's'} ·{' '}
                      {formatBytes(document.file_size)} ·{' '}
                      {new Date(document.created_at).toLocaleDateString(undefined, {
                        day: 'numeric',
                        month: 'short',
                        year: 'numeric',
                      })}
                    </p>
                  </div>
                  <span className={cn('shrink-0 text-xs', status.className)}>{status.label}</span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
