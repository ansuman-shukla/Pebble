import { useFrame, useThree } from '@react-three/fiber';
import { type RefObject, useCallback, useEffect, useRef } from 'react';
import { Matrix4, type PerspectiveCamera, Quaternion, Vector3 } from 'three';

import { DODGE_ARM, dodgeFor, type Swing } from './camera-dodge';
import {
  easeInOut,
  FLIGHT_SECONDS,
  flightPoint,
  startFlight,
} from './camera-flight';
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
import type { GlobeWalk } from '@/lib/world/globe-walk';

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
const wanted = new Vector3();
const probe = new Vector3();
const probeEnd = new Vector3();
const turnTo = new Quaternion();
const looking = new Matrix4();

const FOLLOW_DRAG = 0.005;
/** The follow camera never dips closer than this to the ground or the water under it. */
const FOLLOW_CLEARANCE = 1;
const FOLLOW_PITCH: [number, number] = [0.05, 1.45];
const FOLLOW_DISTANCE: [number, number] = [3, 40];
/** The spring arm stops this far short of what it hits... */
const ARM_MARGIN = 0.3;
/** ...is never shorter than this (the avatar hides below 0.7 m)... */
const MIN_ARM = 0.25;
/** ...and eases back out at this rate (1/s) once clear; it pulls in at once. */
const ARM_RETURN = 3;
/** When the ground behind the player hides it, the camera tilts up in steps of this much (radians)... */
const LIFT_STEP = 0.1;
/** ...rising quickly and settling back slowly (1/s). */
const LIFT_RISE = 8;
const LIFT_FALL = 2;
/** The camera keeps this far from walls beside it (near plane 0.1 m: its corners reach ~0.09 m). */
const CAMERA_CLEARANCE = 0.25;
/** The eye eases along the vertical so the view doesn't bob over the terrain's facets... */
const EYE_SMOOTHING = 12;
/** ...but jumps when the player is moved (a drop). */
const EYE_JUMP = 3;
/** Swinging round what cuts the boom (camera-dodge.ts): it looks again this often (s) while swung or cut short... */
const DODGE_SEARCH_S = 0.25;
/** ...and eases round at this rate (1/s). */
const DODGE_RATE = 4;

const wrapAngle = (angle: number) =>
  Math.atan2(Math.sin(angle), Math.cos(angle));

/** The swing the boom eases to, where it is now, and the seconds until the next search. */
interface Dodging extends Swing {
  shownYaw: number;
  shownPitch: number;
  wait: number;
}

export function GlobeFollowCamera({
  terrain,
  playerRef,
  rigRef,
  walkRef,
  focusRef,
  dodge = false,
}: {
  terrain: GlobeTerrain;
  playerRef: RefObject<GlobePlayerState>;
  rigRef: RefObject<GlobeRig>;
  /** The walk's collisions for the spring arm (null until it is built). */
  walkRef: RefObject<GlobeWalk | null>;
  focusRef: RefObject<Vector3>;
  /** Swing round what cuts the boom short instead of pulling in to the face (following a citizen, not steering). */
  dodge?: boolean;
}) {
  const radius = terrain.globe.radius;
  const camera = useThree((state) => state.camera);
  const eyeHeight = useRef<number | null>(null);
  const swing = useRef<Dodging>({
    yaw: 0,
    pitch: 0,
    shownYaw: 0,
    shownPitch: 0,
    wait: 0,
  });

  useEffect(() => {
    const rig = rigRef.current;
    // switching into follow (C, the orbit handover) flies in from the current view
    if (rig.settled && !rig.flight) startFlight(rig, camera);
  }, [rigRef, camera]);

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

  useFrame((_, frameDelta) => {
    const delta = Math.min(frameDelta, MAX_FRAME);
    const { position, facing } = playerRef.current;
    const rig = rigRef.current;
    const walk = walkRef.current;
    /** Never closer than FOLLOW_CLEARANCE to the ground or the water under it (also while the walk loads). */
    const keepAbove = (point: Vector3) => {
      const ground = walk
        ? walk.floorAt(point)
        : Math.max(terrain.heightAt(point), WATER_SURFACE);
      const floor = radius + ground + FOLLOW_CLEARANCE;
      return point.length() < floor ? point.setLength(floor) : point;
    };
    up.copy(position).normalize();
    tangent(rig.heading, up, facing);
    const eyeTarget = position.length() + PLAYER_EYE_HEIGHT;
    const previous = eyeHeight.current;
    const smoothed =
      previous === null || Math.abs(eyeTarget - previous) > EYE_JUMP
        ? eyeTarget
        : previous + (eyeTarget - previous) * smoothing(EYE_SMOOTHING, delta);
    eyeHeight.current = smoothed;
    eye.copy(up).multiplyScalar(smoothed);
    // a slope behind the player tilts the camera up over it rather than pulling it in to the head
    let pitch = rig.pitch;
    const shown = swing.current;
    const aim = (angle: number, yaw = shown.shownYaw, out = offset) =>
      out
        .copy(rig.heading)
        .applyAxisAngle(up, yaw)
        .multiplyScalar(-Math.cos(angle))
        .addScaledVector(up, Math.sin(angle));
    while (
      walk &&
      pitch < FOLLOW_PITCH[1] &&
      !walk.aboveGround(
        eye,
        wanted.copy(eye).addScaledVector(aim(pitch), rig.distance),
        FOLLOW_CLEARANCE,
      )
    )
      pitch += LIFT_STEP;
    const lift = Math.min(pitch, FOLLOW_PITCH[1]) - rig.pitch;
    const lifted = lift > rig.lift;
    rig.lift +=
      (lift - rig.lift) *
      (rig.settled ? smoothing(lifted ? LIFT_RISE : LIFT_FALL, delta) : 1);
    const wantedPitch = rig.pitch + rig.lift;
    if (dodge && walk) {
      const reach = (yaw: number, angle: number) =>
        walk.cameraReach(
          eye,
          probeEnd
            .copy(eye)
            .addScaledVector(aim(angle, yaw, probe), rig.distance),
          FOLLOW_CLEARANCE,
        ) * rig.distance;
      const good = Math.min(rig.distance, DODGE_ARM);
      shown.wait -= delta;
      const swung = shown.yaw !== 0 || shown.pitch !== 0;
      if (
        shown.wait <= 0 &&
        (swung || reach(shown.yaw, wantedPitch + shown.pitch) < good)
      ) {
        Object.assign(shown, dodgeFor(wantedPitch, good, reach));
        shown.wait = DODGE_SEARCH_S;
      }
      const ease = rig.settled ? smoothing(DODGE_RATE, delta) : 1;
      shown.shownYaw = wrapAngle(
        shown.shownYaw + wrapAngle(shown.yaw - shown.shownYaw) * ease,
      );
      shown.shownPitch += (shown.pitch - shown.shownPitch) * ease;
    }
    aim(
      clamp(wantedPitch + shown.shownPitch, FOLLOW_PITCH[0], FOLLOW_PITCH[1]),
    );
    wanted.copy(eye).addScaledVector(offset, rig.distance);
    const reach = walk ? walk.cameraReach(eye, wanted, FOLLOW_CLEARANCE) : 1;
    const clear =
      reach >= 1
        ? rig.distance
        : Math.max(reach * rig.distance - ARM_MARGIN, MIN_ARM);
    rig.arm =
      clear < rig.arm || !rig.settled
        ? clear
        : rig.arm + (clear - rig.arm) * smoothing(ARM_RETURN, delta);
    wanted.copy(eye).addScaledVector(offset, rig.arm);
    if (walk) walk.clearCamera(wanted, CAMERA_CLEARANCE);
    rig.settled = true;

    const flight = rig.flight;
    if (flight) {
      flight.elapsed += delta;
      const t = easeInOut(Math.min(flight.elapsed / FLIGHT_SECONDS, 1));
      flightPoint(flight.from, wanted, t, radius, camera.position);
      keepAbove(camera.position);
      camera.up.copy(camera.position).normalize();
      looking.lookAt(camera.position, eye, camera.up);
      turnTo.setFromRotationMatrix(looking);
      camera.quaternion
        .copy(flight.quaternion)
        .slerp(turnTo, Math.min(t / 0.4, 1));
      if (flight.elapsed >= FLIGHT_SECONDS) rig.flight = null;
    } else {
      camera.position.copy(keepAbove(wanted));
      camera.up.copy(up);
      camera.lookAt(eye);
    }
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
/** When the clock goes past ×10 the orbit camera eases up to at least this altitude, to see the trails (10 §4.2.3). */
const TIME_LAPSE_ALTITUDE = 150;

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
  timeLapse,
  onHandover,
}: {
  radius: number;
  terrain: GlobeTerrain;
  playerRef: RefObject<GlobePlayerState>;
  focusRef: RefObject<Vector3>;
  timeLapse: boolean;
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

  useEffect(() => {
    const current = view.current;
    if (timeLapse)
      current.target = Math.max(current.target, radius + TIME_LAPSE_ALTITUDE);
  }, [timeLapse, radius]);

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
