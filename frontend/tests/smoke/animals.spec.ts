import { expect, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import type { AnimalActivity } from '../../src/lib/live/animal-motion';
import type { LiveAnimal } from '../../src/lib/live/live-contract';
import { SCENE_IDS, sceneAnimals } from '../../src/lib/live/mock-animal-scenes';
import { anchorMapping, latLonFromDirection } from '../../src/lib/world/globe';
import { SPEEDS } from './animal-speeds';
import { openGlobe, WORLD_URL } from './globe-helpers';

/*
 * Animals' behaviour on the globe (10 §4.2, §4.6; D144-D146), played by the mock feed's scripted scenes by band A's
 * camp: every behaviour is in the scripts, a wolf reaches the deer where it falls and its carcass is bones a day
 * later, movers face their way and keep pace at ×10, and every kind shows every standing layer. The pure motion
 * rules are `animal-motion.spec.ts`.
 */

test.describe.configure({ timeout: 120_000 });

const R = 2000;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number): [number, number, number] =>
  new Vector3(x / R, z / R, 1).normalize().toArray();

// --- the mock's scripted scenes ---

/** Every scene animal over a period, tick by tick (the chart is flat local metres here). */
function playScenes(ticks: number) {
  const place = ([x, z]: [number, number]) => ({
    unit: at(x, -z),
    height_m: 0,
    lat: 0,
    lon: 0,
  });
  return Array.from({ length: ticks }, (_, tick) => sceneAnimals(tick, place));
}

test('the mock’s scenes show every behaviour the globe draws, at the bible’s speeds', () => {
  const frames = playScenes(2 * 24 * 60);
  const seen = new Set(frames.flat().map((animal) => animal.activity));
  const water: AnimalActivity[] = ['floating', 'swimming'];
  const v0: AnimalActivity[] = ['running', 'hunting'];
  const vocabulary: AnimalActivity[] = [
    'idle',
    'grazing',
    'alert',
    'walking',
    'trotting',
    'fleeing',
    'frozen',
    'prowling',
    'stalking',
    'chasing',
    'pouncing',
    'attacking',
    'feeding',
    'drinking',
    'sleeping',
    'dead',
    'remains',
  ];
  expect([...seen].sort()).toEqual(vocabulary.sort());
  expect(
    vocabulary.filter((word) => water.includes(word) || v0.includes(word)),
  ).toEqual([]);
  // no leg of any route is faster than its kind's run
  for (const animal of frames.flat()) {
    const [, run] = SPEEDS[animal.kind] ?? [0, Infinity];
    for (let k = 1; k < animal.route.length; k++) {
      const [a, b] = [animal.route[k - 1], animal.route[k]];
      const metres = new Vector3(...a.unit).angleTo(new Vector3(...b.unit)) * R;
      const seconds = (b.t_s ?? 0) - (a.t_s ?? 0);
      if (metres > 1e-3)
        expect(metres / seconds, animal.id).toBeLessThanOrEqual(run * 1.001);
    }
  }
});

/** The scene animal `id` in a frame. */
const find = (frame: LiveAnimal[], id: string) => {
  const found = frame.find((animal) => animal.id === id);
  if (!found) throw new Error(`no ${id}`);
  return found;
};

test('the mock’s hunt: the wolf reaches the deer where it falls, the carcass is remains a day later', () => {
  const frames = playScenes(2 * 24 * 60);
  const kill = frames.findIndex(
    (frame) => find(frame, 'deer:203').activity === 'dead',
  );
  const deer = find(frames[kill], 'deer:203');
  const wolf = find(frames[kill], 'wolf:211');
  expect(wolf.activity).toBe('pouncing');
  expect(find(frames[kill], 'deer:201').activity).toBe('fleeing'); // the herd bolts
  expect(find(frames[kill - 1], 'deer:201').activity).toBe('alert');
  expect(find(frames[kill - 1], 'wolf:211').activity).toBe('stalking');
  // both routes end at the catch, within a second of each other; the deer's ends where it lies
  const end = (animal: LiveAnimal) => animal.route[animal.route.length - 1];
  const gap =
    new Vector3(...end(deer).unit).angleTo(new Vector3(...end(wolf).unit)) * R;
  expect(gap).toBeLessThan(1.5);
  expect(Math.abs((end(deer).t_s ?? 0) - (end(wolf).t_s ?? 0))).toBeLessThan(1);
  expect(end(deer).unit).toEqual(deer.position.unit);
  expect(find(frames[kill + 1], 'wolf:211').activity).toBe('attacking');
  expect(find(frames[kill + 2], 'wolf:211').activity).toBe('feeding');
  expect(find(frames[kill + 24 * 60 - 1], 'deer:203').activity).toBe('dead');
  expect(find(frames[kill + 24 * 60], 'deer:203').activity).toBe('remains');
  expect(SCENE_IDS.size).toBe(frames[0].length);
});

// --- drawn on the globe (mock feed) ---

type MockLiveWindow = {
  __pebbleMockLive: {
    skip(ticks: number): void;
    setClock(change: { speed?: number; paused?: boolean }): void;
  };
};

let world: WorldView;
test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  world = (await (await api.get(WORLD_URL)).json()) as WorldView;
  await api.dispose();
});

/** Where a scene's local metres are on the real world (band A's camp chart, as `mock-wild.ts` places them). */
function placeOnWorld([x, z]: [number, number]) {
  const site = world.sites.find((s) => s.id === 'band_a_camp')!;
  const unit = anchorMapping(site.anchor, world.radius_m)
    .toWorld(x, 0, z, new Vector3())
    .normalize();
  const { lat, lon } = latLonFromDirection(unit);
  return { unit: unit.toArray(), height_m: site.anchor.height_m, lat, lon };
}

/** Opens the globe with the player `metres` south of where scene animal `id` is at `tick`, facing north at it. */
async function openAt(
  page: Page,
  errors: string[],
  id: string,
  tick: number,
  metres: number,
) {
  const animal = find(sceneAnimals(tick, placeOnWorld), id);
  const degree = (world.radius_m * Math.PI) / 180;
  const { lat, lon } = animal.position;
  const live = await openGlobe(
    page,
    errors,
    `?mockLive=1&at=${lat - metres / degree},${lon},0`,
  );
  await expect(live).toHaveAttribute('data-live-status', 'live');
  return animal;
}

interface Drawn {
  id: string;
  activity: string;
  clip: string;
  layer: string;
  pace: number;
  speed: number;
  roll: number;
  position: Vector3;
  facing: Vector3;
}

/** What is drawn of the animals near the camera right now. */
async function drawn(page: Page): Promise<Map<string, Drawn>> {
  const hooks = page.getByTestId('animals');
  const entries = async (name: string) =>
    new Map(
      ((await hooks.getAttribute(`data-${name}`)) ?? '')
        .split(' ')
        .filter(Boolean)
        .map((entry): [string, string[]] => {
          const [kind, number, ...rest] = entry.split(':');
          return [`${kind}:${number}`, rest];
        }),
    );
  const [clips, motion, positions, facing] = await Promise.all(
    ['near-clips', 'near-motion', 'near-positions', 'near-facing'].map(entries),
  );
  const vector = (text = '0,0,0') =>
    new Vector3(...text.split(',').map(Number));
  return new Map(
    [...clips].map(([id, [activity, clip]]): [string, Drawn] => {
      const [layer, pace, speed, roll] = motion.get(id) ?? [];
      return [
        id,
        {
          id,
          activity,
          clip,
          layer,
          pace: Number(pace),
          speed: Number(speed),
          roll: Number(roll),
          position: vector(positions.get(id)?.[0]),
          facing: vector(facing.get(id)?.[0]),
        },
      ];
    }),
  );
}

const skip = (page: Page, ticks: number) =>
  page.evaluate(
    (count) =>
      (globalThis as unknown as MockLiveWindow).__pebbleMockLive.skip(count),
    ticks,
  );
const setClock = (page: Page, change: { speed?: number; paused?: boolean }) =>
  page.evaluate(
    (clock) =>
      (globalThis as unknown as MockLiveWindow).__pebbleMockLive.setClock(
        clock,
      ),
    change,
  );

test('a drawn kill: the wolf runs in and pounces, the deer flees, falls where it is caught, and is bones a day later', async ({
  page,
}) => {
  const errors: string[] = [];
  const frames = playScenes(12);
  const kill = frames.findIndex(
    (frame) => find(frame, 'deer:203').activity === 'dead',
  );
  const caught = find(sceneAnimals(kill, placeOnWorld), 'deer:203');
  await openAt(page, errors, 'deer:203', kill, 30);
  await expect
    .poll(async () => (await drawn(page)).get('deer:203')?.clip ?? '', {
      timeout: 30_000,
    })
    .not.toBe('');
  await skip(page, kill - 1); // the tick before: wolves crouched, the herd looking up
  await page.waitForTimeout(1_000);
  await skip(page, 1); // the kill's tick, drawn in real time over the next minute
  const samples: Map<string, Drawn>[] = [];
  const started = Date.now();
  while (Date.now() - started < 24_000) {
    samples.push(await drawn(page));
    await page.waitForTimeout(50);
  }
  const deer = samples.map((sample) => sample.get('deer:203')!);
  const fell = deer.findIndex((d) => d.activity === 'dead');
  expect(fell).toBeGreaterThan(0);
  // it ran before it fell, with its run clip paced to its speed
  expect(deer.slice(0, fell).map((d) => d.activity)).toContain('grazing');
  expect(
    deer
      .slice(0, fell)
      .some((d) => d.activity === 'running' && d.clip === 'Run'),
  ).toBe(true);
  // where it fell: the catch point, the wolf on it
  const catchPoint = new Vector3(...caught.position.unit);
  const wolfThen = samples[fell].get('wolf:211')!;
  expect(
    deer[fell].position.clone().normalize().angleTo(catchPoint) *
      world.radius_m,
  ).toBeLessThan(0.5);
  expect(wolfThen.position.distanceTo(deer[fell].position)).toBeLessThan(2.5);
  expect(
    samples
      .slice(fell)
      .some(
        (s) =>
          s.get('wolf:211')?.layer === 'pounce' ||
          s.get('wolf:211')?.layer === 'bite',
      ),
  ).toBe(true);
  // the herd fled in the same tick, running (paced: speed over pace is the deer's own stride, 2.21 m/s)
  const fleeing = samples
    .map((sample) => sample.get('deer:201'))
    .filter((d): d is Drawn => d?.clip === 'Run' && d.speed > 5);
  expect(fleeing.length).toBeGreaterThan(0);
  for (const d of fleeing) expect(d.speed / d.pace).toBeCloseTo(2.21, 1);
  // it lies on its side once the fall is done
  await expect
    .poll(async () => (await drawn(page)).get('deer:203')?.roll ?? 0)
    .toBeCloseTo(Math.PI / 2, 1);
  // a day later only bones are left
  await skip(page, 24 * 60);
  await expect
    .poll(async () => (await drawn(page)).get('deer:203')?.layer)
    .toBe('bones');
  expect(errors).toEqual([]);
});

test('no moonwalking at ×10: movers face the way they go and their gait keeps pace with the ground', async ({
  page,
}) => {
  const errors: string[] = [];
  await openAt(page, errors, 'antelope:241', 4, 60);
  await skip(page, 3); // the lion prowls in; next tick the antelope bolt, then trot
  await setClock(page, { speed: 10 });
  const ways = new Map<string, Vector3>();
  let previous = await drawn(page);
  let checked = 0;
  const started = Date.now();
  while (Date.now() - started < 20_000) {
    await page.waitForTimeout(100);
    const now = await drawn(page);
    for (const [id, d] of now) {
      const before = previous.get(id);
      if (!before || d.speed <= 0 || d.clip === 'Idle') continue;
      const going = d.position.clone().sub(before.position);
      if (going.length() < 0.5) continue;
      going.normalize();
      const straight = (ways.get(id)?.dot(going) ?? 0) > 0.99; // not turning
      ways.set(id, going);
      if (!straight) continue;
      expect(going.dot(d.facing), `${id} faces its way`).toBeGreaterThan(0.9);
      expect(d.pace, `${id} paced`).toBeGreaterThan(0);
      checked += 1;
    }
    previous = now;
  }
  expect(checked).toBeGreaterThan(5);
  expect(errors).toEqual([]);
});

test('every kind in the line-up shows every standing behaviour', async ({
  page,
}) => {
  const errors: string[] = [];
  await openAt(page, errors, 'wolf:270', 0, 30);
  await setClock(page, { paused: true });
  const lineUp = (sample: Map<string, Drawn>) =>
    [...sample.values()].filter((d) => /^line-up/.test(groups.get(d.id) ?? ''));
  const groups = new Map(
    sceneAnimals(0, placeOnWorld).map((animal) => [animal.id, animal.group]),
  );
  await expect
    .poll(async () => lineUp(await drawn(page)).filter((d) => d.clip).length, {
      timeout: 60_000,
    })
    .toBe(13);
  const layers: Partial<Record<AnimalActivity, string>> = {
    idle: 'none',
    grazing: 'graze',
    alert: 'alert',
    stalking: 'stalk',
    frozen: 'frozen',
    pouncing: 'pounce',
    attacking: 'bite',
    feeding: 'feed',
    drinking: 'drink',
    sleeping: 'sleep',
    dead: 'dead',
  };
  const rears = new Set(['bear', 'polar_bear']);
  const shown = new Set<string>();
  for (let tick = 2; tick <= 22; tick += 2) {
    await skip(page, 2);
    const feed = sceneAnimals(tick, placeOnWorld).filter((animal) =>
      animal.group.startsWith('line-up'),
    );
    const activity = feed[0].activity;
    shown.add(activity);
    await expect
      .poll(async () =>
        lineUp(await drawn(page))
          .map((d) => `${d.id}:${d.activity}:${d.layer}`)
          .sort(),
      )
      .toEqual(
        feed
          .map((animal) => {
            const layer = layers[activity];
            const reared = layer === 'bite' && rears.has(animal.kind);
            return `${animal.id}:${activity}:${reared ? 'rear' : layer}`;
          })
          .sort(),
      );
  }
  expect(shown.size).toBe(Object.keys(layers).length);
  expect(errors).toEqual([]);
});
