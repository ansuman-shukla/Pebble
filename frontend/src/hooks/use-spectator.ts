import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query';

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
 * answer is the world now and refreshes every LIVE_POLL_MS.
 * TODO(live feed): invalidate these queries on the `/api/v1/live` WebSocket's `tick` messages instead of polling
 * (`use-live-citizens` keeps the globe's own frame state, so the pages would need a small subscriber of their own).
 */
const LIVE_POLL_MS = 2_000;

const live = (at: number | null) => (at === null ? LIVE_POLL_MS : false);
const atQuery = (at: number | null) => (at === null ? {} : { at });

export function useClock() {
  return useQuery({
    queryKey: ['clock'],
    queryFn: async () =>
      (await clockReadGameClock({ throwOnError: true })).data,
    refetchInterval: LIVE_POLL_MS,
    retry: false,
  });
}

export function useCitizens(at: number | null = null) {
  return useQuery({
    queryKey: ['citizens', at],
    queryFn: async () =>
      (await citizensReadCitizens({ query: atQuery(at), throwOnError: true }))
        .data,
    refetchInterval: live(at),
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useCitizen(id: string, at: number | null = null) {
  return useQuery({
    queryKey: ['citizen', id, at],
    queryFn: async () =>
      (
        await citizensReadCitizen({
          path: { citizen_id: id },
          query: atQuery(at),
          throwOnError: true,
        })
      ).data,
    refetchInterval: live(at),
    retry: false,
  });
}

const TIMELINE_PAGE = 60;

/** The citizen's life, newest first, a page at a time (up to `at` when replaying). */
export function useCitizenTimeline(id: string, at: number | null = null) {
  return useInfiniteQuery({
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
    refetchInterval: at === null ? LIVE_POLL_MS * 2 : false,
    retry: false,
  });
}

/** Needs over the game day before `at` (or now). */
export function useCitizenNeeds(id: string, at: number | null = null) {
  return useQuery({
    queryKey: ['citizen-needs', id, at],
    queryFn: async () =>
      (
        await citizensReadCitizenNeeds({
          path: { citizen_id: id },
          query: at === null ? {} : { to_tick: at },
          throwOnError: true,
        })
      ).data,
    refetchInterval: at === null ? LIVE_POLL_MS * 5 : false,
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
  return useQuery({
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
    refetchInterval: range.live ? LIVE_POLL_MS * 2 : false,
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useStats(at: number | null = null) {
  return useQuery({
    queryKey: ['stats', at],
    queryFn: async () =>
      (await statsReadStats({ query: atQuery(at), throwOnError: true })).data,
    refetchInterval: at === null ? LIVE_POLL_MS * 2 : false,
    placeholderData: keepPreviousData,
    retry: false,
  });
}
