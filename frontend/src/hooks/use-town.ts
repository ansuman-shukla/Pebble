import { useQuery } from '@tanstack/react-query';

import { townReadTown } from '@/lib/client/sdk.gen';

/** The authored town (static for a backend build, so it is fetched once). */
export function useTown() {
  return useQuery({
    queryKey: ['town'],
    queryFn: async () => (await townReadTown({ throwOnError: true })).data,
    staleTime: Infinity,
    retry: false,
  });
}
