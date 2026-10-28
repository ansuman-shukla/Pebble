import { expect, test } from '@playwright/test';

import type { LiveMessage } from '../../src/lib/live/live-contract';
import {
  type LiveLink,
  LiveUpdates,
  REFRESH_MS,
} from '../../src/lib/live/live-updates';
import type { LiveSocket } from '../../src/lib/live/mock-live';

/* The spectator pages' shared feed subscriber: throttled refreshes, reconnects, one socket for every user. */

class FakeSocket implements LiveSocket {
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  close() {
    this.closed = true;
  }
  tick(tick: number) {
    const message = {
      type: 'tick',
      run_id: 'r',
      tick,
      day: 0,
      time: '08:00',
      speed: 1,
      paused: false,
      citizens: [],
    };
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

function setUp() {
  const sockets: FakeSocket[] = [];
  const refreshed: number[] = [];
  const links: LiveLink[] = [];
  const updates = new LiveUpdates({
    open: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    refresh: (message: LiveMessage) =>
      refreshed.push(message.type === 'tick' ? message.tick : -1),
  });
  updates.subscribe(() => links.push(updates.getLink()));
  return { sockets, refreshed, links, updates };
}

const wait = (ms: number) => new Promise((done) => setTimeout(done, ms));

test('a burst of ticks refreshes at once and then once more with the last', async () => {
  const { sockets, refreshed, updates } = setUp();
  const release = updates.acquire();
  const socket = sockets[0];
  socket.onopen?.();
  expect(updates.getLink()).toBe('live');
  for (let tick = 1; tick <= 5; tick += 1) socket.tick(tick);
  expect(refreshed).toEqual([1]);
  await wait(REFRESH_MS + 150);
  expect(refreshed).toEqual([1, 5]);
  await wait(200);
  expect(refreshed).toEqual([1, 5]); // nothing new, no refresh
  release();
});

test('every page shares one socket, which closes after the last one leaves', async () => {
  const { sockets, updates } = setUp();
  const first = updates.acquire();
  const second = updates.acquire();
  expect(sockets).toHaveLength(1);
  first();
  first(); // releasing twice counts once
  await wait(1_200);
  expect(sockets[0].closed).toBe(false);
  second();
  await wait(1_200);
  expect(sockets[0].closed).toBe(true);
  const again = updates.acquire();
  expect(sockets).toHaveLength(2);
  again();
});

test('a dropped socket goes down and reconnects; a new run reconnects at once', async () => {
  const { sockets, links, updates } = setUp();
  const release = updates.acquire();
  sockets[0].onopen?.();
  sockets[0].onclose?.({ code: 1006 });
  expect(updates.getLink()).toBe('down');
  expect(sockets).toHaveLength(1);
  await wait(700); // first retry after 0.5 s
  expect(sockets).toHaveLength(2);
  sockets[1].onopen?.();
  sockets[1].onclose?.({ code: 1012 });
  await wait(150);
  expect(sockets).toHaveLength(3);
  sockets[2].onopen?.();
  expect(links).toEqual(['live', 'down', 'live', 'down', 'live']);
  release();
});
