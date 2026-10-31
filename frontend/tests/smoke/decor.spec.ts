import { expect, test } from '@playwright/test';
import { BoxGeometry, Matrix4, MeshBasicMaterial, Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  BIOME_PROPS,
  FEATURE_LOOKS,
  FLORA_LOOKS,
  ROCK_DECOR,
} from '../../src/lib/world/biome-props';
import {
  type FloraTable,
  floraDirection,
  floraNodeId,
  floraRows,
} from '../../src/lib/world/flora';
import {
  buildTerrain,
  cellDirection,
  decodeWorld,
  type GlobeTerrain,
} from '../../src/lib/world/globe';
import {
  biomeGroundClaims,
  groundWeights,
} from '../../src/lib/world/globe-mesh';
import { GROUND_LAYERS } from '../../src/lib/world/ground-shader';
import {
  fillMeshes,
  type KindPart,
  tierMeshes,
} from '../../src/lib/world/instanced-tiers';
import {
  createScatter,
  NODE_CLEARANCE,
  ROAD_CLEARANCE,
  type Scatter,
} from '../../src/lib/world/scatter';
import { FLORA_URL, floraOf, WORLD_URL } from './globe-helpers';

/*
 * The wild ground of the real world (10 §5.2): every flora item and mineral seam is a node exactly where the
 * table has it, never cleared around sites; the client's own scatter is decor only, nothing anyone can use, and
 * it keeps off nodes and their work spots, roads and paths, and (rocks) the mineral hotspots.
 */

const SITE_CLEARING = 45;
const TOWN_CLEARING = 300;

let view: WorldView;
let terrain: GlobeTerrain;
let flora: FloraTable;
let scatter: Scatter;

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  view = (await (await api.get(WORLD_URL)).json()) as WorldView;
  flora = floraOf(view, await (await api.get(FLORA_URL)).body());
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
  scatter = createScatter({
    terrain,
    seed: view.seed,
    frequency: view.frequency,
    biomeNames: view.biome_names,
    table: BIOME_PROPS,
    clearings: view.sites.map((site) => ({
      direction: new Vector3(...site.anchor.position),
      radius: site.kind === 'town' ? TOWN_CLEARING : SITE_CLEARING,
    })),
    rivers: view.rivers.map((river) => river.cells),
    flora,
    places: view.places,
  });
});

const R = () => terrain.globe.radius;
const unit = (position: [number, number, number] | number[]) =>
  new Vector3(...position).normalize();
const metres = (a: Vector3, b: Vector3) =>
  a.clone().normalize().angleTo(b.clone().normalize()) * R();

/** The places the owner looks at: camps' home rings, the Elder grove, the obsidian crater, the flint seams. */
function cellsOfInterest() {
  const places = [
    ...view.sites
      .filter((site) => site.kind === 'camp')
      .map((site) => ({ at: unit(site.anchor.position), reach: 420 })),
    ...view.places.hotspots
      .filter((h) =>
        [
          'elder_grove',
          'obsidian_field',
          'painted_cave_flint',
          'eastern_wall_scar',
          'b_wood',
        ].includes(h.id),
      )
      .map((h) => ({ at: unit(h.centre), reach: h.radius_m + 30 })),
  ];
  return [
    ...new Set(
      places.flatMap(({ at, reach }) => scatter.cellsAround(at, reach)),
    ),
  ];
}

test('every flora item of a cell is one node at its table position, with its id and look', () => {
  const rows = floraRows(flora, terrain.globe.cellCount);
  const at = new Vector3();
  let checked = 0;
  for (const cell of cellsOfInterest()) {
    const [start, end] = rows(cell);
    const nodes = scatter.nodes(cell).filter((node) => node.flora !== null);
    expect(nodes.map((node) => node.id).sort()).toEqual(
      Array.from({ length: end - start }, (_, k) =>
        floraNodeId(start + k),
      ).sort(),
    );
    for (const node of nodes) {
      const index = node.flora!;
      floraDirection(terrain.globe, flora, index, at);
      expect(metres(node.position, at)).toBeLessThan(0.05);
      expect(node.kind).toBe(FLORA_LOOKS[flora.kinds[flora.kind[index]]]);
      expect(node.node).toBe(flora.nodes[flora.kind[index]]);
      // standing on the drawn ground (sunk at most a little into a slope)
      const ground = terrain.heightAt(at);
      expect(node.position.length() - R()).toBeLessThanOrEqual(ground);
      expect(node.position.length() - R()).toBeGreaterThan(ground - 2.5);
      checked += 1;
    }
  }
  expect(checked).toBeGreaterThan(500);
});

test('the mineral seams are nodes at their features, and nodes are never cleared around sites', () => {
  const seams = view.places.features.filter((f) => FEATURE_LOOKS[f.kind]);
  expect(seams.length).toBe(6);
  for (const seam of seams) {
    const found = scatter
      .nodes(seam.cell)
      .filter((node) => node.id === seam.id);
    expect(found.length, seam.id).toBe(1);
    expect(found[0].kind).toBe(FEATURE_LOOKS[seam.kind]);
    expect(metres(found[0].position, unit(seam.position))).toBeLessThan(0.05);
  }
  // flora inside the camps' and landmarks' decor clearings is still drawn
  const sites = view.sites.filter((site) => site.kind !== 'town');
  let inClearings = 0;
  for (const site of sites)
    for (const cell of scatter.cellsAround(
      unit(site.anchor.position),
      SITE_CLEARING + 40,
    ))
      for (const node of scatter.nodes(cell))
        if (metres(node.position, unit(site.anchor.position)) < SITE_CLEARING)
          inClearings += 1;
  expect(inClearings).toBeGreaterThan(10);
});

test('every flora kind of the world has a look', () => {
  expect(view.places.flora_kinds.length).toBeGreaterThan(10);
  for (const kind of view.places.flora_kinds)
    expect(FLORA_LOOKS[kind], kind).toBeDefined();
});

test('no decor grows where the ground is mostly rock', () => {
  const { globe } = terrain;
  const mountain = view.biome_names.indexOf('mountain');
  const claims = view.biome_names.map(biomeGroundClaims);
  const weights = new Float64Array(GROUND_LAYERS.length);
  const rock = GROUND_LAYERS.indexOf('rock');
  const rockAt = (direction: Vector3) => {
    const hit = terrain.locate(direction);
    groundWeights(
      {
        claims: claims[globe.biomes[hit.cell]],
        slope: (Math.acos(1 - hit.tilt) * 180) / Math.PI,
        height: hit.height,
        lakeLevel: Infinity,
      },
      weights,
    );
    return weights[rock];
  };
  const cells = [...globe.biomes.keys()].filter(
    (cell) => globe.biomes[cell] === mountain,
  );
  expect(cells.length).toBeGreaterThan(200);
  let rocky = 0;
  let decor = 0;
  const faults: string[] = [];
  for (const cell of cells) {
    if (rockAt(cellDirection(globe, cell, new Vector3())) > 0.5) rocky += 1;
    for (const instance of scatter.decor(cell)) {
      decor += 1;
      if (rockAt(instance.position.clone().normalize()) > 0.5)
        faults.push(`${instance.kind} on rock`);
    }
  }
  expect(faults).toEqual([]);
  // mountains have rock ground and decor between it
  expect(rocky).toBeGreaterThan(20);
  expect(decor).toBeGreaterThan(500);
});

test('decor keeps off nodes and their spots, roads and paths, and rocks keep out of mineral hotspots', () => {
  const minerals = view.places.hotspots
    .filter((h) =>
      view.places.features.some(
        (f) =>
          f.hotspot === h.id &&
          ['flint_seam', 'obsidian_field', 'gold_pool'].includes(f.kind),
      ),
    )
    .map((h) => ({ at: unit(h.centre), radius: h.radius_m }));
  expect(minerals.length).toBeGreaterThanOrEqual(5);
  const roadCells = new Map<number, [number, number, number][]>();
  for (const road of view.places.roads)
    road.cells.forEach((cell, i) => {
      if (i === 0) return;
      for (const c of [cell, road.cells[i - 1]])
        roadCells.set(c, [
          ...(roadCells.get(c) ?? []),
          [road.cells[i - 1], cell, ROAD_CLEARANCE[road.kind]],
        ]);
    });
  const cells = [
    ...cellsOfInterest(),
    // along the roads out of the camps and the town
    ...view.places.roads.flatMap((road) => road.cells.slice(0, 40)),
  ];
  const a = new Vector3();
  const b = new Vector3();
  const faults: string[] = [];
  let decor = 0;
  let nearRoads = 0;
  for (const cell of new Set(cells)) {
    const near = [cell, ...terrain.neighbours(cell)];
    const nodes = near.flatMap((c) => scatter.nodes(c));
    const segments = near.flatMap((c) => roadCells.get(c) ?? []);
    for (const instance of scatter.decor(cell)) {
      decor += 1;
      for (const node of nodes)
        if (
          metres(instance.position, node.position) <
          node.footprint + NODE_CLEARANCE
        )
          faults.push(`${instance.kind} by ${node.id}`);
      const p = unit(instance.position.toArray()).multiplyScalar(R());
      for (const [from, to, clear] of segments) {
        cellDirection(terrain.globe, from, a).multiplyScalar(R());
        cellDirection(terrain.globe, to, b).multiplyScalar(R());
        const ab = b.clone().sub(a);
        const t = Math.min(
          1,
          Math.max(0, p.clone().sub(a).dot(ab) / ab.lengthSq()),
        );
        const distance = p.distanceTo(a.clone().addScaledVector(ab, t));
        if (distance < clear + 3) nearRoads += 1;
        if (distance < clear) faults.push(`${instance.kind} on a road`);
      }
      if (ROCK_DECOR.has(instance.kind))
        for (const mineral of minerals)
          if (metres(instance.position, mineral.at) < mineral.radius)
            faults.push(`${instance.kind} in a mineral hotspot`);
    }
  }
  expect(faults).toEqual([]);
  expect(decor).toBeGreaterThan(2000);
  // decor still grows right beside the roads: the rule is exercised, not a blanket clearing
  expect(nearRoads).toBeGreaterThan(20);
});

test('a tier that overflows its capacity is reported once, not dropped silently', () => {
  const errors: string[] = [];
  const original = console.error;
  console.error = (message: string) => errors.push(message);
  try {
    const meshes = tierMeshes(
      [
        {
          geometry: new BoxGeometry(),
          material: new MeshBasicMaterial(),
        } as unknown as KindPart,
      ],
      2,
      false,
    );
    const models = [new Matrix4(), new Matrix4(), new Matrix4()];
    fillMeshes(meshes, models.slice(0, 2), 'test oak far');
    expect(errors).toEqual([]);
    fillMeshes(meshes, models, 'test oak far');
    fillMeshes(meshes, models, 'test oak far');
    expect(errors).toEqual([
      'test oak far: 3 instances in a tier of 2; the rest are not drawn',
    ]);
    expect(meshes[0].count).toBe(2);
  } finally {
    console.error = original;
  }
});
