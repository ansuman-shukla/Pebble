import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import { type Group, Matrix4, type Quaternion, Vector3 } from 'three';

import {
  MAX_FRAME,
  MOVE_EVENT_INTERVAL,
  RUN_SPEED,
  smoothing,
  WALK_SPEED,
} from '@/components/world/player/motion';
import {
  axis,
  BACK,
  FORWARD,
  isRunning,
  LEFT,
  RIGHT,
  useKeys,
} from '@/components/world/player/use-keys';
import { useVisitor } from '@/components/world/player/use-visitor';
import { latLonFromDirection, tangent } from '@/lib/world/globe';
import type { GlobeWalk } from '@/lib/world/globe-walk';

/** Fast travel for reviewing the planet (T toggles it); it skips scattered props and the slope limit. */
const TRAVEL_SPEED = 25;
/** How quickly the pace follows the keys (1/s): about 0.3 s from standing to a walk. */
const ACCELERATION = 10;
/** Pace on the steepest walkable slope, uphill and downhill, as a share of the flat pace. */
const UPHILL_PACE = 0.4;
const DOWNHILL_PACE = 0.75;
/** Ground changes bigger than this in one frame (a step up onto paving or a bridge) are eased, not snapped. */
const STEP_EASE = 0.25;
/** The avatar hides when the camera is pulled in closer than this (it would fill the view). */
const HIDE_ARM = 0.7;

/** The player's live pose on the planet, mutated every frame and read by the cameras. */
export interface GlobePlayerState {
  /** World position of the feet. */
  position: Vector3;
  /** Unit tangent the avatar faces. */
  facing: Vector3;
  /** Height above sea level of the ground under the player. */
  ground: number;
}

/** The camera easing from where it was into the follow view (after a drop or a camera switch). */
interface CameraFlight {
  from: Vector3;
  quaternion: Quaternion;
  elapsed: number;
}

/** Third-person rig, kept by the walker so it survives camera switches. */
export interface GlobeRig {
  /** Unit tangent the camera looks along (the player walks relative to it). */
  heading: Vector3;
  pitch: number;
  /** Wanted distance of the camera from the player's eye (wheel zoom). */
  distance: number;
  /** Extra pitch (radians) that keeps the camera above a slope behind the player. */
  lift: number;
  /** Spring arm: the distance actually used, shortened where something stands between camera and player. */
  arm: number;
  flight: CameraFlight | null;
  /** False until the follow view has rendered once (the very first follow view doesn't fly in). */
  settled: boolean;
}

/** What the page gets about the player, about 10 times a second. */
export interface GlobeMove {
  x: number;
  y: number;
  z: number;
  ground: number;
  lat: number;
  lon: number;
  biome: number;
  /** Town local metres while inside the town's chart. */
  town: { x: number; z: number } | null;
  cameraDistance: number;
  /** Camera world position and quaternion (x, y, z, qx, qy, qz, qw). */
  camera: number[];
  /** Spring arm length (follow view). */
  arm: number;
  flying: boolean;
  /** Avatar world position and quaternion (x, y, z, qx, qy, qz, qw). */
  avatar: number[];
  /** The locomotion clip playing (null until the clips load). */
  clip: string | null;
  /** Left then right foot in the avatar's own frame (x, y, z each). */
  feet: number[];
}

const up = new Vector3();
const forward = new Vector3();
const right = new Vector3();
const step = new Vector3();
const side = new Vector3();
const basis = new Matrix4();
const foot = new Vector3();

/** Pace multiplier for walking along a slope of `grade` (rise per metre, negative downhill). */
function slopePace(grade: number) {
  const steepness = Math.min(Math.abs(grade), 1);
  return 1 - steepness * (1 - (grade > 0 ? UPHILL_PACE : DOWNHILL_PACE));
}

export function GlobePlayer({
  walk,
  radius,
  playerRef,
  rigRef,
  steerable,
  travel,
  following,
  onReady,
  onMove,
}: {
  walk: GlobeWalk;
  radius: number;
  playerRef: RefObject<GlobePlayerState>;
  rigRef: RefObject<GlobeRig>;
  /** Whether the keyboard steers the player (only in the follow camera). */
  steerable: boolean;
  travel: boolean;
  /** In the follow view the avatar hides whenever the spring arm is very short. */
  following: boolean;
  onReady: () => void;
  onMove?: (move: GlobeMove) => void;
}) {
  const keys = useKeys();
  const group = useRef<Group>(null);
  const { character, animation } = useVisitor(onReady);
  const feet = useMemo(
    () =>
      ['LeftFoot', 'RightFoot'].flatMap(
        (name) => character.getObjectByName(name) ?? [],
      ),
    [character],
  );
  const motion = useRef({
    speed: 0,
    pace: 0,
    sinceEvent: Infinity,
    clip: null as string | null,
  });
  const previous = useMemo(() => new Vector3(), []);
  const heading = useMemo(() => new Vector3(), []);

  useEffect(() => {
    const player = playerRef.current;
    const direction = player.position.clone().normalize();
    player.ground = walk.groundAt(direction, player.ground);
    player.position.copy(direction).multiplyScalar(radius + player.ground);
  }, [walk, radius, playerRef]);

  useFrame(({ camera }, frameDelta) => {
    const delta = Math.min(frameDelta, MAX_FRAME);
    const current = motion.current;
    const player = playerRef.current;
    const rig = rigRef.current;
    const { position, facing } = player;
    previous.copy(position);
    up.copy(position).normalize();

    const live = steerable && !rig.flight;
    const ahead = live ? axis(keys.current, BACK, FORWARD) : 0;
    const aside = live ? axis(keys.current, LEFT, RIGHT) : 0;
    let height = position.length();
    if (ahead || aside) {
      tangent(forward.copy(rig.heading), up, facing);
      right.crossVectors(forward, up);
      heading
        .copy(forward)
        .multiplyScalar(ahead)
        .addScaledVector(right, aside)
        .normalize();
      // turn towards the move: signed angle from facing to the heading about up
      const turn = Math.atan2(
        side.crossVectors(facing, heading).dot(up),
        facing.dot(heading),
      );
      facing.applyAxisAngle(up, turn * smoothing(12, delta));
    }
    const wanted =
      ahead || aside
        ? travel
          ? TRAVEL_SPEED
          : (isRunning(keys.current) ? RUN_SPEED : WALK_SPEED) *
            slopePace(walk.grade(position, heading))
        : 0;
    current.pace += (wanted - current.pace) * smoothing(ACCELERATION, delta);
    if (wanted === 0 && current.pace < 0.05) current.pace = 0;

    // a zero step still pushes the player out of townspeople walking into it
    step.copy(heading).multiplyScalar(current.pace * delta);
    const direction = walk.move(position, step, player.ground, travel);
    const moved = direction.angleTo(up) * radius;
    player.ground = walk.groundAt(direction, player.ground);
    up.copy(direction);
    tangent(facing, up, forward);
    tangent(rig.heading, up, facing);
    const target = radius + player.ground;
    // the terrain is continuous: follow it exactly (no sinking on slopes); ease real steps
    if (Math.abs(target - height) <= STEP_EASE + moved * 2) height = target;
    else height += (target - height) * smoothing(14, delta);
    position.copy(direction).multiplyScalar(height);
    const speed = previous.distanceTo(position) / delta;
    current.speed += (speed - current.speed) * smoothing(10, delta);

    const avatar = group.current;
    if (avatar) {
      avatar.position.copy(position);
      basis.makeBasis(side.crossVectors(up, facing), up, facing);
      avatar.quaternion.setFromRotationMatrix(basis);
      avatar.visible = !following || rig.flight !== null || rig.arm > HIDE_ARM;
    }
    const action = animation.current?.locomotion(
      Math.min(current.speed, RUN_SPEED * 1.2),
    );
    current.clip = action?.getClip().name ?? null;
    animation.current?.update(delta);

    current.sinceEvent += frameDelta;
    if (onMove && current.sinceEvent >= MOVE_EVENT_INTERVAL) {
      current.sinceEvent = 0;
      const { lat, lon } = latLonFromDirection(position);
      const town = walk.townPoint(position);
      onMove({
        x: position.x,
        y: position.y,
        z: position.z,
        ground: player.ground,
        lat,
        lon,
        biome: walk.biomeAt(position),
        town: town && { x: town[0], z: town[1] },
        cameraDistance: camera.position.length(),
        camera: [...camera.position.toArray(), ...camera.quaternion.toArray()],
        arm: rig.arm,
        flying: rig.flight !== null,
        avatar: avatar
          ? [...avatar.position.toArray(), ...avatar.quaternion.toArray()]
          : [],
        clip: current.clip,
        feet: avatar
          ? feet.flatMap((bone) =>
              avatar.worldToLocal(bone.getWorldPosition(foot)).toArray(),
            )
          : [],
      });
    }
  });

  return (
    <group ref={group}>
      <primitive object={character} />
    </group>
  );
}
