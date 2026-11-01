/*
 * A gold pool's glints (10 §1.1, `node_stages.yaml`: "a pool glinting with gold", stage `glints-N` of 4, rounded
 * up): N sparks of gold twinkling on the water over the pool, fewer as it is panned out, none once it is empty, so
 * the panning spot reads from the bank. A pool the feed never mentioned is full.
 */
import { Vector3 } from 'three';

import { type GlobeTerrain, tangentFrame } from './globe';
import type { NodeState } from './node-stages';
import { lakeSurface } from './water-mesh';

export const GLINTS = 4;
/** The glints lie on a ring this wide (metres) round the pool's point, GLINT_LIFT over the water or the ground. */
const GLINT_RING_M = 1.2;
const GLINT_LIFT = 0.2; // over a river ribbon too (it floats 0.15 m up)

/** How many glints a gold pool shows: its stage's count (`glints-N`), all of them while it is full. */
export function glintCount(state: NodeState | undefined) {
  if (!state) return GLINTS;
  const named =
    state.stage === null ? null : /^glints-(\d+)$/.exec(state.stage);
  if (named) return Math.min(GLINTS, Number(named[1]));
  return Math.ceil(GLINTS * state.fill - 1e-9);
}

/** Where a pool's glints lie (world metres): round its point, on the water drawn there (or the ground above it). */
export function glintSpots(direction: Vector3, terrain: GlobeTerrain) {
  const { radius } = terrain.globe;
  const up = direction.clone().normalize();
  const { east, north } = tangentFrame(up);
  return Array.from({ length: GLINTS }, (_, k) => {
    const angle = ((k + 0.5) / GLINTS) * Math.PI * 2;
    const reach = GLINT_RING_M * (k % 2 ? 0.55 : 1);
    const at = up
      .clone()
      .multiplyScalar(radius)
      .addScaledVector(east, Math.cos(angle) * reach)
      .addScaledVector(north, Math.sin(angle) * reach)
      .normalize();
    const hit = terrain.locate(at);
    const height = Math.max(
      hit.height,
      lakeSurface(terrain.globe, hit.triangle),
    );
    return at.multiplyScalar(radius + height + GLINT_LIFT);
  });
}
