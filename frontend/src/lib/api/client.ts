import { client } from '@/lib/client/client.gen';

// Same origin by default: vite proxies /api to the backend (see vite.config.ts).
const API_URL = import.meta.env.VITE_API_URL ?? '';

export function configureApiClient() {
  client.setConfig({ baseUrl: API_URL });
}
