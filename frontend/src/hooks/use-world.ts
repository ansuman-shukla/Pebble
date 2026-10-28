import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';

import { API_URL } from '@/lib/api/client';
import type { WorldView } from '@/lib/world/world-view';

async function mockWorld(frequency: number | undefined) {
  const { createMockWorld } = await import('@/lib/world/mock-world');
  return createMockWorld({ frequency });
}

/**
 * The planet (static for a backend build, so it is fetched once). `?mock=1` (and `&frequency=N`) uses the
 * dev/test mock; until the backend serves /api/v1/world, a 404 falls back to the mock too.
 */
export function useWorld() {
  const [params] = useSearchParams();
  const mock = params.has('mock');
  const frequency = Number(params.get('frequency')) || undefined;
  return useQuery({
    queryKey: ['world', mock, frequency],
    queryFn: async (): Promise<WorldView> => {
      if (mock) return mockWorld(frequency);
      const response = await fetch(`${API_URL}/api/v1/world`);
      // TODO(M3 integration): drop this fallback once the backend serves the world
      if (response.status === 404) return mockWorld(frequency);
      if (!response.ok)
        throw new Error(`GET /api/v1/world: HTTP ${response.status}`);
      return (await response.json()) as WorldView;
    },
    staleTime: Infinity,
    retry: false,
  });
}
