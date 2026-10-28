/*
 * Where a place's local metres (x east, y up, z south, as the town is authored) land in the rendered world:
 * unchanged on the flat town page, wrapped onto the planet by a site mapping (globe.ts) on the globe.
 */
import type { Matrix4, Vector3 } from 'three';

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
