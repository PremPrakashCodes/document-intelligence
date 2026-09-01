import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: HomePage,
})

function HomePage() {
  return (
    <section className="flex flex-col gap-5">
      <h1 className="text-2xl font-semibold tracking-tight">GI Dashboard</h1>
      <p className="max-w-prose text-sm text-muted-foreground">
        Collecting, parsing, and browsing insurers&rsquo; public disclosure filings.
      </p>
    </section>
  )
}
