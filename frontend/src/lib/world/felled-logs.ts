/*
 * Where a felled tree's logs lie (10 §1.1: a tree falls along its yaw and leaves its logs by the stump): a fallen log
 * LOGS_OFFSET × the tree's scale out along the fall, its two ends on the drawn ground, so on a slope it tilts with
 * the ground instead of hanging at trunk height. The falling tree (node-field.ts) lands on the same line, and the
 * ground stacks (ground-stacks.ts) draw the logs there.
 */
import { Matrix4, Vector3 } from 'three';

import { assetSize, PROPS } from './assets';
import { LOGS_LOOK } from './biome-props';
import { tangentFrame } from './globe';
import type { NodeInstance } from './scatter';
import type { PlaceOnGround } from './walk-charts';

/** The logs' centre lies this far (× the tree's scale) out along the fall from the trunk. */
const LOGS_OFFSET = 2;
/** The fallen log model's length (its x axis, centred on its origin). */
const LOGS_LENGTH = assetSize(PROPS[LOGS_LOOK]).x;

/** The way a tree at `position` falls: its compass bearing (radians, 0 north, π/2 east) on the tangent plane. */
export function fallDirection(
  position: Vector3,
  bearing: number,
  target: Vector3,
) {
  const { east, north } = tangentFrame(position);
  return target
    .copy(north)
    .multiplyScalar(Math.cos(bearing))
    .addScaledVector(east, Math.sin(bearing));
}

export interface LyingLogs {
  /** The model's matrix: origin on the ground line midway, x along the fall, y up off the line. */
  model: Matrix4;
  /** The ground line's direction, from the end by the stump to the far end. */
  axis: Vector3;
}

/** A felled tree's logs, `bearing` the way it fell: lying on the ground between their two ends. */
export function lyingLogs(
  node: NodeInstance,
  bearing: number,
  place: PlaceOnGround,
): LyingLogs {
  const along = fallDirection(node.position, bearing, new Vector3());
  const centre = LOGS_OFFSET * node.scale;
  const half = (LOGS_LENGTH / 2) * node.scale;
  const end = (metres: number) =>
    place(
      node.position.clone().addScaledVector(along, metres).normalize(),
      new Vector3(),
    );
  const near = end(centre - half);
  const far = end(centre + half);
  const axis = far.clone().sub(near).normalize();
  const origin = near.clone().add(far).multiplyScalar(0.5);
  const up = origin.clone().normalize();
  up.addScaledVector(axis, -up.dot(axis)).normalize();
  const across = new Vector3().crossVectors(axis, up);
  const model = new Matrix4()
    .makeBasis(axis, up, across)
    .scale(new Vector3().setScalar(node.scale))
    .setPosition(origin);
  return { model, axis };
}

/** How far (radians) the tree at `node` turns about its base to land along the logs' ground line (π/2 on the flat). */
export function landingAngle(
  node: NodeInstance,
  bearing: number,
  place: PlaceOnGround,
) {
  const { axis } = lyingLogs(node, bearing, place);
  const up = node.position.clone().normalize();
  const along = fallDirection(node.position, bearing, new Vector3());
  return Math.atan2(axis.dot(along), axis.dot(up));
}
