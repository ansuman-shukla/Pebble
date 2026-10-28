import { expect, type Locator, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  buildTerrain,
  cellDirection,
  decodeWorld,
  latLonFromDirection,
  tangentFrame,
  WATER_BIOMES,
} from '../../src/lib/world/globe';
import { createMockWorld } from '../../src/lib/world/mock-world';

/*
 * The globe at /?mock=1 (the dev/test mock world, the town from /api/v1/town): the player spawns at the town's
 * spawn (local 0, 120) facing the main gate, on the town's plateau. Positions are world metres (planet centre at
 * the origin); data-town-x/z are the town's local metres while the player is inside the town.
 */

interface Sample {
  x: number;
  y: number;
  z: number;
  ground: number;
  biome: string;
  townX: number | null;
  townZ: number | null;
}

const view = createMockWorld();
const globe = decodeWorld(view);
const R = globe.radius;
const DRAW_CALL_BUDGET = 300;
/** South face of the 0.7 m town wall at z = 100, plus the player's 0.3 m radius, minus a little tolerance. */
const WALL_SOUTH_LIMIT = 100.6;

/** A land cell near the town with ocean next to it, and the bearing from it towards the water. */
function coast() {
  const terrain = buildTerrain(globe);
  const town = new Vector3(...view.sites[0].anchor.position);
  const land = new Vector3();
  const water = new Vector3();
  for (let cell = 0; cell < globe.cellCount; cell++) {
    if (WATER_BIOMES.has(globe.biomes[cell]) || globe.heights[cell] < 2)
      continue;
    cellDirection(globe, cell, land);
    if (land.angleTo(town) * R > 1500) continue;
    const wet = [...terrain.neighbours(cell)].filter(
      (near) => globe.biomes[near] <= 1,
    );
    if (wet.length < 2) continue;
    cellDirection(globe, wet[0], water);
    const { east, north } = tangentFrame(land);
    const toWater = water.clone().sub(land);
    const bearing =
      (Math.atan2(toWater.dot(east), toWater.dot(north)) * 180) / Math.PI;
    const { lat, lon } = latLonFromDirection(land);
    return { at: `${lat},${lon},${bearing}`, water: water.clone() };
  }
  throw new Error('no coast near the town');
}

async function openGlobe(page: Page, errors: string[], query = '') {
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.goto(`/?mock=1${query}`);
  const world = page.getByTestId('world');
  await expect(world).toHaveAttribute('data-world-ready', 'true', {
    timeout: 60_000,
  });
  await expect(world).toHaveAttribute('data-player-x', /\d/);
  return world;
}

async function sample(world: Locator): Promise<Sample> {
  const read = (name: string) => world.getAttribute(`data-${name}`);
  const [x, y, z, ground, biome, townX, townZ] = await Promise.all(
    [
      'player-x',
      'player-y',
      'player-z',
      'player-ground',
      'player-biome',
      'town-x',
      'town-z',
    ].map(read),
  );
  const maybe = (value: string | null) =>
    value === null ? null : Number(value);
  return {
    x: Number(x),
    y: Number(y),
    z: Number(z),
    ground: Number(ground),
    biome: biome ?? '',
    townX: maybe(townX),
    townZ: maybe(townZ),
  };
}

const radiusOf = ({ x, y, z }: Sample) => Math.hypot(x, y, z);

/** Polls samples until `done` holds, keeping every sample. */
async function track(
  world: Locator,
  done: (sample: Sample) => boolean,
  timeout = 45_000,
) {
  const samples: Sample[] = [];
  await expect
    .poll(
      async () => {
        const current = await sample(world);
        samples.push(current);
        return done(current);
      },
      { timeout, intervals: [100] },
    )
    .toBe(true);
  return samples;
}

async function sampleFor(world: Locator, page: Page, duration: number) {
  const samples: Sample[] = [];
  for (let elapsed = 0; elapsed < duration; elapsed += 100) {
    samples.push(await sample(world));
    await page.waitForTimeout(100);
  }
  return samples;
}

async function hold(page: Page, keys: string[], run: () => Promise<unknown>) {
  for (const key of keys) await page.keyboard.down(key);
  await run();
  for (const key of keys) await page.keyboard.up(key);
}

test.describe.configure({ timeout: 120_000 });

test('the globe starts at the town spawn in the follow view, under the draw call budget', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors);

  await expect(world).toHaveAttribute('data-camera-mode', 'follow');
  const start = await sample(world);
  expect(start.townX).toBeCloseTo(0, 1);
  expect(start.townZ).toBeCloseTo(120, 1);
  expect(start.ground).toBeCloseTo(view.sites[0].anchor.height_m, 1);
  expect(Math.abs(radiusOf(start) - (R + start.ground))).toBeLessThan(0.05);
  await expect(world).toHaveAttribute('data-citizens-ready', '6', {
    timeout: 30_000,
  });
  await expect(world).toHaveAttribute('data-draw-calls-mode', 'follow', {
    timeout: 30_000,
  });
  const drawCalls = Number(await world.getAttribute('data-draw-calls'));
  expect(drawCalls).toBeGreaterThan(0);
  expect(drawCalls).toBeLessThan(DRAW_CALL_BUDGET);
  expect(errors).toEqual([]);
});

test('walking out in the wild keeps the player on the terrain', async ({
  page,
}) => {
  const errors: string[] = [];
  // a broadleaf forest west of the town, walking east
  const world = await openGlobe(page, errors, '&at=31.717,0,90');
  const start = await sample(world);
  expect(start.biome).toBe('broadleaf_forest');

  let samples: Sample[] = [];
  await hold(page, ['Shift', 'KeyW'], async () => {
    samples = await sampleFor(world, page, 3_000);
  });

  const end = samples[samples.length - 1];
  const walked = Math.hypot(end.x - start.x, end.y - start.y, end.z - start.z);
  expect(walked).toBeGreaterThan(5);
  for (const current of samples)
    expect(Math.abs(radiusOf(current) - (R + current.ground))).toBeLessThan(
      0.5,
    );
  expect(new Set(samples.map(({ ground }) => ground)).size).toBeGreaterThan(1);
  expect(errors).toEqual([]);
});

test('the ocean stops a walk at the shore', async ({ page }) => {
  const errors: string[] = [];
  const shore = coast();
  const world = await openGlobe(page, errors, `&at=${shore.at}`);
  const start = await sample(world);
  const distanceToWater = (current: Sample) =>
    new Vector3(current.x, current.y, current.z)
      .normalize()
      .angleTo(shore.water) * R;

  await page.keyboard.press('KeyT');
  await expect(world).toHaveAttribute('data-travel', 'true');
  let samples: Sample[] = [];
  await hold(page, ['KeyW'], async () => {
    samples = await sampleFor(world, page, 4_000);
  });

  for (const current of samples) {
    expect(current.biome).not.toMatch(/ocean|lake/);
    expect(current.ground).toBeGreaterThan(0.19);
  }
  // it walked up to the water and no further
  const end = samples[samples.length - 1];
  expect(distanceToWater(end)).toBeLessThan(distanceToWater(start) - 10);
  const last = samples.slice(-10);
  const drift = Math.hypot(
    last[last.length - 1].x - last[0].x,
    last[last.length - 1].y - last[0].y,
    last[last.length - 1].z - last[0].z,
  );
  expect(drift).toBeLessThan(25);
  expect(errors).toEqual([]);
});

test('the town wall still stops a walk straight at it away from the gates', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors);

  // east along the outside of the wall, then north into it
  await hold(page, ['Shift', 'KeyD'], () =>
    track(world, ({ townX }) => (townX ?? 0) > 30),
  );
  const start = await sample(world);
  let samples: Sample[] = [];
  await hold(page, ['Shift', 'KeyW'], async () => {
    samples = await track(world, ({ townZ }) => (townZ ?? 200) < 102);
    samples.push(...(await sampleFor(world, page, 3_000)));
  });

  const end = samples[samples.length - 1];
  for (const { townZ } of samples)
    expect(townZ).toBeGreaterThan(WALL_SOUTH_LIMIT);
  expect(Math.abs(end.townX! - start.townX!)).toBeLessThan(1);
  expect(errors).toEqual([]);
});

test('orbit shows the whole planet and zooming onto the player hands back to follow', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors);
  const distance = async () =>
    Number(await world.getAttribute('data-camera-distance'));

  await page.keyboard.press('KeyC');
  await expect(world).toHaveAttribute('data-camera-mode', 'orbit');
  await expect.poll(distance, { timeout: 10_000 }).toBeGreaterThan(2500 + R);
  // the player stays put while the camera orbits
  const before = await sample(world);
  await hold(page, ['KeyW'], () => page.waitForTimeout(700));
  expect(await sample(world)).toEqual(before);

  await page.mouse.move(640, 400);
  await expect
    .poll(
      async () => {
        await page.mouse.wheel(0, -400);
        return world.getAttribute('data-camera-mode');
      },
      { timeout: 20_000, intervals: [200] },
    )
    .toBe('follow');
  await expect.poll(distance).toBeLessThan(R + 100);
  expect(errors).toEqual([]);
});

test('the time toggle runs the clock sixty times faster', async ({ page }) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors);
  const minutes = async () =>
    Number(await world.getAttribute('data-game-minutes'));

  const start = await minutes();
  await page.waitForTimeout(2_000);
  const normal = (await minutes()) - start;
  expect(normal).toBeGreaterThanOrEqual(1);
  expect(normal).toBeLessThanOrEqual(4);

  await page.getByRole('button', { name: 'time ×60' }).click();
  const fastStart = await minutes();
  await page.waitForTimeout(2_000);
  expect((await minutes()) - fastStart).toBeGreaterThan(90);
  expect(errors).toEqual([]);
});
