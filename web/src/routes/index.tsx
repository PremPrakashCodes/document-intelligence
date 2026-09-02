import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileStack,
  FileText,
  Gauge,
  Layers3,
} from 'lucide-react'

import { DocumentStatusBadge } from '@/components/extraction/DocumentStatusBadge'
import { UploadDropzone } from '@/components/extraction/UploadDropzone'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
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
import { Progress } from '@/components/ui/progress'
import { Separator } from '@/components/ui/separator'
import { formatBytes, formatDocumentDate } from '@/lib/format'
import { documentsQuery } from '@/lib/queries'
import type { DocumentSummary } from '@/lib/types'

export const Route = createFileRoute('/')({
  component: HomePage,
})

function HomePage() {
  const { data, isError, isLoading } = useQuery(documentsQuery())
  const documents = data?.items ?? []
  const completed = documents.filter((document) => document.status === 'completed').length
  const active = documents.filter(
    (document) => document.status === 'pending' || document.status === 'processing',
  ).length
  const needsAttention = documents.filter(
    (document) => document.status === 'partial' || document.status === 'failed',
  ).length
  const totalPages = documents.reduce((sum, document) => sum + document.page_count, 0)
  const successRate = documents.length ? Math.round((completed / documents.length) * 100) : 0

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">
            Extraction workspace
          </p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Overview</h1>
          <p className="text-sm text-muted-foreground">
            Upload, review, and trace every extracted value back to its source.
          </p>
        </div>
        <Button variant="outline" asChild>
          <Link to="/documents">
            View all documents
            <ArrowRight data-icon="inline-end" />
          </Link>
        </Button>
      </header>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4" aria-label="Workspace summary">
        <MetricCard label="Documents" value={documents.length} icon={FileStack} hint="In this workspace" />
        <MetricCard label="Pages processed" value={totalPages} icon={Layers3} hint="Across all documents" />
        <MetricCard
          label="Extraction success"
          value={`${successRate}%`}
          icon={Gauge}
          hint={documents.length ? `${completed} ready to review` : 'No runs yet'}
        />
        <MetricCard
          label="Active jobs"
          value={active}
          icon={Clock3}
          hint={active ? 'Processing automatically' : 'Queue is clear'}
        />
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(18rem,0.75fr)]">
        <Card>
          <CardHeader>
            <CardTitle>New extraction</CardTitle>
            <CardDescription>Upload one PDF and open its extracted tables as soon as processing begins.</CardDescription>
          </CardHeader>
          <CardContent>
            <UploadDropzone compact />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Pipeline health</CardTitle>
            <CardDescription>Current document outcomes</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex items-end justify-between">
              <div>
                <p className="text-3xl font-semibold tracking-tight">{successRate}%</p>
                <p className="text-xs text-muted-foreground">
                  {isLoading ? 'Loading workspace data' : isError ? 'Data service unavailable' : 'Completed successfully'}
                </p>
              </div>
              <CheckCircle2 className="size-5 text-confirmed-strong" />
            </div>
            <Progress value={successRate} aria-label={`${successRate}% completed successfully`} />
            <Separator />
            <div className="flex flex-col gap-3 text-sm">
              <HealthRow icon={CheckCircle2} label="Ready to review" value={completed} />
              <HealthRow icon={Clock3} label="In progress" value={active} />
              <HealthRow icon={CircleAlert} label="Needs attention" value={needsAttention} />
            </div>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Recent documents</CardTitle>
          <CardDescription>Your latest uploads and extraction status.</CardDescription>
          {documents.length > 0 ? (
            <CardAction>
              <Button variant="ghost" size="sm" asChild>
                <Link to="/documents">
                  View all
                  <ArrowRight data-icon="inline-end" />
                </Link>
              </Button>
            </CardAction>
          ) : null}
        </CardHeader>
        <CardContent className="-mb-(--card-spacing)">
          {documents.length ? (
            <div className="-mx-(--card-spacing) divide-y border-t">
              {documents.slice(0, 5).map((document) => (
                <RecentDocument key={document.id} document={document} />
              ))}
            </div>
          ) : (
            <Empty className="min-h-48 border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FileText />
                </EmptyMedia>
                <EmptyTitle>No documents yet</EmptyTitle>
                <EmptyDescription>Your first extraction will appear here after you upload a PDF.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function MetricCard({
  label,
  value,
  icon: Icon,
  hint,
}: {
  label: string
  value: string | number
  icon: typeof FileStack
  hint: string
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardAction>
          <span className="flex size-8 items-center justify-center rounded-lg bg-muted text-muted-foreground">
            <Icon className="size-4" />
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <p className="text-2xl font-semibold tracking-tight sm:text-3xl">{value}</p>
        <p className="truncate text-[11px] text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  )
}

function HealthRow({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof CheckCircle2
  label: string
  value: number
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon className="size-4 text-muted-foreground" />
      <span className="flex-1 text-muted-foreground">{label}</span>
      <span className="font-mono text-xs font-medium">{value}</span>
    </div>
  )
}

function RecentDocument({ document }: { document: DocumentSummary }) {
  return (
    <Link
      to="/documents/$documentId"
      params={{ documentId: document.id }}
      className="group flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-muted/45 sm:px-5"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-background text-muted-foreground">
        <FileText className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium group-hover:text-primary">{document.filename}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {document.page_count} page{document.page_count === 1 ? '' : 's'} · {formatBytes(document.file_size)}
          <span className="hidden sm:inline"> · {formatDocumentDate(document.created_at)}</span>
        </p>
      </div>
      <DocumentStatusBadge status={document.status} />
      <ArrowRight className="hidden size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 sm:block" />
    </Link>
  )
}
