import { expect, type Locator, type Page, test } from '@playwright/test';

/*
 * The flat town at /town (backend /api/v1/town): spawn (0, 120) facing north on the approach road; the plaster town wall
 * runs along z = 100 with the main gatehouse at x = 0; the main street leads north to the moat (z 31..37), crossed
 * by the bridge at x = 0, then the castle gatehouse at z = 28 opens into the courtyard.
 */

interface Position {
  x: number;
  y: number;
  z: number;
}

const TOWN_LOOKS = [
  'town-lord',
  'town-samurai',
  'town-merchant',
  'town-farmer',
  'town-weaver',
  'town-child',
];
/*
 * 157 calls at spawn: one per sub-mesh of each of the 39 kinds plus their shadow pass, the ground, the citizens
 * and the player. One mesh per placement (no instancing) measured 766 there even with frustum culling.
 */
const DRAW_CALL_BUDGET = 500;
/** Half the open passage between the gatehouse's pillars (the door leaves swing back against them). */
const GATE_HALF_WIDTH = 1;
/** South face of the 0.7 m town wall at z = 100, plus the player's 0.3 m radius, minus a little tolerance. */
const WALL_SOUTH_LIMIT = 100.6;

async function openWorld(page: Page, errors: string[]) {
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.goto('/town');
  const world = page.getByTestId('world');
  await expect(world).toHaveAttribute('data-world-ready', 'true', {
    timeout: 60_000,
  });
  return world;
}

async function position(world: Locator): Promise<Position> {
  const [x, y, z] = await Promise.all(
    ['x', 'y', 'z'].map((axis) => world.getAttribute(`data-player-${axis}`)),
  );
  return { x: Number(x), y: Number(y), z: Number(z) };
}

/** Polls the player position until `done` holds, keeping every sample. */
async function track(
  world: Locator,
  done: (position: Position) => boolean,
  timeout = 45_000,
) {
  const samples: Position[] = [];
  await expect
    .poll(
      async () => {
        const sample = await position(world);
        samples.push(sample);
        return done(sample);
      },
      { timeout, intervals: [100] },
    )
    .toBe(true);
  return samples;
}

/** Samples the player position every 100 ms for `duration` ms. */
async function sampleFor(world: Locator, page: Page, duration: number) {
  const samples: Position[] = [];
  for (let elapsed = 0; elapsed < duration; elapsed += 100) {
    samples.push(await position(world));
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

test('the town loads with its townspeople, labels and instanced placements', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openWorld(page, errors);

  await expect(world).toHaveAttribute('data-citizens-ready', '6', {
    timeout: 30_000,
  });
  for (const look of TOWN_LOOKS)
    await expect(page.locator(`[data-label="${look}"]`)).toHaveCount(1);
  await expect(page.locator('[data-label="town-lord"]')).toHaveText(
    'Lord of the castle',
  );
  expect(await position(world)).toEqual({ x: 0, y: 0, z: 120 });

  await expect(world).toHaveAttribute('data-draw-calls', /\d+/, {
    timeout: 30_000,
  });
  const drawCalls = Number(await world.getAttribute('data-draw-calls'));
  expect(drawCalls).toBeGreaterThan(0);
  expect(drawCalls).toBeLessThan(DRAW_CALL_BUDGET);
  expect(errors).toEqual([]);
});

test('walks from spawn through the main gate, up the street and over the bridge into the castle', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openWorld(page, errors);

  let samples: Position[] = [];
  await hold(page, ['Shift', 'KeyW'], async () => {
    samples = await track(world, ({ z }) => z < 24);
  });

  const inGate = samples.filter(({ z }) => z > 97 && z < 103);
  expect(inGate.length).toBeGreaterThan(0);
  for (const { x } of inGate) expect(Math.abs(x)).toBeLessThan(GATE_HALF_WIDTH);
  // the bridge deck is the only ground over the moat
  const overMoat = samples.filter(({ z }) => z > 31 && z < 37);
  expect(overMoat.length).toBeGreaterThan(0);
  for (const { x } of overMoat) expect(Math.abs(x)).toBeLessThan(1);
  expect(errors).toEqual([]);
});

test('the town wall stops a walk straight at it away from the gates', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openWorld(page, errors);

  // east along the outside of the wall, then north into it
  await hold(page, ['Shift', 'KeyD'], () => track(world, ({ x }) => x > 30));
  const start = await position(world);
  let samples: Position[] = [];
  await hold(page, ['Shift', 'KeyW'], async () => {
    samples = await track(world, ({ z }) => z < 102);
    samples.push(...(await sampleFor(world, page, 3_000)));
  });

  const end = samples[samples.length - 1];
  for (const { z } of samples) expect(z).toBeGreaterThan(WALL_SOUTH_LIMIT);
  expect(Math.abs(end.x - start.x)).toBeLessThan(1);
  expect(errors).toEqual([]);
});
