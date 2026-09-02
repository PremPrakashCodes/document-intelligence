import type { QueryClient } from '@tanstack/react-query'
import { Link, Outlet, createRootRouteWithContext } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'

import { TooltipProvider } from '@/components/ui/tooltip'

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
  notFoundComponent: () => (
    <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
      <p>That page doesn’t exist.</p>
      <Link to="/" className="underline underline-offset-4">
        Back home
      </Link>
    </div>
  ),
})

/** A page with a table grid, one cell traced — the product in one glyph. */
function BrandMark() {
  return (
    <svg viewBox="0 0 32 32" className="size-4" aria-hidden>
      <rect
        x="5" y="3" width="22" height="26" rx="2.5"
        fill="none" stroke="currentColor" strokeWidth="2.2"
      />
      <path d="M5 12h22M13 12v17" stroke="currentColor" strokeWidth="1.6" opacity="0.45" />
      <rect
        x="13" y="12" width="9" height="8"
        fill="var(--confirmed)" fillOpacity="0.25"
        stroke="var(--confirmed)" strokeWidth="2.2"
      />
    </svg>
  )
}

function RootComponent() {
  return (
    <TooltipProvider delayDuration={300}>
    <div className="flex h-screen min-h-0 flex-col">
      <header className="flex items-center gap-6 border-b bg-card px-4 py-2.5">
        <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <BrandMark />
          Document Intelligence
        </Link>
        <nav className="flex gap-4">
          <Link
            to="/documents"
            className="text-sm"
            activeProps={{ className: 'font-medium text-foreground' }}
            inactiveProps={{
              className: 'text-muted-foreground hover:text-foreground',
            }}
          >
            Documents
          </Link>
        </nav>
      </header>

      <main className="flex min-h-0 flex-1 flex-col">
        <Outlet />
      </main>

      {import.meta.env.DEV ? (
        <>
          <TanStackRouterDevtools position="bottom-right" />
          <ReactQueryDevtools buttonPosition="bottom-left" />
        </>
      ) : null}
    </div>
    </TooltipProvider>
  )
}
