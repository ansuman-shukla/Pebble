import { expect, test } from '@playwright/test';

import type { LiveEventMessage } from '../../src/lib/live/live-contract';
import {
  addEntry,
  FEED_KEEP,
  type FeedEntry,
  feedEntry,
  type FeedSubjects,
  shows,
} from '../../src/lib/live/event-feed';
import { type MockLiveWindow, openHeld } from './ui-helpers';

/* The event feed: lines and importance, merged repeats, filters (no browser); a mock death in the page. */

const SUBJECTS: FeedSubjects = {
  names: new Map([
    ['tek', 'Tek'],
    ['pip', 'Pip'],
  ]),
  animals: new Map([
    ['boar:35', 'boar'],
    ['elk:2', 'elk'],
    ['polar_bear:1', 'polar_bear'],
  ]),
};

let serial = 0;
const event = (
  type: string,
  actor: string | null,
  payload: Record<string, unknown> = {},
  extra: Record<string, unknown> = {},
  tick = 600,
): LiveEventMessage => ({
  type: 'event',
  run_id: 'run-1',
  tick,
  event: { id: `e${(serial += 1)}`, type, actor_id: actor, payload, ...extra },
});

const entry = (message: LiveEventMessage) => feedEntry(message, SUBJECTS)!;

test('today’s events get a plain line and importance: a death 3, speech 1, actions hidden', () => {
  expect(entry(event('died', 'pip', { cause: 'thirst' }))).toMatchObject({
    type: 'died',
    actorId: 'pip',
    line: 'Pip died (thirst)',
    importance: 3,
    time: '18:00',
    position: null,
    count: 1,
  });
  expect(entry(event('died', 'pip')).line).toBe('Pip died');
  expect(entry(event('said', 'tek', { words: 'Fish!' }))).toMatchObject({
    line: 'Tek: “Fish!”',
    importance: 1,
  });
  expect(feedEntry(event('action_started', 'tek'), SUBJECTS)).toBeNull();
  expect(feedEntry(event('action_finished', 'tek'), SUBJECTS)).toBeNull();
  expect(entry(event('said', 'stranger', { words: 'Hm.' })).line).toBe(
    'Someone: “Hm.”',
  );
});

test('an animal’s death names its kind, is importance 2 and no danger to people (only citizens are 3)', () => {
  const hunted = entry(event('died', 'boar:35', { cause: 'hunted' }));
  expect(hunted).toMatchObject({
    line: 'A boar was hunted',
    importance: 2,
    animal: true,
  });
  expect(entry(event('died', 'elk:2', { cause: 'old age' })).line).toBe(
    'An elk died (old age)',
  );
  expect(entry(event('died', 'polar_bear:1')).line).toBe('A polar bear died');
  const filters = (one: FeedEntry) =>
    (['all', 'people', 'danger', 'economy'] as const).filter((filter) =>
      shows(one, filter),
    );
  expect(filters(hunted)).toEqual(['all']);
  const citizen = entry(event('died', 'pip', { cause: 'hunted' }));
  expect(citizen).toMatchObject({
    line: 'Pip died (hunted)',
    importance: 3,
    animal: false,
  });
  expect(filters(citizen)).toEqual(['all', 'danger']);
});

test('an event’s own line, importance and position win (the backend line registry)', () => {
  const sale = entry(
    event(
      'sold',
      'tek',
      {},
      {
        line: 'Tek sold 3 fish to Fumiko for 6 mon',
        importance: 2,
        position: { unit: [0, 0, 1] },
      },
    ),
  );
  expect(sale).toMatchObject({
    line: 'Tek sold 3 fish to Fumiko for 6 mon',
    importance: 2,
    position: [0, 0, 1],
  });
  expect(
    feedEntry(event('node_changed', null, {}, { importance: 0 }), SUBJECTS),
  ).toBeNull();
});

test('repeats merge into a recent entry, counted and moved to the top', () => {
  const fished = () =>
    entry(event('crafted', 'tek', {}, { line: 'Tek fished', importance: 2 }));
  let feed: FeedEntry[] = [];
  feed = addEntry(feed, fished());
  feed = addEntry(feed, entry(event('said', 'pip', { words: 'Look!' })));
  feed = addEntry(feed, fished());
  feed = addEntry(feed, fished());
  expect(feed.map(({ line, count }) => `${line} ×${count}`)).toEqual([
    'Tek fished ×3',
    'Pip: “Look!” ×1',
  ]);
  // the same event twice (a resend) adds nothing
  const once = entry(event('died', 'pip'));
  expect(addEntry(addEntry([], once), once)).toEqual([once]);
  // the same words from someone else are another story
  const felled = (actor: string) =>
    entry(
      event('tree_felled', actor, {}, { line: 'A tree fell', importance: 2 }),
    );
  expect(addEntry(addEntry([], felled('tek')), felled('pip'))).toHaveLength(2);
});

test('a repeat older than the six newest entries starts a new one; the feed keeps 60', () => {
  const tek = entry(event('said', 'tek', { words: 'Again' }));
  let feed = addEntry([], tek);
  for (let k = 0; k < 6; k++)
    feed = addEntry(feed, entry(event('said', 'pip', { words: `w${k}` })));
  feed = addEntry(feed, entry(event('said', 'tek', { words: 'Again' })));
  expect(feed.filter((one) => one.line === 'Tek: “Again”')).toHaveLength(2);
  for (let k = 0; k < 80; k++)
    feed = addEntry(feed, entry(event('said', 'pip', { words: `x${k}` })));
  expect(feed).toHaveLength(FEED_KEEP);
  expect(feed[0].line).toBe('Pip: “x79”');
});

test('filters: People, Danger, Economy; All shows everything', () => {
  const kinds = (type: string) =>
    (['all', 'people', 'danger', 'economy'] as const).filter((filter) =>
      shows(
        entry(event(type, 'tek', {}, { line: type, importance: 2 })),
        filter,
      ),
    );
  expect(kinds('said')).toEqual(['all', 'people']);
  expect(kinds('died')).toEqual(['all', 'danger']);
  expect(kinds('judged')).toEqual(['all', 'people', 'danger']);
  expect(kinds('sold')).toEqual(['all', 'economy']);
  expect(kinds('fire_changed')).toEqual(['all']);
});

test('a mock death shows in the feed with the tick it happened; the filters and ▶ work', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  const feed = page.getByTestId('event-feed');
  await page.evaluate(() => {
    const mock = (
      globalThis as unknown as MockLiveWindow & {
        __pebbleMockLive: {
          queueEvent(
            type: string,
            actor: string | null,
            payload: Record<string, unknown>,
          ): void;
        };
      }
    ).__pebbleMockLive;
    mock.queueEvent('died', 'pip', { cause: 'a fall' });
    mock.setClock({ speed: 60, paused: false });
  });
  const tick = Number(await world.getAttribute('data-live-tick'));
  const death = feed.locator('[data-event-type="died"]');
  await expect(death).toContainText('Pip died (a fall)', { timeout: 3_000 });
  await expect(death).toHaveAttribute('data-importance', '3');
  // within one tick of when it happened: the page is at most a tick past it
  expect(
    Number(await world.getAttribute('data-live-tick')),
  ).toBeLessThanOrEqual(tick + 2);

  await page.getByRole('button', { name: 'People', exact: true }).click();
  await expect(death).toHaveCount(0);
  await page.getByRole('button', { name: 'Danger', exact: true }).click();
  await expect(death).toHaveCount(1);

  await death.getByRole('button', { name: /fly to/ }).click();
  await expect(world).toHaveAttribute('data-camera-site', 'band_b_camp', {
    timeout: 10_000,
  });

  await page.keyboard.press('KeyL');
  await expect(feed).toHaveCount(0);
  await page.keyboard.press('KeyL');
  await expect(feed.locator('[data-event-type="died"]')).toHaveCount(1);
  expect(errors).toEqual([]);
});
