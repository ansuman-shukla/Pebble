/*
 * The camera's flight into the follow view (after a drop, a "Go to" or a camera switch): from wherever it was,
 * around the planet's centre and down to the third-person spot behind the player in FLIGHT_SECONDS.
 */
import { Quaternion, Vector3 } from 'three';

import type { GlobeRig } from './globe-player';

/** Seconds the camera takes to fly into the follow view. */
export const FLIGHT_SECONDS = 1.5;
/** The flight rises over long hops: up to half the distance covered, at most this high. */
const FLIGHT_MAX_RISE = 3000;

const from = new Vector3();
const to = new Vector3();
const arc = new Quaternion();
const partial = new Quaternion();
const NO_TURN = new Quaternion();

export const easeInOut = (t: number) =>
  t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;

/** Starts a flight from wherever the camera is now into the follow view. */
export function startFlight(
  rig: GlobeRig,
  camera: { position: Vector3; quaternion: Quaternion },
) {
  rig.flight = {
    from: camera.position.clone(),
    quaternion: camera.quaternion.clone(),
    elapsed: 0,
  };
}

/**
 * Where the camera is `t` (eased, 0..1) of the way from `start` to `end`: around the planet's centre along the
 * great circle, with the altitude interpolated in log space (fast high up, slow near the ground) and lifted
 * over long hops so the path never cuts through the planet.
 */
export function flightPoint(
  start: Vector3,
  end: Vector3,
  t: number,
  radius: number,
  target: Vector3,
) {
  from.copy(start).normalize();
  to.copy(end).normalize();
  arc.setFromUnitVectors(from, to);
  partial.copy(NO_TURN).slerp(arc, t);
  const startAltitude = Math.max(start.length() - radius, 1);
  const endAltitude = Math.max(end.length() - radius, 1);
  const altitude = Math.exp(
    Math.log(startAltitude) * (1 - t) + Math.log(endAltitude) * t,
  );
  const rise =
    Math.min((from.angleTo(to) * radius) / 2, FLIGHT_MAX_RISE) *
    Math.sin(Math.PI * t);
  return target
    .copy(from)
    .applyQuaternion(partial)
    .multiplyScalar(radius + Math.max(altitude, rise));
}
