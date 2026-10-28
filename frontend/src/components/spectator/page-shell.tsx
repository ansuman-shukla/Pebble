import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router';

import { useReplayTick } from '@/hooks/use-replay-tick';
import { tickLabel } from '@/lib/spectator/time';

type PageShellProps = {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  testId: string;
};

/** A scrolling spectator page with a header and, while replaying, a banner back to the live world. */
export function PageShell({
  title,
  subtitle,
  actions,
  children,
  testId,
}: PageShellProps) {
  const at = useReplayTick();
  const { pathname } = useLocation();
  return (
    <main className="h-full overflow-y-auto" data-testid={testId}>
      <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4">
        {at !== null && (
          <div
            className="flex items-center justify-between rounded-lg bg-amber-100 px-3 py-2 text-sm text-amber-900"
            data-testid="replay-banner"
          >
            <span>Replaying {tickLabel(at)}</span>
            <Link to={pathname} className="underline">
              Back to live
            </Link>
          </div>
        )}
        <header className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h1 className="text-xl font-semibold">{title}</h1>
            {subtitle && (
              <p className="text-muted-foreground text-sm">{subtitle}</p>
            )}
          </div>
          {actions}
        </header>
        {children}
      </div>
    </main>
  );
}

/** A small "loading / failed" line for a query. */
export function QueryState({
  isPending,
  error,
}: {
  isPending: boolean;
  error: Error | null;
}) {
  if (error)
    return (
      <p className="text-destructive text-sm" role="alert">
        {error.message || 'The world could not be read.'}
      </p>
    );
  if (isPending)
    return <p className="text-muted-foreground text-sm">Loading…</p>;
  return null;
}
