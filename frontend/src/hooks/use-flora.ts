import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { Vector3 } from 'three';

import { worldReadFlora } from '@/lib/client/sdk.gen';
import type { WorldView } from '@/lib/client/types.gen';
import { decodeFlora, type FloraTable } from '@/lib/world/flora';
import { decodeWorld } from '@/lib/world/globe';

/** The mock world's flora keeps out of its town plateau and camp grounds, like the backend's. */
const MOCK_TOWN_CLEARING = 200;
const MOCK_CAMP_CLEARING = 12;

async function mockTable(view: WorldView): Promise<FloraTable> {
  const { mockFlora } = await import('@/lib/world/mock-flora');
  return mockFlora(
    decodeWorld(view),
    view.biome_names,
    view.frequency,
    view.seed,
    view.sites
      .filter((site) => site.kind !== 'landmark')
      .map((site) => ({
        direction: new Vector3(...site.anchor.position),
        radius: site.kind === 'town' ? MOCK_TOWN_CLEARING : MOCK_CAMP_CLEARING,
      })),
  );
}

/**
 * The world's usable flora from GET /api/v1/world/flora (static for a world, fetched once), decoded with the kind
 * lists of its places. `?mock=1` grows a stand-in table on the mock world.
 */
export function useFlora(view: WorldView | undefined) {
  const [params] = useSearchParams();
  const mock = params.has('mock');
  return useQuery({
    queryKey: ['flora', mock, view?.seed, view?.generator_version],
    queryFn: async (): Promise<FloraTable> => {
      if (!view) throw new Error('the world is not loaded');
      if (mock) return mockTable(view);
      const { data } = await worldReadFlora({
        parseAs: 'blob',
        throwOnError: true,
      });
      return decodeFlora(
        await data.arrayBuffer(),
        view.places.flora_kinds,
        view.places.flora_nodes,
      );
    },
    enabled: view !== undefined,
    staleTime: Infinity,
    retry: false,
  });
}
