/*
 * Fast-forward trails (10 §4.2.3): above ×10 every walker drags the last TRAIL_S real seconds of its drawn path. Each
 * mover keeps a ring of spots: every corner of its streamed route it walked through (so the trail runs where the
 * body walked, round the moat and through the gates, however fast the clock runs), and between them one each
 * `trailStep` drawn metres; then its tip, where it is drawn now. `writeTrails` lays all of them out as line segments
 * (one merged mesh, one draw call), from the oldest spot to the tip, fading with age. Where the body faded across (a
 * resync) the line breaks, and a leg longer than `gap` metres is left out. Pure (no DOM, no React): `time-lapse-trails.tsx` drives it and
 * the tests too.
 */
import type { BufferAttribute, Vector3 } from 'three';

/** Real seconds of drawn path a trail shows. */
export const TRAIL_S = 20;
/** Spots a trail keeps at most: room for STEP_SPOTS laid by distance and the corners walked between them. */
const SPOTS = 1000;
/** Spots laid by distance in TRAIL_S of walking... */
const STEP_SPOTS = 400;
/** ...at least this far apart (metres)... */
const MIN_STEP_M = 0.5;
/** ...at this pace (m/s, game time). */
const WALK_MPS = 1.4;

/** How far apart (drawn metres) a trail lays down its spots at the clock's `rate` (game seconds per real second). */
export const trailStep = (rate: number) =>
  Math.max(MIN_STEP_M, (WALK_MPS * rate * TRAIL_S) / (STEP_SPOTS - 1));

interface Trail {
  /** SPOTS spots (x, y, z each) in a ring; `head` is where the next one goes. */
  spots: Float32Array;
  /** When each spot was laid down (real seconds). */
  times: Float64Array;
  /** 1 where the mover got to a spot by fading across (a resync), not by walking: no leg runs into it. */
  breaks: Uint8Array;
  head: number;
  count: number;
  /** Where the mover is drawn now (x, y, z): the trail always ends there. */
  tip: Float32Array;
}

export type Trails = Map<string, Trail>;

const squared = (
  a: ArrayLike<number>,
  i: number,
  b: ArrayLike<number>,
  j = 0,
) =>
  (a[i] - b[j]) ** 2 + (a[i + 1] - b[j + 1]) ** 2 + (a[i + 2] - b[j + 2]) ** 2;

/**
 * Moves a mover's trail on to where it is drawn (`spot`, copied) at real time `now`, through the route `corners` it
 * walked since the last call (each laid down as a spot): it lays a spot down once it is `step` metres from the last,
 * and forgets spots older than TRAIL_S. A mover that `jumped` (faded across since the last call: a resync) starts a
 * new line there.
 */
export function sampleTrail(
  trails: Trails,
  id: string,
  spot: Vector3,
  now: number,
  step: number,
  corners: readonly Vector3[] = [],
  jumped = false,
) {
  let trail = trails.get(id);
  if (!trail) {
    trail = {
      spots: new Float32Array(SPOTS * 3),
      times: new Float64Array(SPOTS),
      breaks: new Uint8Array(SPOTS),
      head: 0,
      count: 0,
      tip: new Float32Array(3),
    };
    trails.set(id, trail);
  }
  const { spots, times, tip } = trail;
  while (
    trail.count > 0 &&
    now - times[(trail.head + SPOTS - trail.count) % SPOTS] > TRAIL_S
  )
    trail.count -= 1;
  let broken = jumped;
  for (const corner of corners) {
    corner.toArray(tip);
    lay(trail, now, broken);
    broken = false;
  }
  spot.toArray(tip);
  const last = ((trail.head + SPOTS - 1) % SPOTS) * 3;
  if (!broken && trail.count > 0 && squared(spots, last, tip) < step * step)
    return;
  lay(trail, now, broken);
}

/** Lays the trail's tip down as its newest spot (`broken`: got to by fading across). */
function lay(trail: Trail, now: number, broken: boolean) {
  trail.spots.set(trail.tip, trail.head * 3);
  trail.times[trail.head] = now;
  trail.breaks[trail.head] = broken ? 1 : 0;
  trail.head = (trail.head + 1) % SPOTS;
  trail.count = Math.min(trail.count + 1, SPOTS);
}

/** Forgets the trails of movers no longer drawn. */
export function pruneTrails(trails: Trails, drawn: ReadonlySet<string>) {
  for (const id of trails.keys()) if (!drawn.has(id)) trails.delete(id);
}

/** How many segment vertices `writeTrails` may write for `movers` movers (size its buffers with this). */
export const trailVertices = (movers: number) => movers * SPOTS * 2;

/**
 * Writes every trail's legs as segments into `positions` (x, y, z per vertex) and `alphas` (one per vertex: 1 now,
 * fading to 0 TRAIL_S ago), its last leg ending at the tip; skips legs longer than `gap` metres and returns the
 * vertices written. Stops when the buffers are full.
 */
export function writeTrails(
  trails: Trails,
  positions: Float32Array,
  alphas: Float32Array,
  gap: number,
  now: number,
) {
  let vertices = 0;
  const room = Math.min(positions.length / 3, alphas.length);
  const fade = (time: number) => Math.max(1 - (now - time) / TRAIL_S, 0);
  for (const { spots, times, breaks, head, count, tip } of trails.values()) {
    const first = (head + SPOTS - count) % SPOTS; // the oldest spot
    for (let k = 0; k < count && vertices + 2 <= room; k++) {
      const a = (first + k) % SPOTS;
      const last = k === count - 1; // its last leg runs to the tip
      if (!last && breaks[(a + 1) % SPOTS]) continue; // faded across, not walked
      const to = last ? tip : spots;
      const b = last ? 0 : ((a + 1) % SPOTS) * 3;
      const length = squared(spots, a * 3, to, b);
      if (length === 0 || length > gap * gap) continue;
      for (let axis = 0; axis < 3; axis++) {
        positions[vertices * 3 + axis] = spots[a * 3 + axis];
        positions[vertices * 3 + 3 + axis] = to[b + axis];
      }
      alphas[vertices] = fade(times[a]);
      alphas[vertices + 1] = last ? 1 : fade(times[(a + 1) % SPOTS]);
      vertices += 2;
    }
  }
  return vertices;
}

/**
 * Asks three to upload only the first `vertices` vertices of each attribute. With none written there is nothing to
 * upload: an empty update range would make three send the whole buffer.
 */
export function uploadTrails(
  attributes: readonly BufferAttribute[],
  vertices: number,
) {
  if (vertices === 0) return;
  for (const attribute of attributes) {
    attribute.clearUpdateRanges();
    attribute.addUpdateRange(0, vertices * attribute.itemSize);
    attribute.needsUpdate = true;
  }
}
