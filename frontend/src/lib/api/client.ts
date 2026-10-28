import { client } from '@/lib/client/client.gen';

// Same origin by default: vite proxies /api to the backend (see vite.config.ts).
const API_URL = import.meta.env.VITE_API_URL ?? '';

export function configureApiClient() {
  client.setConfig({ baseUrl: API_URL });
}

/** WebSocket URL of an API path: the API's own origin when VITE_API_URL is set, else this page's. */
export function socketUrl(path: string) {
  const base = new URL(API_URL || window.location.origin);
  base.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
  return new URL(path, base).href;
}
