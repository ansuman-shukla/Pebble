import { client } from '@/lib/client/client.gen';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8100';

export function configureApiClient() {
  client.setConfig({ baseUrl: API_URL });
}
