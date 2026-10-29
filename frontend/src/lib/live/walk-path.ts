/*
 * Drawing a mover between engine ticks. Each tick the feed gives everyone who moved a timed path (`route`): from
 * where they stood when the tick began (t_s 0, where the last tick's path left them), through where they are now,
 * then on along their plan for a couple of game minutes. The client walks them along it by its times, game seconds
 * passing at the clock's speed, so each tick's move is drawn as walking over the next tick: one tick behind the
 * sim, never a jump, never cutting a corner the route doesn't, slowing down where the ground is harder.
 *
 *   route[0] ──────▶ route[1] ──────▶ route[2]        `time` = game seconds walked from route[0]
 *     t 0        t 25 (corner)     t 60 (now)  ─▶ ahead
 *
 * Feeds recorded before routes were timed have no `t_s`: their route starts where the walker is and is walked at
 * `speed_mps`. Pure (no DOM, no React): `globe-npcs.tsx` keeps one per citizen and the tests drive it directly.
 */
import { Vector3 } from 'three';

import type { RoutePoint } from '@/lib/client/types.gen';

/** Drawn farther off its new path than this (and than SNAP_SECONDS of its drawn walking), it is a resync. */
const SNAP_M = 30;
const SNAP_SECONDS = 2.5;

export interface WalkPath {
  /** Unit directions from the planet's centre; one point = standing there. */
  points: Vector3[];
  /** Metres from the first point to each point along the path. */
  starts: number[];
  /** Game seconds from the first point to each point (the same at every point when standing). */
  times: number[];
  /** Game seconds walked from the first point. */
  time: number;
}

/** A path through the given directions (at least one), passed at the given game seconds. */
export function walkPath(
  units: readonly (readonly [number, number, number])[],
  times: readonly number[],
  radius: number,
): WalkPath {
  if (units.length === 0) throw new Error('a walk path needs a point');
  if (times.length !== units.length)
    throw new Error('a walk path needs a time per point');
  const points = units.map(([x, y, z]) => new Vector3(x, y, z).normalize());
  const starts = [0];
  for (let k = 1; k < points.length; k++)
    starts.push(starts[k - 1] + points[k - 1].angleTo(points[k]) * radius);
  return { points, starts, times: [...times], time: times[0] };
}

/** Where someone stands still. */
const standing = (
  unit: readonly [number, number, number],
  radius: number,
): WalkPath => walkPath([unit], [0], radius);

/** The feed's path for a citizen: the route when they moved, else just where they stand. */
export function citizenPath(
  citizen: {
    position: { unit: [number, number, number] };
    route: RoutePoint[];
    speed_mps: number;
  },
  radius: number,
): WalkPath {
  const { route, speed_mps: speed } = citizen;
  if (route.length < 2) return standing(citizen.position.unit, radius);
  const units = route.map((point) => point.unit);
  const timed = route.every((point) => point.t_s != null);
  if (timed)
    return walkPath(
      units,
      route.map((point) => point.t_s ?? 0),
      radius,
    );
  const untimed = walkPath(
    units,
    units.map(() => 0),
    radius,
  );
  untimed.times = untimed.starts.map((metres) =>
    speed > 0 ? metres / speed : 0,
  );
  return untimed;
}

const endTime = (path: WalkPath) => path.times[path.times.length - 1];

/** Still something ahead to walk. */
export const walking = (path: WalkPath) => path.time < endTime(path);

/** Walks `seconds` of game time on (stopping at the end); the clock's speed turns real seconds into game ones. */
export function advance(path: WalkPath, seconds: number) {
  path.time = Math.min(path.time + seconds, endTime(path));
}

/** The leg the walker is on (index of its start point). */
function legAt(path: WalkPath) {
  let leg = 0;
  while (leg < path.points.length - 2 && path.times[leg + 1] <= path.time)
    leg += 1;
  return leg;
}

/** How far along its leg the walker is (0..1). */
function shareOf(path: WalkPath, leg: number) {
  const span = path.times[leg + 1] - path.times[leg];
  return span > 0
    ? Math.min(Math.max((path.time - path.times[leg]) / span, 0), 1)
    : 1;
}

/** Where the walker is: a unit direction (written into `out`). */
export function pointAt(path: WalkPath, out: Vector3) {
  const { points } = path;
  if (points.length === 1) return out.copy(points[0]);
  const leg = legAt(path);
  return out
    .lerpVectors(points[leg], points[leg + 1], shareOf(path, leg))
    .normalize();
}

/** Ground speed where the walker is (game metres per game second); 0 standing or at the end. */
export function groundSpeed(path: WalkPath) {
  if (!walking(path)) return 0;
  const leg = legAt(path);
  const span = path.times[leg + 1] - path.times[leg];
  return span > 0 ? (path.starts[leg + 1] - path.starts[leg]) / span : 0;
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
  const { points, times } = path;
  const spot = new Vector3();
  const leg = new Vector3();
  let best = drawn.angleTo(points[0]) * radius;
  let time = times[0];
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
      time = times[k] + t * (times[k + 1] - times[k]);
    }
  }
  path.time = time;
  return best;
}

/**
 * How far off its new path a drawn mover may be and still ease onto it (metres), from its drawn ground speed (game
 * metres per game second) and the clock (game seconds per real second): a tick that comes a little late finds a
 * walker that walked on into its old path's look-ahead, farther at faster clocks. Beyond it is a resync.
 */
export const snapMetres = (speed: number, rate: number) =>
  Math.max(SNAP_M, SNAP_SECONDS * speed * rate);
