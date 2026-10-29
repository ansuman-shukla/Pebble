/*
 * One shared subscription to the engine's live feed (`WS /api/v1/live`) for the spectator pages. Every `snapshot`,
 * `tick` or `event` message asks the pages to refresh (at most once per REFRESH_MS, the last message always lands);
 * while the socket is down the pages poll instead. The socket opens with the first user and closes a little after
 * the last one leaves (route changes and StrictMode remounts keep it).
 */
import { LIVE_CLOSE, type LiveMessage } from './live-contract';
import type { LiveSocket } from './mock-live';

/** live: the socket is open; connecting: not yet; down: dropped or refused (the pages poll). */
export type LiveLink = 'connecting' | 'live' | 'down';

export const REFRESH_MS = 1_000;
const RETRY_FIRST_MS = 500;
const RETRY_MAX_MS = 15_000;
const RESYNC_RETRY_MS = 50;
const IDLE_CLOSE_MS = 1_000;

export interface LiveUpdatesDeps {
  open: () => LiveSocket;
  /** Called with the message that triggered the refresh (throttled). */
  refresh: (message: LiveMessage) => void;
  now?: () => number;
}

export class LiveUpdates {
  private link: LiveLink = 'connecting';
  private readonly listeners = new Set<() => void>();
  private users = 0;
  private socket: LiveSocket | null = null;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private idle: ReturnType<typeof setTimeout> | undefined;
  private trailing: ReturnType<typeof setTimeout> | undefined;
  private pending: LiveMessage | null = null;
  private lastRefresh = -Infinity;
  private attempt = 0;

  constructor(private readonly deps: LiveUpdatesDeps) {}

  getLink = (): LiveLink => this.link;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** A page starts using the feed; call the returned function when it stops. */
  acquire(): () => void {
    this.users += 1;
    clearTimeout(this.idle);
    if (!this.socket && this.retry === undefined) this.connect();
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.users -= 1;
      if (this.users === 0)
        this.idle = setTimeout(() => this.shutDown(), IDLE_CLOSE_MS);
    };
  }

  private now() {
    return this.deps.now?.() ?? Date.now();
  }

  private setLink(link: LiveLink) {
    if (link === this.link) return;
    this.link = link;
    for (const listener of this.listeners) listener();
  }

  private connect() {
    this.retry = undefined;
    const socket = this.deps.open();
    this.socket = socket;
    socket.onopen = () => {
      this.attempt = 0;
      this.setLink('live');
    };
    socket.onmessage = ({ data }) =>
      this.receive(JSON.parse(data) as LiveMessage);
    socket.onclose = ({ code }) => {
      if (this.socket !== socket) return; // closed on purpose
      this.socket = null;
      this.setLink('down');
      const delay =
        code === LIVE_CLOSE.resync
          ? RESYNC_RETRY_MS
          : Math.min(RETRY_FIRST_MS * 2 ** this.attempt++, RETRY_MAX_MS);
      this.retry = setTimeout(() => this.connect(), delay);
    };
  }

  private receive(message: LiveMessage) {
    this.pending = message;
    if (this.trailing !== undefined) return;
    const wait = this.lastRefresh + REFRESH_MS - this.now();
    if (wait <= 0) this.flush();
    else this.trailing = setTimeout(() => this.flush(), wait);
  }

  private flush() {
    this.trailing = undefined;
    const message = this.pending;
    this.pending = null;
    if (!message) return;
    this.lastRefresh = this.now();
    this.deps.refresh(message);
  }

  private shutDown() {
    clearTimeout(this.retry);
    clearTimeout(this.trailing);
    this.retry = this.trailing = undefined;
    this.pending = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.attempt = 0;
    this.setLink('connecting');
  }
}
