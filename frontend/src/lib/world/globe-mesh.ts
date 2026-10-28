/*
 * Geometry for the planet: the terrain (the refined surface of terrain-surface.ts, coloured by blending its
 * cells' biomes) and the rivers (ribbons that follow the terrain along their cell paths).
 */
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  Vector3,
} from 'three';

import {
  cellDirection,
  type GlobeTerrain,
  WATER_BIOMES,
  WATER_SURFACE,
} from './globe';

const BIOME_COLORS: Record<string, string> = {
  deep_ocean: '#24405e',
  shallow_ocean: '#5f9c9e',
  beach: '#e6d6a2',
  grassland: '#93b55c',
  broadleaf_forest: '#4f8a3c',
  taiga: '#3e6a4c',
  wetland: '#6f8c5c',
  hills: '#9c9a62',
  mountain: '#8b847a',
  savanna: '#c6b264',
  tundra: '#a9a892',
  snow: '#f1f4f6',
  ice: '#d9ebf4',
  lake: '#5f9c9e',
  volcanic: '#5e5450',
};
const FALLBACK_COLOR = '#ff00ff';
/** Lakes are terrain faces flat at their surface height, drawn the colour the sea shows near its shores. */
const LAKE_WATER = '#4284b0';
/** How far a dry face touching water turns to sand: a sea beach, a lake shore. */
const BEACH_SAND = 0.6;
const LAKE_SHORE_SAND = 0.25;

/** The terrain colour of a biome (by name, so the client never depends on the id order). */
export const biomeColor = (name: string) =>
  BIOME_COLORS[name] ?? FALLBACK_COLOR;

/** Small deterministic per-cell brightness jitter, blended across the cell like its colour. */
function jitter(index: number) {
  let h = Math.imul(index + 1, 0x27d4eb2d);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  return (((h ^ (h >>> 13)) >>> 0) / 4294967296) * 2 - 1;
}

/** Sand fades in below this height above the sea (a beach) or above a lake's surface (a shore). */
const BEACH_TOP = 2.5;
const LAKE_SHORE_TOP = 1.5;
/** Sea floor colour fades from the shallows to the deep over this depth. */
const DEEP_FLOOR = -40;
/** A face corner this close to a lake's surface is the lake's water. */
const LAKE_LEVEL_TOLERANCE = 0.02;
/** A land cell's colour counts this many times its land neighbours' colours each, so biomes fade over a cell. */
const OWN_COLOR_WEIGHT = 3;

const smoothstep = (edge0: number, edge1: number, x: number) => {
  const t = Math.min(Math.max((x - edge0) / (edge1 - edge0), 0), 1);
  return t * t * (3 - 2 * t);
};

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
 * corners are shared and the normals smooth). Colours blend the corners' biomes across cell borders; the
 * ground under the sea fades from sand at the waterline to the deep floor; a corner on a lake's surface is the
 * lake's water (lakes lie above the sea, flat at their surface height); sand fades in just above the sea and
 * a lake's surface. A corner on a grid edge only reads the edge's two cells, so both triangles agree on it.
 */
export function terrainGeometry(
  terrain: GlobeTerrain,
  biomeNames: readonly string[],
) {
  const { globe, surface } = terrain;
  const { heights, biomes, triangles, cellCount } = globe;
  const { divisions: n, edgeCount, triangleEdges, edgeCells } = surface;
  const palette = biomeNames.map((name) => new Color(biomeColor(name)));
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
  const shallows = new Color(biomeColor('shallow_ocean'));
  const deep = new Color(biomeColor('deep_ocean'));
  const lakeWater = new Color(LAKE_WATER);
  const lake = biomeNames.indexOf('lake');
  const triangleCount = triangles.length / 3;
  const interior = ((n - 1) * (n - 2)) / 2;
  const edgeBase = cellCount;
  const faceBase = cellCount + edgeCount * (n - 1);
  const vertexCount = faceBase + triangleCount * interior;
  const vertices = new Float32Array(vertexCount * 3);
  const colors = new Float32Array(vertexCount * 3);
  const normals = new Float32Array(vertexCount * 3);
  const cellNormals = gridNormals(terrain);
  const done = new Uint8Array(vertexCount);
  const color = new Color();
  const part = new Color();
  const position = new Float64Array(3);

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

  function paint(t: number, i: number, j: number, offset: number) {
    const corners = triangles.subarray(t * 3, t * 3 + 3);
    const weights = [n - i - j, i, j].map((w) => w / n);
    const height = surface.height(t, weights[0], weights[1], weights[2]);
    let lakeLevel = Infinity;
    let total = 0;
    let shade = 0;
    color.setRGB(0, 0, 0);
    corners.forEach((cell, k) => {
      if (weights[k] <= 0) return;
      if (biomes[cell] === lake) lakeLevel = Math.min(lakeLevel, heights[cell]);
      if (WATER_BIOMES.has(biomes[cell])) return;
      const weight = weights[k];
      color.add(part.copy(cellColors[cell]).multiplyScalar(weight));
      shade += jitter(cell) * weight;
      total += weight;
    });
    if (height <= WATER_SURFACE) {
      color
        .copy(shallows)
        .lerp(deep, smoothstep(WATER_SURFACE, DEEP_FLOOR, height))
        .lerp(sand, smoothstep(-1.5, WATER_SURFACE, height) * BEACH_SAND);
    } else if (
      lakeLevel < Infinity &&
      height <= lakeLevel + LAKE_LEVEL_TOLERANCE
    ) {
      color.copy(lakeWater);
    } else {
      if (total > 0) color.multiplyScalar(1 / total);
      else color.copy(sand);
      color.lerp(
        sand,
        smoothstep(BEACH_TOP, WATER_SURFACE, height) * BEACH_SAND,
      );
      if (lakeLevel < Infinity)
        color.lerp(
          sand,
          smoothstep(lakeLevel + LAKE_SHORE_TOP, lakeLevel, height) *
            LAKE_SHORE_SAND,
        );
      // higher land a touch lighter, plus a little noise per cell
      color.multiplyScalar(
        1 +
          (total > 0 ? (shade / total) * 0.04 : 0) +
          Math.max(0, height) / 1500,
      );
    }
    color.toArray(colors, offset);
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
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3));
  geometry.setAttribute('color', new Float32BufferAttribute(colors, 3));
  geometry.setAttribute('normal', new Float32BufferAttribute(normals, 3));
  geometry.setIndex(new BufferAttribute(index, 1));
  return geometry;
}

const RIVER_WIDTH = 6;
const RIVER_LIFT = 0.35;
const RIVER_STEPS = 4;

/** Shore points are found to this many halvings of a path step (10 m / 2⁸ ≈ 4 cm). */
const SHORE_REFINE = 8;

/**
 * Ribbons along each river's cell path, sampled several times per cell and lifted just above the ground. A
 * ribbon stops at the shore where the river reaches the sea or a lake (and starts again where it leaves one),
 * so it never lies over water.
 */
export function riverGeometry(terrain: GlobeTerrain, rivers: number[][]) {
  const { globe } = terrain;
  const { radius } = globe;
  const vertices: number[] = [];
  const surface = (direction: Vector3, hint: number) =>
    direction
      .clone()
      .multiplyScalar(
        radius + Math.max(terrain.heightAt(direction, hint), 0) + RIVER_LIFT,
      );
  const wet = (direction: Vector3, hint: number) =>
    WATER_BIOMES.has(terrain.biomeAt(direction, hint)) ||
    terrain.heightAt(direction, hint) <= WATER_SURFACE;
  /** The shore between a dry and a wet point (by bisection), on the dry side. */
  const shore = (dry: Vector3, water: Vector3, hint: number) => {
    let [low, high] = [dry, water];
    for (let k = 0; k < SHORE_REFINE; k++) {
      const middle = low.clone().lerp(high, 0.5).normalize();
      if (wet(middle, hint)) high = middle;
      else low = middle;
    }
    return low;
  };
  type PathPoint = { direction: Vector3; cell: number };

  function ribbon(path: PathPoint[]) {
    if (path.length < 2) return;
    const edges = path.map(({ direction, cell }, i) => {
      const ahead = path[Math.min(i + 1, path.length - 1)].direction;
      const behind = path[Math.max(i - 1, 0)].direction;
      const side = new Vector3()
        .subVectors(ahead, behind)
        .cross(direction)
        .normalize()
        .multiplyScalar(RIVER_WIDTH / 2 / radius);
      return [
        surface(direction.clone().add(side).normalize(), cell),
        surface(direction.clone().sub(side).normalize(), cell),
      ];
    });
    for (let i = 0; i + 1 < edges.length; i++) {
      const [a, b] = edges[i];
      const [c, d] = edges[i + 1];
      // a and c are on the right bank: counter-clockwise seen from above
      vertices.push(...a.toArray(), ...c.toArray(), ...b.toArray());
      vertices.push(...c.toArray(), ...d.toArray(), ...b.toArray());
    }
  }

  for (const cells of rivers) {
    if (cells.length < 2) continue;
    const path: PathPoint[] = [];
    for (let i = 0; i + 1 < cells.length; i++) {
      const a = cellDirection(globe, cells[i], new Vector3());
      const b = cellDirection(globe, cells[i + 1], new Vector3());
      for (let s = 0; s < RIVER_STEPS; s++)
        path.push({
          direction: a
            .clone()
            .lerp(b, s / RIVER_STEPS)
            .normalize(),
          cell: cells[i],
        });
    }
    const last = cells[cells.length - 1];
    path.push({
      direction: cellDirection(globe, last, new Vector3()),
      cell: last,
    });
    // split the path into its dry runs, each ending exactly at the shore
    let run: PathPoint[] = [];
    path.forEach((point, i) => {
      const previous = path[i - 1];
      if (wet(point.direction, point.cell)) {
        if (run.length > 0)
          run.push({
            direction: shore(previous.direction, point.direction, point.cell),
            cell: point.cell,
          });
        ribbon(run);
        run = [];
        return;
      }
      if (run.length === 0 && previous)
        run.push({
          direction: shore(point.direction, previous.direction, point.cell),
          cell: point.cell,
        });
      run.push(point);
    });
    ribbon(run);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3));
  geometry.computeVertexNormals();
  return geometry;
}
