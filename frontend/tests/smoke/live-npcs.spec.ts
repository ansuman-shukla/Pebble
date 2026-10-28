import { expect, type Locator, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { EntitiesView, WorldView } from '../../src/lib/client/types.gen';
import type { Activity } from '../../src/lib/live/live-contract';
import { npcLook } from '../../src/lib/live/npc-activity';
import {
  anchorMapping,
  buildTerrain,
  decodeWorld,
  type GlobeTerrain,
  type SiteMapping,
} from '../../src/lib/world/globe';
import { TOWN_GROUND_RADIUS } from './explore-helpers';
import {
  DRAW_CALL_BUDGET,
  hold,
  openGlobe,
  sample,
  WORLD_URL,
} from './globe-helpers';

/*
 * The live citizens on the planet: the dev/test mock feed (`?mockLive=1`) for movement, clips, speech, the
 * People panel, follow / go to, collisions and reconnecting; and the real `GET /api/v1/entities` once.
 */

const ENTITIES_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1/entities`;

let terrain: GlobeTerrain;
let R: number;
let town: { mapping: SiteMapping; height: number };

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const view = (await (await api.get(WORLD_URL)).json()) as WorldView;
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
  R = view.radius_m;
  const site = view.sites.find((candidate) => candidate.kind === 'town')!;
  town = {
    mapping: anchorMapping(site.anchor, R),
    height: site.anchor.height_m,
  };
});

interface Npc {
  id: string;
  position: Vector3;
  ground: number;
  activity: Activity;
  label: string;
  clip: string;
  loaded: boolean;
}

type Dataset = { dataset: Record<string, string | undefined> };
type MockLiveWindow = {
  __pebbleMockLive: {
    dropConnections(): void;
    sayNow(actor: string, words: string): void;
  };
};

/** Every drawn citizen as the page's hidden hooks show it now. */
async function npcs(page: Page): Promise<Npc[]> {
  const raw = await page
    .locator('[data-npc]')
    .evaluateAll((nodes) =>
      nodes.map((node) => ({ ...(node as unknown as Dataset).dataset })),
    );
  return raw.map((data) => ({
    id: data.npc!,
    position: new Vector3(
      Number(data.npcX),
      Number(data.npcY),
      Number(data.npcZ),
    ),
    ground: Number(data.npcGround),
    activity: data.npcActivity as Activity,
    label: data.npcLabel ?? '',
    clip: data.npcClip ?? '',
    loaded: data.npcLoaded === 'true',
  }));
}

/** Samples every citizen every 100 ms for `ms`. */
async function trackNpcs(page: Page, ms: number) {
  const samples: Npc[][] = [];
  for (let elapsed = 0; elapsed < ms; elapsed += 100) {
    samples.push(await npcs(page));
    await page.waitForTimeout(100);
  }
  return samples;
}

const npcOf = async (page: Page, id: string) =>
  (await npcs(page)).find((npc) => npc.id === id)!;

/** The ground as drawn under a direction: the town's disc at its plateau height, else the terrain. */
function groundUnder(direction: Vector3) {
  const local = town.mapping.toLocal(
    direction.clone().multiplyScalar(R),
    new Vector3(),
  );
  return Math.hypot(local.x, local.z) < TOWN_GROUND_RADIUS
    ? town.height
    : terrain.heightAt(direction);
}

async function openLive(page: Page, errors: string[], query = '?mockLive=1') {
  const world = await openGlobe(page, errors, query);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    '15',
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  return world;
}

const playerOf = async (world: Locator) => {
  const current = await sample(world);
  return new Vector3(current.x, current.y, current.z);
};

const cameraOf = async (world: Locator) => {
  const [x, y, z] = (await world.getAttribute('data-camera'))!
    .split(',')
    .map(Number);
  return new Vector3(x, y, z);
};

/** Waits for a camera flight (follow, go to) to start and land. */
async function landed(world: Locator) {
  await expect(world).toHaveAttribute('data-camera-flying', 'true');
  await expect(world).toHaveAttribute('data-camera-flying', 'false', {
    timeout: 10_000,
  });
}

test('the 15 citizens glide between ticks, stand on the ground and play their activity', async ({
  page,
}) => {
  const errors: string[] = [];
  await openLive(page, errors);
  // the townspeople are within reach of the spawn: their models load
  await expect
    .poll(async () => (await npcs(page)).filter((npc) => npc.loaded).length, {
      timeout: 30_000,
    })
    .toBeGreaterThanOrEqual(6);

  const samples = await trackNpcs(page, 9_000);
  const ids = samples[0].map((npc) => npc.id);
  expect(ids).toHaveLength(15);
  let moved = 0;
  let biggestStep = 0;
  for (const id of ids) {
    const path = samples.map((all) => all.find((npc) => npc.id === id)!);
    for (const npc of path) {
      const direction = npc.position.clone().normalize();
      expect(
        Math.abs(npc.position.length() - (R + groundUnder(direction))),
      ).toBeLessThan(0.5);
    }
    const travelled = path[0].position.distanceTo(
      path[path.length - 1].position,
    );
    if (travelled > 40) moved += 1;
    for (let k = 1; k < path.length; k++)
      biggestStep = Math.max(
        biggestStep,
        path[k].position.distanceTo(path[k - 1].position),
      );
  }
  // someone walked a long way (Kenji: 82 m to the gate in one tick) without jumping there
  expect(moved).toBeGreaterThanOrEqual(1);
  expect(biggestStep).toBeLessThan(35);

  // each loaded citizen plays its activity's clip (walkers: the gait, or standing once arrived); a new
  // activity's clip takes a moment to fetch, so this settles over a few polls
  const mismatches = (all: Npc[]) =>
    all
      .filter((npc) => npc.loaded && npc.clip)
      .filter((npc) =>
        npc.activity === 'walking'
          ? !['Walk', 'Idle'].includes(npc.clip)
          : npc.clip !==
            npcLook({ activity: npc.activity, action_label: npc.label }).clip,
      )
      .map((npc) => `${npc.id} ${npc.activity} ${npc.label}: ${npc.clip}`);
  await expect.poll(async () => mismatches(await npcs(page))).toEqual([]);
  const near = (await npcs(page)).filter((npc) => npc.loaded && npc.clip);
  expect(near.length).toBeGreaterThanOrEqual(6);
  expect(near.find((npc) => npc.id === 'genzo')).toBeDefined();
  // the camps are 4 km away: their people aren't loaded
  for (const id of ['oru', 'brak'])
    expect((await npcOf(page, id)).loaded).toBe(false);

  const world = page.getByTestId('world');
  await expect(world).toHaveAttribute('data-draw-calls-mode', 'follow');
  expect(Number(await world.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );
  expect(errors).toEqual([]);
});

test('a said event shows a speech bubble for a few seconds', async ({
  page,
}) => {
  const errors: string[] = [];
  await openLive(page, errors);
  // Haru calls out at the market on the first tick (the feed's own said event)
  await expect(page.locator('[data-label="say-haru"]')).toHaveText(
    /Fresh rice and good salt today/,
    { timeout: 5_000 },
  );
  // a said event right now: the bubble shows at once and stays about 4 s
  const words =
    'Halt! Who goes there? State your name and your business at the castle gate.';
  const said = Date.now();
  await page.evaluate(
    (text) =>
      (globalThis as unknown as MockLiveWindow).__pebbleMockLive.sayNow(
        'kenji',
        text,
      ),
    words,
  );
  const bubble = page.locator('[data-label="say-kenji"]');
  await expect(bubble).toHaveText(words, { timeout: 1_000 });
  await expect(bubble).toHaveAttribute('data-label-kind', 'speech');
  await expect(bubble).toHaveCount(0, { timeout: 8_000 });
  const lasted = Date.now() - said;
  expect(lasted).toBeGreaterThan(3_500);
  expect(lasted).toBeLessThan(5_500);
  expect(errors).toEqual([]);
});

test('the People panel follows a citizen with the camera and Esc returns to the player', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors);
  const player = await playerOf(world);
  await page.getByRole('button', { name: 'people', exact: true }).click();
  const rows = page.locator('[data-person]');
  await expect(rows).toHaveCount(15);
  await expect(page.locator('[data-person="oru"]')).toContainText(
    'Band A leader',
  );

  // Oru is at band A's camp, 4 km away: the camera flies there and his model loads
  await page
    .locator('[data-person="oru"]')
    .getByRole('button', { name: 'follow' })
    .click();
  await expect(world).toHaveAttribute('data-follow', 'oru');
  await landed(world);
  await expect.poll(async () => (await npcOf(page, 'oru')).loaded).toBe(true);
  const oru = await npcOf(page, 'oru');
  const focus = (await page.getByTestId('npcs').getAttribute('data-focus'))!
    .split(',')
    .map(Number);
  expect(new Vector3(...focus).distanceTo(oru.position)).toBeLessThan(1);
  expect((await cameraOf(world)).distanceTo(oru.position)).toBeLessThan(45);
  // the player stayed in town
  expect((await playerOf(world)).distanceTo(player)).toBeLessThan(0.5);
  await expect(page.getByText('following Oru')).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(world).not.toHaveAttribute('data-follow');
  await landed(world);
  expect((await cameraOf(world)).distanceTo(player)).toBeLessThan(45);
  expect(errors).toEqual([]);
});

test('go to drops the player next to a citizen, who is labelled and solid', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors);
  await page.getByRole('button', { name: 'people', exact: true }).click();
  // the lord stands about in the castle courtyard, then rests there
  await page
    .locator('[data-person="tadamasa"]')
    .getByRole('button', { name: 'go to' })
    .click();
  await landed(world);
  const lord = (await npcOf(page, 'tadamasa')).position;
  const start = (await playerOf(world)).distanceTo(lord);
  expect(start).toBeLessThan(5);
  expect(start).toBeGreaterThan(0.5);
  await expect(page.locator('[data-label="npc-tadamasa"]')).toBeVisible();
  await expect(page.locator('[data-label="npc-tadamasa"]')).toHaveText(
    /^Lord Tadamasa · (standing about|resting)/,
  );

  // the player faces the lord after a go to: walking on stops at him
  const distances: number[] = [];
  await hold(page, ['KeyW'], async () => {
    for (let k = 0; k < 30; k++) {
      distances.push((await playerOf(world)).distanceTo(lord));
      await page.waitForTimeout(100);
    }
  });
  expect(Math.min(...distances)).toBeGreaterThan(0.5);
  expect(distances[distances.length - 1]).toBeLessThan(1.2);
  expect(errors).toEqual([]);
});

test('the clock follows the feed, its speed buttons drive it, and a dropped feed reconnects', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors);
  const tick = async () => Number(await world.getAttribute('data-live-tick'));
  // the sky runs on engine time: tick 0 is 08:00
  await expect
    .poll(async () => {
      const minutes = Number(await world.getAttribute('data-game-minutes'));
      return Math.abs(minutes - (480 + (await tick())));
    })
    .toBeLessThanOrEqual(1);
  await expect(page.getByRole('button', { name: 'time ×60' })).toHaveCount(0);

  await page.getByRole('button', { name: '×60', exact: true }).click();
  const fast = await tick();
  await page.waitForTimeout(1_000);
  expect((await tick()) - fast).toBeGreaterThan(20);
  await page.getByRole('button', { name: 'pause', exact: true }).click();
  await page.waitForTimeout(300);
  const paused = await tick();
  await page.waitForTimeout(1_500);
  expect(await tick()).toBe(paused);
  await expect(page.getByTestId('live-time')).toHaveText(/^day 0 · \d\d:\d\d$/);
  await page.getByRole('button', { name: '×1', exact: true }).click();

  // the server goes away: the client reconnects and resyncs from the new snapshot
  await expect(world).toHaveAttribute('data-live-connects', '1');
  await page.evaluate(() =>
    (
      globalThis as unknown as MockLiveWindow
    ).__pebbleMockLive.dropConnections(),
  );
  await expect(world).toHaveAttribute('data-live-status', 'reconnecting');
  await expect(world).toHaveAttribute('data-live-status', 'live', {
    timeout: 5_000,
  });
  await expect(world).toHaveAttribute('data-live-connects', '2');
  const resumed = await tick();
  await expect.poll(tick, { timeout: 5_000 }).toBeGreaterThan(resumed);
  expect(errors).toEqual([]);
});

test('the real feed: the citizens of GET /api/v1/entities stand where the backend says', async ({
  page,
}) => {
  const errors: string[] = [];
  const api = await page.request.get(ENTITIES_URL);
  expect(api.status()).toBe(200);
  const entities = (await api.json()) as EntitiesView;
  expect(entities.citizens.length).toBeGreaterThan(0);
  const world = await openGlobe(page, errors);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    String(entities.citizens.length),
    { timeout: 30_000 },
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  const drawn = await npcs(page);
  for (const citizen of entities.citizens) {
    const npc = drawn.find((candidate) => candidate.id === citizen.id)!;
    expect(npc, citizen.id).toBeDefined();
    // at most one tick of walking from where the answer put them
    const unit = new Vector3(...citizen.position.unit);
    expect(npc.position.clone().normalize().angleTo(unit) * R).toBeLessThan(90);
  }
  await page.getByRole('button', { name: 'people', exact: true }).click();
  await expect(page.locator('[data-person]')).toHaveCount(
    entities.citizens.length,
  );
  await expect(page.getByRole('region', { name: 'People' })).toContainText(
    entities.citizens[0].name,
  );
  expect(errors).toEqual([]);
});
