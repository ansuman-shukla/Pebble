import { expect, test } from '@playwright/test';
import { type BufferGeometry, Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  buildTerrain,
  decodeWorld,
  type GlobeTerrain,
} from '../../src/lib/world/globe';
import { terrainGeometry } from '../../src/lib/world/globe-mesh';
import { WORLD_URL } from './globe-helpers';

/*
 * The terrain mesh of the real world (GET /api/v1/world): a refined surface with no stray faces, the height
 * lookup the walker uses lies exactly on it, and lakes, which lie above the sea, are drawn as water.
 */

/** Longest grid edge on the planet (the icosahedron's subdivision is uneven): 44 m. */
const LONGEST_GRID_EDGE = 44;
const TERRAIN_TRIANGLE_BUDGET = 1_200_000;

let view: WorldView;
let terrain: GlobeTerrain;
let mesh: BufferGeometry;

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const response = await api.get(WORLD_URL);
  expect(response.ok()).toBe(true);
  view = (await response.json()) as WorldView;
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
  mesh = terrainGeometry(terrain, view.biome_names);
});

const corners = (face: number) => {
  const position = mesh.getAttribute('position');
  const index = mesh.index!.array;
  return [0, 1, 2].map((k) =>
    new Vector3().fromBufferAttribute(position, index[face * 3 + k]),
  );
};

test('the terrain mesh has no stray faces: short edges, all on the planet, facing out', () => {
  const R = view.radius_m;
  const faces = mesh.index!.count / 3;
  expect(faces).toBeLessThanOrEqual(TERRAIN_TRIANGLE_BUDGET);
  const position = mesh.getAttribute('position');
  const point = new Vector3();
  let [lowest, highest] = [Infinity, -Infinity];
  for (let v = 0; v < position.count; v++) {
    const radius = point.fromBufferAttribute(position, v).length();
    lowest = Math.min(lowest, radius - R);
    highest = Math.max(highest, radius - R);
  }
  expect(lowest).toBeGreaterThanOrEqual(-150);
  expect(highest).toBeLessThanOrEqual(400);
  let longest = 0;
  let inward = 0;
  const normal = new Vector3();
  for (let face = 0; face < faces; face++) {
    const [a, b, c] = corners(face);
    longest = Math.max(
      longest,
      a.distanceTo(b),
      b.distanceTo(c),
      c.distanceTo(a),
    );
    normal.subVectors(b, a).cross(point.subVectors(c, a));
    if (normal.dot(a) <= 0) inward += 1;
  }
  const spacing = LONGEST_GRID_EDGE / terrain.surface.divisions;
  expect(longest).toBeLessThan(3 * spacing);
  expect(inward).toBe(0);
});

test('the height lookup lies on the drawn faces', () => {
  const R = view.radius_m;
  const faces = mesh.index!.count / 3;
  let worst = 0;
  for (let k = 0; k < 5000; k++) {
    const face = Math.floor(((k * 0.6180339887) % 1) * faces);
    const [a, b, c] = corners(face);
    let [u, w] = [(k * 0.7548776662) % 1, (k * 0.569840291) % 1];
    if (u + w > 1) [u, w] = [1 - u, 1 - w];
    const point = a
      .multiplyScalar(1 - u - w)
      .addScaledVector(b, u)
      .addScaledVector(c, w);
    worst = Math.max(
      worst,
      Math.abs(terrain.heightAt(point) - (point.length() - R)),
    );
  }
  expect(worst).toBeLessThan(0.002);
});

test('lakes above the sea are drawn as water, not sand', () => {
  const { biomes, heights, cellCount } = terrain.globe;
  const colors = mesh.getAttribute('color');
  const lake = view.biome_names.indexOf('lake');
  let lakeCells = 0;
  // a cell's own point is mesh vertex `cell`
  for (let cell = 0; cell < cellCount; cell++) {
    if (biomes[cell] !== lake || heights[cell] <= 0.2) continue;
    lakeCells += 1;
    const [r, g, b] = [0, 1, 2].map((k) => colors.getComponent(cell, k));
    expect(b, `cell ${cell}`).toBeGreaterThan(r + 0.2);
    expect(b, `cell ${cell}`).toBeGreaterThan(g);
  }
  expect(lakeCells).toBeGreaterThan(50);
});
