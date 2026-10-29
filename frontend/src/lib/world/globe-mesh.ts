/*
 * Geometry for the planet's ground: the refined surface of terrain-surface.ts with, per vertex, its grass tint
 * (the vertex colour, blended from its cells' biomes) and its 8 ground layer weights for the ground shader
 * (ground-shader.ts; the water on it is water-mesh.ts).
 */
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  InterleavedBuffer,
  InterleavedBufferAttribute,
  Vector3,
} from 'three';

import { type GlobeTerrain, WATER_BIOMES, WATER_SURFACE } from './globe';
import {
  GROUND_LAYERS,
  type GroundLayer,
  type GroundWeights,
} from './ground-shader';
import { biomeColor } from './ground-style';

export { biomeColor };

/** Small deterministic per-cell brightness jitter, blended across the cell like its colour. */
function jitter(index: number) {
  let h = Math.imul(index + 1, 0x27d4eb2d);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  return (((h ^ (h >>> 13)) >>> 0) / 4294967296) * 2 - 1;
}

/** Sand fades in below this height above the sea (a beach) or above a lake's surface (a shore). */
const BEACH_TOP = 2.5;
const LAKE_SHORE_TOP = 1.5;
/** The sea floor turns from sand to mud between these depths. */
const SEA_SAND_FLOOR: [number, number] = [-1.5, -8];
/** A face corner this close to a lake's surface is the lake's water. */
const LAKE_LEVEL_TOLERANCE = 0.02;
/** A land cell's colour counts this many times its land neighbours' colours each, so biomes fade over a cell. */
const OWN_COLOR_WEIGHT = 3;

/** Rock takes over between these slopes (degrees); snow slides off between the second pair. */
const ROCK_SLOPE: [number, number] = [28, 40];
const SNOW_SLIDES: [number, number] = [35, 50];
/** Snow settles on any ground between these heights (metres). */
const SNOW_LINE: [number, number] = [220, 260];

/** What each biome lays on its ground besides grass (bible §5.1); snow, rock and sand claim first. */
const BIOME_GROUND: Record<string, GroundWeights> = {
  beach: { sand: 0.6 },
  broadleaf_forest: { forest_floor: 0.7 },
  taiga: { forest_floor: 0.7 },
  wetland: { mud: 0.6 },
  hills: { gravel: 0.25 },
  mountain: { rock: 0.5 },
  savanna: { dirt: 0.3 },
  tundra: { gravel: 0.4 },
  snow: { snow: 1 },
  ice: { snow: 1 },
  volcanic: { gravel: 0.6 },
};

const LAYER = Object.fromEntries(
  GROUND_LAYERS.map((layer, index) => [layer, index]),
) as Record<GroundLayer, number>;

const smoothstep = (edge0: number, edge1: number, x: number) => {
  const t = Math.min(Math.max((x - edge0) / (edge1 - edge0), 0), 1);
  return t * t * (3 - 2 * t);
};

/** Where a ground point lies: what its biomes claim (8 layers, blended by area), slope, height and lake. */
export interface GroundPoint {
  claims: ArrayLike<number>;
  /** Degrees from level. */
  slope: number;
  /** Metres above sea level. */
  height: number;
  /** Surface height of a lake touching the point (Infinity: none). */
  lakeLevel: number;
}

/**
 * The 8 layer weights of a ground point (GROUND_LAYERS order, summing to 1) into `out` at `offset`. Under the sea
 * the floor is sand turning to mud with depth, a lake's bed is mud. On land snow claims first (snow biomes and
 * above the snow line, off steep slopes), then rock (steep slopes, mountains), then sand (a band above the sea and
 * the lakes, beaches), then the biome's own layers share the rest with grass.
 */
export function groundWeights(
  { claims, slope, height, lakeLevel }: GroundPoint,
  out: Float32Array | Float64Array | number[],
  offset = 0,
) {
  for (let k = 0; k < GROUND_LAYERS.length; k++) out[offset + k] = 0;
  if (lakeLevel < Infinity && height <= lakeLevel + LAKE_LEVEL_TOLERANCE) {
    out[offset + LAYER.mud] = 1;
    return;
  }
  if (height <= WATER_SURFACE) {
    const sand = 1 - smoothstep(SEA_SAND_FLOOR[0], SEA_SAND_FLOOR[1], height);
    out[offset + LAYER.sand] = sand;
    out[offset + LAYER.mud] = 1 - sand;
    return;
  }
  const snow =
    Math.min(1, claims[LAYER.snow] + smoothstep(...SNOW_LINE, height)) *
    (1 - smoothstep(...SNOW_SLIDES, slope));
  const rock =
    Math.min(1, claims[LAYER.rock] + smoothstep(...ROCK_SLOPE, slope)) *
    (1 - snow);
  const band = Math.max(
    smoothstep(BEACH_TOP, WATER_SURFACE, height),
    lakeLevel < Infinity
      ? smoothstep(lakeLevel + LAKE_SHORE_TOP, lakeLevel, height)
      : 0,
  );
  const sand = Math.min(1, claims[LAYER.sand] + band) * (1 - snow - rock);
  const rest = 1 - snow - rock - sand;
  let grass = rest;
  for (const layer of ['forest_floor', 'dirt', 'gravel', 'mud'] as const) {
    const weight = claims[LAYER[layer]] * rest;
    out[offset + LAYER[layer]] = weight;
    grass -= weight;
  }
  out[offset + LAYER.snow] = snow;
  out[offset + LAYER.rock] = rock;
  out[offset + LAYER.sand] = sand;
  out[offset + LAYER.grass] = Math.max(0, grass);
}

const remainders = new Float64Array(GROUND_LAYERS.length);

/** Weights as bytes summing to exactly 255 (the largest remainders round up). */
function quantize(weights: ArrayLike<number>, out: Uint8Array, offset: number) {
  const count = weights.length;
  let total = 0;
  for (let k = 0; k < count; k++) total += weights[k];
  let left = 255;
  for (let k = 0; k < count; k++) {
    const exact = (weights[k] / total) * 255;
    out[offset + k] = Math.floor(exact);
    left -= out[offset + k];
    remainders[k] = exact - out[offset + k];
  }
  for (; left > 0; left--) {
    let largest = 0;
    for (let k = 1; k < count; k++)
      if (remainders[k] > remainders[largest]) largest = k;
    out[offset + largest] += 1;
    remainders[largest] = -1;
  }
}

/** Per vertex: the slope (degrees) of the area-weighted normal of the faces around it. */
function vertexSlopes(vertices: Float32Array, index: Uint32Array) {
  const sums = new Float64Array(vertices.length);
  const a = new Vector3();
  const b = new Vector3();
  const c = new Vector3();
  for (let f = 0; f < index.length; f += 3) {
    a.fromArray(vertices, index[f] * 3);
    b.fromArray(vertices, index[f + 1] * 3).sub(a);
    c.fromArray(vertices, index[f + 2] * 3).sub(a);
    b.cross(c);
    for (let k = 0; k < 3; k++) {
      const v = index[f + k] * 3;
      sums[v] += b.x;
      sums[v + 1] += b.y;
      sums[v + 2] += b.z;
    }
  }
  const slopes = new Float32Array(vertices.length / 3);
  for (let v = 0; v < slopes.length; v++) {
    a.fromArray(sums, v * 3).normalize();
    b.fromArray(vertices, v * 3).normalize();
    slopes[v] = (Math.acos(Math.min(1, a.dot(b))) * 180) / Math.PI;
  }
  return slopes;
}

/** Four of each vertex's 8 layer bytes, read as 0..1. */
const interleavedLayers = (layers: Uint8Array, offset: number) =>
  new InterleavedBufferAttribute(
    new InterleavedBuffer(layers, 8),
    4,
    offset,
    true,
  );

/** Per cell: the area-weighted normal of the grid triangles around it (through the lifted cell points). */
function gridNormals({ globe }: GlobeTerrain) {
  const { positions, heights, triangles, cellCount, radius } = globe;
  const normals = new Float64Array(cellCount * 3);
  const corner = [new Vector3(), new Vector3(), new Vector3()];
  const face = new Vector3();
  const edge = new Vector3();
  for (let t = 0; t < triangles.length / 3; t++) {
    for (let k = 0; k < 3; k++) {
      const cell = triangles[t * 3 + k];
      corner[k]
        .fromArray(positions, cell * 3)
        .multiplyScalar(radius + heights[cell]);
    }
    face
      .subVectors(corner[1], corner[0])
      .cross(edge.subVectors(corner[2], corner[0]));
    for (let k = 0; k < 3; k++) {
      const cell = triangles[t * 3 + k] * 3;
      normals[cell] += face.x;
      normals[cell + 1] += face.y;
      normals[cell + 2] += face.z;
    }
  }
  return normals;
}

/**
 * The terrain mesh: every grid triangle split into the refined faces of `terrain.surface` (indexed, so the
 * corners are shared and the normals smooth). The vertex colour is the grass tint, blended from the corners'
 * biomes across cell borders; `ground0`/`ground1` hold the 8 layer weights (groundWeights over the corners'
 * biome claims and the slope of the faces around the vertex). A corner on a lake's surface is the lake's bed
 * (lakes lie above the sea, flat at their surface height). A corner on a grid edge only reads the edge's two
 * cells, so both triangles agree on it.
 */
export function terrainGeometry(
  terrain: GlobeTerrain,
  biomeNames: readonly string[],
) {
  const { globe, surface } = terrain;
  const { heights, biomes, triangles, cellCount } = globe;
  const { divisions: n, edgeCount, triangleEdges, edgeCells } = surface;
  const palette = biomeNames.map((name) => new Color(biomeColor(name)));
  const biomeClaims = biomeNames.map((name) =>
    GROUND_LAYERS.map((layer) => BIOME_GROUND[name]?.[layer] ?? 0),
  );
  // each land cell's colour softened towards its land neighbours', so no cell shows as a patch
  const cellColors = Array.from({ length: cellCount }, (_, cell) => {
    const own = palette[biomes[cell]];
    if (WATER_BIOMES.has(biomes[cell])) return own;
    const mixed = own.clone().multiplyScalar(OWN_COLOR_WEIGHT);
    let total = OWN_COLOR_WEIGHT;
    for (const neighbour of terrain.neighbours(cell)) {
      if (WATER_BIOMES.has(biomes[neighbour])) continue;
      mixed.add(palette[biomes[neighbour]]);
      total += 1;
    }
    return mixed.multiplyScalar(1 / total);
  });
  const sand = new Color(biomeColor('beach'));
  const lake = biomeNames.indexOf('lake');
  const triangleCount = triangles.length / 3;
  const interior = ((n - 1) * (n - 2)) / 2;
  const edgeBase = cellCount;
  const faceBase = cellCount + edgeCount * (n - 1);
  const vertexCount = faceBase + triangleCount * interior;
  const vertices = new Float32Array(vertexCount * 3);
  const colors = new Float32Array(vertexCount * 3);
  const normals = new Float32Array(vertexCount * 3);
  const layers = new Uint8Array(vertexCount * 8);
  const cellNormals = gridNormals(terrain);
  const done = new Uint8Array(vertexCount);
  const color = new Color();
  const part = new Color();
  const position = new Float64Array(3);
  const point = {
    claims: new Float64Array(GROUND_LAYERS.length),
    slope: 0,
    height: 0,
    lakeLevel: Infinity,
  };
  const weights = new Float64Array(GROUND_LAYERS.length);

  /** Vertex id of lattice point (i, j) of triangle t (weights (n − i − j, i, j) / n on A, B, C). */
  function vertexId(t: number, i: number, j: number) {
    const k = n - i - j;
    const corners = triangles.subarray(t * 3, t * 3 + 3);
    if (i === 0 && j === 0) return corners[0];
    if (i === n) return corners[1];
    if (j === n) return corners[2];
    // steps from the edge's first corner (A on AB, B on BC, C on CA) and the edge id
    const onEdge = (side: number, step: number) => {
      const edge = triangleEdges[t * 3 + side];
      const from = edgeCells[edge * 2] === corners[side] ? step : n - step;
      return edgeBase + edge * (n - 1) + from - 1;
    };
    if (j === 0) return onEdge(0, i);
    if (k === 0) return onEdge(1, j);
    if (i === 0) return onEdge(2, n - j);
    // interior points in rows j = 1 .. n − 2, i = 1 .. n − 1 − j
    let index = 0;
    for (let row = 1; row < j; row++) index += n - 1 - row;
    return faceBase + t * interior + index + i - 1;
  }

  /** The grass tint of lattice point (i, j) of triangle t: its land corners' colours, a little cell noise. */
  function paint(t: number, i: number, j: number, offset: number) {
    const corners = triangles.subarray(t * 3, t * 3 + 3);
    const weights = [n - i - j, i, j].map((w) => w / n);
    const height = surface.height(t, weights[0], weights[1], weights[2]);
    let total = 0;
    let shade = 0;
    color.setRGB(0, 0, 0);
    corners.forEach((cell, k) => {
      if (weights[k] <= 0 || WATER_BIOMES.has(biomes[cell])) return;
      color.add(part.copy(cellColors[cell]).multiplyScalar(weights[k]));
      shade += jitter(cell) * weights[k];
      total += weights[k];
    });
    if (total > 0) color.multiplyScalar(1 / total);
    else color.copy(sand);
    // higher land a touch lighter, plus a little noise per cell
    color.multiplyScalar(
      1 + (total > 0 ? (shade / total) * 0.04 : 0) + Math.max(0, height) / 1500,
    );
    color.toArray(colors, offset);
  }

  /** The ground point of lattice point (i, j) of triangle t: its land corners' claims, height and lake. */
  function locate(t: number, i: number, j: number, slope: number) {
    const corners = triangles.subarray(t * 3, t * 3 + 3);
    const shares = [n - i - j, i, j];
    point.claims.fill(0);
    point.lakeLevel = Infinity;
    point.height = surface.height(
      t,
      shares[0] / n,
      shares[1] / n,
      shares[2] / n,
    );
    point.slope = slope;
    let total = 0;
    corners.forEach((cell, k) => {
      if (shares[k] <= 0) return;
      if (biomes[cell] === lake)
        point.lakeLevel = Math.min(point.lakeLevel, heights[cell]);
      if (WATER_BIOMES.has(biomes[cell])) return;
      const claims = biomeClaims[biomes[cell]];
      for (let l = 0; l < claims.length; l++)
        point.claims[l] += claims[l] * shares[k];
      total += shares[k];
    });
    if (total > 0)
      for (let l = 0; l < point.claims.length; l++) point.claims[l] /= total;
    return point;
  }

  /** Shading follows the grid's cell normals, blended like the colours: smooth over the patches' seams. */
  function blendNormal(t: number, i: number, j: number, offset: number) {
    const weights = [n - i - j, i, j];
    let [x, y, z] = [0, 0, 0];
    for (let k = 0; k < 3; k++) {
      const cell = triangles[t * 3 + k] * 3;
      x += weights[k] * cellNormals[cell];
      y += weights[k] * cellNormals[cell + 1];
      z += weights[k] * cellNormals[cell + 2];
    }
    const length = Math.hypot(x, y, z);
    normals[offset] = x / length;
    normals[offset + 1] = y / length;
    normals[offset + 2] = z / length;
  }

  const index = new Uint32Array(triangleCount * n * n * 3);
  let cursor = 0;
  const ids: number[] = [];
  for (let t = 0; t < triangleCount; t++) {
    ids.length = 0;
    for (let j = 0; j <= n; j++)
      for (let i = 0; i + j <= n; i++) {
        const id = vertexId(t, i, j);
        ids.push(id);
        if (done[id]) continue;
        done[id] = 1;
        surface.vertex(t, i, j, position, 0);
        vertices.set(position, id * 3);
        paint(t, i, j, id * 3);
        blendNormal(t, i, j, id * 3);
      }
    // lattice rows: point (i, j) is ids[rowStart(j) + i]
    let rowStart = 0;
    for (let j = 0; j < n; j++) {
      const next = rowStart + n - j + 1;
      for (let i = 0; i + j < n; i++) {
        const p = ids[rowStart + i];
        const right = ids[rowStart + i + 1];
        const up = ids[next + i];
        index.set([p, right, up], cursor);
        cursor += 3;
        if (i + j < n - 1) {
          index.set([right, ids[next + i + 1], up], cursor);
          cursor += 3;
        }
      }
      rowStart = next;
    }
  }
  const slopes = vertexSlopes(vertices, index);
  done.fill(0);
  for (let t = 0; t < triangleCount; t++)
    for (let j = 0; j <= n; j++)
      for (let i = 0; i + j <= n; i++) {
        const id = vertexId(t, i, j);
        if (done[id]) continue;
        done[id] = 1;
        groundWeights(locate(t, i, j, slopes[id]), weights);
        quantize(weights, layers, id * 8);
      }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3));
  geometry.setAttribute('color', new Float32BufferAttribute(colors, 3));
  geometry.setAttribute('normal', new Float32BufferAttribute(normals, 3));
  geometry.setAttribute('ground0', interleavedLayers(layers, 0));
  geometry.setAttribute('ground1', interleavedLayers(layers, 4));
  geometry.setIndex(new BufferAttribute(index, 1));
  return geometry;
}
