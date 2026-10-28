import { Link, useSearchParams } from 'react-router';

import type { LiveState } from '@/lib/live/live-state';

/** Shown instead of the live clock while the globe replays a past tick: the moment, and the way back to live. */
export function ReplayBadge({ state }: { state: LiveState }) {
  const [params] = useSearchParams();
  const live = new URLSearchParams(params);
  live.delete('tick');
  const query = live.toString();
  return (
    <div
      className="flex items-center gap-2 rounded-lg bg-amber-100/90 p-1 px-2 text-sm text-amber-900 shadow"
      data-testid="replay-badge"
    >
      <span className="font-mono">
        replaying day {state.day} · {state.time}
      </span>
      <Link to={query ? `/?${query}` : '/'} className="underline">
        back to live
      </Link>
    </div>
  );
}
