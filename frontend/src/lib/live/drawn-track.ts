/*
 * Where a live citizen is drawn, frame by frame: on the timed path its latest tick streamed (`walk-path.ts`), joined
 * where the last path left it. Normally the new path starts right there (the feed streams each move from where the
 * mover stood when the tick began), so nothing jumps; a drawn spot a little off (a tick that came late) eases onto
 * the path, and one far off (a reconnect, a hidden tab) is a resync: the body fades out where it was and back in on
 * its path instead of jumping.
 *
 *   opacity 1 ──fade out at the old spot──▶ 0 ──fade in on the path──▶ 1      (FADE_S real seconds in all)
 *
 * Pure (no DOM, no React): `globe-npcs.tsx` keeps one per citizen and the tests drive it directly.
 */
import { Vector3 } from 'three';

import {
  advance,
  citizenPath,
  groundSpeed,
  joinAt,
  pointAt,
  snapMetres,
  type WalkPath,
} from './walk-path';
import type { RoutePoint } from '@/lib/client/types.gen';

/** How fast the drawn spot eases onto a new tick's path when it is a little off (1/s). */
const CATCH_UP_RATE = 3;
/** A resync fades the body out where it was drawn and in on its path over this long (real seconds). */
export const FADE_S = 0.3;

/** What a feed frame says of a citizen's place and move. */
interface Streamed {
  position: { unit: [number, number, number] };
  route: RoutePoint[];
  speed_mps: number;
  heading_deg: number;
}

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
}

/**
 * A citizen first seen (a snapshot, a replayed tick) is drawn where the feed says it is now: at the end of its tick's
 * step, walking on along its plan.
 */
export function newTrack(citizen: Streamed, radius: number): Track {
  const path = citizenPath(citizen, radius);
  joinAt(path, new Vector3(...citizen.position.unit), radius);
  return {
    path,
    offset: new Vector3(),
    yaw: (citizen.heading_deg * Math.PI) / 180,
    fade: null,
    opacity: 1,
  };
}

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
  const drawn = onPath(track, new Vector3());
  const limit = snapMetres(groundSpeed(track.path), rate);
  const path = citizenPath(citizen, radius);
  const off = joinAt(path, drawn, radius);
  track.path = path;
  if (off <= limit) {
    track.offset.subVectors(drawn, pointAt(path, new Vector3()));
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
