import { expect, test } from '@playwright/test';

import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import { assetSize, kindScale, PROPS } from '../../src/lib/world/assets';
import { BIOME_PROPS } from '../../src/lib/world/biome-props';
import {
  buildTerrain,
  cellDirection,
  decodeWorld,
} from '../../src/lib/world/globe';
import { createScatter, MAX_PROP_SLOPE_DEG } from '../../src/lib/world/scatter';

/*
 * The real generated world (GET /api/v1/world on the backend) only names kinds the frontend can draw, the
 * backend footprints of its camps and landmarks match the drawn size (asset size x kindScale), and its biome
 * props keep off cliffs.
 */

const WORLD_URL = 'http://localhost:8100/api/v1/world';
/** Footprints are authored to 0.1 m. */
const FOOTPRINT_TOLERANCE = 0.1;

async function fetchWorld(
  request: import('@playwright/test').APIRequestContext,
) {
  const response = await request.get(WORLD_URL);
  expect(response.ok()).toBe(true);
  return (await response.json()) as WorldView;
}

test('every kind placed at a site of the real world is in the registry', async ({
  request,
}) => {
  const world = await fetchWorld(request);
  const kinds = new Set(
    world.sites.flatMap((site) => (site.placements ?? []).map((p) => p.kind)),
  );
  expect(kinds.size).toBeGreaterThan(10);
  expect([...kinds].filter((kind) => !(kind in PROPS))).toEqual([]);
});

test('site footprints match the drawn size of their kind', async ({
  request,
}) => {
  const world = await fetchWorld(request);
  const placements = world.sites
    .filter((site) => site.kind !== 'town')
    .flatMap((site) => site.placements ?? []);
  expect(placements.some((p) => p.kind === 'giant_tree')).toBe(true);
  for (const placement of placements) {
    const size = assetSize(PROPS[placement.kind as keyof typeof PROPS]);
    const scale = kindScale(placement.kind);
    const turned = placement.rotation_deg % 180 !== 0;
    const [x, z] = turned
      ? [size.z * scale, size.x * scale]
      : [size.x * scale, size.z * scale];
    const { x: fx, z: fz } = placement.footprint; // already turned by rotation_deg
    expect(Math.abs(fx - x), `${placement.kind} x`).toBeLessThanOrEqual(
      FOOTPRINT_TOLERANCE,
    );
    expect(Math.abs(fz - z), `${placement.kind} z`).toBeLessThanOrEqual(
      FOOTPRINT_TOLERANCE,
    );
  }
});

test('biome props of the real world never stand on cliffs', async ({
  request,
}) => {
  const world = await fetchWorld(request);
  const terrain = buildTerrain(decodeWorld(world));
  const scatter = createScatter({
    terrain,
    seed: world.seed,
    frequency: world.frequency,
    biomeNames: world.biome_names,
    table: BIOME_PROPS,
    clearings: [],
    rivers: world.rivers.map((river) => river.cells),
  });
  const maxTilt = 1 - Math.cos((MAX_PROP_SLOPE_DEG * Math.PI) / 180);
  let steepCells = 0;
  let instances = 0;
  for (let cell = 0; cell < world.cell_count; cell += 11) {
    const grown = scatter.cell(cell);
    instances += grown.length;
    const centre = cellDirection(terrain.globe, cell, new Vector3());
    if (terrain.locate(centre, cell).tilt > maxTilt) steepCells += 1;
    for (const instance of grown)
      expect(
        terrain.locate(instance.position.clone().normalize(), cell).tilt,
      ).toBeLessThanOrEqual(maxTilt);
  }
  // the real terrain has cliffs, so the rule is exercised
  expect(steepCells).toBeGreaterThan(20);
  expect(instances).toBeGreaterThan(10_000);
});
