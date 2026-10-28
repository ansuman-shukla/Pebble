import { type QueryClient, useQueryClient } from '@tanstack/react-query';
import { useEffect, useSyncExternalStore } from 'react';

import { socketUrl } from '@/lib/api/client';
import { openSocket } from '@/lib/api/live-socket';
import { type LiveLink, LiveUpdates } from '@/lib/live/live-updates';

/** Marks a query as showing the world now: the live feed refreshes it (`staleMs`: not more often than that). */
export interface LiveMeta extends Record<string, unknown> {
  live: true;
  staleMs?: number;
}

let clientOfFeed: QueryClient | null = null;

/** Refetches every live spectator query that is old enough; replayed (`?at=`) answers never change. */
function refreshLive() {
  const now = Date.now();
  void clientOfFeed?.invalidateQueries({
    predicate: (query) => {
      const meta = query.meta as Partial<LiveMeta> | undefined;
      return (
        meta?.live === true &&
        now - query.state.dataUpdatedAt >= (meta.staleMs ?? 0)
      );
    },
  });
}

const feed = new LiveUpdates({
  open: () => openSocket(socketUrl('/api/v1/live')),
  refresh: refreshLive,
});

/**
 * Keeps the spectator pages live from the engine's feed while they are mounted; returns whether the socket is up
 * (when it isn't, the queries poll).
 */
export function useLiveUpdates(): LiveLink {
  const queryClient = useQueryClient();
  useEffect(() => {
    clientOfFeed = queryClient;
    return feed.acquire();
  }, [queryClient]);
  return useSyncExternalStore(feed.subscribe, feed.getLink);
}
