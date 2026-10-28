import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { TownView, WorldView } from '../../src/lib/client/types.gen';
import {
  anchorMapping,
  buildTerrain,
  cellDirection,
  decodeWorld,
  directionFromLatLon,
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
  fallPath,
  fallSheetGeometry,
  LAKE_LIFT,
  riverGeometry,
  stillWaterGeometry,
} from '../../src/lib/world/water-mesh';
import { TOWN_GROUND_RADIUS, TOWN_URL } from './explore-helpers';
import { DRAW_CALL_BUDGET, openGlobe, WORLD_URL } from './globe-helpers';

/*
 * The planet's water on the real world (GET /api/v1/world): rivers follow smooth curves that widen downstream,
 * start thin at their springs and never lie over open water; the Mill river runs through the town's stream;
 * the great falls drops as a sheet clear of its cliff into its lake; the sea and the lakes carry the depth of
 * the water under them. In the browser the falls are in the scene and the water animates.
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
  const narrowing: string[] = [];
  for (const { river, points } of layout.runs) {
    // (a site's channel sets its own width: the river may be narrower again past it)
    for (let i = 1; i < points.length; i++)
      if (points[i].width < points[i - 1].width && !points[i - 1].flat)
        narrowing.push(`river ${river} at ${points[i].along} m`);
    const cells = view.rivers[river].cells;
    if (points[0].along > 0 || WATER_BIOMES.has(biomes[cells[0]])) continue;
    springs += 1;
    expect(points[0].width).toBeLessThan(1);
    expect(points[0].fade).toBe(0);
    // grown gradually to the river's own width a little way down
    const near = points.find((point) => point.along >= 10);
    const below = points.find((point) => point.along >= 60);
    if (near && below) {
      expect(below.width).toBeGreaterThan(3 * points[0].width);
      expect(near.width).toBeLessThan(0.6 * below.width);
    }
  }
  expect(narrowing).toEqual([]);
  expect(springs).toBeGreaterThan(30);
  // a river leaving a lake starts at full width: the lake's water flows on
  const outflows = layout.runs.filter(
    ({ river, points }) =>
      WATER_BIOMES.has(biomes[view.rivers[river].cells[0]]) &&
      points[0] === layout.runs.find((run) => run.river === river)!.points[0],
  );
  expect(outflows.length).toBeGreaterThan(3);
  for (const { points } of outflows) expect(points[0].width).toBeGreaterThan(5);
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
    // as wide as the stream it fills
    expect(point.width).toBeGreaterThanOrEqual(8);
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
  // the ribbon lies flat on the stream's water, not on the ground the stream is cut into
  const ribbons = riverGeometry(terrain, layout);
  const position = ribbons.getAttribute('position');
  const inStream: number[] = [];
  for (let i = 0; i < position.count; i++) {
    const at = new Vector3().fromBufferAttribute(position, i);
    if (at.clone().normalize().angleTo(up) * R < 200)
      inStream.push(at.length() - R);
  }
  expect(inStream.length).toBeGreaterThan(100);
  const level = site.anchor.height_m + TOWN_WATER_Y;
  expect(Math.min(...inStream)).toBeGreaterThan(level);
  expect(Math.max(...inStream)).toBeLessThan(level + 0.3);
});

test('the great falls drops from its lip as a sheet clear of the cliff into the lake', () => {
  const R = view.radius_m;
  const site = view.sites.find((candidate) => candidate.id === 'great_falls')!;
  const anchor = new Vector3(...site.anchor.position);
  const [falls] = layout.falls.filter(
    (fall) => fall.lip.angleTo(anchor) * R < 100,
  );
  expect(falls).toBeDefined();
  expect(falls.lipHeight).toBeGreaterThan(site.anchor.height_m - 3);
  expect(falls.lipHeight).toBeLessThan(site.anchor.height_m + 3);
  expect(falls.intoWater).toBe(true);
  expect(falls.footHeight).toBeCloseTo(30, 0);
  // the river ribbon stops at the lip instead of running down the cliff face
  for (const { points } of layout.runs)
    for (const point of points) {
      if (point.direction.angleTo(falls.lip) * R > 60) continue;
      expect(point.height).toBeGreaterThan(falls.lipHeight - 3);
    }
  // the sheet keeps off the cliff all the way down and lands on the lake
  const { up, out } = { up: falls.lip, out: falls.foot.clone().sub(falls.lip) };
  out.addScaledVector(up, -out.dot(up)).normalize();
  const path = fallPath(terrain, falls);
  path.slice(1, -1).forEach(({ x, height }) => {
    const below = up
      .clone()
      .addScaledVector(out, x / R)
      .normalize();
    expect(height).toBeGreaterThan(terrain.heightAt(below) + 1);
  });
  // even where the water would land closer in, the sheet is pushed clear of the cliff
  const closer = {
    ...falls,
    foot: falls.lip.clone().lerp(falls.foot, 0.15).normalize(),
  };
  fallPath(terrain, closer)
    .slice(1, -1)
    .forEach(({ x, height }) => {
      const below = up
        .clone()
        .addScaledVector(out, x / R)
        .normalize();
      expect(height).toBeGreaterThan(terrain.heightAt(below) + 1);
    });
  expect(path[0].height).toBe(falls.lipHeight);
  expect(path[path.length - 1].height).toBe(falls.footHeight);
  const sheet = fallSheetGeometry(terrain, falls);
  const position = sheet.getAttribute('position');
  const heights = Array.from(
    { length: position.count },
    (_, i) => new Vector3().fromBufferAttribute(position, i).length() - R,
  );
  expect(Math.max(...heights)).toBeGreaterThan(falls.lipHeight);
  expect(Math.min(...heights)).toBeLessThan(falls.footHeight + 1);
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
        if (Math.abs(surface - heights[cell] - LAKE_LIFT) > 0.01 || depth <= 1)
          wrong.push(`lake over ${cell}: surface ${surface}, depth ${depth}`);
      } else if (heights[cell] > surface && depth > 0)
        // dry land above the water's surface is out of the water
        wrong.push(`land ${cell}: depth ${depth}`);
    }
  expect(wrong).toEqual([]);
  expect(lakes).toBeGreaterThan(200);
  expect(seas).toBeGreaterThan(10_000);
  // near the shore the sea is refined like the terrain (vertices between the cells), so its depth follows
  // the real shoreline
  let refinedShore = 0;
  for (let i = 0; i < position.count; i++) {
    const surface = point.fromBufferAttribute(position, i).length() - R;
    if (Math.abs(surface - WATER_SURFACE) > 0.15 || Math.abs(water.getX(i)) > 1)
      continue;
    const cell = terrain.nearestCell(point.normalize());
    const centre = cellDirection(terrain.globe, cell, new Vector3());
    if (point.angleTo(centre) * R > 1) refinedShore += 1;
  }
  expect(refinedShore).toBeGreaterThan(5000);
  // a lake cell in the middle of the falls lake is deeper than one on its shore
  const deepest = Math.max(
    ...[...byCell].flatMap(([cell, ids]) =>
      biomes[cell] === lake ? ids.map((i) => water.getX(i)) : [],
    ),
  );
  expect(deepest).toBeGreaterThan(5);
});

test.describe('in the browser', () => {
  test.describe.configure({ timeout: 120_000 });

  test('the great falls is in the scene and the water animates', async ({
    page,
  }) => {
    const errors: string[] = [];
    const R = view.radius_m;
    const site = view.sites.find(
      (candidate) => candidate.id === 'great_falls',
    )!;
    const anchor = new Vector3(...site.anchor.position);
    // on the lake shore, looking at the falls
    const world = await openGlobe(page, errors, '?at=1.9622,13.2856,30');
    await expect(world).toHaveAttribute('data-waterfalls', /\d/, {
      timeout: 30_000,
    });
    const lips = (await world.getAttribute('data-waterfalls'))!
      .split(';')
      .map((spot) => spot.split(',').map(Number));
    expect(
      lips.some(
        ([lat, lon]) => directionFromLatLon(lat, lon).angleTo(anchor) * R < 100,
      ),
    ).toBe(true);
    await expect(world).toHaveAttribute('data-water-time', /\d/, {
      timeout: 30_000,
    });
    const first = Number(await world.getAttribute('data-water-time'));
    await expect
      .poll(async () => Number(await world.getAttribute('data-water-time')), {
        timeout: 10_000,
      })
      .toBeGreaterThan(first + 0.5);
    const calls = Number(await world.getAttribute('data-draw-calls'));
    expect(calls).toBeGreaterThan(0);
    expect(calls).toBeLessThan(DRAW_CALL_BUDGET);
    expect(errors).toEqual([]);
  });
});
