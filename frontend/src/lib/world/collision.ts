/*
 * 2D walking collisions on the flat town ground. Polyfork colliders (convex hulls in model space) are placed,
 * flattened to convex polygons on the ground (x, z) and keep their y-range: a part blocks the player only where
 * it overlaps the body band, so roofs, canopies and gate lintels never block. Water blocks unless a walkable
 * surface (a bridge) covers it.
 */
import { assetBaseY, kindScale, PROPS, type PropKind } from './assets';
import { openDoorParts } from './doors';

/** A ground point (x, z) in metres. */
export type Point = [number, number];
export type ColliderPart = [number, number, number][];
export interface ColliderFile {
  id: string;
  parts: ColliderPart[];
}

export interface WalkPlacement {
  id: string;
  kind: string;
  x: number;
  z: number;
  rotation_deg: 0 | 90 | 180 | 270;
  walk: 'solid' | 'surface' | 'none';
}
export interface WalkSpawn {
  x: number;
  z: number;
  heading_deg: number;
}
export interface WalkWater {
  polygon: Point[];
  holes?: Point[][];
}

interface Box {
  minX: number;
  minZ: number;
  maxX: number;
  maxZ: number;
}

/** One placed collider part: a convex ground polygon (counter-clockwise in x, z) with its height range. */
export interface Shape {
  placementId: string;
  polygon: Point[];
  minY: number;
  maxY: number;
  box: Box;
}

const PLAYER_RADIUS = 0.3;
/** Heights above the player's ground that the body occupies: lower parts are stepped over, higher ones walked under. */
const BODY_BAND: [number, number] = [0.3, 1.7];
/** Longest move resolved at once; keeps a fast player from tunnelling through thin parts. */
const MAX_SUBSTEP = PLAYER_RADIUS / 2;
const PUSH_ITERATIONS = 4;
const GRID_CELL = 4;
const EPSILON = 1e-9;

export function assetIdForKind(kind: string) {
  if (!Object.hasOwn(PROPS, kind)) throw new Error(`unknown prop kind ${kind}`);
  return PROPS[kind as PropKind];
}

/** Asset ids whose colliders a placement set needs (solid and surface placements). */
export const colliderIdsOf = (placements: WalkPlacement[]) =>
  placements
    .filter((placement) => placement.walk !== 'none')
    .map((placement) => assetIdForKind(placement.kind));

const cross = (o: Point, a: Point, b: Point) =>
  (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

/** Convex hull (Andrew's monotone chain), counter-clockwise, without collinear points. */
function convexHull(points: Point[]): Point[] {
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (sorted.length < 3) return sorted;
  const half = (input: Point[]) => {
    const chain: Point[] = [];
    for (const point of input) {
      while (
        chain.length >= 2 &&
        cross(chain[chain.length - 2], chain[chain.length - 1], point) <= 0
      )
        chain.pop();
      chain.push(point);
    }
    chain.pop();
    return chain;
  };
  return [...half(sorted), ...half([...sorted].reverse())];
}

function boxOf(polygon: Point[]): Box {
  const xs = polygon.map(([x]) => x);
  const zs = polygon.map(([, z]) => z);
  return {
    minX: Math.min(...xs),
    minZ: Math.min(...zs),
    maxX: Math.max(...xs),
    maxZ: Math.max(...zs),
  };
}

/** Collider parts moved by `place` (model space -> local metres), flattened to ground polygons with y-ranges. */
export function shapesOf(
  placementId: string,
  parts: ColliderPart[],
  place: (vertex: [number, number, number]) => [number, number, number],
): Shape[] {
  return parts.map((part) => {
    const placed = part.map(place);
    const polygon = convexHull(placed.map(([x, , z]) => [x, z]));
    const ys = placed.map(([, y]) => y);
    return {
      placementId,
      polygon,
      minY: Math.min(...ys),
      maxY: Math.max(...ys),
      box: boxOf(polygon),
    };
  });
}

/**
 * Places collider parts like three.js would place the model: uniform scale, rotation.y = deg·π/180, then
 * translation to (x, baseY, z).
 */
export function placeParts(
  placement: WalkPlacement,
  parts: ColliderPart[],
  baseY = 0,
  scale = 1,
): Shape[] {
  const angle = (placement.rotation_deg * Math.PI) / 180;
  const cos = Math.cos(angle) * scale;
  const sin = Math.sin(angle) * scale;
  return shapesOf(placement.id, parts, ([x, y, z]) => [
    placement.x + x * cos + z * sin,
    baseY + y * scale,
    placement.z - x * sin + z * cos,
  ]);
}

/** A standing cylinder (as a 12-sided prism), e.g. a person. */
export function circleShape(
  placementId: string,
  [x, z]: Point,
  radius: number,
  minY: number,
  maxY: number,
): Shape {
  const polygon = Array.from({ length: 12 }, (_, i): Point => {
    const angle = (i / 12) * Math.PI * 2;
    return [x + Math.cos(angle) * radius, z + Math.sin(angle) * radius];
  });
  return { placementId, polygon, minY, maxY, box: boxOf(polygon) };
}

/** Uniform grid over shape bounding boxes, for "what is near this point" queries. */
class ShapeGrid {
  private readonly cells = new Map<string, Shape[]>();

  constructor(shapes: Shape[]) {
    for (const shape of shapes) {
      this.forCells(shape.box, (key) => {
        const cell = this.cells.get(key);
        if (cell) cell.push(shape);
        else this.cells.set(key, [shape]);
      });
    }
  }

  near(box: Box): Shape[] {
    const found = new Set<Shape>();
    this.forCells(box, (key) => {
      for (const shape of this.cells.get(key) ?? []) found.add(shape);
    });
    return [...found];
  }

  private forCells(box: Box, visit: (key: string) => void) {
    const cell = (value: number) => Math.floor(value / GRID_CELL);
    for (let i = cell(box.minX); i <= cell(box.maxX); i++) {
      for (let j = cell(box.minZ); j <= cell(box.maxZ); j++) visit(`${i},${j}`);
    }
  }
}

export interface WalkWorld {
  blockers: ShapeGrid;
  surfaces: ShapeGrid;
  water: WalkWater[];
}

/** Extra local height of a placement's base (e.g. standing it on uneven terrain); 0 on flat ground. */
export type PlacementLift = (
  placement: Pick<WalkPlacement, 'x' | 'z'>,
) => number;

/**
 * Builds the collision world; `colliders` must hold the colliders file of every solid and surface asset.
 * Parts are placed like the rendered model: at assetBaseY plus `lift`, scaled by kindScale. `extra` adds
 * blockers that are not placements (e.g. scattered trees).
 */
export function buildWalkWorld(
  placements: WalkPlacement[],
  water: WalkWater[],
  colliders: ReadonlyMap<string, ColliderFile>,
  lift?: PlacementLift,
  extra: Shape[] = [],
): WalkWorld {
  const blockers: Shape[] = [...extra];
  const surfaces: Shape[] = [];
  for (const placement of placements) {
    const id = assetIdForKind(placement.kind);
    if (placement.walk === 'none') continue;
    const file = colliders.get(id);
    if (!file) throw new Error(`colliders for ${id} are not loaded`);
    const shapes = placeParts(
      placement,
      openDoorParts(id, file.parts),
      assetBaseY(id) + (lift?.(placement) ?? 0),
      kindScale(placement.kind),
    );
    (placement.walk === 'solid' ? blockers : surfaces).push(...shapes);
  }
  return {
    blockers: new ShapeGrid(blockers),
    surfaces: new ShapeGrid(surfaces),
    water,
  };
}

/** A collision world of blockers only (scattered props in the wild). */
export const blockerWorld = (blockers: Shape[]): WalkWorld => ({
  blockers: new ShapeGrid(blockers),
  surfaces: new ShapeGrid([]),
  water: [],
});

export const blocksBody = (shape: Shape, groundY: number) =>
  shape.maxY > groundY + BODY_BAND[0] && shape.minY < groundY + BODY_BAND[1];

/** Even-odd point in polygon test (any simple polygon). */
export function pointInPolygon([x, z]: Point, polygon: Point[]) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, zi] = polygon[i];
    const [xj, zj] = polygon[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi)
      inside = !inside;
  }
  return inside;
}

const pointBox = ([x, z]: Point, margin = 0): Box => ({
  minX: x - margin,
  minZ: z - margin,
  maxX: x + margin,
  maxZ: z + margin,
});

/** Walkable surfaces whose footprint holds the point. */
export const surfacesAt = (world: WalkWorld, point: Point) =>
  world.surfaces
    .near(pointBox(point))
    .filter((shape) => pointInPolygon(point, shape.polygon));

export function isWater(world: WalkWorld, point: Point) {
  const wet = world.water.some(
    (water) =>
      pointInPolygon(point, water.polygon) &&
      !(water.holes ?? []).some((hole) => pointInPolygon(point, hole)),
  );
  return wet && surfacesAt(world, point).length === 0;
}

function closestOnSegment(p: Point, a: Point, b: Point): Point {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const lengthSq = dx * dx + dz * dz;
  const t =
    lengthSq < EPSILON
      ? 0
      : Math.max(
          0,
          Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / lengthSq),
        );
  return [a[0] + t * dx, a[1] + t * dz];
}

/** Smallest displacement that moves a circle out of a convex polygon, or null if they don't overlap. */
function pushOutOfConvex(
  center: Point,
  radius: number,
  polygon: Point[],
): Point | null {
  if (polygon.length >= 3) {
    let deepest = -Infinity;
    let normal: Point = [0, 0];
    for (let i = 0; i < polygon.length; i++) {
      const a = polygon[i];
      const b = polygon[(i + 1) % polygon.length];
      const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const n: Point = [(b[1] - a[1]) / length, -(b[0] - a[0]) / length];
      const distance = (center[0] - a[0]) * n[0] + (center[1] - a[1]) * n[1];
      if (distance > deepest) {
        deepest = distance;
        normal = n;
      }
    }
    if (deepest <= 0) {
      const depth = radius - deepest;
      return [normal[0] * depth, normal[1] * depth];
    }
  }
  let closest: Point = polygon[0];
  let best = Infinity;
  for (let i = 0; i < polygon.length; i++) {
    const candidate = closestOnSegment(
      center,
      polygon[i],
      polygon[(i + 1) % polygon.length],
    );
    const distance = Math.hypot(
      center[0] - candidate[0],
      center[1] - candidate[1],
    );
    if (distance < best) {
      best = distance;
      closest = candidate;
    }
  }
  if (best >= radius || best < EPSILON) return null;
  const depth = (radius - best) / best;
  return [(center[0] - closest[0]) * depth, (center[1] - closest[1]) * depth];
}

/** Blockers near a point plus the moving ones (people). */
function blockersNear(
  world: WalkWorld,
  box: Box,
  dynamic: readonly Shape[],
): Shape[] {
  const near = world.blockers.near(box);
  for (const shape of dynamic) {
    const other = shape.box;
    if (
      other.maxX >= box.minX &&
      other.minX <= box.maxX &&
      other.maxZ >= box.minZ &&
      other.minZ <= box.maxZ
    )
      near.push(shape);
  }
  return near;
}

/** Moves a circle out of every blocker that `blocks` (by default: overlapping the body band above groundY). */
function pushOutOfBlockers(
  world: WalkWorld,
  point: Point,
  groundY: number,
  dynamic: readonly Shape[],
  radius = PLAYER_RADIUS,
  blocks = (shape: Shape) => blocksBody(shape, groundY),
): Point {
  let [x, z] = point;
  for (let iteration = 0; iteration < PUSH_ITERATIONS; iteration++) {
    let moved = false;
    for (const shape of blockersNear(
      world,
      pointBox([x, z], radius),
      dynamic,
    )) {
      if (!blocks(shape)) continue;
      const push = pushOutOfConvex([x, z], radius, shape.polygon);
      if (!push) continue;
      x += push[0];
      z += push[1];
      moved = true;
    }
    if (!moved) break;
  }
  return [x, z];
}

/** Whether a player circle at the point overlaps any blocker in its body band. */
export function isBlocked(
  world: WalkWorld,
  point: Point,
  groundY: number,
  dynamic: readonly Shape[] = [],
) {
  return blockersNear(world, pointBox(point, PLAYER_RADIUS), dynamic).some(
    (shape) =>
      blocksBody(shape, groundY) &&
      pushOutOfConvex(point, PLAYER_RADIUS, shape.polygon) !== null,
  );
}

/** Whether a player at `point` may step there from `from` (water, a ledge too high, a cliff...). */
export type CanEnter = (point: Point, from: Point) => boolean;

function resolveStep(
  world: WalkWorld,
  from: Point,
  to: Point,
  groundY: number,
  canEnter: CanEnter,
  dynamic: readonly Shape[],
): Point {
  const enterable = (point: Point) =>
    !isWater(world, point) && canEnter(point, from);
  // whole move first, then each axis alone so the player slides along banks and ledges
  for (const target of [
    to,
    [to[0], from[1]] as Point,
    [from[0], to[1]] as Point,
  ]) {
    const resolved = pushOutOfBlockers(world, target, groundY, dynamic);
    if (enterable(resolved)) return resolved;
  }
  return from;
}

/**
 * Where a player at `from` ends up when trying to move to `to`: slides along blockers (the world's and the
 * `dynamic` ones), never enters water and never enters a point `canEnter` rejects (e.g. a step up that is too
 * high).
 */
export function resolveMove(
  world: WalkWorld,
  from: Point,
  to: Point,
  groundY: number,
  canEnter: CanEnter = () => true,
  dynamic: readonly Shape[] = [],
): Point {
  const steps = Math.max(
    1,
    Math.ceil(Math.hypot(to[0] - from[0], to[1] - from[1]) / MAX_SUBSTEP),
  );
  const step: Point = [(to[0] - from[0]) / steps, (to[1] - from[1]) / steps];
  let position = from;
  for (let i = 0; i < steps; i++) {
    position = resolveStep(
      world,
      position,
      [position[0] + step[0], position[1] + step[1]],
      groundY,
      canEnter,
      dynamic,
    );
  }
  return position;
}

/** A local point with its height: (x, y, z). */
export type LocalPoint = [number, number, number];

/**
 * Where along the segment from `from` to `to` (0..1) it first enters a blocker's volume (its ground polygon
 * extruded over its y-range), or 1 if it never does. Blockers the segment starts inside are ignored.
 */
export function raycastBlockers(
  world: WalkWorld,
  from: LocalPoint,
  to: LocalPoint,
  dynamic: readonly Shape[] = [],
): number {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const dz = to[2] - from[2];
  const box: Box = {
    minX: Math.min(from[0], to[0]),
    minZ: Math.min(from[2], to[2]),
    maxX: Math.max(from[0], to[0]),
    maxZ: Math.max(from[2], to[2]),
  };
  let first = 1;
  for (const shape of blockersNear(world, box, dynamic)) {
    // Cyrus-Beck: clip the segment against every face plane of the convex prism
    let enter = 0;
    let exit = first;
    let startsInside = true;
    const clip = (start: number, rate: number) => {
      // inside where start + rate·t <= 0
      if (start > 0) startsInside = false;
      if (Math.abs(rate) < EPSILON) return start <= 0;
      const t = -start / rate;
      if (rate < 0) enter = Math.max(enter, t);
      else exit = Math.min(exit, t);
      return enter <= exit;
    };
    let hit = clip(from[1] - shape.maxY, dy) && clip(shape.minY - from[1], -dy);
    const { polygon } = shape;
    for (let i = 0; hit && i < polygon.length; i++) {
      const a = polygon[i];
      const b = polygon[(i + 1) % polygon.length];
      const nx = b[1] - a[1];
      const nz = -(b[0] - a[0]);
      hit = clip(
        (from[0] - a[0]) * nx + (from[2] - a[1]) * nz,
        dx * nx + dz * nz,
      );
    }
    if (hit && !startsInside && enter < first) first = enter;
  }
  return first;
}

/** Pushes a point (e.g. the camera) at height y out of blockers within `radius` of it. */
export const clearOfBlockers = (
  world: WalkWorld,
  point: Point,
  y: number,
  radius: number,
  dynamic: readonly Shape[] = [],
) =>
  pushOutOfBlockers(
    world,
    point,
    y,
    dynamic,
    radius,
    (shape) => shape.maxY > y - radius && shape.minY < y + radius,
  );
