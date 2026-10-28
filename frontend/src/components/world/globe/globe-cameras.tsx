import { useFrame, useThree } from '@react-three/fiber';
import { type RefObject, useCallback, useEffect, useRef } from 'react';
import { Matrix4, type PerspectiveCamera, Quaternion, Vector3 } from 'three';

import type { GlobePlayerState, GlobeRig } from './globe-player';
import {
  axis,
  BACK,
  FORWARD,
  isRunning,
  LEFT,
  RIGHT,
  useKeys,
} from '@/components/world/player/use-keys';
import { useDrag } from '@/components/world/player/use-drag';
import { MAX_FRAME, smoothing } from '@/components/world/player/motion';
import { PLAYER_EYE_HEIGHT } from '@/components/world/player/player-state';
import { type GlobeTerrain, tangent, WATER_SURFACE } from '@/lib/world/globe';

/*
 * Cameras on the planet, all with "up" = the local normal under them. follow: third person behind the player;
 * orbit: the whole planet around its centre, zooming down to the surface (and handing over to follow when it
 * zooms onto the player); fly: free flight. Each keeps `focusRef` on the surface point it looks after.
 */

const clamp = (value: number, min: number, max: number) =>
  Math.min(max, Math.max(min, value));

const useWheel = (onWheel: (deltaY: number) => void) => {
  const canvas = useThree((state) => state.gl.domElement);
  const handler = useRef(onWheel);
  useEffect(() => {
    handler.current = onWheel;
  }, [onWheel]);
  useEffect(() => {
    const zoom = (event: WheelEvent) => {
      event.preventDefault();
      handler.current(event.deltaY);
    };
    canvas.addEventListener('wheel', zoom, { passive: false });
    return () => canvas.removeEventListener('wheel', zoom);
  }, [canvas]);
};

const up = new Vector3();
const eye = new Vector3();
const offset = new Vector3();

const FOLLOW_DRAG = 0.005;
/** The follow camera never dips closer than this to the ground or the water under it. */
const FOLLOW_CLEARANCE = 1;
const FOLLOW_PITCH: [number, number] = [0.05, 1.45];
const FOLLOW_DISTANCE: [number, number] = [3, 40];

export function GlobeFollowCamera({
  terrain,
  playerRef,
  rigRef,
  focusRef,
}: {
  terrain: GlobeTerrain;
  playerRef: RefObject<GlobePlayerState>;
  rigRef: RefObject<GlobeRig>;
  focusRef: RefObject<Vector3>;
}) {
  useDrag(
    useCallback(
      (dx: number, dy: number) => {
        const rig = rigRef.current;
        up.copy(playerRef.current.position).normalize();
        rig.heading.applyAxisAngle(up, -dx * FOLLOW_DRAG);
        rig.pitch = clamp(rig.pitch + dy * FOLLOW_DRAG, ...FOLLOW_PITCH);
      },
      [rigRef, playerRef],
    ),
  );
  useWheel(
    useCallback(
      (deltaY: number) => {
        const rig = rigRef.current;
        rig.distance = clamp(
          rig.distance * Math.exp(deltaY * 0.001),
          ...FOLLOW_DISTANCE,
        );
      },
      [rigRef],
    ),
  );

  useFrame(({ camera }) => {
    const { position, facing } = playerRef.current;
    const rig = rigRef.current;
    up.copy(position).normalize();
    tangent(rig.heading, up, facing);
    eye.copy(position).addScaledVector(up, PLAYER_EYE_HEIGHT);
    offset
      .copy(rig.heading)
      .multiplyScalar(-Math.cos(rig.pitch) * rig.distance)
      .addScaledVector(up, Math.sin(rig.pitch) * rig.distance);
    camera.position.copy(eye).add(offset);
    // behind a rise the boom would end inside the hill, which then culls away and leaves the player hanging
    const floor =
      terrain.globe.radius +
      Math.max(terrain.heightAt(camera.position), WATER_SURFACE) +
      FOLLOW_CLEARANCE;
    if (camera.position.length() < floor) camera.position.setLength(floor);
    camera.up.copy(up);
    camera.lookAt(eye);
    focusRef.current.copy(position);
  });

  return null;
}

/** Orbit altitude range (metres above sea level) and the start of the view. */
const ORBIT_MIN_ALTITUDE = 120;
const ORBIT_MAX_DISTANCE = 8000;
const ORBIT_START_DISTANCE = 6000;
/** Zooming in below this altitude within HANDOVER_REACH of the player switches to follow. */
const HANDOVER_ALTITUDE = 400;
const HANDOVER_REACH = 600;

const orbitTurn = new Quaternion();
const AXIS_X = new Vector3(1, 0, 0);
const AXIS_Y = new Vector3(0, 1, 0);
const look = new Matrix4();
const ORIGIN = new Vector3();

export function GlobeOrbitCamera({
  radius,
  terrain,
  playerRef,
  focusRef,
  onHandover,
}: {
  radius: number;
  terrain: GlobeTerrain;
  playerRef: RefObject<GlobePlayerState>;
  focusRef: RefObject<Vector3>;
  onHandover: () => void;
}) {
  const camera = useThree((state) => state.camera);
  const view = useRef({
    turn: new Quaternion(),
    distance: ORBIT_START_DISTANCE,
    target: ORBIT_START_DISTANCE,
  });

  useEffect(() => {
    // start over the player (north up), from wherever the camera is now
    const start = view.current;
    const over = playerRef.current.position.clone().normalize();
    const north = AXIS_Y.clone();
    if (Math.abs(over.y) > 0.999) north.set(0, 0, 1);
    look.lookAt(over, ORIGIN, north);
    start.turn.setFromRotationMatrix(look);
    start.distance = Math.max(camera.position.length(), radius + 50);
    start.target = ORBIT_START_DISTANCE;
  }, [camera, radius, playerRef]);

  useDrag(
    useCallback(
      (dx: number, dy: number) => {
        const { turn, distance } = view.current;
        // slower the closer to the ground, so the surface keeps up with the pointer
        const speed = 0.004 * clamp((distance - radius) / radius, 0.02, 1.5);
        turn.multiply(orbitTurn.setFromAxisAngle(AXIS_Y, -dx * speed));
        turn.multiply(orbitTurn.setFromAxisAngle(AXIS_X, -dy * speed));
        turn.normalize();
      },
      [radius],
    ),
  );
  useWheel(
    useCallback(
      (deltaY: number) => {
        const current = view.current;
        const altitude = clamp(
          (current.target - radius) * Math.exp(deltaY * 0.0015),
          ORBIT_MIN_ALTITUDE,
          ORBIT_MAX_DISTANCE - radius,
        );
        current.target = radius + altitude;
        const below = offset.set(0, 0, 1).applyQuaternion(current.turn);
        const reach = below.angleTo(playerRef.current.position) * radius;
        if (
          deltaY < 0 &&
          altitude < HANDOVER_ALTITUDE &&
          reach < HANDOVER_REACH
        )
          onHandover();
      },
      [radius, playerRef, onHandover],
    ),
  );

  useFrame((_, frameDelta) => {
    const current = view.current;
    current.distance +=
      (current.target - current.distance) *
      smoothing(4, Math.min(frameDelta, MAX_FRAME));
    const below = offset.set(0, 0, 1).applyQuaternion(current.turn);
    camera.position.copy(below).multiplyScalar(current.distance);
    camera.quaternion.copy(current.turn);
    camera.up.set(0, 1, 0).applyQuaternion(current.turn);
    focusRef.current
      .copy(below)
      .multiplyScalar(radius + Math.max(terrain.heightAt(below), 0));
  });

  return null;
}

const FLY_LOOK = 0.004;
const FLY_MAX_PITCH = 1.5;

export function GlobeFlyCamera({
  radius,
  terrain,
  focusRef,
}: {
  radius: number;
  terrain: GlobeTerrain;
  focusRef: RefObject<Vector3>;
}) {
  const camera = useThree((state) => state.camera);
  const keys = useKeys();
  const look = useRef({ heading: new Vector3(), pitch: 0 });

  useEffect(() => {
    const direction = camera.getWorldDirection(new Vector3());
    up.copy(camera.position).normalize();
    const pitch = Math.asin(clamp(direction.dot(up), -1, 1));
    look.current = {
      heading: tangent(direction.clone(), up, new Vector3(1, 0, 0)),
      pitch: clamp(pitch, -FLY_MAX_PITCH, FLY_MAX_PITCH),
    };
  }, [camera]);

  useDrag(
    useCallback(
      (dx: number, dy: number) => {
        const current = look.current;
        up.copy(camera.position).normalize();
        current.heading.applyAxisAngle(up, -dx * FLY_LOOK);
        current.pitch = clamp(
          current.pitch - dy * FLY_LOOK,
          -FLY_MAX_PITCH,
          FLY_MAX_PITCH,
        );
      },
      [camera],
    ),
  );

  useFrame((_, frameDelta) => {
    const delta = Math.min(frameDelta, MAX_FRAME);
    const current = look.current;
    up.copy(camera.position).normalize();
    tangent(current.heading, up, new Vector3(1, 0, 0));
    const forward = eye
      .copy(current.heading)
      .multiplyScalar(Math.cos(current.pitch))
      .addScaledVector(up, Math.sin(current.pitch));
    const right = new Vector3().crossVectors(current.heading, up);
    const move = offset
      .set(0, 0, 0)
      .addScaledVector(forward, axis(keys.current, BACK, FORWARD))
      .addScaledVector(right, axis(keys.current, LEFT, RIGHT))
      .addScaledVector(up, axis(keys.current, ['KeyQ'], ['KeyE']));
    const ground = radius + Math.max(terrain.heightAt(up), 0);
    if (move.lengthSq() > 0) {
      const altitude = camera.position.length() - ground;
      const speed =
        clamp(altitude * 0.6, 8, 800) * (isRunning(keys.current) ? 3 : 1);
      camera.position.addScaledVector(move.normalize(), speed * delta);
    }
    if (camera.position.length() < ground + 1.5)
      camera.position.setLength(ground + 1.5);
    camera.up.copy(up);
    camera.lookAt(camera.position.clone().add(forward));
    focusRef.current.copy(up).multiplyScalar(ground);
  });

  return null;
}

/** Highest terrain, for how far the far plane must reach past the horizon. */
const HIGHEST = 400;

/** Keeps near/far tight around what can be seen: from 0.1 m on the ground to the far limb from orbit. */
export function CameraRange({ radius }: { radius: number }) {
  useFrame(({ camera }) => {
    const perspective = camera as PerspectiveCamera;
    const distance = camera.position.length();
    const altitude = distance - radius;
    const horizon =
      Math.sqrt(Math.max(distance * distance - radius * radius, 0)) +
      Math.sqrt((radius + HIGHEST) ** 2 - radius * radius);
    const near = clamp((altitude - HIGHEST) * 0.5, 0.1, 2000);
    const far = Math.max(1500, horizon + 100);
    if (perspective.near !== near || perspective.far !== far) {
      perspective.near = near;
      perspective.far = far;
      perspective.updateProjectionMatrix();
    }
  });
  return null;
}
