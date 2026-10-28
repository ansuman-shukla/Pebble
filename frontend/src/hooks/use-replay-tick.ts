import { useSearchParams } from 'react-router';

import { parseTick } from '@/lib/spectator/time';

/** The replayed tick of a spectator page (`?at=N`), or null when it shows the world now. */
export function useReplayTick(): number | null {
  const [params] = useSearchParams();
  return parseTick(params.get('at'));
}
