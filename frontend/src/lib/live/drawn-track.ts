/*
 * Where a live citizen is drawn, frame by frame, and what it is shown doing: on the timed path its latest tick
 * streamed (`walk-path.ts`), one tick behind the sim, joined where the last path left it. Normally the new path starts
 * right there (the feed streams each move from where the mover stood when the tick began), so nothing jumps; a walker
 * drawn short of it (a page opened mid-tick) walks the rest of its old path first; a drawn spot a little past it (a
 * tick that came late) eases onto the path, and one far off (a hidden tab) is a resync: the body fades out where it
 * was and back in on its path instead of jumping.
 *
 *   opacity 1 ──fade out at the old spot──▶ 0 ──fade in on the path──▶ 1      (FADE_S real seconds in all)
 *
 * While the drawn body still walks to where the feed says the citizen is now, it is shown moving: a walk that ended
 * within the tick (in sleep, a collapse, death) shows its new activity and pose only once the body gets there.
 *
 * Pure (no DOM, no React): `globe-npcs.tsx` keeps one per citizen and the tests drive it directly.
 */
import { Vector3 } from 'three';

import {
  advance,
  carriedOn,
  citizenPath,
  groundSpeed,
  headingAt,
  joinAt,
  metresLeft,
  pointAt,
  snapMetres,
  walking,
  type WalkPath,
} from './walk-path';
import type { CitizenEntity, RoutePoint } from '@/lib/client/types.gen';

/** How fast the drawn spot eases onto a new tick's path when it is a little off (1/s). */
const CATCH_UP_RATE = 3;
/** A resync fades the body out where it was drawn and in on its path over this long (real seconds). */
export const FADE_S = 0.3;
/** Walkers are drawn this far right of their route, so two passing on one street don't merge (10 §4.3). */
export const LANE_M = 0.35;
/** How fast a walker steps into its lane as it sets off (1/s, real time)... */
const LANE_RATE = 4;
/** ...and over how many metres before the end of its path it steps back onto the route. */
const LANE_OUT_M = 1.5;

/** What a citizen is shown doing (the label's words and the pose come from it). */
export type Doing = Pick<
  CitizenEntity,
  'activity' | 'action_label' | 'cause_of_death'
>;

/** What a feed frame says of a citizen's place, move and doing. */
interface Streamed extends Doing {
  position: { unit: [number, number, number] };
  route: RoutePoint[];
  speed_mps: number;
  heading_deg: number;
}

/** The activities of someone on the move (drawn with the gait, standing). */
const MOVING: ReadonlySet<Doing['activity']> = new Set([
  'walking',
  'running',
  'hunting',
]);
/** Shown for a body that moved before it was seen doing anything moving. */
const WALKING: Doing = {
  activity: 'walking',
  action_label: '',
  cause_of_death: null,
};

const doingOf = ({ activity, action_label, cause_of_death }: Doing): Doing => ({
  activity,
  action_label,
  cause_of_death,
});

export interface Track {
  /** The path the feed streamed for this tick (one point when standing) and how far along it the citizen is. */
  path: WalkPath;
  /** Drawn spot minus the spot on the path (unit-sphere vector), easing to zero after a new tick. */
  offset: Vector3;
  /** Rendered yaw (radians, the heading convention). */
  yaw: number;
  /** A resync under way: where the body was drawn (it fades out there) and real seconds since it began. */
  fade: { from: Vector3; elapsed: number } | null;
  /** How opaque the body is drawn (below 1 only while fading). */
  opacity: number;
  /** What the latest frame says the citizen is doing. */
  doing: Doing;
  /** What it is shown doing instead while the drawn body walks to where the frame says it is (moving). */
  held: Doing | null;
  /** How far into its keep-right lane the body is drawn (0 on its spot standing, 1 walking)... */
  lane: number;
  /** ...towards this side (unit, right of the way it last walked). */
  side: Vector3;
}

/**
 * A citizen first seen (a snapshot) is drawn like any other, one tick behind: where its tick's step began, walking
 * it. A replayed moment (`now`), which no tick follows, draws it where the frame says it is.
 */
export function newTrack(
  citizen: Streamed,
  radius: number,
  now = false,
): Track {
  const path = citizenPath(citizen, radius);
  if (now) path.time = path.arrive;
  return {
    path,
    offset: new Vector3(),
    yaw: (citizen.heading_deg * Math.PI) / 180,
    fade: null,
    opacity: 1,
    doing: doingOf(citizen),
    held: MOVING.has(citizen.activity) ? null : WALKING,
    lane: 0,
    side: new Vector3(),
  };
}

/** What the citizen is shown doing now (the same object until it changes). */
export const shownDoing = (track: Track) =>
  track.held && track.path.time < track.path.arrive ? track.held : track.doing;

/** Where the citizen is drawn on its path, eased by the catch-up offset (a unit direction into `out`). */
const onPath = (track: Track, out: Vector3) =>
  pointAt(track.path, out).add(track.offset).normalize();

/**
 * Puts a new frame's path under the citizen, joined where it is drawn now (no jump, no step back); far off, a
 * resync starts. `rate` is the clock (game seconds per real second).
 */
export function follow(
  track: Track,
  citizen: Streamed,
  radius: number,
  rate: number,
) {
  const shown = shownDoing(track);
  track.doing = doingOf(citizen);
  track.held = MOVING.has(citizen.activity)
    ? null
    : MOVING.has(shown.activity)
      ? shown
      : WALKING;
  const next = citizenPath(citizen, radius);
  const carried = carriedOn(track.path, next, radius);
  if (carried) {
    track.path = carried; // the offset carries on easing
    return;
  }
  const drawn = onPath(track, new Vector3());
  const limit = snapMetres(groundSpeed(track.path), rate);
  const off = joinAt(next, drawn, radius);
  track.path = next;
  if (off <= limit) {
    track.offset.subVectors(drawn, pointAt(next, new Vector3()));
    return;
  }
  track.offset.set(0, 0, 0);
  // a resync during a resync fades out where the body was last seen
  track.fade = { from: track.fade?.from ?? drawn, elapsed: 0 };
}

/**
 * Moves the citizen on by `delta` real seconds at the clock's `rate` (game seconds per real second); returns where
 * the body is drawn (a unit direction into `out`) and updates its opacity.
 */
export function moveOn(
  track: Track,
  delta: number,
  rate: number,
  out: Vector3,
) {
  advance(track.path, delta * rate);
  track.offset.multiplyScalar(Math.exp(-CATCH_UP_RATE * delta));
  onPath(track, out);
  const { fade } = track;
  if (!fade) return out;
  fade.elapsed += delta;
  const half = FADE_S / 2;
  track.opacity = Math.min(Math.abs(fade.elapsed - half) / half, 1);
  if (fade.elapsed >= FADE_S) track.fade = null;
  return fade.elapsed < half ? out.copy(fade.from) : out;
}

const going = new Vector3();

/**
 * Shifts the drawn spot `at` (a unit direction, changed in place) into the walker's keep-right lane: LANE_M right of
 * the way it walks, stepped into over a fraction of a second as it sets off and left over the last LANE_OUT_M of its
 * path, so it stops (and sits, works...) exactly where the feed says. Drawn only: the sim's walkers may pass
 * through each other, and the path and its joins stay on the route.
 */
export function keepRight(
  track: Track,
  delta: number,
  at: Vector3,
  radius: number,
) {
  const onward = walking(track.path) && headingAt(track.path, going);
  if (onward) {
    going.crossVectors(going, at); // right of the way it walks, on the tangent plane
    if (going.lengthSq() > 1e-18) track.side.copy(going).normalize();
  }
  track.lane +=
    ((onward ? 1 : 0) - track.lane) * (1 - Math.exp(-LANE_RATE * delta));
  track.lane = Math.min(track.lane, metresLeft(track.path) / LANE_OUT_M);
  if (track.lane < 1e-4) return at;
  return at
    .addScaledVector(track.side, (LANE_M * track.lane) / radius)
    .normalize();
}
