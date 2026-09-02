import { useCallback, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { FileUp, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ApiError, api } from '@/lib/api'
import { documentKeys } from '@/lib/queries'
import { cn } from '@/lib/utils'

/**
 * Drop or choose a PDF, then go straight to it.
 *
 * Shared by the landing page and the documents list so that uploading behaves
 * and reads identically wherever someone starts. On success it navigates to the
 * document rather than returning to a list: the reason to upload is to look at
 * the result.
 */
export function UploadDropzone({ className }: { className?: string }) {
  const queryClient = useQueryClient()
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const upload = useMutation({
    mutationFn: (file: File) => api.upload(file),
    onSuccess: async (response) => {
      setError(null)
      await queryClient.invalidateQueries({ queryKey: documentKeys.list() })
      void router.navigate({ to: '/documents/$documentId', params: { documentId: response.id } })
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  })

  const accept = useCallback(
    (files: FileList | null) => {
      const file = files?.[0]
      if (!file) return
      if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
        setError('That file is not a PDF. Choose a PDF to extract tables from it.')
        return
      }
      upload.mutate(file)
    },
    [upload],
  )

  return (
    <div className={className}>
      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          accept(event.dataTransfer.files)
        }}
        className={cn(
          'flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center transition-colors',
          dragging ? 'border-ring bg-accent/60' : 'border-border bg-card',
        )}
      >
        <FileUp
          className={cn(
            'size-5 transition-colors',
            dragging ? 'text-foreground' : 'text-muted-foreground',
          )}
        />
        <div className="space-y-0.5">
          <p className="text-sm font-medium">Drop a PDF here</p>
          <p className="text-xs text-muted-foreground">
            Scanned or born-digital, up to 64&nbsp;MB
          </p>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          onChange={(event) => accept(event.target.files)}
        />
        <Button
          variant="outline"
          size="sm"
          disabled={upload.isPending}
          onClick={() => inputRef.current?.click()}
        >
          {upload.isPending ? (
            <>
              <Loader2 className="size-3.5 animate-spin" />
              Uploading
            </>
          ) : (
            'Choose a file'
          )}
        </Button>
      </div>

      {error ? (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  )
}
