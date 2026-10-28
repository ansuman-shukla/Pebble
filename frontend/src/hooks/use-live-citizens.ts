import { useCallback, useEffect, useReducer, useState } from 'react';

import { socketUrl } from '@/lib/api/client';
import { adminChangeClock, entitiesReadEntities } from '@/lib/client/sdk.gen';
import type { WorldView } from '@/lib/client/types.gen';
import { LIVE_CLOSE, type LiveMessage } from '@/lib/live/live-contract';
import {
  applyEntities,
  applyMessage,
  EMPTY_LIVE,
  type EntitiesAnswer,
  type LiveState,
  pruneSpeech,
  SPEECH_MS,
} from '@/lib/live/live-state';
import { type LiveSocket, MockLiveServer } from '@/lib/live/mock-live';

/*
 * The citizens live: `GET /api/v1/entities` first, then the engine's feed (WebSocket `/api/v1/live`, one `tick`
 * per engine tick plus `event`s). A dropped socket reconnects with backoff and resyncs from the `snapshot` the
 * server sends on connect; "no run yet" (4404) keeps retrying with backoff; "a newer run started" (1012)
 * reconnects at once and takes the new run's snapshot. The `mock` source is the dev/test mock server (the same
 * socket path); `off`: no feed.
 */

/**
 * live: socket open; connecting / reconnecting: waiting for a socket; no-run: the backend has no run yet;
 * off: no feed at all.
 */
export type LiveStatus =
  'connecting' | 'live' | 'reconnecting' | 'no-run' | 'off';

/** Where the citizens come from: the backend, the dev/test mock server, or nowhere. */
export type LiveSource = 'backend' | 'mock' | 'off';

export interface ClockChange {
  speed?: number;
  paused?: boolean;
}

export interface LiveFeed {
  state: LiveState;
  status: LiveStatus;
  /** Sockets opened so far (a reconnect makes it 2). */
  connects: number;
  setClock: (change: ClockChange) => void;
}

/** Backoff after a dropped socket: 0.5 s, 1 s, 2 s ... up to 15 s. */
const RETRY_FIRST_MS = 500;
const RETRY_MAX_MS = 15_000;
/** A newer run started: reconnect right away. */
const NEW_RUN_RETRY_MS = 50;

type Action =
  | { type: 'entities'; view: EntitiesAnswer }
  | { type: 'message'; message: LiveMessage; now: number }
  | { type: 'clock'; change: ClockChange }
  | { type: 'prune'; now: number };

function reduce(state: LiveState, action: Action): LiveState {
  switch (action.type) {
    case 'entities':
      return applyEntities(state, action.view);
    case 'message':
      return applyMessage(state, action.message, action.now);
    case 'clock':
      return { ...state, ...action.change };
    case 'prune':
      return pruneSpeech(state, action.now);
  }
}

/** A browser WebSocket behind the small interface the mock implements too. */
function openSocket(url: string): LiveSocket {
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

async function fetchEntities(): Promise<EntitiesAnswer> {
  return (await entitiesReadEntities({ throwOnError: true })).data;
}

export function useLiveCitizens(
  world: WorldView,
  { source }: { source: LiveSource },
): LiveFeed {
  const [server] = useState<MockLiveServer | null>(() =>
    source === 'mock' ? new MockLiveServer(world) : null,
  );
  const [state, dispatch] = useReducer(reduce, EMPTY_LIVE);
  const [status, setStatus] = useState<LiveStatus>(
    source === 'off' ? 'off' : 'connecting',
  );
  const [connects, setConnects] = useState(0);
  // the socket (mock or real), reconnecting with backoff
  useEffect(() => {
    if (source === 'off') return;
    let disposed = false;
    let socket: LiveSocket | null = null;
    let retry: number | undefined;
    let attempt = 0;
    const open = () => {
      socket = server
        ? server.connect()
        : openSocket(socketUrl('/api/v1/live'));
      socket.onopen = () => setConnects((count) => count + 1);
      // live from the snapshot on: the backend accepts a socket before it knows whether there is a run (4404)
      socket.onmessage = ({ data }) => {
        attempt = 0;
        setStatus('live');
        dispatch({
          type: 'message',
          message: JSON.parse(data) as LiveMessage,
          now: performance.now(),
        });
      };
      socket.onclose = ({ code }) => {
        if (disposed) return;
        if (code === LIVE_CLOSE.newRun) {
          attempt = 0;
          setStatus('reconnecting');
          retry = window.setTimeout(open, NEW_RUN_RETRY_MS);
          return;
        }
        setStatus(code === LIVE_CLOSE.noRun ? 'no-run' : 'reconnecting');
        const delay = Math.min(RETRY_FIRST_MS * 2 ** attempt, RETRY_MAX_MS);
        attempt += 1;
        retry = window.setTimeout(open, delay);
      };
    };
    if (server) dispatch({ type: 'entities', view: server.entities() });
    else
      fetchEntities().then(
        (view) => !disposed && dispatch({ type: 'entities', view }),
        () => undefined, // the socket's snapshot fills in
      );
    // deferred: StrictMode's mount-unmount-mount in dev would otherwise close a socket still connecting (a warning)
    retry = window.setTimeout(open, 0);
    return () => {
      disposed = true;
      window.clearTimeout(retry);
      socket?.close();
    };
  }, [server, source]);

  // speech bubbles expire
  const { speech } = state;
  useEffect(() => {
    if (speech.length === 0) return;
    const oldest = Math.min(...speech.map(({ at }) => at));
    const timer = window.setTimeout(
      () => dispatch({ type: 'prune', now: performance.now() }),
      Math.max(oldest + SPEECH_MS - performance.now(), 0) + 20,
    );
    return () => window.clearTimeout(timer);
  }, [speech]);

  const setClock = useCallback(
    (change: ClockChange) => {
      dispatch({ type: 'clock', change });
      if (server) server.setClock(change);
      else void adminChangeClock({ body: change });
    },
    [server],
  );

  useEffect(() => {
    if (!server) return;
    window.__pebbleMockLive = server;
    return () => server.stop();
  }, [server]);

  return { state, status, connects, setClock };
}
