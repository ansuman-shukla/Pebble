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
 * People panel, follow / go to, collisions and reconnecting (dropped, 1012, 4404); and the real feed
 * of the running engine once.
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
    dropConnections(code?: number): void;
    sayNow(actor: string, words: string): void;
    restartRun(): void;
    noRun: boolean;
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
  const world = await openLive(page, errors);
  // Haru calls out at the market on a run's first tick (the feed's own said event); a fresh run makes sure the
  // bubble isn't already gone while a busy machine loads the page (its snapshot drops the old run's bubbles)
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.restartRun(),
  );
  await expect(world).toHaveAttribute('data-live-connects', '2');
  await expect(world).toHaveAttribute('data-live-status', 'live');
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
  // the page's own start time gives way to the engine's
  const world = await openLive(page, errors, '?mockLive=1&time=20:00');
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

test('a new run (1012) resyncs at once; no run yet (4404) waits and retries', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors);
  await expect
    .poll(async () => Number(await world.getAttribute('data-live-tick')))
    .toBeGreaterThanOrEqual(3);
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.restartRun(),
  );
  // the new run's snapshot: tick 0 again, 08:00, everyone back home, right away (no backoff)
  await expect(world).toHaveAttribute('data-live-connects', '2', {
    timeout: 1_000,
  });
  await expect(world).toHaveAttribute('data-live-status', 'live');
  expect(Number(await world.getAttribute('data-live-tick'))).toBeLessThan(2);
  await expect(page.getByTestId('live-time')).toHaveText(/08:0[01]$/);

  // the run goes away: every connection is accepted and closed with 4404; the client says so and retries with
  // backoff (0.5 s, 1 s, 2 s ...), not at once and not as "live"
  await page.evaluate(() => {
    const mock = (globalThis as unknown as MockLiveWindow).__pebbleMockLive;
    mock.noRun = true;
    mock.dropConnections();
  });
  const connects = async () =>
    Number(await world.getAttribute('data-live-connects'));
  await expect(world).toHaveAttribute('data-live-status', 'reconnecting');
  await expect(world).toHaveAttribute('data-live-status', 'no-run');
  await expect(page.getByTestId('live-clock')).toContainText('no run yet');
  const refused = await connects();
  const statuses = new Set<string>();
  for (let k = 0; k < 30; k++) {
    statuses.add((await world.getAttribute('data-live-status'))!);
    await page.waitForTimeout(100);
  }
  expect([...statuses]).toEqual(['no-run']);
  // 3 s of backoff after the first refusal: two or three more tries (not 6 at a steady 0.5 s)
  expect((await connects()) - refused).toBeGreaterThanOrEqual(1);
  expect((await connects()) - refused).toBeLessThanOrEqual(3);

  // a run starts: the next try takes its snapshot
  await page.evaluate(() => {
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.noRun = false;
  });
  await expect(world).toHaveAttribute('data-live-status', 'live', {
    timeout: 10_000,
  });
  const resumed = Number(await world.getAttribute('data-live-tick'));
  await expect
    .poll(async () => Number(await world.getAttribute('data-live-tick')), {
      timeout: 5_000,
    })
    .toBeGreaterThan(resumed);
  expect(errors).toEqual([]);
});

test('the real feed: the 15 citizens stand where the engine says, on the ground, and follow its ticks', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    '15',
    { timeout: 30_000 },
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  const tick = async () => Number(await world.getAttribute('data-live-tick'));
  const startTick = await tick();

  // the feed is live: within a few seconds someone drawn moves or starts doing something else
  const first = await npcs(page);
  await expect
    .poll(
      async () =>
        (await npcs(page)).filter((npc) => {
          const was = first.find((candidate) => candidate.id === npc.id)!;
          return (
            npc.activity !== was.activity ||
            npc.position.distanceTo(was.position) > 0.01
          );
        }).length,
      { timeout: 5_000 },
    )
    .toBeGreaterThan(0);

  // the engine's positions (at most a tick of walking apart while frames glide in)
  const api = await page.request.get(ENTITIES_URL);
  expect(api.status()).toBe(200);
  const entities = (await api.json()) as EntitiesView;
  expect(entities.citizens).toHaveLength(15);
  expect(new Set(entities.citizens.map((citizen) => citizen.region))).toEqual(
    new Set(['town', 'band_a', 'band_b']),
  );
  const drawn = await npcs(page);
  for (const citizen of entities.citizens) {
    const npc = drawn.find((candidate) => candidate.id === citizen.id)!;
    expect(npc, citizen.id).toBeDefined();
    const unit = new Vector3(...citizen.position.unit);
    expect(npc.position.clone().normalize().angleTo(unit) * R).toBeLessThan(90);
    const direction = npc.position.clone().normalize();
    expect(
      Math.abs(npc.position.length() - (R + groundUnder(direction))),
    ).toBeLessThan(0.5);
  }

  // the engine ticks on and the drawn citizens follow it: at the page's tick, everyone who stood still since the
  // tick before is exactly where the engine has them, and everyone does what the engine says
  await expect.poll(tick, { timeout: 5_000 }).toBeGreaterThan(startTick);
  const at = async (when: number) =>
    (
      (await (
        await page.request.get(`${ENTITIES_URL}?at=${when}`)
      ).json()) as EntitiesView
    ).citizens;
  await expect
    .poll(
      async () => {
        const when = await tick();
        const [now, previous] = await Promise.all([at(when), at(when - 1)]);
        await page.waitForTimeout(150); // the hooks refresh every 100 ms
        const shown = await npcs(page);
        if ((await tick()) !== when) return ['the page moved on'];
        return now.flatMap((citizen) => {
          const npc = shown.find((candidate) => candidate.id === citizen.id)!;
          const unit = new Vector3(...citizen.position.unit);
          const before = previous.find((old) => old.id === citizen.id)!;
          const still =
            unit.angleTo(new Vector3(...before.position.unit)) * R < 0.01;
          const off = npc.position.clone().normalize().angleTo(unit) * R;
          return [
            ...(npc.activity === citizen.activity
              ? []
              : [`${citizen.id}: ${npc.activity} ≠ ${citizen.activity}`]),
            ...(off < (still ? 0.5 : 90)
              ? []
              : [`${citizen.id}: ${off.toFixed(2)} m off`]),
          ];
        });
      },
      { timeout: 15_000 },
    )
    .toEqual([]);

  // the townspeople near the spawn play their activity's clip
  await expect
    .poll(async () => (await npcs(page)).filter((npc) => npc.loaded).length, {
      timeout: 30_000,
    })
    .toBeGreaterThan(0);
  await expect
    .poll(async () =>
      (await npcs(page))
        .filter((npc) => npc.loaded && npc.clip && npc.activity !== 'walking')
        .filter(
          (npc) =>
            npc.clip !==
            npcLook({ activity: npc.activity, action_label: npc.label }).clip,
        )
        .map((npc) => `${npc.id} ${npc.activity} ${npc.label}: ${npc.clip}`),
    )
    .toEqual([]);

  await page.getByRole('button', { name: 'people', exact: true }).click();
  await expect(page.locator('[data-person]')).toHaveCount(15);
  await expect(page.getByRole('region', { name: 'People' })).toContainText(
    entities.citizens[0].name,
  );
  expect(errors).toEqual([]);
});
