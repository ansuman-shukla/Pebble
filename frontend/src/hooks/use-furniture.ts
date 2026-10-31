import { useQuery } from '@tanstack/react-query';

import { worldReadFurniture } from '@/lib/client/sdk.gen';

/** The log seats, stools and mats under the slots (static for a backend build, so fetched once; drawn when here). */
export function useFurniture() {
  return useQuery({
    queryKey: ['furniture'],
    queryFn: async () =>
      (await worldReadFurniture({ throwOnError: true })).data,
    staleTime: Infinity,
    retry: false,
  });
}
