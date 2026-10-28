import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { TownView, WorldView } from '../../src/lib/client/types.gen';
import {
  anchorMapping,
  buildTerrain,
  cellDirection,
  decodeWorld,
  type GlobeTerrain,
  tangentFrame,
  WATER_BIOMES,
  WATER_SURFACE,
} from '../../src/lib/world/globe';
import { TOWN_WATER_Y } from '../../src/lib/world/ground-shape';
import {
  isOpenWater,
  type RiverLayout,
  riverLayout,
  streamChannels,
} from '../../src/lib/world/river-courses';
import {
  riverGeometry,
  stillWaterGeometry,
} from '../../src/lib/world/water-mesh';
import { TOWN_GROUND_RADIUS, TOWN_URL } from './explore-helpers';
import { WORLD_URL } from './globe-helpers';

/*
 * The planet's water on the real world (GET /api/v1/world): rivers follow smooth curves that widen downstream,
 * start thin at their springs and never lie over open water; the Mill river runs through the town's stream;
 * the sea and the lakes carry the depth of the water under them.
 */

/** Sharpest turn (degrees) allowed between two ribbon steps of at least a metre, and the 99th percentile. */
const SHARPEST_TURN = 45;
const TYPICAL_TURN = 15;
/** Extra triangles the water may add over the old 48-subdivision ocean sphere and 6 m ribbons. */
const STILL_WATER_BUDGET = 150_000;
const RIBBON_BUDGET = 80_000;

let view: WorldView;
let town: TownView;
let terrain: GlobeTerrain;
let layout: RiverLayout;
let mapping: ReturnType<typeof anchorMapping>;

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const [world, townResponse] = await Promise.all([
    api.get(WORLD_URL),
    api.get(TOWN_URL),
  ]);
  expect(world.ok()).toBe(true);
  view = (await world.json()) as WorldView;
  town = (await townResponse.json()) as TownView;
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
  const site = view.sites.find((candidate) => candidate.kind === 'town')!;
  const R = view.radius_m;
  mapping = anchorMapping(site.anchor, R);
  layout = riverLayout(
    terrain,
    view.rivers.map((river) => river.cells),
    {
      hole: {
        up: new Vector3(...site.anchor.position),
        angle: Math.atan(TOWN_GROUND_RADIUS / (R + site.anchor.height_m)),
      },
      channels: streamChannels(
        town.water,
        mapping,
        site.anchor.height_m,
        TOWN_WATER_Y,
      ),
    },
  );
});

test('rivers follow smooth curves instead of zig-zagging from cell to cell', () => {
  const R = view.radius_m;
  const turns: number[] = [];
  for (const { points } of layout.runs)
    for (let i = 1; i + 1 < points.length; i++) {
      const before = points[i].direction.clone().sub(points[i - 1].direction);
      const after = points[i + 1].direction.clone().sub(points[i].direction);
      if (before.length() * R < 1 || after.length() * R < 1) continue;
      turns.push((before.angleTo(after) * 180) / Math.PI);
    }
  turns.sort((a, b) => a - b);
  expect(turns.length).toBeGreaterThan(3000);
  expect(turns[turns.length - 1]).toBeLessThan(SHARPEST_TURN);
  expect(turns[Math.floor(turns.length * 0.99)]).toBeLessThan(TYPICAL_TURN);
});

test('rivers start thin at a spring, fade in, and never narrow downstream', () => {
  const { biomes } = terrain.globe;
  let springs = 0;
  for (const { river, points } of layout.runs) {
    for (let i = 1; i < points.length; i++)
      expect(points[i].width).toBeGreaterThanOrEqual(points[i - 1].width);
    const cells = view.rivers[river].cells;
    if (points[0].along > 0 || WATER_BIOMES.has(biomes[cells[0]])) continue;
    springs += 1;
    expect(points[0].width).toBeLessThan(1);
    expect(points[0].fade).toBe(0);
    // grown to the river's own width a little way down
    const below = points.find((point) => point.along >= 60);
    if (below) expect(below.width).toBeGreaterThan(3 * points[0].width);
  }
  expect(springs).toBeGreaterThan(30);
  // the long rivers end much wider than they start
  const mill = layout.runs.filter((run) => run.river === 0);
  expect(mill.at(-1)!.points.at(-1)!.width).toBeGreaterThan(10);
});

test('no visible ribbon lies over open water: rivers fade out at the shore', () => {
  const ribbons = riverGeometry(terrain, layout);
  expect(ribbons.index!.count / 3).toBeLessThan(RIBBON_BUDGET);
  const position = ribbons.getAttribute('position');
  const water = ribbons.getAttribute('water');
  const R = view.radius_m;
  let wetVertices = 0;
  let visibleOverOpenWater = 0;
  for (let i = 0; i < position.count; i++) {
    const at = new Vector3().fromBufferAttribute(position, i).normalize();
    if (!isOpenWater(terrain, at)) continue;
    wetVertices += 1;
    const { east, north } = tangentFrame(at);
    const around = [east, north, east.clone().negate(), north.clone().negate()]
      .map((axis) =>
        at.clone().multiplyScalar(R).addScaledVector(axis, 3).normalize(),
      )
      .every((direction) => isOpenWater(terrain, direction));
    const visible = water.getW(i) > 0.4 && Math.abs(water.getX(i)) <= 1;
    if (around && visible) visibleOverOpenWater += 1;
  }
  // ribbons do run a few metres past the shore (faded), so some vertices lie over water
  expect(wetVertices).toBeGreaterThan(50);
  expect(visibleOverOpenWater).toBe(0);
  // and every mouth fades to nothing
  for (const { points } of layout.runs) {
    const end = points[points.length - 1];
    if (isOpenWater(terrain, end.direction)) expect(end.fade).toBe(0);
  }
});

test('the Mill river runs through the town stream instead of stopping at the town', () => {
  const stream = town.water.find((area) => area.kind === 'stream')!;
  const xs = stream.polygon.map(([x]) => x);
  const centreX = (Math.min(...xs) + Math.max(...xs)) / 2;
  const R = view.radius_m;
  const site = view.sites.find((candidate) => candidate.kind === 'town')!;
  const through = layout.runs.filter((run) =>
    run.points.some((point) => point.flat),
  );
  expect(through.map((run) => run.river)).toEqual([0]);
  const local = through[0].points.map((point) =>
    mapping.toLocal(
      point.direction.clone().multiplyScalar(R + site.anchor.height_m),
      new Vector3(),
    ),
  );
  const zs: number[] = [];
  for (const [k, point] of through[0].points.entries()) {
    if (!point.flat) continue;
    zs.push(local[k].z);
    expect(Math.abs(local[k].x - centreX)).toBeLessThan(0.01);
    expect(point.height).toBeCloseTo(site.anchor.height_m + TOWN_WATER_Y, 5);
    expect(point.fade).toBe(1);
  }
  // one run carries the river into the stream's north end and out of its south end
  expect(Math.min(...zs)).toBeLessThan(-155);
  expect(Math.max(...zs)).toBeGreaterThan(155);
  const up = new Vector3(...site.anchor.position);
  const outside = through[0].points
    .map((point, k) => ({ point, z: local[k].z }))
    .filter(
      ({ point }) => point.direction.angleTo(up) * R > TOWN_GROUND_RADIUS,
    );
  expect(outside.some(({ z }) => z < 0)).toBe(true);
  expect(outside.some(({ z }) => z > 0)).toBe(true);
  // no ribbon crosses the town's ground outside the stream (only where it enters and leaves the stream)
  const ends = [Math.min(...zs), Math.max(...zs)].map((z) =>
    mapping.toWorld(centreX, 0, z, new Vector3()).normalize(),
  );
  const intruders = layout.runs.flatMap((run) =>
    run.points.filter(
      (point) =>
        !point.flat &&
        point.direction.angleTo(up) * R < TOWN_GROUND_RADIUS - 10 &&
        ends.every((end) => point.direction.angleTo(end) * R > 20),
    ),
  );
  expect(intruders).toEqual([]);
});

test('the sea and the lakes carry the depth of the water under them', () => {
  const still = stillWaterGeometry(terrain);
  expect(still.index!.count / 3).toBeLessThan(STILL_WATER_BUDGET);
  const position = still.getAttribute('position');
  const water = still.getAttribute('water');
  const R = view.radius_m;
  const { heights, biomes } = terrain.globe;
  const lake = view.biome_names.indexOf('lake');
  // index the water vertices that sit right above a cell
  const byCell = new Map<number, number[]>();
  const point = new Vector3();
  for (let i = 0; i < position.count; i++) {
    point.fromBufferAttribute(position, i).normalize();
    const cell = terrain.nearestCell(point);
    const centre = cellDirection(terrain.globe, cell, new Vector3());
    if (point.angleTo(centre) * R > 0.01) continue;
    byCell.set(cell, [...(byCell.get(cell) ?? []), i]);
  }
  let lakes = 0;
  let seas = 0;
  // collected and checked once: expect() in a loop over thousands of vertices is slow
  const wrong: string[] = [];
  for (const [cell, ids] of byCell)
    for (const i of ids) {
      const depth = water.getX(i);
      const surface = point.fromBufferAttribute(position, i).length() - R;
      if (Math.abs(surface - WATER_SURFACE) < 0.01) {
        // the sea's depth is the drop to the ground under it (negative on land)
        seas += 1;
        if (Math.abs(depth - (surface - heights[cell])) > 0.01)
          wrong.push(`sea over ${cell}: depth ${depth}`);
      } else if (biomes[cell] === lake) {
        // a lake lies on its flat bed, deeper away from the shore
        lakes += 1;
        if (Math.abs(surface - heights[cell] - 0.05) > 0.01 || depth <= 1)
          wrong.push(`lake over ${cell}: surface ${surface}, depth ${depth}`);
      } else if (depth > 0.05) wrong.push(`land ${cell}: depth ${depth}`);
    }
  expect(wrong).toEqual([]);
  expect(lakes).toBeGreaterThan(200);
  expect(seas).toBeGreaterThan(10_000);
  // a lake cell in the middle of the falls lake is deeper than one on its shore
  const deepest = Math.max(
    ...[...byCell].flatMap(([cell, ids]) =>
      biomes[cell] === lake ? ids.map((i) => water.getX(i)) : [],
    ),
  );
  expect(deepest).toBeGreaterThan(5);
});
