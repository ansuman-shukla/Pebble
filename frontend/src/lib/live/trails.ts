/*
 * Fast-forward trails (10 §4.2.3): above ×10 every walker drags the last TRAIL_S real seconds of its drawn path. Each
 * mover keeps a ring of spots sampled every SAMPLE_S; `writeTrails` lays all of them out as line segments (one merged
 * mesh, one draw call), fading from the walker back to the oldest spot. A leg longer than `gap` metres (a resync that
 * faded the body across) is left out. Pure (no DOM, no React): `time-lapse-trails.tsx` drives it and the tests too.
 */
import type { Vector3 } from 'three';

/** Real seconds of drawn path a trail shows... */
export const TRAIL_S = 20;
/** ...sampled this often. */
export const SAMPLE_S = 0.25;
const SAMPLES = Math.round(TRAIL_S / SAMPLE_S);
/** Spots closer than this (metres) to the last one aren't kept: someone standing adds nothing. */
const STILL_M = 0.05;

interface Trail {
  /** SAMPLES spots (x, y, z each) in a ring; `head` is where the next one goes. */
  spots: Float32Array;
  head: number;
  count: number;
}

export type Trails = Map<string, Trail>;

/** Adds a sampled spot to a mover's trail (a copy), dropping its oldest past TRAIL_S. */
export function sampleTrail(trails: Trails, id: string, spot: Vector3) {
  let trail = trails.get(id);
  if (!trail) {
    trail = { spots: new Float32Array(SAMPLES * 3), head: 0, count: 0 };
    trails.set(id, trail);
  }
  if (trail.count > 0) {
    const last = ((trail.head + SAMPLES - 1) % SAMPLES) * 3;
    const { spots } = trail;
    const dx = spots[last] - spot.x;
    const dy = spots[last + 1] - spot.y;
    const dz = spots[last + 2] - spot.z;
    if (dx * dx + dy * dy + dz * dz < STILL_M * STILL_M) return;
  }
  trail.spots.set([spot.x, spot.y, spot.z], trail.head * 3);
  trail.head = (trail.head + 1) % SAMPLES;
  trail.count = Math.min(trail.count + 1, SAMPLES);
}

/** Forgets the trails of movers no longer drawn. */
export function pruneTrails(trails: Trails, drawn: ReadonlySet<string>) {
  for (const id of trails.keys()) if (!drawn.has(id)) trails.delete(id);
}

/** How many segment vertices `writeTrails` may write for `movers` movers (size its buffers with this). */
export const trailVertices = (movers: number) => movers * (SAMPLES - 1) * 2;

/**
 * Writes every trail's legs as segments into `positions` (x, y, z per vertex) and `alphas` (one per vertex: 1 at the
 * walker, fading to 0 TRAIL_S back), skipping legs longer than `gap` metres; returns the vertices written.
 * Stops when the buffers are full.
 */
export function writeTrails(
  trails: Trails,
  positions: Float32Array,
  alphas: Float32Array,
  gap: number,
) {
  let vertices = 0;
  const room = Math.min(positions.length / 3, alphas.length);
  for (const { spots, head, count } of trails.values()) {
    const first = (head + SAMPLES - count) % SAMPLES; // the oldest spot
    for (let k = 1; k < count && vertices + 2 <= room; k++) {
      const a = ((first + k - 1) % SAMPLES) * 3;
      const b = ((first + k) % SAMPLES) * 3;
      const dx = spots[a] - spots[b];
      const dy = spots[a + 1] - spots[b + 1];
      const dz = spots[a + 2] - spots[b + 2];
      if (dx * dx + dy * dy + dz * dz > gap * gap) continue;
      positions.set(spots.subarray(a, a + 3), vertices * 3);
      positions.set(spots.subarray(b, b + 3), vertices * 3 + 3);
      alphas[vertices] = 1 - (count - k) / (SAMPLES - 1);
      alphas[vertices + 1] = 1 - (count - 1 - k) / (SAMPLES - 1);
      vertices += 2;
    }
  }
  return vertices;
}
