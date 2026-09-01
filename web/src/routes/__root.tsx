import type { QueryClient } from '@tanstack/react-query'
import { Link, Outlet, createRootRouteWithContext } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'

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

function RootComponent() {
  return (
    <div className="min-h-screen">
      <header className="flex items-baseline gap-8 border-b bg-card px-6 py-4">
        <Link to="/" className="font-semibold">
          GI Dashboard
        </Link>
        <nav className="flex gap-5">
          <Link
            to="/"
            activeOptions={{ exact: true }}
            className="text-sm"
            activeProps={{ className: 'font-medium text-foreground' }}
            inactiveProps={{
              className: 'text-muted-foreground hover:text-foreground',
            }}
          >
            Home
          </Link>
        </nav>
      </header>

      <main className="mx-auto max-w-4xl px-6 pt-8 pb-16">
        <Outlet />
      </main>

      <TanStackRouterDevtools position="bottom-right" />
      <ReactQueryDevtools buttonPosition="bottom-left" />
    </div>
  )
}
