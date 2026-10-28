/*
 * Planet math for the globe contract (.runtime/briefs/globe-contract.md, later docs/plans): +Y north, metres,
 * cells as unit vectors with heights, the tangent frame, the gnomonic local <-> globe mapping of a site, and the
 * terrain lookup (which triangle is under a direction, and the rendered surface height there).
 */
import { Matrix4, Vector3 } from 'three';

import type { LocalMapping } from './local-mapping';
import { createSurface, type TerrainSurface } from './terrain-surface';
import type { Anchor, WorldView } from '@/lib/client/types.gen';

/** The rendered water surface above sea level: keeps beaches dry and shallows visibly under water. */
export const WATER_SURFACE = 0.2;

/** Not walkable: deep_ocean, shallow_ocean, lake. */
export const WATER_BIOMES: ReadonlySet<number> = new Set([0, 1, 13]);

const DEG = Math.PI / 180;
const Y_AXIS = new Vector3(0, 1, 0);
const Z_AXIS = new Vector3(0, 0, 1);
/** Below this |cross(Y, u)| the tangent frame takes east from Z instead (at the poles). */
const POLE_EPSILON = 1e-6;

// --- base64 typed arrays (little-endian) ---

export function decodeBase64(text: string): Uint8Array {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function encodeBase64(bytes: Uint8Array): string {
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK)
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  return btoa(binary);
}

export function float32FromBase64(text: string): Float32Array {
  const bytes = decodeBase64(text);
  const view = new DataView(bytes.buffer);
  const values = new Float32Array(bytes.length / 4);
  for (let i = 0; i < values.length; i++)
    values[i] = view.getFloat32(i * 4, true);
  return values;
}

export function uint32FromBase64(text: string): Uint32Array {
  const bytes = decodeBase64(text);
  const view = new DataView(bytes.buffer);
  const values = new Uint32Array(bytes.length / 4);
  for (let i = 0; i < values.length; i++)
    values[i] = view.getUint32(i * 4, true);
  return values;
}

export function float32ToBase64(values: ArrayLike<number>): string {
  const view = new DataView(new ArrayBuffer(values.length * 4));
  for (let i = 0; i < values.length; i++)
    view.setFloat32(i * 4, values[i], true);
  return encodeBase64(new Uint8Array(view.buffer));
}

export function uint32ToBase64(values: ArrayLike<number>): string {
  const view = new DataView(new ArrayBuffer(values.length * 4));
  for (let i = 0; i < values.length; i++)
    view.setUint32(i * 4, values[i], true);
  return encodeBase64(new Uint8Array(view.buffer));
}

/** The planet's grid: a WorldView's arrays, decoded. */
export interface Globe {
  radius: number;
  cellCount: number;
  /** Unit vectors, x y z per cell. */
  positions: Float32Array;
  heights: Float32Array;
  biomes: Uint8Array;
  /** Three cell indices per triangle, counter-clockwise from outside. */
  triangles: Uint32Array;
}

export function decodeWorld(view: WorldView): Globe {
  const globe: Globe = {
    radius: view.radius_m,
    cellCount: view.cell_count,
    positions: float32FromBase64(view.positions),
    heights: float32FromBase64(view.heights),
    biomes: decodeBase64(view.biomes),
    triangles: uint32FromBase64(view.triangles),
  };
  if (
    globe.positions.length !== view.cell_count * 3 ||
    globe.heights.length !== view.cell_count ||
    globe.biomes.length !== view.cell_count
  )
    throw new Error(`world arrays do not match cell_count ${view.cell_count}`);
  return globe;
}

export const cellDirection = (globe: Globe, cell: number, target: Vector3) =>
  target.fromArray(globe.positions, cell * 3);

// --- directions and frames ---

export function directionFromLatLon(
  latDeg: number,
  lonDeg: number,
  target = new Vector3(),
) {
  const lat = latDeg * DEG;
  const lon = lonDeg * DEG;
  return target.set(
    Math.cos(lat) * Math.sin(lon),
    Math.sin(lat),
    Math.cos(lat) * Math.cos(lon),
  );
}

/** Degrees; the direction need not be unit length. */
export function latLonFromDirection(direction: Vector3) {
  const { x, y, z } = direction;
  return {
    lat: Math.atan2(y, Math.hypot(x, z)) / DEG,
    lon: Math.atan2(x, z) / DEG,
  };
}

export interface TangentFrame {
  up: Vector3;
  east: Vector3;
  north: Vector3;
  south: Vector3;
}

/** Local axes at a unit direction: X = east, Y = up, Z = south (east × up = south). */
export function tangentFrame(direction: Vector3): TangentFrame {
  const up = direction.clone().normalize();
  const east = new Vector3().crossVectors(Y_AXIS, up);
  if (east.length() < POLE_EPSILON) east.crossVectors(Z_AXIS, up);
  east.normalize();
  const north = new Vector3().crossVectors(up, east);
  return { up, east, north, south: north.clone().negate() };
}

/** Projects a vector onto the tangent plane at unit `up` and normalizes it (to `fallback` if it degenerates). */
export function tangent(vector: Vector3, up: Vector3, fallback?: Vector3) {
  vector.addScaledVector(up, -vector.dot(up));
  if (vector.lengthSq() < 1e-12 && fallback) vector.copy(fallback);
  return vector.normalize();
}

// --- local metres <-> globe (gnomonic, one per site) ---

export interface SiteMapping extends LocalMapping {
  /** World point -> local metres; y is the height above the plateau. */
  toLocal(point: Vector3, target: Vector3): Vector3;
  /** Columns east', up', south' at the local point (x, z). */
  basis(x: number, z: number, target: Matrix4): Matrix4;
}

const scratch = {
  v: new Vector3(),
  east: new Vector3(),
  south: new Vector3(),
  yaw: new Matrix4(),
};

/**
 * The mapping of a site anchored at `up` with plateau radius `plateau` (R + h0): forward
 * v = up·plateau + east·x + south·z, u' = v / |v|, point = u'·(plateau + y); it inverts exactly.
 */
export function siteMapping(
  frame: Pick<TangentFrame, 'up' | 'east' | 'south'>,
  plateau: number,
): SiteMapping {
  const up = frame.up.clone();
  const east = frame.east.clone();
  const south = frame.south.clone();
  const direction = (x: number, z: number, target: Vector3) =>
    target
      .copy(up)
      .multiplyScalar(plateau)
      .addScaledVector(east, x)
      .addScaledVector(south, z)
      .normalize();

  const mapping: SiteMapping = {
    curved: true,
    toWorld: (x, y, z, target) =>
      direction(x, z, target).multiplyScalar(plateau + y),
    toLocal(point, target) {
      const v = scratch.v.copy(point).normalize();
      const t = plateau / v.dot(up);
      return target.set(
        t * v.dot(east),
        point.length() - plateau,
        t * v.dot(south),
      );
    },
    basis(x, z, target) {
      const upAt = direction(x, z, scratch.v);
      const eastAt = scratch.east
        .copy(east)
        .addScaledVector(upAt, -east.dot(upAt))
        .normalize();
      const southAt = scratch.south.crossVectors(eastAt, upAt);
      return target.makeBasis(eastAt, upAt, southAt);
    },
    matrix(x, y, z, yaw, target) {
      mapping.basis(x, z, target);
      target.multiply(scratch.yaw.makeRotationY(yaw));
      const position = mapping.toWorld(x, y, z, scratch.v);
      return target.setPosition(position);
    },
  };
  return mapping;
}

function anchorFrame(anchor: Anchor): TangentFrame {
  const north = new Vector3(...anchor.north);
  return {
    up: new Vector3(...anchor.position),
    east: new Vector3(...anchor.east),
    north,
    south: north.clone().negate(),
  };
}

export const anchorMapping = (anchor: Anchor, radius: number) =>
  siteMapping(anchorFrame(anchor), radius + anchor.height_m);

// --- terrain lookup ---

interface TerrainHit {
  /** Height above sea level of the rendered surface (the refined faces of terrain-surface.ts). */
  height: number;
  /** The grid triangle under the direction. */
  triangle: number;
  /** The cell nearest to the direction. */
  cell: number;
  /** 1 − cos(slope) of the rendered face: 0 on level ground. */
  tilt: number;
}

export interface GlobeTerrain {
  globe: Globe;
  /** The refined surface the terrain mesh draws and the lookups sample. */
  surface: TerrainSurface;
  /** Cells sharing a triangle edge with `cell`. */
  neighbours(cell: number): Uint32Array;
  /** Greedy walk over neighbours from `hint` (or the last answer) towards the direction. */
  nearestCell(direction: Vector3, hint?: number): number;
  /** The triangle under a direction and the rendered surface height there. */
  locate(direction: Vector3, hint?: number): TerrainHit;
  heightAt(direction: Vector3, hint?: number): number;
  /** Biome of the nearest cell. */
  biomeAt(direction: Vector3, hint?: number): number;
}

/** Compressed rows: items of row i are values[offsets[i] .. offsets[i + 1]). */
interface Rows {
  offsets: Uint32Array;
  values: Uint32Array;
}

function buildRows(lists: Iterable<number>[]): Rows {
  const arrays = lists.map((list) => [...list]);
  const offsets = new Uint32Array(arrays.length + 1);
  arrays.forEach((list, i) => (offsets[i + 1] = offsets[i] + list.length));
  const values = new Uint32Array(offsets[arrays.length]);
  arrays.forEach((list, i) => values.set(list, offsets[i]));
  return { offsets, values };
}

const row = (rows: Rows, index: number) =>
  rows.values.subarray(rows.offsets[index], rows.offsets[index + 1]);

/** A direction on a grid triangle's edge belongs to both triangles. */
const INSIDE_TOLERANCE = -1e-12;

export function buildTerrain(globe: Globe): GlobeTerrain {
  const { positions, biomes, triangles, cellCount, radius } = globe;
  const surface = createSurface(globe);
  const divisions = surface.divisions;
  const near: Set<number>[] = Array.from(
    { length: cellCount },
    () => new Set(),
  );
  const around: number[][] = Array.from({ length: cellCount }, () => []);
  for (let t = 0; t < triangles.length / 3; t++) {
    const [a, b, c] = triangles.subarray(t * 3, t * 3 + 3);
    near[a].add(b).add(c);
    near[b].add(a).add(c);
    near[c].add(a).add(b);
    around[a].push(t);
    around[b].push(t);
    around[c].push(t);
  }
  const neighbourRows = buildRows(near);
  const triangleRows = buildRows(around);
  let last = 0;

  const dotCell = (direction: Vector3, cell: number) =>
    direction.x * positions[cell * 3] +
    direction.y * positions[cell * 3 + 1] +
    direction.z * positions[cell * 3 + 2];

  function nearestCell(direction: Vector3, hint = last) {
    let cell = hint;
    let best = dotCell(direction, cell);
    for (;;) {
      let next = cell;
      for (const neighbour of row(neighbourRows, cell)) {
        const score = dotCell(direction, neighbour);
        if (score > best) {
          best = score;
          next = neighbour;
        }
      }
      if (next === cell) break;
      cell = next;
    }
    last = cell;
    return cell;
  }

  /** dir · (p × q) for cells p and q. */
  function spans(direction: Vector3, p: number, q: number) {
    const [px, py, pz] = [
      positions[p * 3],
      positions[p * 3 + 1],
      positions[p * 3 + 2],
    ];
    const [qx, qy, qz] = [
      positions[q * 3],
      positions[q * 3 + 1],
      positions[q * 3 + 2],
    ];
    return (
      direction.x * (py * qz - pz * qy) +
      direction.y * (pz * qx - px * qz) +
      direction.z * (px * qy - py * qx)
    );
  }

  /** Barycentric weights of the direction on triangle t's cone (A, B, C), or null when it passes outside. */
  const weights = [0, 0, 0];
  function inside(direction: Vector3, t: number) {
    const [a, b, c] = [
      triangles[t * 3],
      triangles[t * 3 + 1],
      triangles[t * 3 + 2],
    ];
    const w0 = spans(direction, b, c);
    const w1 = spans(direction, c, a);
    const w2 = spans(direction, a, b);
    const sum = w0 + w1 + w2;
    if (sum <= 0) return false;
    weights[0] = w0 / sum;
    weights[1] = w1 / sum;
    weights[2] = w2 / sum;
    return Math.min(...weights) >= INSIDE_TOLERANCE;
  }

  const face = new Float64Array(9);
  const e1 = new Vector3();
  const e2 = new Vector3();
  const normal = new Vector3();
  const origin = new Vector3();

  /** Height and tilt of the rendered face of triangle t that the direction passes through (weights set). */
  function hitFace(direction: Vector3, t: number) {
    const x = Math.max(weights[1], 0) * divisions;
    const y = Math.max(weights[2], 0) * divisions;
    const i = Math.min(Math.floor(x), divisions - 1);
    const j = Math.min(Math.floor(y), divisions - 1 - i);
    const upper = x - i + (y - j) > 1 && i + j < divisions - 1;
    const corners: [number, number][] = upper
      ? [
          [i + 1, j],
          [i + 1, j + 1],
          [i, j + 1],
        ]
      : [
          [i, j],
          [i + 1, j],
          [i, j + 1],
        ];
    corners.forEach(([ci, cj], k) => surface.vertex(t, ci, cj, face, k * 3));
    origin.fromArray(face, 0);
    e1.fromArray(face, 3).sub(origin);
    e2.fromArray(face, 6).sub(origin);
    normal.crossVectors(e1, e2);
    const distance = origin.dot(normal) / direction.dot(normal);
    return {
      height: distance - radius,
      tilt: 1 - Math.abs(normal.normalize().dot(direction)),
    };
  }

  const dir = new Vector3();

  function locate(direction: Vector3, hint?: number): TerrainHit {
    dir.copy(direction).normalize();
    const cell = nearestCell(dir, hint);
    const candidates = [cell, ...row(neighbourRows, cell)];
    for (const owner of candidates) {
      for (const t of row(triangleRows, owner)) {
        if (!inside(dir, t)) continue;
        return { ...hitFace(dir, t), triangle: t, cell };
      }
    }
    throw new Error('no terrain triangle under the direction');
  }

  return {
    globe,
    surface,
    neighbours: (cell) => row(neighbourRows, cell),
    nearestCell,
    locate,
    heightAt: (direction, hint) => locate(direction, hint).height,
    biomeAt: (direction, hint) => biomes[nearestCell(direction, hint)],
  };
}
