import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  buildTerrain,
  decodeWorld,
  directionFromLatLon,
  type GlobeTerrain,
  latLonFromDirection,
} from '../../src/lib/world/globe';
import { globeMarkGround } from '../../src/lib/world/ground-marks';
import { riverLayout } from '../../src/lib/world/river-courses';
import {
  poolGeometry,
  poolHoles,
  WATERHOLE_BANK_M,
  WATERHOLE_POOL_M,
  type WaterholePool,
  waterholePools,
} from '../../src/lib/world/waterholes';
import { openGlobe, stillWorld, WORLD_URL } from './globe-helpers';

/*
 * Waterholes away from rivers and lakes are drawn as pools (10 §4.6; critic round 1: herds "drinking at the
 * waterhole" stood on a dry patch of slope): level water held in a muddy bowl that meets the terrain at its rim.
 */

/** The bank holds the water at least this far out (waterholes.ts CREST_M); a dam's outer face may fall below. */
const CREST = 4;

let view: WorldView;
let terrain: GlobeTerrain;
let pools: WaterholePool[];

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  view = (await (await api.get(WORLD_URL)).json()) as WorldView;
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
  pools = waterholePools(view.places.features, terrain);
});

test('every waterhole without a river or lake at hand is a pool', () => {
  const expected = view.places.features
    .filter((feature) => feature.kind === 'waterhole' && feature.pool)
    .map((feature) => feature.id);
  expect(expected.length).toBeGreaterThan(0);
  expect(pools.map((pool) => pool.id)).toEqual(expected);
  // the terrain leaves each pool's bowl to it
  for (const [hole, pool] of poolHoles(pools, view.radius_m).map(
    (cone, i) => [cone, pools[i]] as const,
  )) {
    expect(hole.up.angleTo(pool.up)).toBe(0);
    expect(Math.acos(hole.cos) * view.radius_m).toBeCloseTo(
      WATERHOLE_BANK_M - 0.2,
      6,
    );
  }
});

test('the water lies level in its bowl, the bank holds it all round and meets the ground at the rim', () => {
  const { bank, water } = poolGeometry(pools, terrain, view.biome_names);
  const faults: string[] = [];
  const at = new Vector3();
  const position = bank.getAttribute('position');
  for (let i = 0; i < position.count; i++) {
    at.fromBufferAttribute(position, i);
    const direction = at.clone().normalize();
    const pool = pools.find(
      ({ up }) =>
        direction.angleTo(up) * view.radius_m < WATERHOLE_BANK_M + 0.01,
    )!;
    const r = direction.angleTo(pool.up) * view.radius_m;
    const height = at.length() - view.radius_m;
    if (r > WATERHOLE_POOL_M - 0.01 && r < CREST + 0.01 && height < pool.level)
      faults.push(`${pool.id}: bank ${r.toFixed(2)} m out below the water`);
    if (r < WATERHOLE_POOL_M - 0.5 && height > pool.level - 0.1)
      faults.push(`${pool.id}: bed ${r.toFixed(2)} m out above the water`);
    if (
      r > WATERHOLE_BANK_M - 0.01 &&
      Math.abs(height - terrain.heightAt(direction)) > 0.01
    )
      faults.push(`${pool.id}: rim ${height.toFixed(2)} off the ground`);
  }
  const surface = water.getAttribute('position');
  for (let i = 0; i < surface.count; i++) {
    at.fromBufferAttribute(surface, i);
    const pool = pools.find(
      ({ up }) => at.angleTo(up) * view.radius_m < WATERHOLE_POOL_M + 0.01,
    )!;
    if (Math.abs(at.length() - view.radius_m - pool.level) > 1e-3)
      faults.push(`${pool.id}: water not level`);
  }
  expect(surface.count).toBeGreaterThan(0);
  expect(faults).toEqual([]);
  // the pools sit on slopes: the bank is cut into the hill above the water and dammed below it
  const rises = pools.map((pool) => {
    const heights = [0, 1, 2, 3, 4, 5, 6, 7].map((k) => {
      const a = (k / 8) * Math.PI * 2;
      const { lat, lon } = latLonFromDirection(pool.up);
      const north = directionFromLatLon(lat + 0.001, lon).sub(pool.up);
      const east = new Vector3(0, 1, 0).cross(pool.up).normalize();
      north.normalize();
      const rim = pool.up
        .clone()
        .multiplyScalar(view.radius_m)
        .addScaledVector(east, Math.cos(a) * WATERHOLE_BANK_M)
        .addScaledVector(north, Math.sin(a) * WATERHOLE_BANK_M)
        .normalize();
      return terrain.heightAt(rim) - pool.level;
    });
    return [Math.min(...heights), Math.max(...heights)];
  });
  expect(rises.some(([low, high]) => low < 0 && high > 1)).toBe(true);
});

test('no ground mark lies over a pool or its bank', () => {
  const ground = globeMarkGround({
    terrain,
    rivers: riverLayout(
      terrain,
      view.rivers.map((river) => river.cells),
    ),
    pools,
    town: {
      mapping: { toLocal: (_: Vector3, out: Vector3) => out.set(1e6, 0, 1e6) },
      groundRadius: 0,
      height: 0,
      water: [],
      areas: [],
    } as unknown as Parameters<typeof globeMarkGround>[0]['town'],
  });
  for (const pool of pools) {
    expect(ground.heightAt(pool.up)).toBeNull();
    const east = new Vector3(0, 1, 0).cross(pool.up).normalize();
    const out = (metres: number) =>
      pool.up
        .clone()
        .multiplyScalar(view.radius_m)
        .addScaledVector(east, metres)
        .normalize();
    expect(ground.heightAt(out(WATERHOLE_BANK_M - 0.1))).toBeNull();
    expect(ground.heightAt(out(WATERHOLE_BANK_M + 0.5))).not.toBeNull();
  }
});

test("the pool's numbers are the backend's (herds drink round its edge there)", () => {
  const source = readFileSync(
    path.resolve(import.meta.dirname, '../../../backend/app/world/view.py'),
    'utf8',
  );
  const value = (name: string) =>
    Number(new RegExp(`^${name} = ([0-9.]+)`, 'm').exec(source)?.[1]);
  expect(value('POOL_RADIUS_M')).toBe(WATERHOLE_POOL_M);
  expect(value('POOL_BANK_M')).toBe(WATERHOLE_BANK_M);
});

/** Pool-water pixels (blue-green over the savanna's yellow-greens; the sky is paler) on the scene canvas. */
const WATER_PIXELS = `(() => {
  const scene = document.querySelector('canvas[data-engine]');
  const copy = document.createElement('canvas');
  copy.width = scene.width;
  copy.height = scene.height;
  const context = copy.getContext('2d');
  context.drawImage(scene, 0, 0);
  const { data } = context.getImageData(0, 0, copy.width, copy.height);
  let water = 0;
  for (let i = 0; i < data.length; i += 4) {
    const [r, g, b] = [data[i], data[i + 1], data[i + 2]];
    if (b > r + 25 && b > g - 10 && r < 140) water += 1;
  }
  return water / (data.length / 4);
})()`;

test('a pool shows its water on screen', async ({ page }) => {
  const errors: string[] = [];
  const pool = pools.find(({ id }) => id === 'a_savanna:waterhole')!;
  // 12 m north of the waterhole, up the slope, facing it, at its noon (band A lies 6 h ahead of the town)
  const { lat, lon } = latLonFromDirection(pool.up);
  await stillWorld(page);
  await openGlobe(
    page,
    errors,
    `?at=${(lat + 12 / 35).toFixed(4)},${lon.toFixed(4)},180&time=06:00`,
  );
  await page.waitForTimeout(1500);
  const share = await page.evaluate<number>(WATER_PIXELS);
  expect(share).toBeGreaterThan(0.002); // measured 0.006 (the visitor stands in front); none without the pool
  expect(errors).toEqual([]);
});
