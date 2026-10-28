/*
 * Where a place's local metres (x east, y up, z south, as the town is authored) land in the rendered world:
 * unchanged on the flat town page, wrapped onto the planet by a site mapping (globe.ts) on the globe.
 */
import { Matrix4, Quaternion, Vector3 } from 'three';

export interface LocalMapping {
  /** False when local metres are world metres, so flat shapes need no subdividing before mapping. */
  readonly curved: boolean;
  toWorld(x: number, y: number, z: number, target: Vector3): Vector3;
  /** A model placed at (x, y, z) and turned `yaw` radians about its local up (three.js rotation.y). */
  matrix(
    x: number,
    y: number,
    z: number,
    yaw: number,
    target: Matrix4,
  ): Matrix4;
}

const Y_AXIS = new Vector3(0, 1, 0);
const UNIT = new Vector3(1, 1, 1);
const turn = new Quaternion();
const at = new Vector3();

export const FLAT_MAPPING: LocalMapping = {
  curved: false,
  toWorld: (x, y, z, target) => target.set(x, y, z),
  matrix: (x, y, z, yaw, target) =>
    target.compose(at.set(x, y, z), turn.setFromAxisAngle(Y_AXIS, yaw), UNIT),
};
