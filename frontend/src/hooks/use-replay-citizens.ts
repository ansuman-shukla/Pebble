import { useQuery } from '@tanstack/react-query';

import { entitiesReadEntities } from '@/lib/client/sdk.gen';
import {
  applyEntities,
  EMPTY_LIVE,
  type LiveState,
} from '@/lib/live/live-state';

/** `?tick=N`: a whole number ≥ 0, else null (the live world). */
export function parseReplayTick(value: string | null): number | null {
  return value !== null && /^\d+$/.test(value) ? Number(value) : null;
}

/**
 * The world at a past tick (`/?tick=N`, from the spectator pages): the citizens of `GET /api/v1/entities?at=N` as a
 * paused frame in the live state's shape, so the globe draws them like the feed's. Null when not replaying.
 */
export function useReplayCitizens(tick: number | null): LiveState | null {
  const { data } = useQuery({
    queryKey: ['entities-at', tick],
    queryFn: async () =>
      (
        await entitiesReadEntities({
          query: { at: tick ?? 0 },
          throwOnError: true,
        })
      ).data,
    enabled: tick !== null,
    staleTime: Infinity,
    retry: false,
  });
  if (tick === null) return null;
  const replayed = data ? applyEntities(EMPTY_LIVE, data, 0) : EMPTY_LIVE;
  return { ...replayed, paused: true };
}
