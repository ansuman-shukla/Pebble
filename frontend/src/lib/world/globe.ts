/*
 * Planet math for the globe contract (.runtime/briefs/globe-contract.md, later docs/plans): +Y north, metres,
 * cells as unit vectors with heights, the tangent frame, the gnomonic local <-> globe mapping of a site, and the
 * terrain lookup (which triangle is under a direction, and the rendered surface height there).
 */
import { Matrix4, Vector3 } from 'three';

import type { LocalMapping } from './local-mapping';
import type { Anchor, WorldView } from './world-view';

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
  /** Height above sea level of the rendered surface (flat triangles through u·(R + h) corners). */
  height: number;
  triangle: number;
  /** The cell nearest to the direction. */
  cell: number;
  /** 1 − cos(slope) of the triangle: 0 on level ground. */
  tilt: number;
}

export interface GlobeTerrain {
  globe: Globe;
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

const BARY_EPSILON = 1e-9;

export function buildTerrain(globe: Globe): GlobeTerrain {
  const { positions, heights, biomes, triangles, cellCount, radius } = globe;
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

  const corner = [new Vector3(), new Vector3(), new Vector3()];
  const e1 = new Vector3();
  const e2 = new Vector3();
  const p = new Vector3();
  const q = new Vector3();

  /** Distance along the unit direction to the triangle's plane if the ray passes inside it, else null. */
  function hitTriangle(direction: Vector3, t: number): number | null {
    for (let k = 0; k < 3; k++) {
      const cell = triangles[t * 3 + k];
      corner[k]
        .fromArray(positions, cell * 3)
        .multiplyScalar(radius + heights[cell]);
    }
    e1.subVectors(corner[1], corner[0]);
    e2.subVectors(corner[2], corner[0]);
    p.crossVectors(direction, e2);
    const det = e1.dot(p);
    if (Math.abs(det) < BARY_EPSILON) return null;
    const toOrigin = corner[0].negate();
    const u = toOrigin.dot(p) / det;
    q.crossVectors(toOrigin, e1);
    const v = direction.dot(q) / det;
    const tolerance = 1e-7;
    if (u < -tolerance || v < -tolerance || u + v > 1 + tolerance) return null;
    const distance = e2.dot(q) / det;
    return distance > 0 ? distance : null;
  }

  const dir = new Vector3();

  function locate(direction: Vector3, hint?: number): TerrainHit {
    dir.copy(direction).normalize();
    const cell = nearestCell(dir, hint);
    const candidates = [cell, ...row(neighbourRows, cell)];
    for (const owner of candidates) {
      for (const t of row(triangleRows, owner)) {
        const distance = hitTriangle(dir, t);
        if (distance === null) continue;
        const tilt = 1 - p.crossVectors(e1, e2).normalize().dot(dir);
        return { height: distance - radius, triangle: t, cell, tilt };
      }
    }
    throw new Error('no terrain triangle under the direction');
  }

  return {
    globe,
    neighbours: (cell) => row(neighbourRows, cell),
    nearestCell,
    locate,
    heightAt: (direction, hint) => locate(direction, hint).height,
    biomeAt: (direction, hint) => biomes[nearestCell(direction, hint)],
  };
}
