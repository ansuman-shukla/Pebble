import { expect, type Locator, type Page } from '@playwright/test';
import { Vector3 } from 'three';

import {
  cellDirection,
  type GlobeTerrain,
  latLonFromDirection,
  tangentFrame,
  WATER_BIOMES,
} from '../../src/lib/world/globe';

/*
 * Shared by the globe browser tests: open the page, read the player off the world element's data attributes,
 * hold keys. Positions are world metres (planet centre at the origin); data-town-x/z are the town's local metres
 * while the player is inside the town.
 */

export interface Sample {
  x: number;
  y: number;
  z: number;
  ground: number;
  biome: string;
  site: string | null;
  townX: number | null;
  townZ: number | null;
}

/** The backend the tests read the world from directly (PLAYWRIGHT_API_URL points them at a worktree's own). */
export const WORLD_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1/world`;

export const DRAW_CALL_BUDGET = 300;
/** The town's plateau and its blend (metres from the anchor): beyond it is the wild. */
export const TOWN_CLEARING = 300;

/** West of the town, just outside its walls and ground disc: open grassland at street level, facing the town. */
export const OUTSIDE_THE_WALLS = '?at=37.49,3.22,85&time=12:00';
/** The South marsh, just south of the town: mud and puddles at street level, facing the town. */
export const SOUTH_MARSH = '?at=31.2,12,0&time=12:00';

/** Opens the globe at `/<query>` and waits until the world is ready and the player is placed. */
export async function openGlobe(page: Page, errors: string[], query = '') {
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.goto(`/${query}`);
  const world = page.getByTestId('world');
  await expect(world).toHaveAttribute('data-world-ready', 'true', {
    timeout: 60_000,
  });
  await expect(world).toHaveAttribute('data-player-x', /\d/);
  return world;
}

export async function sample(world: Locator): Promise<Sample> {
  const read = (name: string) => world.getAttribute(`data-${name}`);
  const [x, y, z, ground, biome, site, townX, townZ] = await Promise.all(
    [
      'player-x',
      'player-y',
      'player-z',
      'player-ground',
      'player-biome',
      'player-site',
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
    site,
    townX: maybe(townX),
    townZ: maybe(townZ),
  };
}

export const radiusOf = ({ x, y, z }: Sample) => Math.hypot(x, y, z);

export const directionOf = ({ x, y, z }: Sample) =>
  new Vector3(x, y, z).normalize();

/** Polls samples until `done` holds, keeping every sample. */
export async function track(
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

export async function sampleFor(world: Locator, page: Page, duration: number) {
  const samples: Sample[] = [];
  for (let elapsed = 0; elapsed < duration; elapsed += 100) {
    samples.push(await sample(world));
    await page.waitForTimeout(100);
  }
  return samples;
}

export async function hold(
  page: Page,
  keys: string[],
  run: () => Promise<unknown>,
) {
  for (const key of keys) await page.keyboard.down(key);
  await run();
  for (const key of keys) await page.keyboard.up(key);
}

/** `lat,lon,bearing` for `?at=` from a direction and the tangent it should face. */
export function atParam(direction: Vector3, facing: Vector3) {
  const { east, north } = tangentFrame(direction);
  const bearing =
    (Math.atan2(facing.dot(east), facing.dot(north)) * 180) / Math.PI;
  const { lat, lon } = latLonFromDirection(direction);
  return `${lat},${lon},${bearing}`;
}

/**
 * The land cell nearest to `near` but at least `beyond` metres away (outside the town) with ocean next to it,
 * and the bearing from it towards the water.
 */
export function coast(terrain: GlobeTerrain, near: Vector3, beyond: number) {
  const { globe } = terrain;
  const land = new Vector3();
  let best: { distance: number; land: Vector3; water: Vector3 } | null = null;
  for (let cell = 0; cell < globe.cellCount; cell++) {
    if (WATER_BIOMES.has(globe.biomes[cell]) || globe.heights[cell] < 2)
      continue;
    const distance =
      cellDirection(globe, cell, land).angleTo(near) * globe.radius;
    if (distance < beyond || (best && distance >= best.distance)) continue;
    const wet = [...terrain.neighbours(cell)].filter(
      (other) => globe.biomes[other] <= 1,
    );
    if (wet.length < 2) continue;
    best = {
      distance,
      land: land.clone(),
      water: cellDirection(globe, wet[0], new Vector3()),
    };
  }
  if (!best) throw new Error('no coast');
  return {
    at: atParam(best.land, best.water.clone().sub(best.land)),
    water: best.water,
  };
}
