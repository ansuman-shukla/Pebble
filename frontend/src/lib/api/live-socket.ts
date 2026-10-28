import type { LiveSocket } from '@/lib/live/mock-live';

/** A browser WebSocket behind the small interface the mock implements too. */
export function openSocket(url: string): LiveSocket {
  const ws = new WebSocket(url);
  const socket: LiveSocket = {
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    close: () => ws.close(),
  };
  ws.onopen = () => socket.onopen?.();
  ws.onmessage = (event) => socket.onmessage?.({ data: String(event.data) });
  ws.onclose = (event) => socket.onclose?.({ code: event.code });
  ws.onerror = () => socket.onerror?.();
  return socket;
}
