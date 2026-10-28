import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';

import { worldReadWorld } from '@/lib/client/sdk.gen';
import type { WorldView } from '@/lib/client/types.gen';

async function mockWorld(frequency: number | undefined) {
  const { createMockWorld } = await import('@/lib/world/mock-world');
  return createMockWorld({ frequency });
}

/**
 * The planet from GET /api/v1/world (static for a backend build, so it is fetched once). `?mock=1` (and
 * `&frequency=N`) uses the dev/test mock instead.
 */
export function useWorld() {
  const [params] = useSearchParams();
  const mock = params.has('mock');
  const frequency = Number(params.get('frequency')) || undefined;
  return useQuery({
    queryKey: ['world', mock, frequency],
    queryFn: async (): Promise<WorldView> =>
      mock
        ? mockWorld(frequency)
        : (await worldReadWorld({ throwOnError: true })).data,
    staleTime: Infinity,
    retry: false,
  });
}
