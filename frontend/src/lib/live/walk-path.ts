/*
 * Drawing a walker between engine ticks. Each tick the feed says where a citizen is (`route[0]`), the path they will
 * walk next (`route`, about two game minutes of it, along walkable ground) and their ground speed (`speed_mps`, game
 * metres per game second). The client moves them along that path at `speed_mps × clock speed` real metres per
 * second, so the walk stays smooth with a real minute between ticks (×1) and never cuts a corner the route doesn't.
 *
 *   route[0] ──────▶ route[1] ──────▶ route[2]        `along` = metres walked from route[0]
 *        drawn ●────────┘                             a new tick projects the drawn spot onto the new path
 *
 * Pure (no DOM, no React): `globe-npcs.tsx` keeps one per citizen and the tests drive it directly.
 */
import { Vector3 } from 'three';

import type { RoutePoint } from '@/lib/client/types.gen';

export interface WalkPath {
  /** Unit directions from the planet's centre; one point = standing there. */
  points: Vector3[];
  /** Metres from the first point to each point along the path. */
  starts: number[];
  /** Metres walked from the first point. */
  along: number;
  /** Ground speed, game metres per game second (0 when not walking). */
  speed: number;
}

/** A path through the given directions (at least one), walked at `speed`. */
export function walkPath(
  units: readonly (readonly [number, number, number])[],
  speed: number,
  radius: number,
): WalkPath {
  if (units.length === 0) throw new Error('a walk path needs a point');
  const points = units.map(([x, y, z]) => new Vector3(x, y, z).normalize());
  const starts = [0];
  for (let k = 1; k < points.length; k++)
    starts.push(starts[k - 1] + points[k - 1].angleTo(points[k]) * radius);
  return { points, starts, along: 0, speed };
}

/** The feed's path for a citizen: the route while walking on, else just where they stand. */
export function citizenPath(
  citizen: {
    position: { unit: [number, number, number] };
    route: RoutePoint[];
    speed_mps: number;
  },
  radius: number,
): WalkPath {
  return citizen.route.length > 1
    ? walkPath(
        citizen.route.map((point) => point.unit),
        citizen.speed_mps,
        radius,
      )
    : walkPath([citizen.position.unit], 0, radius);
}

export const pathLength = (path: WalkPath) =>
  path.starts[path.starts.length - 1];

/** Still something ahead to walk. */
export const walking = (path: WalkPath) =>
  path.speed > 0 && path.along < pathLength(path);

/** Walks `seconds` of game time on (stopping at the end); the clock's speed turns real seconds into game ones. */
export function advance(path: WalkPath, seconds: number) {
  path.along = Math.min(path.along + path.speed * seconds, pathLength(path));
}

/** The leg the walker is on (index of its start point). */
function legAt(path: WalkPath) {
  let leg = 0;
  while (leg < path.points.length - 2 && path.starts[leg + 1] <= path.along)
    leg += 1;
  return leg;
}

/** Where the walker is: a unit direction (written into `out`). */
export function pointAt(path: WalkPath, out: Vector3) {
  const { points, starts } = path;
  if (points.length === 1) return out.copy(points[0]);
  const leg = legAt(path);
  const length = starts[leg + 1] - starts[leg];
  const t = length > 0 ? Math.min((path.along - starts[leg]) / length, 1) : 1;
  return out.lerpVectors(points[leg], points[leg + 1], t).normalize();
}

/** The way the walker is going (the current leg's direction, not normalized to the tangent plane); null standing. */
export function headingAt(path: WalkPath, out: Vector3) {
  if (path.points.length === 1) return null;
  const leg = legAt(path);
  return out.subVectors(path.points[leg + 1], path.points[leg]);
}

/**
 * Puts the walker on a new tick's path where the drawn spot is closest to it (a walker drawn slightly ahead
 * carries on instead of stepping back); returns how far (metres) the drawn spot is off that point.
 */
export function joinAt(path: WalkPath, drawn: Vector3, radius: number) {
  const { points, starts } = path;
  const spot = new Vector3();
  const leg = new Vector3();
  let best = drawn.angleTo(points[0]) * radius;
  let along = 0;
  for (let k = 0; k < points.length - 1; k++) {
    leg.subVectors(points[k + 1], points[k]);
    const lengthSq = leg.lengthSq();
    const t =
      lengthSq > 0
        ? Math.min(
            Math.max(spot.subVectors(drawn, points[k]).dot(leg) / lengthSq, 0),
            1,
          )
        : 0;
    spot.copy(points[k]).addScaledVector(leg, t).normalize();
    const off = drawn.angleTo(spot) * radius;
    if (off < best) {
      best = off;
      along = starts[k] + t * (starts[k + 1] - starts[k]);
    }
  }
  path.along = along;
  return best;
}
