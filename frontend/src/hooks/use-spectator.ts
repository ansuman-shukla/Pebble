import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query';

import { type LiveMeta, useLiveUpdates } from '@/hooks/use-live-updates';
import {
  citizensReadCitizen,
  citizensReadCitizenNeeds,
  citizensReadCitizens,
  citizensReadCitizenTimeline,
  clockReadGameClock,
  conversationsReadConversations,
  statsReadStats,
} from '@/lib/client/sdk.gen';

/*
 * Read hooks of the spectator pages. `at` replays a past tick (a fixed answer, fetched once); without it the
 * answer is the world now: the live feed refreshes it on every engine tick (`useLiveUpdates`), and while the
 * socket is down it polls every LIVE_POLL_MS instead.
 */
const LIVE_POLL_MS = 2_000;
const SLOW_MS = 5_000; // needs and the timeline: enough to refresh every few seconds

/** How a query stays current: refreshed by the feed (meta) and polled only while the socket is down. */
function useLive(isLive: boolean, staleMs = 0) {
  const link = useLiveUpdates();
  return {
    meta: isLive ? ({ live: true, staleMs } satisfies LiveMeta) : undefined,
    refetchInterval:
      isLive && link !== 'live' ? Math.max(LIVE_POLL_MS, staleMs) : false,
  } as const;
}

const atQuery = (at: number | null) => (at === null ? {} : { at });

export function useClock() {
  const live = useLive(true);
  return useQuery({
    ...live,
    queryKey: ['clock'],
    queryFn: async () =>
      (await clockReadGameClock({ throwOnError: true })).data,
    retry: false,
  });
}

export function useCitizens(at: number | null = null) {
  const live = useLive(at === null);
  return useQuery({
    ...live,
    queryKey: ['citizens', at],
    queryFn: async () =>
      (await citizensReadCitizens({ query: atQuery(at), throwOnError: true }))
        .data,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useCitizen(id: string, at: number | null = null) {
  const live = useLive(at === null);
  return useQuery({
    ...live,
    queryKey: ['citizen', id, at],
    queryFn: async () =>
      (
        await citizensReadCitizen({
          path: { citizen_id: id },
          query: atQuery(at),
          throwOnError: true,
        })
      ).data,
    retry: false,
  });
}

const TIMELINE_PAGE = 60;

/** The citizen's life, newest first, a page at a time (up to `at` when replaying). */
export function useCitizenTimeline(id: string, at: number | null = null) {
  const live = useLive(at === null, SLOW_MS);
  return useInfiniteQuery({
    ...live,
    queryKey: ['citizen-timeline', id, at],
    queryFn: async ({ pageParam }) =>
      (
        await citizensReadCitizenTimeline({
          path: { citizen_id: id },
          query: {
            order: 'desc',
            limit: TIMELINE_PAGE,
            ...(at === null ? {} : { to_tick: at }),
            ...(pageParam === null ? {} : { cursor: pageParam }),
          },
          throwOnError: true,
        })
      ).data,
    initialPageParam: null as number | null,
    getNextPageParam: (page) => page.next_cursor,
    retry: false,
  });
}

/** Needs over the game day before `at` (or now). */
export function useCitizenNeeds(id: string, at: number | null = null) {
  const live = useLive(at === null, SLOW_MS);
  return useQuery({
    ...live,
    queryKey: ['citizen-needs', id, at],
    queryFn: async () =>
      (
        await citizensReadCitizenNeeds({
          path: { citizen_id: id },
          query: at === null ? {} : { to_tick: at },
          throwOnError: true,
        })
      ).data,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useConversations(range: {
  fromTick?: number;
  toTick?: number;
  place?: string;
  live: boolean;
}) {
  const live = useLive(range.live);
  return useQuery({
    ...live,
    queryKey: ['conversations', range.fromTick, range.toTick, range.place],
    queryFn: async () =>
      (
        await conversationsReadConversations({
          query: {
            from_tick: range.fromTick,
            to_tick: range.toTick,
            place: range.place,
            limit: 100,
          },
          throwOnError: true,
        })
      ).data,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useStats(at: number | null = null) {
  const live = useLive(at === null);
  return useQuery({
    ...live,
    queryKey: ['stats', at],
    queryFn: async () =>
      (await statsReadStats({ query: atQuery(at), throwOnError: true })).data,
    placeholderData: keepPreviousData,
    retry: false,
  });
}
