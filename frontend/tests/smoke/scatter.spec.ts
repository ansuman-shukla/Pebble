import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import { BIOME_PROPS, type BiomeName } from '../../src/lib/world/biome-props';
import {
  buildTerrain,
  cellDirection,
  decodeWorld,
  WATER_BIOMES,
} from '../../src/lib/world/globe';
import { createMockWorld } from '../../src/lib/world/mock-world';
import {
  createScatter,
  type ScatterOptions,
} from '../../src/lib/world/scatter';

/* Biome props are a pure function of (seed, cell): the same cell always grows the same instances. */

const view = createMockWorld();
const globe = decodeWorld(view);
const town = view.sites.find((site) => site.kind === 'town')!;
const townDirection = new Vector3(...town.anchor.position);

function scatterFor(seed: number, overrides: Partial<ScatterOptions> = {}) {
  return createScatter({
    terrain: buildTerrain(globe),
    seed,
    frequency: view.frequency,
    biomeNames: view.biome_names,
    table: BIOME_PROPS,
    clearings: [{ direction: townDirection, radius: 300 }],
    rivers: view.rivers.map((river) => river.cells),
    ...overrides,
  });
}

const landCells = [...globe.biomes.keys()].filter(
  (cell) =>
    BIOME_PROPS[view.biome_names[globe.biomes[cell]] as BiomeName].length,
);

test('the same cell grows the same instances, another seed others', () => {
  const first = scatterFor(view.seed);
  const second = scatterFor(view.seed);
  const sample = landCells.filter((_, i) => i % 40 === 0);
  // scattered in a different order, through a different terrain instance
  const again = new Map(
    [...sample].reverse().map((cell) => [cell, second.cell(cell)]),
  );
  let total = 0;
  for (const cell of sample) {
    const instances = first.cell(cell);
    total += instances.length;
    expect(again.get(cell)).toEqual(instances);
  }
  expect(total).toBeGreaterThan(sample.length);
  const other = scatterFor(view.seed + 1);
  expect(sample.map((cell) => other.cell(cell))).not.toEqual(
    sample.map((cell) => first.cell(cell)),
  );
});

test('instances use their biome kinds, stand on the terrain near their cell and avoid water', () => {
  const scatter = scatterFor(view.seed);
  const terrain = buildTerrain(globe);
  const centre = new Vector3();
  for (const cell of landCells.filter((_, i) => i % 25 === 0)) {
    const kinds = BIOME_PROPS[
      view.biome_names[globe.biomes[cell]] as BiomeName
    ].map((prop) => prop.kind);
    cellDirection(globe, cell, centre);
    for (const instance of scatter.cell(cell)) {
      expect(kinds).toContain(instance.kind);
      const direction = instance.position.clone().normalize();
      expect(direction.angleTo(centre) * globe.radius).toBeLessThan(
        scatter.spacing * 0.56,
      );
      const ground = terrain.heightAt(direction);
      const height = instance.position.length() - globe.radius;
      expect(height).toBeLessThanOrEqual(ground);
      expect(height).toBeGreaterThan(ground - 2.5);
      expect(WATER_BIOMES.has(terrain.biomeAt(direction))).toBe(false);
    }
  }
});

test('clearings stay empty and the area query returns the cells in reach', () => {
  const scatter = scatterFor(view.seed);
  const around = scatter.cellsAround(townDirection, 600);
  expect(around.length).toBeGreaterThan(10);
  const at = new Vector3();
  for (const cell of around) {
    const distance =
      cellDirection(globe, cell, at).angleTo(townDirection) * globe.radius;
    expect(distance).toBeLessThanOrEqual(600);
    if (distance < 300) expect(scatter.cell(cell)).toEqual([]);
  }
  const inReach = [...globe.biomes.keys()].filter(
    (cell) =>
      cellDirection(globe, cell, at).angleTo(townDirection) * globe.radius <=
      600,
  );
  expect(new Set(around)).toEqual(new Set(inReach));
});
