import type { QueryClient } from '@tanstack/react-query'
import { Link, Outlet, createRootRouteWithContext, useRouterState } from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { FileStack, LayoutDashboard, ShieldCheck } from 'lucide-react'

import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'

export interface RouterContext {
  queryClient: QueryClient
}

export const Route = createRootRouteWithContext<RouterContext>()({
  component: RootComponent,
  notFoundComponent: () => <NotFound />,
})

/** A page with a table grid, one cell traced — the product in one glyph. */
function BrandMark() {
  return (
    <svg viewBox="0 0 32 32" className="size-5" aria-hidden>
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
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const isDocumentReview = pathname.startsWith('/documents/') && pathname !== '/documents/'

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen min-h-0 flex-col bg-background">
        {!isDocumentReview ? (
          <header className="flex h-16 shrink-0 items-center border-b bg-card/95 px-4 backdrop-blur sm:px-6 lg:px-8">
            <div className="mx-auto flex w-full max-w-7xl items-center gap-6">
              <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
                <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
                  <BrandMark />
                </span>
                <span className="hidden sm:inline">Document Intelligence</span>
              </Link>

              <nav className="flex items-center gap-1" aria-label="Primary navigation">
                <NavItem to="/" label="Overview" icon={LayoutDashboard} />
                <NavItem to="/documents" label="Documents" icon={FileStack} />
              </nav>

              <div className="ml-auto hidden items-center gap-2 rounded-full border bg-background px-3 py-1.5 text-xs text-muted-foreground md:flex">
                <ShieldCheck className="size-3.5" />
                Source-linked extraction
              </div>
            </div>
          </header>
        ) : null}

        <main className="flex min-h-0 flex-1 flex-col overflow-auto">
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

function NavItem({
  to,
  label,
  icon: Icon,
}: {
  to: '/' | '/documents'
  label: string
  icon: typeof LayoutDashboard
}) {
  return (
    <Link
      to={to}
      activeOptions={{ exact: to === '/' }}
      className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors sm:px-3"
      activeProps={{ className: 'bg-accent font-medium text-accent-foreground' }}
      inactiveProps={{ className: 'text-muted-foreground hover:bg-accent/70 hover:text-foreground' }}
    >
      <Icon className="size-4" />
      <span className="hidden sm:inline">{label}</span>
    </Link>
  )
}

function NotFound() {
  return (
    <Empty className="m-auto max-w-xl border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <FileStack />
        </EmptyMedia>
        <EmptyTitle>Page not found</EmptyTitle>
        <EmptyDescription>The page you are looking for is not part of this workspace.</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button asChild>
          <Link to="/">Return to overview</Link>
        </Button>
      </EmptyContent>
    </Empty>
  )
}
