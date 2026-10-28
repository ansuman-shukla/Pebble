import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { Site, WorldView } from '../../src/lib/client/types.gen';
import {
  anchorMapping,
  buildTerrain,
  cellDirection,
  decodeWorld,
  type GlobeTerrain,
  type SiteMapping,
} from '../../src/lib/world/globe';
import {
  atParam,
  coast,
  directionOf,
  DRAW_CALL_BUDGET,
  hold,
  openGlobe,
  radiusOf,
  sample,
  type Sample,
  sampleFor,
  TOWN_CLEARING,
  track,
  WORLD_URL,
} from './globe-helpers';

/*
 * The real planet at / (GET /api/v1/world from the backend, no mock): the player spawns at the town's gate
 * approach, walks out of the main gate onto the terrain, is stopped by the sea, crosses the ice gate, and the
 * readout names the camps and landmarks. Points are picked from the same world the page loads.
 */

/** The town's ground disc (local metres); beyond it the player stands on the terrain. */
const TOWN_GROUND_RADIUS = 225;
/** Main gate of the town wall (local z), the passage is x ∈ [-1.3, 1.3]. */
const MAIN_GATE_Z = 100;
/** The densest forest view keeps roughly to this many triangles (shadow pass included). */
const FOREST_TRIANGLE_BUDGET = 4_000_000;

let view: WorldView;
let terrain: GlobeTerrain;
let R: number;
let town: Site;
let townMapping: SiteMapping;
let townDirection: Vector3;

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const response = await api.get(WORLD_URL);
  expect(response.ok()).toBe(true);
  view = (await response.json()) as WorldView;
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
  R = view.radius_m;
  town = view.sites.find((site) => site.kind === 'town')!;
  townMapping = anchorMapping(town.anchor, R);
  townDirection = new Vector3(...town.anchor.position);
});

const site = (id: string) =>
  view.sites.find((candidate) => candidate.id === id)!;
const anchorAt = (id: string) =>
  atParam(new Vector3(...site(id).anchor.position), new Vector3(0, 1, 0));
const biomeName = (direction: Vector3) =>
  view.biome_names[terrain.biomeAt(direction)];

/** `?at=` for a point in the town's local metres, facing along (dx, dz). */
function townAt(x: number, z: number, dx: number, dz: number) {
  const from = townMapping.toWorld(x, 0, z, new Vector3());
  const to = townMapping.toWorld(x + dx, 0, z + dz, new Vector3());
  return atParam(from.clone().normalize(), to.sub(from));
}

/** A broadleaf cell far from every site with the most broadleaf within 250 m. */
function densestForest() {
  const forest = view.biome_names.indexOf('broadleaf_forest');
  const { positions, biomes, cellCount } = terrain.globe;
  const sites = view.sites.map((s) => new Vector3(...s.anchor.position));
  const within = Math.cos(250 / R);
  const at = new Vector3();
  let best = { cell: -1, share: 0 };
  for (let cell = 0; cell < cellCount; cell += 3) {
    if (biomes[cell] !== forest) continue;
    at.fromArray(positions, cell * 3);
    if (sites.some((s) => s.angleTo(at) * R < 500)) continue;
    let total = 0;
    let trees = 0;
    for (let other = 0; other < cellCount; other++) {
      const k = other * 3;
      const dot =
        positions[k] * at.x + positions[k + 1] * at.y + positions[k + 2] * at.z;
      if (dot < within) continue;
      total += 1;
      if (biomes[other] === forest) trees += 1;
    }
    if (trees / total > best.share) best = { cell, share: trees / total };
  }
  return new Vector3().fromArray(positions, best.cell * 3);
}

const onTerrain = (current: Sample) => {
  expect(Math.abs(radiusOf(current) - (R + current.ground))).toBeLessThan(0.5);
  expect(
    Math.abs(current.ground - terrain.heightAt(directionOf(current))),
  ).toBeLessThan(0.5);
};

test('the real planet loads, the player spawns at the town gate and orbit shows the whole planet', async ({
  page,
}) => {
  const errors: string[] = [];
  const loaded = page.waitForResponse((response) =>
    response.url().endsWith('/api/v1/world'),
  );
  const world = await openGlobe(page, errors);
  const response = await loaded;
  expect(response.status()).toBe(200);
  expect(((await response.json()) as WorldView).seed).toBe(view.seed);

  await expect(world).toHaveAttribute('data-camera-mode', 'follow');
  const start = await sample(world);
  expect(start.site).toBe('town');
  expect(start.townX).toBeCloseTo(0, 1);
  expect(start.townZ).toBeCloseTo(120, 1);
  expect(start.ground).toBeCloseTo(town.anchor.height_m, 1);
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

  await page.keyboard.press('KeyC');
  await expect(world).toHaveAttribute('data-camera-mode', 'orbit');
  await expect
    .poll(
      async () => Number(await world.getAttribute('data-camera-distance')),
      {
        timeout: 10_000,
      },
    )
    .toBeGreaterThan(R + 2500);
  await expect(world).toHaveAttribute('data-draw-calls-mode', 'orbit', {
    timeout: 10_000,
  });
  expect(Number(await world.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );
  expect(errors).toEqual([]);
});

test('walking out of the main gate leads south onto the terrain', async ({
  page,
}) => {
  const errors: string[] = [];
  // inside the town wall, on the main street, facing the main gate (south)
  const world = await openGlobe(page, errors, `?at=${townAt(0, 90, 0, 1)}`);
  const start = await sample(world);
  expect(start.townZ).toBeCloseTo(90, 0);

  await page.keyboard.press('KeyT');
  await expect(world).toHaveAttribute('data-travel', 'true');
  const fromTown = (current: Sample) =>
    directionOf(current).angleTo(townDirection) * R;
  let samples: Sample[] = [];
  await hold(page, ['KeyW'], async () => {
    samples = await track(
      world,
      (current) => fromTown(current) > TOWN_GROUND_RADIUS + 30,
      30_000,
    );
  });
  await page.keyboard.press('KeyT');
  await page.waitForTimeout(600);

  // straight through the gate passage: the wall would have stopped it anywhere else
  const inTown = samples.filter((current) => current.townZ !== null);
  expect(inTown.some((current) => current.townZ! < MAIN_GATE_Z)).toBe(true);
  expect(inTown.some((current) => current.townZ! > MAIN_GATE_Z + 5)).toBe(true);
  for (const current of inTown.filter((c) => c.townZ! < MAIN_GATE_Z + 10))
    expect(Math.abs(current.townX!)).toBeLessThan(1.3);
  const end = await sample(world);
  expect(fromTown(end)).toBeGreaterThan(TOWN_GROUND_RADIUS + 30);
  onTerrain(end);
  expect(errors).toEqual([]);
});

test('the sea stops a walk at the shore near the town', async ({ page }) => {
  const errors: string[] = [];
  const shore = coast(terrain, townDirection, TOWN_CLEARING);
  const world = await openGlobe(page, errors, `?at=${shore.at}`);
  const start = await sample(world);
  const toWater = (current: Sample) =>
    directionOf(current).angleTo(shore.water) * R;

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
  const end = samples[samples.length - 1];
  expect(toWater(end)).toBeLessThan(toWater(start));
  // 4 s of travel would cover 100 m: the shore held it back
  const last = samples.slice(-10);
  expect(
    directionOf(last[0]).angleTo(directionOf(last[last.length - 1])) * R,
  ).toBeLessThan(25);
  expect(errors).toEqual([]);
});

test('the readout names the band A camp and the smoking mountain', async ({
  page,
}) => {
  for (const [id, biome] of [
    ['band_a_camp', null],
    ['smoking_mountain', 'volcanic'],
  ] as const) {
    const errors: string[] = [];
    const world = await openGlobe(page, errors, `?at=${anchorAt(id)}`);
    const here = await sample(world);
    expect(here.site).toBe(id);
    expect(here.biome).toBe(
      biome ?? biomeName(new Vector3(...site(id).anchor.position)),
    );
    expect(here.ground).toBeCloseTo(site(id).anchor.height_m, 0);
    expect(errors).toEqual([]);
  }
});

test('the ice gate carries the land loop across the sounds', async ({
  page,
}) => {
  const errors: string[] = [];
  const gate = site('ice_gate');
  const loop = view.land_loop;
  const index = loop.indexOf(gate.cell);
  expect(index).toBeGreaterThanOrEqual(0);
  const { globe } = terrain;
  const here = cellDirection(globe, gate.cell, new Vector3());
  const ahead = cellDirection(
    globe,
    loop[(index + 2) % loop.length],
    new Vector3(),
  );
  const world = await openGlobe(
    page,
    errors,
    `?at=${atParam(here, ahead.clone().sub(here))}`,
  );
  const start = await sample(world);
  expect(start.biome).toBe('ice');

  await page.keyboard.press('KeyT');
  let samples: Sample[] = [];
  await hold(page, ['KeyW'], async () => {
    samples = await sampleFor(world, page, 2_500);
  });
  for (const current of samples) expect(current.biome).not.toMatch(/ocean/);
  const end = samples[samples.length - 1];
  expect(directionOf(start).angleTo(directionOf(end)) * R).toBeGreaterThan(40);
  expect(errors).toEqual([]);
});

test('the densest forest stays under the draw call and triangle budgets', async ({
  page,
}) => {
  const errors: string[] = [];
  const forest = densestForest();
  const world = await openGlobe(
    page,
    errors,
    `?at=${atParam(forest, new Vector3(0, 1, 0))}`,
  );
  expect((await sample(world)).biome).toBe('broadleaf_forest');
  await expect(world).toHaveAttribute('data-draw-calls-mode', 'follow', {
    timeout: 30_000,
  });
  // let the scatter settle and the stats resample
  await page.waitForTimeout(2_500);
  const drawCalls = Number(await world.getAttribute('data-draw-calls'));
  const triangles = Number(await world.getAttribute('data-triangles'));
  expect(drawCalls).toBeLessThan(DRAW_CALL_BUDGET);
  console.log(
    'FOREST',
    atParam(forest, new Vector3(0, 1, 0)),
    drawCalls,
    triangles,
  );
  // the trees are there...
  expect(triangles).toBeGreaterThan(500_000);
  // ...in reach tiers that keep the forest affordable
  expect(triangles).toBeLessThan(FOREST_TRIANGLE_BUDGET);
  expect(errors).toEqual([]);
});
