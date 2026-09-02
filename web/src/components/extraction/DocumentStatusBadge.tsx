import { CheckCircle2, CircleAlert, Clock3, LoaderCircle, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { DocumentStatus } from '@/lib/types'

const STATUS = {
  pending: { label: 'Queued', icon: Clock3, variant: 'secondary' },
  processing: { label: 'Extracting', icon: LoaderCircle, variant: 'secondary' },
  completed: { label: 'Ready', icon: CheckCircle2, variant: 'outline' },
  partial: { label: 'Text only', icon: CircleAlert, variant: 'outline' },
  failed: { label: 'Failed', icon: XCircle, variant: 'destructive' },
} as const satisfies Record<
  DocumentStatus,
  { label: string; icon: typeof CheckCircle2; variant: 'secondary' | 'outline' | 'destructive' }
>

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const config = STATUS[status]
  const Icon = config.icon

  return (
    <Badge variant={config.variant}>
      <Icon data-icon="inline-start" className={status === 'processing' ? 'animate-spin' : undefined} />
      {config.label}
    </Badge>
  )
}
