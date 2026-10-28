/*
 * DEV/TEST ONLY: a deterministic stand-in for GET /api/v1/world until the backend generator lands. Same fields and
 * encodings as the contract; a coarser icosphere by default (frequency 30, 9002 cells) so it builds in ~0.1 s.
 * Sites are authored by lat/lon like world.yaml, and the terrain is shaped around them (town plateau with the sea
 * to its south, camps by ponds, the volcano, the falls into a lake, the land loop closed by the ice gate).
 */
import { Vector3 } from 'three';

import { icosphere } from './icosphere';
import {
  buildTerrain,
  directionFromLatLon,
  float32ToBase64,
  type Globe,
  siteMapping,
  tangentFrame,
  uint32ToBase64,
  encodeBase64,
} from './globe';
import type { TownPlacement } from '@/lib/client/types.gen';
import type { River, Site, WorldView } from './world-view';

const MOCK_BIOME_NAMES = [
  'deep_ocean',
  'shallow_ocean',
  'beach',
  'grassland',
  'broadleaf_forest',
  'taiga',
  'wetland',
  'hills',
  'mountain',
  'savanna',
  'tundra',
  'snow',
  'ice',
  'lake',
  'volcanic',
] as const;

const B = Object.fromEntries(
  MOCK_BIOME_NAMES.map((name, index) => [name, index]),
) as Record<(typeof MOCK_BIOME_NAMES)[number], number>;

const RADIUS = 2000;
export const MOCK_TOWN_HEIGHT = 8;
const TOWN_FLAT = 230;
const TOWN_BLEND = 300;
const OCEAN_SHARE = 0.5;
/** Water bodies smaller than this share of the cells are lakes; the rest is ocean (the land loop splits it). */
const LAKE_SHARE = 0.02;

// --- noise ---

function hash(ix: number, iy: number, iz: number, seed: number) {
  let h = Math.imul(ix, 374761393) ^ Math.imul(iy, 668265263);
  h = (h ^ Math.imul(iz, 1274126177) ^ Math.imul(seed, 2246822519)) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

const smooth = (t: number) => t * t * (3 - 2 * t);
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/** Value noise in [-1, 1]. */
function noise(x: number, y: number, z: number, seed: number) {
  const [ix, iy, iz] = [Math.floor(x), Math.floor(y), Math.floor(z)];
  const [fx, fy, fz] = [smooth(x - ix), smooth(y - iy), smooth(z - iz)];
  const corner = (dx: number, dy: number, dz: number) =>
    hash(ix + dx, iy + dy, iz + dz, seed);
  const plane = (dz: number) =>
    lerp(
      lerp(corner(0, 0, dz), corner(1, 0, dz), fx),
      lerp(corner(0, 1, dz), corner(1, 1, dz), fx),
      fy,
    );
  return lerp(plane(0), plane(1), fz) * 2 - 1;
}

function fbm(p: Vector3, scale: number, octaves: number, seed: number) {
  let sum = 0;
  let amplitude = 1;
  let norm = 0;
  let frequency = scale;
  for (let octave = 0; octave < octaves; octave++) {
    sum +=
      amplitude *
      noise(p.x * frequency, p.y * frequency, p.z * frequency, seed + octave);
    norm += amplitude;
    amplitude *= 0.5;
    frequency *= 2.03;
  }
  return sum / norm;
}

// --- authored sites ---

interface SiteSpec {
  id: string;
  kind: Site['kind'];
  name: string;
  lat: number;
  lon: number;
  /** Flattened to the anchor height within this many metres, blended out over as many again. */
  flat: number;
  placements?: [kind: string, x: number, z: number, rotation?: number][];
}

const ring = (kind: string, count: number, radius: number) =>
  Array.from({ length: count }, (_, i): [string, number, number, number] => [
    kind,
    Math.round(Math.sin((i / count) * Math.PI * 2) * radius * 10) / 10,
    Math.round(Math.cos((i / count) * Math.PI * 2) * radius * 10) / 10,
    (i * 90) % 360,
  ]);

const CAMP: SiteSpec['placements'] = [
  ['fire_pit', 0, 0],
  ['cook_tripod', 0, 0],
  ['lean_to', 4, -4, 180],
  ['firewood', -3, 2],
  ['reed_basket', 2, 3],
  ['reed_torch', -4, -3],
  ['fallen_log', 0, 5, 90],
];

const SITES: SiteSpec[] = [
  {
    id: 'town',
    kind: 'town',
    name: 'The castle town',
    lat: 32,
    lon: 20,
    flat: 0,
  },
  {
    id: 'band_a_camp',
    kind: 'camp',
    name: 'Band A camp',
    lat: -10,
    lon: 140,
    flat: 90,
    placements: CAMP,
  },
  {
    id: 'band_b_camp',
    kind: 'camp',
    name: 'Band B camp',
    lat: 14,
    lon: -110,
    flat: 90,
    placements: CAMP,
  },
  {
    id: 'smoking_mountain',
    kind: 'landmark',
    name: 'The smoking mountain',
    lat: 5,
    lon: 75,
    flat: 40,
    placements: ring('rock', 5, 18),
  },
  {
    id: 'great_falls',
    kind: 'landmark',
    name: 'The great falls',
    lat: 40,
    lon: -30,
    flat: 0,
  },
  {
    id: 'elder_tree',
    kind: 'landmark',
    name: 'The elder tree',
    lat: 50,
    lon: 60,
    flat: 90,
    placements: [['maple_tree', 0, 0], ...ring('azalea', 4, 6)],
  },
  {
    id: 'standing_stones',
    kind: 'landmark',
    name: 'The standing stones',
    lat: -35,
    lon: 30,
    flat: 90,
    placements: ring('rock', 8, 9),
  },
  {
    id: 'painted_cave',
    kind: 'landmark',
    name: 'The painted cave',
    lat: -4,
    lon: 149,
    flat: 90,
    placements: [
      ['petroglyph_boulder', 0, 0],
      ['petroglyph_boulder', 4, 1, 90],
      ...ring('rock', 4, 7),
    ],
  },
  {
    id: 'ice_gate',
    kind: 'landmark',
    name: 'The ice gate',
    lat: 72,
    lon: 180,
    flat: 90,
    placements: [
      ['rock', -6, 0],
      ['rock', 6, 0],
      ['rock', -6, 8],
      ['rock', 6, 8],
    ],
  },
  {
    id: 'hot_springs',
    kind: 'landmark',
    name: 'The hot springs',
    lat: 24,
    lon: 105,
    flat: 90,
    placements: [
      ['stone_basin', 0, 0],
      ['stone_basin', 3, 2, 90],
      ['reeds', -3, 1],
      ...ring('rock', 5, 8),
    ],
  },
];

/** The land loop: the great circle whose highest point is the ice gate (72°N, 180°). */
const LOOP_AXIS = directionFromLatLon(18, 0);
const LOOP_WIDTH = 0.1;
/** Half-width of the always-dry causeway along the loop, and of the shelf down to the sea floor beside it. */
const LOOP_CAUSEWAY = 90;
const LOOP_SHELF = 200;
const VOLCANO_RADIUS = 700;
const VOLCANO_PEAK = 320;

export interface MockWorldOptions {
  seed?: number;
  frequency?: number;
}

/** DEV/TEST ONLY: the mock world in the exact `GET /api/v1/world` format. */
export function createMockWorld({
  seed = 7,
  frequency = 30,
}: MockWorldOptions = {}): WorldView {
  const { positions, triangles } = icosphere(frequency);
  const cellCount = positions.length / 3;
  const heights = new Float32Array(cellCount);
  const globe: Globe = {
    radius: RADIUS,
    cellCount,
    positions,
    heights,
    biomes: new Uint8Array(cellCount),
    triangles,
  };
  const terrain = buildTerrain(globe);
  const dirs = Array.from({ length: cellCount }, (_, i) =>
    new Vector3().fromArray(positions, i * 3),
  );
  const distance = (a: Vector3, b: Vector3) => a.angleTo(b) * RADIUS;
  const siteDirs = new Map(
    SITES.map((site) => [site.id, directionFromLatLon(site.lat, site.lon)]),
  );
  const at = (id: string) => siteDirs.get(id)!;

  // continents + the loop band, sea level at the OCEAN_SHARE quantile
  const raw = dirs.map((u) => {
    const band = Math.exp(-((u.dot(LOOP_AXIS) / LOOP_WIDTH) ** 2));
    return fbm(u, 1.4, 5, seed) + 0.5 * band;
  });
  const sorted = [...raw].sort((a, b) => a - b);
  const sea = sorted[Math.floor(cellCount * OCEAN_SHARE)];
  const [low, high] = [sorted[0], sorted[cellCount - 1]];
  dirs.forEach((u, i) => {
    const e = raw[i] - sea;
    if (e < 0) heights[i] = -120 * (-e / (sea - low)) ** 1.3;
    else {
      const land = e / (high - sea);
      const ridges = 1 - Math.abs(fbm(u, 5, 3, seed + 50));
      heights[i] = 1.5 + 200 * land ** 1.4 + 60 * land * ridges ** 3;
    }
  });

  // the land loop stays walkable all the way round: a causeway with shelving sides
  const loop = traceCells(terrain, greatCircle(LOOP_AXIS, 720));
  dirs.forEach((u, i) => {
    const off = Math.abs(u.dot(LOOP_AXIS)) * RADIUS;
    if (off < LOOP_CAUSEWAY)
      heights[i] = Math.max(heights[i], 3 + 6 * hash(i, 1, 2, seed));
    else if (off < LOOP_CAUSEWAY + LOOP_SHELF)
      heights[i] = Math.max(
        heights[i],
        lerp(3, -40, (off - LOOP_CAUSEWAY) / LOOP_SHELF),
      );
  });

  // town: land around it, the sea to its south (local z > 420)
  const town = at('town');
  const townFrame = tangentFrame(town);
  const townLocal = siteMapping(townFrame, RADIUS + MOCK_TOWN_HEIGHT);
  const local = new Vector3();
  dirs.forEach((u, i) => {
    const d = distance(u, town);
    if (d > 1600) return;
    townLocal.toLocal(u.clone().multiplyScalar(RADIUS), local);
    if (local.z > 430)
      heights[i] = Math.min(heights[i], -6 - (local.z - 430) * 0.04);
    else if (d < 600)
      heights[i] = Math.max(heights[i], 4 + Math.max(0, -local.z - 200) * 0.08);
  });

  // volcano cone with a crater
  const volcano = at('smoking_mountain');
  dirs.forEach((u, i) => {
    const d = distance(u, volcano);
    if (d >= VOLCANO_RADIUS) return;
    const cone = (1 - d / VOLCANO_RADIUS) ** 1.6;
    heights[i] = Math.max(heights[i], 0) * (1 - cone) + VOLCANO_PEAK * cone;
    if (d < 60) heights[i] -= 25;
  });

  // hot springs among mountains
  const springs = at('hot_springs');
  dirs.forEach((u, i) => {
    const d = distance(u, springs);
    if (d < 900)
      heights[i] = Math.max(heights[i], 210 * (1 - d / 900) ** 0.7 + 5);
  });

  // the great falls: a lake below a cliff, fed from the north
  const falls = at('great_falls');
  const fallsFrame = tangentFrame(falls);
  const fallsLocal = siteMapping(fallsFrame, RADIUS);
  dirs.forEach((u, i) => {
    const d = distance(u, falls);
    if (d < 240) heights[i] = -10;
    else if (d < 1300) {
      fallsLocal.toLocal(u.clone().multiplyScalar(RADIUS), local);
      const rim = local.z < 0 ? 70 + Math.max(0, -local.z - 240) * 0.12 : 12;
      heights[i] = Math.max(heights[i], rim * (1 - (d - 240) / 1060) + 2);
    }
  });

  // camps by a pond each
  for (const id of ['band_a_camp', 'band_b_camp']) {
    const camp = at(id);
    const pond = tangentFrame(camp);
    const pondCentre = siteMapping(pond, RADIUS)
      .toWorld(230, 0, 0, new Vector3())
      .normalize();
    dirs.forEach((u, i) => {
      const d = distance(u, camp);
      if (d < 500) heights[i] = Math.max(heights[i], 3 + d * 0.02);
      if (distance(u, pondCentre) < 110) heights[i] = -5;
    });
  }

  // flatten the sites
  // one cell further than the contract's radii, so the rendered triangles are flat all the way out to them
  const spacing = (RADIUS * 1.11) / frequency;
  const anchorHeights = new Map<string, number>();
  for (const site of SITES) {
    const u = at(site.id);
    const flat = site.kind === 'town' ? TOWN_FLAT + spacing : site.flat;
    const blend = site.kind === 'town' ? TOWN_BLEND + spacing : site.flat * 2;
    const h0 =
      site.kind === 'town'
        ? MOCK_TOWN_HEIGHT
        : Math.max(terrain.heightAt(u), site.flat > 0 ? 3 : -Infinity);
    anchorHeights.set(site.id, h0);
    if (flat <= 0) continue;
    dirs.forEach((cell, i) => {
      const d = distance(cell, u);
      if (d <= flat) heights[i] = h0;
      else if (d < blend)
        heights[i] = lerp(h0, heights[i], smooth((d - flat) / (blend - flat)));
    });
  }

  // rivers: authored courses carved so they always run downhill into water
  const townWorld = (x: number, z: number) =>
    townLocal.toWorld(x, 0, z, new Vector3()).normalize();
  const rivers: River[] = [
    {
      id: 'town_river',
      name: 'Castle river',
      cells: carveRiver(
        traceCells(terrain, [
          townWorld(520, -1400),
          townWorld(420, -500),
          townWorld(380, 0),
          townWorld(470, 900),
        ]),
        heights,
        terrain,
      ),
    },
    {
      id: 'falls_river',
      name: 'Falls river',
      cells: carveRiver(
        traceCells(terrain, [
          fallsLocalDir(fallsLocal, 60, -950),
          fallsLocalDir(fallsLocal, 0, -600),
          falls,
        ]),
        heights,
        terrain,
      ),
    },
    {
      id: 'springs_river',
      cells: carveRiver(
        traceCells(terrain, [
          springs,
          directionFromLatLon(5, 112),
          directionFromLatLon(-15, 118),
        ]),
        heights,
        terrain,
      ),
    },
  ];

  // polar caps: sea ice above the water
  dirs.forEach((u, i) => {
    if (Math.abs(u.y) > Math.sin(78 * (Math.PI / 180)) && heights[i] < 1)
      heights[i] = 1 + hash(i, 3, 4, seed);
  });

  const biomes = assignBiomes(dirs, heights, terrain, seed, {
    volcano,
    town,
    rivers: new Set(rivers.flatMap((river) => river.cells)),
  });

  const sites: Site[] = SITES.map((spec) => {
    const u = at(spec.id);
    const frame = tangentFrame(u);
    return {
      id: spec.id,
      kind: spec.kind,
      name: spec.name,
      cell: terrain.nearestCell(u),
      anchor: {
        position: u.toArray(),
        east: frame.east.toArray(),
        north: frame.north.toArray(),
        height_m: anchorHeights.get(spec.id)!,
      },
      placements: (spec.placements ?? []).map(
        ([kind, x, z, rotation = 0], index): TownPlacement => ({
          id: `${spec.id}-${kind}-${index}`,
          kind,
          x,
          z,
          rotation_deg: rotation as TownPlacement['rotation_deg'],
          footprint: { x: 1, z: 1 },
          walk: 'none',
        }),
      ),
    };
  });

  return {
    seed,
    generator_version: `mock-1-f${frequency}`,
    radius_m: RADIUS,
    frequency,
    cell_count: cellCount,
    biome_names: [...MOCK_BIOME_NAMES],
    positions: float32ToBase64(positions),
    heights: float32ToBase64(heights),
    biomes: encodeBase64(biomes),
    triangles: uint32ToBase64(triangles),
    rivers,
    land_loop: loop,
    sites,
  };
}

const fallsLocalDir = (
  mapping: ReturnType<typeof siteMapping>,
  x: number,
  z: number,
) => mapping.toWorld(x, 0, z, new Vector3()).normalize();

/** Points around the great circle perpendicular to `axis`. */
function greatCircle(axis: Vector3, count: number) {
  const frame = tangentFrame(axis);
  return Array.from({ length: count + 1 }, (_, i) => {
    const angle = (i / count) * Math.PI * 2;
    return frame.east
      .clone()
      .multiplyScalar(Math.cos(angle))
      .addScaledVector(frame.north, Math.sin(angle));
  });
}

/** Cells along a path of directions (slerped finely), consecutive duplicates removed. */
function traceCells(
  terrain: ReturnType<typeof buildTerrain>,
  waypoints: Vector3[],
) {
  const cells: number[] = [];
  const step = new Vector3();
  for (let w = 0; w + 1 < waypoints.length; w++) {
    const [a, b] = [waypoints[w], waypoints[w + 1]];
    const samples = Math.max(2, Math.ceil(a.angleTo(b) / 0.002));
    for (let s = 0; s <= samples; s++) {
      step
        .copy(a)
        .lerp(b, s / samples)
        .normalize();
      const cell = terrain.nearestCell(step);
      if (cells[cells.length - 1] !== cell) cells.push(cell);
    }
  }
  if (cells.length > 2 && cells[0] === cells[cells.length - 1]) cells.pop();
  return cells;
}

/** The shortest cell path from the end of a course to the nearest water, appended to it. */
function extendToWater(
  course: number[],
  heights: Float32Array,
  terrain: ReturnType<typeof buildTerrain>,
) {
  const end = course[course.length - 1];
  if (course.some((cell) => heights[cell] < 0)) return course;
  const from = new Map<number, number>([[end, end]]);
  const queue = [end];
  for (let k = 0; k < queue.length; k++) {
    const cell = queue[k];
    if (heights[cell] < 0) {
      const path: number[] = [];
      for (let at = cell; at !== end; at = from.get(at)!) path.push(at);
      return [...course, ...path.reverse()];
    }
    for (const near of terrain.neighbours(cell)) {
      if (!from.has(near)) {
        from.set(near, cell);
        queue.push(near);
      }
    }
  }
  return course;
}

/** Lowers a course so it falls at least 0.4 m per cell; ends at the first cell under water. */
function carveRiver(
  course: number[],
  heights: Float32Array,
  terrain: ReturnType<typeof buildTerrain>,
) {
  const cells: number[] = [];
  let previous = Infinity;
  for (const cell of extendToWater(course, heights, terrain)) {
    cells.push(cell);
    if (heights[cell] < 0) break;
    heights[cell] = Math.max(0.6, Math.min(heights[cell], previous - 0.4));
    previous = heights[cell];
  }
  return cells;
}

function assignBiomes(
  dirs: Vector3[],
  heights: Float32Array,
  terrain: ReturnType<typeof buildTerrain>,
  seed: number,
  places: { volcano: Vector3; town: Vector3; rivers: Set<number> },
) {
  const count = dirs.length;
  const biomes = new Uint8Array(count);
  // ocean = big connected water bodies; small ones are lakes
  const ocean = new Uint8Array(count);
  const seen = new Uint8Array(count);
  for (let start = 0; start < count; start++) {
    if (seen[start] || heights[start] >= 0) continue;
    const body = [start];
    seen[start] = 1;
    for (let k = 0; k < body.length; k++) {
      for (const near of terrain.neighbours(body[k])) {
        if (!seen[near] && heights[near] < 0) {
          seen[near] = 1;
          body.push(near);
        }
      }
    }
    if (body.length > count * LAKE_SHARE)
      for (const cell of body) ocean[cell] = 1;
  }
  const touchesOcean = (cell: number) =>
    [...terrain.neighbours(cell)].some((near) => ocean[near]);

  dirs.forEach((u, i) => {
    const h = heights[i];
    const lat =
      Math.abs(Math.asin(Math.max(-1, Math.min(1, u.y)))) * (180 / Math.PI);
    const temperature = 1 - lat / 85 - Math.max(h, 0) / 500;
    const moisture =
      0.5 + 0.6 * fbm(u, 3, 3, seed + 99) + (touchesOcean(i) ? 0.15 : 0);
    const nearVolcano = u.angleTo(places.volcano) * RADIUS;
    const nearTown = u.angleTo(places.town) * RADIUS;
    let biome: number;
    if (h < 0)
      biome = ocean[i] ? (h < -25 ? B.deep_ocean : B.shallow_ocean) : B.lake;
    else if (lat > 78) biome = B.ice;
    else if (nearTown < TOWN_BLEND) biome = B.grassland;
    else if (nearVolcano < 330) biome = B.volcanic;
    else if (temperature < 0.08) biome = B.snow;
    else if (temperature < 0.18) biome = B.tundra;
    else if (h > 175) biome = temperature < 0.4 ? B.snow : B.mountain;
    else if (h > 115) biome = B.hills;
    else if (h < 3.5 && touchesOcean(i)) biome = B.beach;
    else if (temperature < 0.35) biome = B.taiga;
    else if (moisture > 0.72 && h < 30 && !places.rivers.has(i))
      biome = B.wetland;
    else if (temperature > 0.72)
      biome = moisture < 0.5 ? B.savanna : B.broadleaf_forest;
    else biome = moisture > 0.55 ? B.broadleaf_forest : B.grassland;
    biomes[i] = biome;
  });
  return biomes;
}
