import { expect, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { LiveEventMessage } from '../../src/lib/live/live-contract';
import {
  addEntry,
  FEED_KEEP,
  FOLD_TICKS,
  type FeedEntry,
  feedEntry,
  type FeedSubjects,
  flightTarget,
  foldDetail,
  shows,
} from '../../src/lib/live/event-feed';
import { cameraOf, landed, type MockLiveWindow, openHeld } from './ui-helpers';

/* The event feed: lines and importance, merged repeats, filters (no browser); a mock death in the page. */

const SUBJECTS: FeedSubjects = {
  animals: new Map([
    ['boar:35', 'boar'],
    ['elk:2', 'elk'],
  ]),
  groups: new Map(),
};

type Told = Pick<LiveEventMessage['event'], 'line' | 'importance'> &
  Partial<Pick<LiveEventMessage['event'], 'position'>>;

let serial = 0;
const event = (
  type: string,
  actor: string | null,
  told: Told,
  payload: Record<string, unknown> = {},
  tick = 600,
): LiveEventMessage => ({
  type: 'event',
  run_id: 'run-1',
  tick,
  event: {
    id: `e${(serial += 1)}`,
    type,
    actor_id: actor,
    payload,
    position: null,
    ...told,
  },
});
const said = (actor: string, name: string, words: string) =>
  event(
    'said',
    actor,
    { line: `${name}: “${words}”`, importance: 1 },
    { words },
  );
const at = (x: number, y: number, z: number) => ({
  unit: [x, y, z] as [number, number, number],
  height_m: 0,
  lat: 0,
  lon: 0,
});

const entry = (message: LiveEventMessage) => feedEntry(message, SUBJECTS)!;

test('an event’s line, importance and place come as the backend told them; importance 0 is hidden', () => {
  expect(
    entry(
      event('died', 'pip', {
        line: 'Pip dies (thirst)',
        importance: 3,
        position: at(0, 0, 1),
      }),
    ),
  ).toMatchObject({
    type: 'died',
    actorId: 'pip',
    line: 'Pip dies (thirst)',
    importance: 3,
    time: '18:00',
    position: [0, 0, 1],
    count: 1,
    animal: false,
  });
  expect(entry(said('tek', 'Tek', 'Fish!'))).toMatchObject({
    line: 'Tek: “Fish!”',
    importance: 1,
    position: null,
  });
  const hidden = { line: 'Tek starts fishing', importance: 0 } as const;
  expect(
    feedEntry(event('action_started', 'tek', hidden), SUBJECTS),
  ).toBeNull();
  expect(
    feedEntry(
      event('node_changed', null, { line: 'x', importance: 0 }),
      SUBJECTS,
    ),
  ).toBeNull();
});

test('an animal’s doings are no danger to people: its death shows under All only', () => {
  const hunted = entry(
    event('died', 'boar:35', {
      line: 'A boar is brought down by a hunter',
      importance: 2,
    }),
  );
  expect(hunted.animal).toBe(true);
  const filters = (one: FeedEntry) =>
    (['all', 'people', 'danger', 'economy'] as const).filter((filter) =>
      shows(one, filter),
    );
  expect(filters(hunted)).toEqual(['all']);
  const citizen = entry(
    event('died', 'pip', { line: 'Pip dies (hunted)', importance: 3 }),
  );
  expect(citizen.animal).toBe(false);
  expect(filters(citizen)).toEqual(['all', 'danger']);
});

test('repeats merge into a recent entry, counted and moved to the top', () => {
  const fished = () =>
    entry(event('crafted', 'tek', { line: 'Tek fished', importance: 2 }));
  let feed: FeedEntry[] = [];
  feed = addEntry(feed, fished());
  feed = addEntry(feed, entry(said('pip', 'Pip', 'Look!')));
  feed = addEntry(feed, fished());
  feed = addEntry(feed, fished());
  expect(feed.map(({ line, count }) => `${line} ×${count}`)).toEqual([
    'Tek fished ×3',
    'Pip: “Look!” ×1',
  ]);
  // the same event twice (a resend) adds nothing, even one merged under a newer repeat
  const once = entry(event('died', 'pip', { line: 'Pip dies', importance: 3 }));
  expect(addEntry(addEntry([], once), once)).toEqual([once]);
  const first = fished();
  const merged = addEntry(addEntry([], first), fished());
  expect(addEntry(merged, first)).toEqual(merged);
  expect(merged[0].count).toBe(2);
  // the same words from someone else are another story
  const felled = (actor: string) =>
    entry(event('tree_felled', actor, { line: 'A tree fell', importance: 2 }));
  expect(addEntry(addEntry([], felled('tek')), felled('pip'))).toHaveLength(2);
});

test('a repeat older than the six newest entries starts a new one; the feed keeps 60', () => {
  let feed = addEntry([], entry(said('tek', 'Tek', 'Again')));
  for (let k = 0; k < 6; k++)
    feed = addEntry(feed, entry(said('pip', 'Pip', `w${k}`)));
  feed = addEntry(feed, entry(said('tek', 'Tek', 'Again')));
  expect(feed.filter((one) => one.line === 'Tek: “Again”')).toHaveLength(2);
  for (let k = 0; k < 80; k++)
    feed = addEntry(feed, entry(said('pip', 'Pip', `x${k}`)));
  expect(feed).toHaveLength(FEED_KEEP);
  expect(feed[0].line).toBe('Pip: “x79”');
});

/* Band B wakes up on day 6 (09:05-09:18 in a seeded run): every one of them waves and greets every other. */
const GROUPS: FeedSubjects = {
  ...SUBJECTS,
  groups: new Map([
    ['nim', 'band_b'],
    ['pip', 'band_b'],
    ['vesa', 'band_b'],
    ['daisuke', 'town'],
    ['tetsu', 'town'],
  ]),
};
const grouped = (message: LiveEventMessage) => feedEntry(message, GROUPS)!;
const waved = (actor: string, name: string, to: string, tick: number) =>
  grouped(
    event(
      'gestured',
      actor,
      { line: `${name} waves to ${to}`, importance: 1 },
      { kind: 'wave', to },
      tick,
    ),
  );
const spoke = (actor: string, name: string, words: string, tick: number) =>
  grouped(
    event(
      'said',
      actor,
      { line: `${name}: “${words}”`, importance: 1 },
      { words },
      tick,
    ),
  );
const shown = (feed: FeedEntry[]) =>
  feed.map((one) =>
    one.folded.length > 0
      ? `${one.line} ×${one.count} · ${foldDetail(one)}`
      : one.line,
  );

test('a band’s greetings and small talk fold into one line; what matters stays on its own', () => {
  let feed: FeedEntry[] = [];
  const add = (one: FeedEntry) => (feed = addEntry(feed, one));
  add(waved('nim', 'Nim', 'Pip', 905));
  expect(shown(feed)).toEqual(['Nim waves to Pip']); // one alone reads as itself
  expect(feed[0]).toMatchObject({ chatter: 'band_b', type: 'gestured' });
  add(spoke('nim', 'Nim', 'Pip! You’re up.', 905));
  add(
    grouped(event('died', 'pip', { line: 'Pip dies (a fall)', importance: 3 })),
  );
  add(spoke('daisuke', 'Daisuke', 'Have you eaten, Tetsu?', 910));
  add(waved('vesa', 'Vesa', 'Nim', 910));
  for (let tick = 911; tick < 918; tick++) {
    add(waved('pip', 'Pip', 'Vesa', tick));
    add(spoke('vesa', 'Vesa', `Morning ${tick}`, tick));
  }
  add(spoke('tetsu', 'Tetsu', 'Well enough, Daisuke.', 918));
  add(waved('pip', 'Pip', 'Nim', 918));
  expect(shown(feed)).toEqual([
    'Band B greet each other and chat ×18 · Vesa: “Morning 917”',
    'Townsfolk chat ×2 · Tetsu: “Well enough, Daisuke.”',
    'Pip dies (a fall)',
  ]);
  const [band] = feed;
  expect(band).toMatchObject({
    type: 'chatter',
    actorId: 'pip',
    tick: 918,
    importance: 1,
  });
  expect(band.ids).toHaveLength(18);
  expect(band.folded.map(({ line }) => line).slice(0, 3)).toEqual([
    'Pip waves to Nim',
    'Vesa: “Morning 917”',
    'Pip waves to Vesa',
  ]);
  expect(band.folded.at(-1)!.line).toBe('Nim waves to Pip');
  // a resend of any folded event adds nothing
  const first = feed[0].ids[0];
  expect(
    addEntry(feed, {
      ...waved('nim', 'Nim', 'Pip', 905),
      id: first,
      ids: [first],
    }),
  ).toEqual(feed);
  // the fold is People news
  expect(shows(band, 'people')).toBe(true);
  expect(shows(band, 'danger')).toBe(false);
});

test('chatter folds only with its own group’s recent chatter; gestures alone greet, speech alone chats', () => {
  let feed = addEntry([], waved('nim', 'Nim', 'Pip', 900));
  feed = addEntry(feed, waved('pip', 'Pip', 'Nim', 900 + FOLD_TICKS));
  expect(shown(feed)).toEqual([
    'Band B greet each other ×2 · Pip waves to Nim',
  ]);
  // later than FOLD_TICKS after the fold's newest: a new story
  feed = addEntry(feed, spoke('vesa', 'Vesa', 'Hi', 901 + 2 * FOLD_TICKS));
  expect(shown(feed)).toEqual([
    'Vesa: “Hi”',
    'Band B greet each other ×2 · Pip waves to Nim',
  ]);
  feed = addEntry(feed, spoke('nim', 'Nim', 'Ho', 902 + 2 * FOLD_TICKS));
  expect(shown(feed)[0]).toBe('Band B chat ×2 · Nim: “Ho”');
  // more than eight newer entries in between: a new story too
  for (let k = 0; k < 8; k++)
    feed = addEntry(
      feed,
      grouped(event('sold', 'tetsu', { line: `sale ${k}`, importance: 2 })),
    );
  feed = addEntry(feed, spoke('pip', 'Pip', 'Late', 903 + 2 * FOLD_TICKS));
  expect(feed[0]).toMatchObject({ line: 'Pip: “Late”', count: 1 });
  // speech that matters (importance 2+) and anyone without a known group never fold
  const loud = spoke('nim', 'Nim', 'Wolves!', 904 + 2 * FOLD_TICKS);
  expect(
    grouped(event('said', 'nim', { line: 'Nim: “Wolves!”', importance: 2 }))
      .chatter,
  ).toBeNull();
  expect(loud.chatter).toBe('band_b');
  expect(entry(said('nim', 'Nim', 'Hi')).chatter).toBeNull();
  expect(
    grouped(event('sold', 'nim', { line: 'Nim sells', importance: 1 })).chatter,
  ).toBeNull();
});

test('filters: People, Danger, Economy; All shows everything', () => {
  const kinds = (type: string) =>
    (['all', 'people', 'danger', 'economy'] as const).filter((filter) =>
      shows(entry(event(type, 'tek', { line: type, importance: 2 })), filter),
    );
  expect(kinds('said')).toEqual(['all', 'people']);
  expect(kinds('died')).toEqual(['all', 'danger']);
  expect(kinds('judged')).toEqual(['all', 'people', 'danger']);
  expect(kinds('sold')).toEqual(['all', 'economy']);
  expect(kinds('fire_changed')).toEqual(['all']);
});

test('▶ flies to where it happened, else to the actor as drawn; nowhere for an actor not drawn', () => {
  const v = (x: number, y: number, z: number) => new Vector3(x, y, z);
  const drawn = {
    animals: new Map([['boar:35', { position: v(0, 0, 2010) }]]),
    citizens: new Map([['tek', { pose: { position: v(2005, 0, 0) } }]]),
  };
  const target = (message: LiveEventMessage) =>
    flightTarget(entry(message), drawn)
      ?.toArray()
      .map((value) => Math.round(value * 1e6) / 1e6) ?? null;
  const fell = { line: 'Tek fells a tree', importance: 2 } as const;
  expect(
    target(event('tree_felled', 'tek', { ...fell, position: at(0, 1, 0) })),
  ).toEqual([0, 1, 0]);
  const boar = {
    line: 'A boar is brought down by a hunter',
    importance: 2,
  } as const;
  expect(target(event('died', 'boar:35', boar))).toEqual([0, 0, 1]);
  expect(target(said('tek', 'Tek', 'Hi'))).toEqual([1, 0, 0]);
  // Pip is not drawn (gone since ▶ was drawn): no flight, so a followed citizen stays followed
  expect(target(said('pip', 'Pip', 'Hi'))).toBeNull();
  expect(
    target(event('died', 'elk:2', { line: 'An elk dies', importance: 1 })),
  ).toBeNull();
  expect(
    target(event('tree_felled', null, { line: 'A tree fell', importance: 2 })),
  ).toBeNull();
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
            told: { line: string; importance: number },
          ): void;
        };
      }
    ).__pebbleMockLive;
    // it happens where Pip stands (band B's camp)
    mock.queueEvent(
      'died',
      'pip',
      { cause: 'a fall' },
      { line: 'Pip dies (a fall)', importance: 3 },
    );
    mock.setClock({ speed: 60, paused: false });
  });
  const tick = Number(await world.getAttribute('data-live-tick'));
  const death = feed.locator('[data-event-type="died"]');
  await expect(death).toContainText('Pip dies (a fall)', { timeout: 3_000 });
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

type QueueWindow = MockLiveWindow & {
  __pebbleMockLive: {
    queueEvent(
      type: string,
      actor: string | null,
      payload: Record<string, unknown>,
      told: Told,
    ): void;
  };
};

const queue = (
  page: Page,
  type: string,
  actor: string | null,
  payload: Record<string, unknown>,
  told: Told,
) =>
  page.evaluate(
    ({ type, actor, payload, told }) =>
      (globalThis as unknown as QueueWindow).__pebbleMockLive.queueEvent(
        type,
        actor,
        payload,
        told,
      ),
    { type, actor, payload, told },
  );

test('a band’s greetings show as one folded line in the page, the newest words after it', async ({
  page,
}) => {
  const errors: string[] = [];
  await openHeld(page, errors);
  const feed = page.getByTestId('event-feed');
  await queue(
    page,
    'gestured',
    'pip',
    { kind: 'wave', to: 'brak' },
    {
      line: 'Pip waves to Brak',
      importance: 1,
    },
  );
  await queue(
    page,
    'said',
    'brak',
    { words: 'Pip! You’re up.' },
    {
      line: 'Brak: “Pip! You’re up.”',
      importance: 1,
    },
  );
  await queue(
    page,
    'gestured',
    'sela',
    { kind: 'bow', to: 'brak' },
    {
      line: 'Sela bows to Brak',
      importance: 1,
    },
  );
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.setClock({
      speed: 60,
      paused: false,
    }),
  );
  // (the mock world chats too: only band B's fold is looked at)
  const folded = feed
    .locator('[data-event-type="chatter"]')
    .filter({ hasText: 'Band B' });
  await expect(folded).toHaveCount(1, { timeout: 3_000 });
  await expect(folded).toContainText('Band B greet each other and chat ×3');
  await expect(folded.getByTestId('fold-detail')).toHaveText(
    ' · Brak: “Pip! You’re up.”',
  );
  await expect(feed.getByText('Pip waves to Brak')).toHaveCount(0);
  await page.getByRole('button', { name: 'People', exact: true }).click();
  await expect(folded).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('▶ lets go of a followed citizen; an animal’s entry flies to the animal as drawn', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  const feed = page.getByTestId('event-feed');
  // the animal farthest from the first citizen (whom Tab selects), and that citizen's spot for a placed event
  const { animal, spot } = await page.evaluate(() => {
    const { citizens, animals } = (
      globalThis as unknown as MockLiveWindow
    ).__pebbleMockLive.entities();
    const [x, y, z] = citizens[0].position.unit;
    const near = ({ unit: [a, b, c] }: { unit: number[] }) =>
      a * x + b * y + c * z;
    const far = [...animals].sort(
      (a, b) => near(a.position) - near(b.position),
    )[0];
    return { animal: far, spot: citizens[0].position.unit };
  });
  expect(
    new Vector3(...animal.position.unit).angleTo(new Vector3(...spot)),
  ).toBeGreaterThan(300 / 2000);
  // a citizen is followed
  await page.keyboard.press('Tab');
  await page.keyboard.press('KeyF');
  await expect(world).toHaveAttribute('data-follow');
  await landed(world);

  await queue(
    page,
    'tree_felled',
    null,
    {},
    {
      line: 'A tree fell',
      importance: 2,
      position: { unit: spot, height_m: 0, lat: 0, lon: 0 },
    },
  );
  const kind = animal.kind.replaceAll('_', ' ');
  const anAnimal = `${/^[aeiou]/.test(kind) ? 'An' : 'A'} ${kind}`;
  await queue(
    page,
    'died',
    animal.id,
    { cause: 'hunted' },
    { line: `${anAnimal} is brought down by a hunter`, importance: 2 },
  );
  await queue(
    page,
    'died',
    'nobody:1',
    {},
    { line: 'Someone dies', importance: 3 },
  );
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.setClock({
      speed: 60,
      paused: false,
    }),
  );
  const felled = feed.locator('[data-event-type="tree_felled"]');
  const hunted = feed
    .locator('[data-event-type="died"]')
    .filter({ hasText: 'brought down' });
  await expect(felled).toHaveCount(1, { timeout: 3_000 });
  await expect(hunted).toHaveAttribute('data-importance', '2');

  // nowhere to go for an actor that is not drawn: no ▶
  const nobody = feed
    .locator('[data-event-type="died"]')
    .filter({ hasText: 'Someone dies' });
  await expect(nobody).toHaveCount(1);
  await expect(nobody.getByRole('button', { name: /fly to/ })).toHaveCount(0);

  await felled.getByRole('button', { name: /fly to/ }).click();
  await expect(world).not.toHaveAttribute('data-follow');
  await landed(world);

  await page.keyboard.press('KeyF');
  await expect(world).toHaveAttribute('data-follow');
  await landed(world);
  await hunted.getByRole('button', { name: /fly to/ }).click();
  await expect(world).not.toHaveAttribute('data-follow');
  await landed(world);
  const at = await page.evaluate(
    (id) =>
      (globalThis as unknown as MockLiveWindow).__pebbleMockLive
        .entities()
        .animals.find((one) => one.id === id)!.position.unit,
    animal.id,
  );
  // landed within ~60 m (the planet's radius is 2000 m) of where the animal is
  expect(
    new Vector3(...at).angleTo((await cameraOf(world)).normalize()),
  ).toBeLessThan(60 / 2000);
  expect(errors).toEqual([]);
});
