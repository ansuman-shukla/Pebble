import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  anchorMapping,
  buildTerrain,
  cellDirection,
  decodeWorld,
  WATER_BIOMES,
} from '../../src/lib/world/globe';
import {
  createMockWorld,
  MOCK_TOWN_HEIGHT,
} from '../../src/lib/world/mock-world';

/* The dev/test mock world keeps the contract's promises, so the globe client can be built against it. */

const view = createMockWorld();
const globe = decodeWorld(view);
const terrain = buildTerrain(globe);

test('the mock world is deterministic and sized like an icosphere', () => {
  expect(createMockWorld()).toEqual(view);
  expect(createMockWorld({ seed: 8 }).heights).not.toEqual(view.heights);
  expect(view.cell_count).toBe(10 * view.frequency ** 2 + 2);
  expect(globe.triangles.length).toBe(20 * view.frequency ** 2 * 3);
  expect(view.biome_names[13]).toBe('lake');
  expect(Math.max(...globe.biomes)).toBeLessThan(view.biome_names.length);
});

test('about 40 % of the planet is water, with poles of snow and ice', () => {
  const water = globe.biomes.filter((biome) => WATER_BIOMES.has(biome)).length;
  expect(water / globe.cellCount).toBeGreaterThan(0.3);
  expect(water / globe.cellCount).toBeLessThan(0.5);
  for (const pole of [new Vector3(0, 1, 0), new Vector3(0, -1, 0)])
    expect(view.biome_names[terrain.biomeAt(pole)]).toMatch(/ice|snow/);
});

test('the town sits on a flat land plateau at h0 with the sea to its south', () => {
  const town = view.sites.find((site) => site.kind === 'town')!;
  expect(town.anchor.height_m).toBe(MOCK_TOWN_HEIGHT);
  const mapping = anchorMapping(town.anchor, globe.radius);
  const point = new Vector3();
  for (let x = -220; x <= 220; x += 20) {
    for (let z = -220; z <= 220; z += 20) {
      if (Math.hypot(x, z) > 220) continue;
      mapping.toWorld(x, 0, z, point);
      expect(terrain.heightAt(point)).toBeGreaterThan(MOCK_TOWN_HEIGHT - 1);
      expect(terrain.heightAt(point)).toBeLessThanOrEqual(
        MOCK_TOWN_HEIGHT + 1e-3,
      );
    }
  }
  expect(
    WATER_BIOMES.has(terrain.biomeAt(mapping.toWorld(0, 0, 700, point))),
  ).toBe(true);
});

test('every site of the contract is there, camps and landmarks on land', () => {
  expect(view.sites.map((site) => site.id).sort()).toEqual(
    [
      'band_a_camp',
      'band_b_camp',
      'elder_tree',
      'great_falls',
      'hot_springs',
      'ice_gate',
      'painted_cave',
      'smoking_mountain',
      'standing_stones',
      'town',
    ].sort(),
  );
  for (const site of view.sites) {
    if (site.id === 'great_falls') continue;
    expect(WATER_BIOMES.has(globe.biomes[site.cell]), site.id).toBe(false);
  }
  const volcano = view.sites.find((site) => site.id === 'smoking_mountain')!;
  expect(volcano.anchor.height_m).toBeGreaterThan(250);
});

test('the land loop is a closed walkable cycle and rivers run downhill into water', () => {
  const loop = view.land_loop;
  expect(loop.length).toBeGreaterThan(50);
  const a = new Vector3();
  const b = new Vector3();
  loop.forEach((cell, i) => {
    expect(WATER_BIOMES.has(globe.biomes[cell])).toBe(false);
    const next = loop[(i + 1) % loop.length];
    // neighbours, or at worst two cells apart where the trace cut a corner
    const gap =
      cellDirection(globe, cell, a).angleTo(cellDirection(globe, next, b)) *
      globe.radius;
    expect(gap).toBeLessThan((2.2 * (globe.radius * 1.11)) / view.frequency);
  });
  expect(view.rivers.length).toBeGreaterThanOrEqual(2);
  for (const river of view.rivers) {
    const heights = river.cells.map((cell) => globe.heights[cell]);
    for (let i = 1; i < heights.length; i++)
      expect(heights[i]).toBeLessThan(heights[i - 1]);
    expect(globe.heights[river.cells[river.cells.length - 1]]).toBeLessThan(0);
  }
});
