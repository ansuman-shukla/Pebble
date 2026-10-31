import { expect, type Locator, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import type {
  CitizenEntity,
  EntitiesView,
  WorldView,
} from '../../src/lib/client/types.gen';
import {
  type Activity,
  TICK_SECONDS,
  tickMs,
} from '../../src/lib/live/live-contract';
import { LANE_M } from '../../src/lib/live/drawn-track';
import {
  type BodyPose,
  motionClips,
  type Motion,
} from '../../src/lib/live/motion';
import { KEEP_M } from '../../src/lib/live/separation';
import type { MockStartHook } from '../../src/lib/live/mock-live';
import { citizenPath, pointAt } from '../../src/lib/live/walk-path';
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
 * People panel, follow / go to, collisions, slow ticks and reconnecting (dropped, 1012, 4404); and the real feed
 * of the running engine once.
 */

const API_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1`;
const ENTITIES_URL = `${API_URL}/entities`;

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
  /** Left and right foot in the model's own frame (none while it isn't animated). */
  feet: Vector3[];
  /** The way the body faces (a unit vector). */
  facing: Vector3;
  /** Seconds of clip time its animation has played. */
  clipClock: number;
  /** How the body is posed: standing, seated, sitting on the ground, lying... */
  posture: BodyPose;
  /** What the body is shown doing (`motion.ts`). */
  motion: Motion;
}

/** The clips of a body drawn walking: a gait, or standing once it arrived. */
const GAIT_CLIPS = ['Walk', 'Walk formal', 'Run', 'Idle'];

type Dataset = { dataset: Record<string, string | undefined> };
type MockLiveWindow = {
  __pebbleMockLive: {
    dropConnections(code?: number): void;
    sayNow(actor: string, words: string): void;
    restartRun(): void;
    crowdCamp(): void;
    setClock(change: { speed?: number; paused?: boolean }): void;
    skip(ticks: number): void;
    entities(): EntitiesView;
    noRun: boolean;
  };
};

const footPair = (feet: string) => {
  const f = feet.split(',').map(Number);
  return [new Vector3(f[0], f[1], f[2]), new Vector3(f[3], f[4], f[5])];
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
    feet: data.npcFeet ? footPair(data.npcFeet) : [],
    facing: new Vector3(...(data.npcFacing ?? '0,0,0').split(',').map(Number)),
    clipClock: Number(data.npcClipClock),
    posture: (data.npcPosture ?? 'standing') as BodyPose,
    motion: (data.npcMotion ?? 'idle') as Motion,
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

/**
 * The globe on the mock feed. Like a new engine run the mock starts in real time (a tick a real minute); most tests
 * run it at ×60 (a tick a second, walkers cover 83 m of it), `speed` 1 keeps real time.
 */
async function openLive(
  page: Page,
  errors: string[],
  query = '?mockLive=1',
  speed = 60,
) {
  const world = await openGlobe(page, errors, query);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    '22',
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  if (speed !== 1)
    await page.evaluate(
      (fast) =>
        (globalThis as unknown as MockLiveWindow).__pebbleMockLive.setClock({
          speed: fast,
        }),
      speed,
    );
  return world;
}

/** Metres from a drawn spot to the nearest point of a route (unit directions), measured on the sphere's surface. */
function offPath(position: Vector3, route: Vector3[]) {
  const spot = position.clone().normalize();
  const leg = new Vector3();
  const nearest = new Vector3();
  let best = spot.angleTo(route[0]);
  for (let k = 0; k < route.length - 1; k++) {
    leg.subVectors(route[k + 1], route[k]);
    const t = Math.min(
      Math.max(nearest.subVectors(spot, route[k]).dot(leg) / leg.lengthSq(), 0),
      1,
    );
    nearest.copy(route[k]).addScaledVector(leg, t).normalize();
    best = Math.min(best, spot.angleTo(nearest));
  }
  return best * R;
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

test('the 22 citizens glide between ticks, stand on the ground and play their activity', async ({
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
  expect(ids).toHaveLength(22);
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
  // a body drawn moving is shown on the move, standing: a walk's last stretch keeps its walking (the frame already
  // says what comes next, e.g. resting by the fire), nobody glides sitting or lying
  const moves = (k: number, id: string) =>
    samples[k]
      .find((npc) => npc.id === id)!
      .position.distanceTo(
        samples[k - 1].find((npc) => npc.id === id)!.position,
      ) > 0.05;
  const gliding = samples.slice(1, -1).flatMap((all, k) =>
    all
      .filter((npc) => moves(k + 1, npc.id) && moves(k + 2, npc.id)) // on the way, not just arrived

      .filter((npc) => npc.activity !== 'walking' || npc.posture !== 'standing')
      .map((npc) => `${npc.id} ${npc.activity} ${npc.posture}`),
  );
  expect(gliding).toEqual([]);

  // each loaded citizen plays its motion's clip (walkers: the gait, or standing once arrived); a new motion's clip
  // takes a moment to fetch, so this settles over a few polls
  const mismatches = (all: Npc[]) =>
    all
      .filter((npc) => npc.loaded && npc.clip)
      .filter((npc) =>
        npc.activity === 'walking'
          ? !GAIT_CLIPS.includes(npc.clip)
          : !motionClips(npc.motion, npc.posture).some(
              (clip) => clip === npc.clip,
            ),
      )
      .map((npc) => `${npc.id} ${npc.activity} ${npc.motion}: ${npc.clip}`);
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

/** The citizens standing in a clip now (not walking), with their feet. */
const standing = async (page: Page) =>
  (await npcs(page)).filter(
    (npc) => npc.clip && npc.clip !== 'Walk' && npc.feet.length,
  );

/** The activities of someone on the move. */
const MOVING: Activity[] = ['walking', 'running', 'hunting'];
/** The fastest anyone moves (game m/s): fleeing, 5 km/h × 1.6 (backend `FLEE_PACE`). */
const FLEE_MPS = (5000 / 3600) * 1.6;
/** How late a tick's frame may come (real seconds): until it does, a drawn mover walks on into its plan ahead. */
const LATE_S = 0.5;

/**
 * What a citizen walked in its tick (unit directions): its route up to a tick in (`t_s` ≤ 60, from where it stood
 * when the tick began to where it is), not the plan ahead; where it stands when it didn't move.
 */
function walkedPart({ route, position }: CitizenEntity) {
  const walked = route.filter(
    ({ t_s }) => t_s != null && t_s <= TICK_SECONDS + 1e-6,
  );
  return (
    walked.length > 0 ? walked.map(({ unit }) => unit) : [position.unit]
  ).map((unit) => new Vector3(...unit));
}

/** How close a walker or runner comes before it pushes others aside (m): a runner's second of look-ahead and more. */
const PASSING_M = 5;

/**
 * How far the drawing may part a body from where the engine has it (D192): KEEP_M for each walker drawn passing by
 * (a walker of its own is pushed by anyone drawn by), nothing with nobody about. The engine itself never crowds a
 * body: its slots keep everyone who stands, sits or lies 0.8 m apart (D117), more than KEEP_M, and those inside a
 * house are out of the crowd.
 */
function parted(npc: Npc, shown: Npc[]) {
  const moving = MOVING.includes(npc.activity);
  const passing = shown.filter(
    (other) =>
      other.id !== npc.id &&
      (moving || MOVING.includes(other.activity)) &&
      other.position.distanceTo(npc.position) < PASSING_M,
  ).length;
  return KEEP_M * Math.sqrt(passing);
}

/** Metres from a drawn spot to the nearest of what a citizen walked in the given ticks. */
const offWalked = (position: Vector3, ticks: CitizenEntity[]) =>
  Math.min(...ticks.map((citizen) => offPath(position, walkedPart(citizen))));

/**
 * How far an idle or talking citizen's feet may slide in 3 s (m): with the hips pinned, Idle slid them 5-10 cm;
 * planted they stay within ~2 cm. (Work clips like Fixing step about in the capture itself, so they aren't
 * held to this.)
 */
const FOOT_DRIFT = 0.025;
const CALM_CLIPS = ['Idle', 'Talking'];

test('standing citizens keep their feet planted', async ({ page }) => {
  const errors: string[] = [];
  await openLive(page, errors);
  // a paused clock holds everyone in their activity (walkers stand once they arrive)
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.setClock({
      paused: true,
    }),
  );
  const calm = async () =>
    (await standing(page)).filter((npc) => CALM_CLIPS.includes(npc.clip))
      .length;
  await expect.poll(calm, { timeout: 30_000 }).toBeGreaterThanOrEqual(3);
  await page.waitForTimeout(1_000);

  const samples: Npc[][] = [];
  for (let elapsed = 0; elapsed < 3_000; elapsed += 100) {
    samples.push(await standing(page));
    await page.waitForTimeout(100);
  }
  const calmAtStart = samples[0].filter((npc) => CALM_CLIPS.includes(npc.clip));
  const sliding = calmAtStart.flatMap(({ id, clip, feet: first }) => {
    const path = samples.map((all) => all.find((npc) => npc.id === id)!);
    expect(path.map((npc) => npc.clip)).toEqual(path.map(() => clip));
    const slid = Math.max(
      ...path.flatMap(({ feet }) =>
        feet.map((foot, side) =>
          Math.hypot(foot.x - first[side].x, foot.z - first[side].z),
        ),
      ),
    );
    return slid < FOOT_DRIFT ? [] : [`${id} ${clip}: ${slid.toFixed(3)} m`];
  });
  expect(calmAtStart.length).toBeGreaterThanOrEqual(3);
  expect(sliding).toEqual([]);
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
  await expect(rows).toHaveCount(22);
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

test('the chips of citizens standing close together cluster instead of covering each other', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors);
  // a fresh run, held: Tak stands about by the camp 2 m from Ana mending the drying rack
  await page.evaluate(() => {
    const mock = (globalThis as unknown as MockLiveWindow).__pebbleMockLive;
    mock.restartRun();
    mock.setClock({ paused: true });
  });
  await expect(world).toHaveAttribute('data-live-connects', '2');
  await page.getByRole('button', { name: 'people', exact: true }).click();
  await page
    .locator('[data-person="tak"]')
    .getByRole('button', { name: 'go to' })
    .click();
  await landed(world);
  const tags = page.locator('[data-label^="npc-"]:visible');
  // both are drawn: each on a chip of their own or in one cluster chip
  await expect
    .poll(async () =>
      (
        await Promise.all(
          (await tags.all()).map((tag) => tag.getAttribute('data-members')),
        )
      )
        .flatMap((members) => members?.split(' ') ?? [])
        .filter((id) => id === 'ana' || id === 'tak')
        .sort(),
    )
    .toEqual(['ana', 'tak']);
  // the clock is held and the camera has landed: the labels stand still while they are read
  const boxes = await Promise.all(
    (await tags.all()).map(async (tag) => {
      const { x, y, width, height } = (await tag.boundingBox())!;
      const id = await tag.getAttribute('data-label');
      return { id, left: x, right: x + width, top: y, bottom: y + height };
    }),
  );
  const covered = boxes.flatMap((a, i) =>
    boxes
      .slice(i + 1)
      .filter(
        (b) =>
          a.left < b.right &&
          b.left < a.right &&
          a.top < b.bottom &&
          b.top < a.bottom,
      )
      .map((b) => `${a.id} / ${b.id}`),
  );
  expect(boxes.length).toBeGreaterThanOrEqual(1);
  expect(covered).toEqual([]);
  expect(errors).toEqual([]);
});

test('in the crowded band A camp of the first dawn no two drawn bodies come within 0.5 m over a minute', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors, '?mockLive=1', 10);
  // four talk and eat on one spot by the fire; Tak and Ana walk through them head-on, a tick (6 s) each way
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.crowdCamp(),
  );
  await expect(world).toHaveAttribute('data-live-connects', '2');
  const camp = ['oru', 'mena', 'lio', 'bo', 'tak', 'ana'];
  await expect
    .poll(async () => (await npcOf(page, 'tak')).activity)
    .toBe('walking');
  const samples = (await trackNpcs(page, 60_000)).map((all) =>
    all.filter((npc) => camp.includes(npc.id)),
  );
  const close = samples.flatMap((all, k) =>
    all.flatMap((a, i) =>
      all
        .slice(i + 1)
        .filter((b) => a.position.distanceTo(b.position) < 0.5)
        .map(
          (b) =>
            `${(k / 10).toFixed(1)} s: ${a.id}-${b.id} ${a.position.distanceTo(b.position).toFixed(2)} m`,
        ),
    ),
  );
  expect(close).toEqual([]);
  // the walkers did walk through the crowd: across the camp and past the fire, close by
  const of = (all: Npc[], id: string) => all.find((npc) => npc.id === id)!;
  for (const id of ['tak', 'ana']) {
    const passing = samples.map((all) =>
      of(all, id).position.distanceTo(of(all, 'oru').position),
    );
    expect(Math.max(...passing)).toBeGreaterThan(10);
    expect(Math.min(...passing)).toBeLessThan(1.5);
  }
  // the four on one spot stand round it: apart and close by
  const last = samples.at(-1)!;
  const four = ['oru', 'mena', 'lio', 'bo'].map((id) => of(last, id).position);
  for (const [i, a] of four.entries())
    for (const b of four.slice(i + 1)) {
      expect(a.distanceTo(b)).toBeGreaterThanOrEqual(0.6);
      expect(a.distanceTo(b)).toBeLessThan(2.5);
    }
  expect(errors).toEqual([]);
});

test('a walk that ends in a rest within the tick is drawn walking all the way there, then sits', async ({
  page,
}) => {
  const errors: string[] = [];
  await openLive(page, errors, '?mockLive=1', 1);
  // Sela gathers berries until tick 19; at tick 20 she walks the 33 m back to the fire pit and sits down to rest
  await page.evaluate(() => {
    const mock = (globalThis as unknown as MockLiveWindow).__pebbleMockLive;
    mock.skip(18);
    mock.setClock({ speed: 10 });
  });
  await page.waitForTimeout(1_000); // past the resync to tick 18
  const tag = page.locator('[data-label="npc-sela"]');
  const samples: (Npc & { tag: string })[] = [];
  for (let elapsed = 0; elapsed < 16_000; elapsed += 100) {
    samples.push({
      ...(await npcOf(page, 'sela')),
      tag: (await tag.textContent()) ?? '',
    });
    await page.waitForTimeout(100);
  }
  const moving = (k: number) =>
    k > 0 &&
    k < samples.length - 1 &&
    samples[k].position.distanceTo(samples[k - 1].position) > 0.05 &&
    samples[k + 1].position.distanceTo(samples[k].position) > 0.05;
  const onTheWay = samples.filter((_, k) => moving(k));
  expect(onTheWay.length).toBeGreaterThanOrEqual(10); // 33 m at ×10: over 2 s of walking
  expect(
    onTheWay.map(({ activity, posture }) => `${activity} ${posture}`),
  ).toEqual(onTheWay.map(() => 'walking standing'));
  // her label says what the drawn body does, not the rest the feed already reports (the hooks lag up to 100 ms
  // behind the body and the label, so a sample counts only if the next one moves on too)
  expect(
    samples
      .filter((_, k) => moving(k) && moving(k + 1))
      .map(({ tag }) => tag)
      .filter((tag) => !tag.startsWith('Sela · walking')),
  ).toEqual([]);
  const last = samples.at(-1)!;
  expect([last.activity, last.posture]).toEqual(['resting', 'sitting']);
  expect(last.tag).toMatch(/^Sela · resting/);
  expect(errors).toEqual([]);
});

test('clips play sped up with the clock like a film, up to ×10, and freeze when paused', async ({
  page,
}) => {
  const errors: string[] = [];
  await openLive(page, errors, '?mockLive=1', 1);
  await expect
    .poll(async () => (await npcs(page)).filter((npc) => npc.loaded).length, {
      timeout: 30_000,
    })
    .toBeGreaterThanOrEqual(6);
  const setClock = (change: { speed?: number; paused?: boolean }) =>
    page.evaluate(
      (clock) =>
        (globalThis as unknown as MockLiveWindow).__pebbleMockLive.setClock(
          clock,
        ),
      change,
    );
  /** Clip seconds played per real second (the median over the loaded citizens). */
  const lapse = async () => {
    const clocks = async () =>
      new Map(
        (await npcs(page))
          .filter((npc) => npc.loaded && npc.clip)
          .map((npc) => [npc.id, npc.clipClock]),
      );
    await page.waitForTimeout(300); // the new clock reaches the page
    const before = await clocks();
    const started = Date.now();
    await page.waitForTimeout(2_000);
    const after = await clocks();
    const seconds = (Date.now() - started) / 1000;
    const rates = [...after]
      .filter(([id]) => before.has(id))
      .map(([id, clock]) => (clock - before.get(id)!) / seconds)
      .sort((a, b) => a - b);
    return rates[Math.floor(rates.length / 2)];
  };
  expect(await lapse()).toBeCloseTo(1, 0);
  await setClock({ speed: 10 });
  expect(await lapse()).toBeGreaterThan(8);
  await setClock({ speed: 60 });
  const capped = await lapse();
  expect(capped).toBeGreaterThan(8);
  expect(capped).toBeLessThan(11);
  await setClock({ paused: true });
  expect(await lapse()).toBe(0);
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

  const badge = page.getByTestId('time-lapse-badge');
  await expect(page.getByTestId('live-speed')).toHaveText('×60');
  await expect(badge).toHaveText('time-lapse ×60');
  await page.getByRole('button', { name: '×600', exact: true }).click();
  await expect(page.getByTestId('live-speed')).toHaveText('×600');
  await expect(badge).toHaveText('time-lapse ×600');
  const fast = await tick();
  await page.waitForTimeout(1_000);
  expect((await tick()) - fast).toBeGreaterThan(5); // a tick every 0.1 s
  await page.getByRole('button', { name: 'pause', exact: true }).click();
  await expect(page.getByTestId('live-speed')).toHaveText('paused');
  await expect(badge).toHaveCount(0);
  await page.waitForTimeout(300);
  const paused = await tick();
  await page.waitForTimeout(1_500);
  expect(await tick()).toBe(paused);
  await expect(page.getByTestId('live-time')).toHaveText(/^day 0 · \d\d:\d\d$/);
  // real time: no tick for a real minute, and the sky's clock runs a game second per real second
  await page.getByRole('button', { name: '×1', exact: true }).click();
  await expect(page.getByTestId('live-speed')).toHaveText('real time');
  await expect(badge).toHaveCount(0);
  const minutes = async () =>
    Number(await world.getAttribute('data-game-minutes'));
  const before = await minutes();
  await page.waitForTimeout(3_000);
  expect(await tick()).toBe(paused);
  expect((await minutes()) - before).toBeGreaterThan(1.5 / 60);
  expect((await minutes()) - before).toBeLessThan(5 / 60);
  await page.getByRole('button', { name: '×60', exact: true }).click();

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

test('in real time a walker walks its streamed route at its own pace, facing the way it goes', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors);
  const tick = async () => Number(await world.getAttribute('data-live-tick'));
  // a fresh run at ×60 until the tick Kenji walks to the gate (82 m: there within the tick), then real time: a tick
  // a real minute, his walk drawn over it
  const kenji = await page.evaluate(async () => {
    const mock = (globalThis as unknown as MockLiveWindow).__pebbleMockLive;
    mock.restartRun();
    const find = () =>
      mock.entities().citizens.find((citizen) => citizen.id === 'kenji')!;
    while (find().route.length < 2)
      await new Promise((done) => setTimeout(done, 10));
    mock.setClock({ speed: 1 });
    return { tick: mock.entities().tick, ...find() };
  });
  await expect(page.getByTestId('live-speed')).toHaveText('real time');
  expect(kenji.route.length).toBeGreaterThan(1);
  expect(kenji.speed_mps).toBeCloseTo(5000 / 3600, 1);
  // let the drawn spot settle onto the new route, then watch 4 s of the tick
  await page.waitForTimeout(1_500);
  const route = kenji.route.map(({ unit }) => new Vector3(...unit));
  const samples: { at: number; npc: Npc }[] = [];
  for (let elapsed = 0; elapsed < 4_000; elapsed += 100) {
    samples.push({ at: Date.now(), npc: await npcOf(page, 'kenji') });
    await page.waitForTimeout(100);
  }
  expect(await tick()).toBe(kenji.tick);
  // on the route the engine streamed (in its keep-right lane), never off it
  for (const { npc } of samples)
    expect(offPath(npc.position, route)).toBeLessThan(LANE_M + 0.3);
  // at 5 km/h of real time: about 1.4 m/s, not 83 m/s
  const first = samples[0];
  const last = samples.at(-1)!;
  const metres = first.npc.position.distanceTo(last.npc.position);
  const seconds = (last.at - first.at) / 1000;
  expect(metres / seconds).toBeGreaterThan(kenji.speed_mps * 0.8);
  expect(metres / seconds).toBeLessThan(kenji.speed_mps * 1.2);
  // facing the way it walks, with the gait
  const going = last.npc.position.clone().sub(first.npc.position).normalize();
  expect(last.npc.facing.dot(going)).toBeGreaterThan(0.95);
  // the lord and his samurai walk formally
  expect(['Walk', 'Walk formal']).toContain(last.npc.clip);
  expect(errors).toEqual([]);
});

test('in orbit the camera rises to at least 150 m when the clock goes into time-lapse', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openLive(page, errors, '?mockLive=1', 1);
  const altitude = async () =>
    Number(await world.getAttribute('data-camera-distance')) - R;
  await page.keyboard.press('KeyC');
  await expect(world).toHaveAttribute('data-camera-mode', 'orbit');
  await expect.poll(altitude, { timeout: 10_000 }).toBeGreaterThan(2500);
  // turn away from the player (zooming in onto it hands over to follow), then all the way down
  await page.mouse.move(640, 400);
  await page.mouse.down();
  await page.mouse.move(640, 150, { steps: 10 });
  await page.mouse.up();
  for (let k = 0; k < 15; k++) await page.mouse.wheel(0, -400);
  await expect.poll(altitude, { timeout: 10_000 }).toBeLessThan(125);
  await page.getByRole('button', { name: '×10', exact: true }).click();
  await page.waitForTimeout(1_000);
  expect(await altitude()).toBeLessThan(125); // ×10 is no time-lapse
  await page.getByRole('button', { name: '×60', exact: true }).click();
  await expect.poll(altitude).toBeGreaterThan(149);
  await expect(world).toHaveAttribute('data-camera-mode', 'orbit');
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

test('the real feed: the 22 citizens stand where the engine says, on the ground, and follow its ticks', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    '22',
    { timeout: 30_000 },
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  const tick = async () => Number(await world.getAttribute('data-live-tick'));
  const startTick = await tick();
  // the engine's clock: at ×1 (real time) a tick comes once a real minute
  const clock = (await (await page.request.get(`${API_URL}/clock`)).json()) as {
    speed: number;
    paused: boolean;
  };
  test.skip(clock.paused, 'the engine is paused');
  const nextTick = tickMs(clock.speed) + 5_000;

  // the feed is live: someone drawn walks on or starts doing something else, or at least a tick comes (at night
  // everyone may be asleep)
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
        }).length + ((await tick()) > startTick ? 1 : 0),
      { timeout: nextTick },
    )
    .toBeGreaterThan(0);

  // the engine's citizens, each drawn on the ground on what it walked in the page's tick (one tick behind) or the
  // tick before (a page opened mid-tick finishes that walk first), never on the plan ahead: a frame that comes a
  // little late (LATE_S) lets a mover walk on into it
  const api = await page.request.get(ENTITIES_URL);
  expect(api.status()).toBe(200);
  const entities = (await api.json()) as EntitiesView;
  expect(entities.citizens).toHaveLength(22);
  expect(new Set(entities.citizens.map((citizen) => citizen.region))).toEqual(
    new Set(['town', 'band_a', 'band_b']),
  );
  const at = async (when: number) =>
    (
      (await (
        await page.request.get(`${ENTITIES_URL}?at=${when}`)
      ).json()) as EntitiesView
    ).citizens;
  const lateM = 0.5 + FLEE_MPS * clock.speed * LATE_S;
  await expect
    .poll(
      async () => {
        const when = await tick();
        const [now, previous] = await Promise.all([at(when), at(when - 1)]);
        await page.waitForTimeout(150); // the hooks refresh every 100 ms
        const shown = await npcs(page);
        if ((await tick()) !== when) return ['the page moved on'];
        return now.flatMap((citizen) => {
          const npc = shown.find((candidate) => candidate.id === citizen.id);
          if (!npc) return [`${citizen.id}: not drawn`];
          const before = previous.find((old) => old.id === citizen.id)!;
          const off = offWalked(npc.position, [citizen, before]);
          const direction = npc.position.clone().normalize();
          const above = npc.position.length() - (R + groundUnder(direction));
          return [
            ...(off < lateM + parted(npc, shown)
              ? []
              : [`${citizen.id}: ${off.toFixed(2)} m off its walk`]),
            ...(Math.abs(above) < 0.5
              ? []
              : [`${citizen.id}: ${above.toFixed(2)} m off the ground`]),
          ];
        });
      },
      { timeout: 15_000 },
    )
    .toEqual([]);

  // the engine ticks on and the drawn citizens follow it: at the page's tick, everyone who stood still since the
  // tick before is exactly where the engine has them (unless walkers drawn by push them aside), and everyone does
  // what the engine says
  await expect.poll(tick, { timeout: nextTick }).toBeGreaterThan(startTick);
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
          // (one still walking to where the engine has them shows the moving activity it had until it gets there)
          const onTheWay =
            !still && MOVING.includes(npc.activity) && off > 0.01;
          // (one who stood still is exactly there, a mover on what it walked)
          const drift = still
            ? off
            : offWalked(npc.position, [citizen, before]);
          return [
            ...(npc.activity === citizen.activity || onTheWay
              ? []
              : [`${citizen.id}: ${npc.activity} ≠ ${citizen.activity}`]),
            ...(drift < (still ? 0.5 : lateM) + parted(npc, shown)
              ? []
              : [`${citizen.id}: ${drift.toFixed(2)} m off`]),
          ];
        });
      },
      { timeout: 15_000 },
    )
    .toEqual([]);

  // between ticks the walkers walk what the engine streamed they walked: they never cut off it (through a wall). A
  // page opened mid-tick draws its walkers that much later, finishing the tick before's walk first. Only checked with
  // ticks far apart (×1 real time, up to ×6): at ×60 a tick lasts a second and the drawn spot is still easing onto
  // the new route
  if (tickMs(clock.speed) >= 10_000)
    await expect
      .poll(
        async () => {
          const when = await tick();
          const [now, previous] = await Promise.all([at(when), at(when - 1)]);
          const walkers = now.filter((citizen) => citizen.route.length > 1);
          await page.waitForTimeout(1_000); // the drawn spot settles onto the tick's route
          const off: string[] = [];
          for (let k = 0; k < 10; k++) {
            const shown = await npcs(page);
            for (const citizen of walkers) {
              const npc = shown.find(
                (candidate) => candidate.id === citizen.id,
              )!;
              const metres = offWalked(npc.position, [
                citizen,
                previous.find((old) => old.id === citizen.id)!,
              ]);
              if (metres > 0.5 + parted(npc, shown))
                off.push(`${citizen.id}: ${metres.toFixed(2)} m`);
            }
            await page.waitForTimeout(100);
          }
          return (await tick()) === when ? off : ['the page moved on'];
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
            !motionClips(npc.motion, npc.posture).some(
              (clip) => clip === npc.clip,
            ),
        )
        .map((npc) => `${npc.id} ${npc.activity} ${npc.motion}: ${npc.clip}`),
    )
    .toEqual([]);

  await page.getByRole('button', { name: 'people', exact: true }).click();
  await expect(page.locator('[data-person]')).toHaveCount(22);
  await expect(page.getByRole('region', { name: 'People' })).toContainText(
    entities.citizens[0].name,
  );
  expect(errors).toEqual([]);
});

test('a page opened mid-tick at ×60 draws each walker as far along its path as the tick has gone', async ({
  page,
}) => {
  // the mock starts at tick 1 (two citizens on their way), held 15 game seconds into it at ×60
  const elapsed = 15;
  await page.addInitScript(
    (start) => {
      (globalThis as MockStartHook).__pebbleMockStart = start;
    },
    { ticks: 1, speed: 60, elapsed },
  );
  const errors: string[] = [];
  const world = await openGlobe(page, errors, '?mockLive=1');
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    '22',
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  const view = await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.entities(),
  );
  expect(view.tick_elapsed_s).toBe(elapsed);
  const shown = new Map(
    (await npcs(page)).map((npc) => [npc.id, npc.position.normalize()]),
  );
  const walkers = view.citizens.filter((citizen) => citizen.route.length > 1);
  expect(walkers.length).toBeGreaterThan(0);
  let farthest = 0;
  for (const walker of walkers) {
    const path = citizenPath(walker, R);
    const start = pointAt(path, new Vector3());
    path.time = Math.min(path.times[0] + elapsed, path.arrive);
    const along = pointAt(path, new Vector3());
    const gone = start.angleTo(along) * R;
    farthest = Math.max(farthest, gone);
    expect(gone).toBeGreaterThan(1); // twice the tolerance below, so being drawn at the start fails
    expect(shown.get(walker.id)!.angleTo(along) * R).toBeLessThan(0.5);
  }
  expect(farthest).toBeGreaterThan(5); // the check means something
  expect(errors).toEqual([]);
});
