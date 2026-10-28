import { useQuery } from '@tanstack/react-query';

import { healthReadHealth } from '@/lib/client/sdk.gen';

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => (await healthReadHealth({ throwOnError: true })).data,
    refetchInterval: 5_000,
    retry: false,
  });
}
