import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import { type Group, Matrix4, Vector3 } from 'three';

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

/** Fast travel for reviewing the planet (T toggles it). */
const TRAVEL_SPEED = 25;

/** The player's live pose on the planet, mutated every frame and read by the cameras. */
export interface GlobePlayerState {
  /** World position of the feet. */
  position: Vector3;
  /** Unit tangent the avatar faces. */
  facing: Vector3;
  /** Height above sea level of the ground under the player. */
  ground: number;
}

/** Third-person rig, kept by the walker so it survives camera switches. */
export interface GlobeRig {
  /** Unit tangent the camera looks along (the player walks relative to it). */
  heading: Vector3;
  pitch: number;
  distance: number;
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
}

const up = new Vector3();
const forward = new Vector3();
const right = new Vector3();
const step = new Vector3();
const side = new Vector3();
const basis = new Matrix4();

export function GlobePlayer({
  walk,
  radius,
  playerRef,
  rigRef,
  steerable,
  travel,
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
  onReady: () => void;
  onMove?: (move: GlobeMove) => void;
}) {
  const keys = useKeys();
  const group = useRef<Group>(null);
  const { character, animation } = useVisitor(onReady);
  const motion = useRef({ speed: 0, sinceEvent: Infinity });
  const previous = useMemo(() => new Vector3(), []);

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
    const { position, facing } = player;
    previous.copy(position);
    up.copy(position).normalize();

    const ahead = steerable ? axis(keys.current, BACK, FORWARD) : 0;
    const aside = steerable ? axis(keys.current, LEFT, RIGHT) : 0;
    let height = position.length();
    if (ahead || aside) {
      tangent(forward.copy(rigRef.current.heading), up, facing);
      right.crossVectors(forward, up);
      step
        .copy(forward)
        .multiplyScalar(ahead)
        .addScaledVector(right, aside)
        .normalize();
      const speed = travel
        ? TRAVEL_SPEED
        : isRunning(keys.current)
          ? RUN_SPEED
          : WALK_SPEED;
      // turn towards the move: signed angle from facing to step about up
      const turn = Math.atan2(
        side.crossVectors(facing, step).dot(up),
        facing.dot(step),
      );
      facing.applyAxisAngle(up, turn * smoothing(12, delta));
      const direction = walk.move(
        position,
        step.multiplyScalar(speed * delta),
        player.ground,
      );
      player.ground = walk.groundAt(direction, player.ground);
      position.copy(direction).multiplyScalar(height);
      up.copy(direction);
      tangent(facing, up, forward);
      tangent(rigRef.current.heading, up, facing);
    }
    height += (radius + player.ground - height) * smoothing(14, delta);
    position.setLength(height);
    const speed = previous.distanceTo(position) / delta;
    current.speed += (speed - current.speed) * smoothing(10, delta);

    const avatar = group.current;
    if (avatar) {
      avatar.position.copy(position);
      basis.makeBasis(side.crossVectors(up, facing), up, facing);
      avatar.quaternion.setFromRotationMatrix(basis);
    }
    animation.current?.locomotion(Math.min(current.speed, RUN_SPEED * 1.2));
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
      });
    }
  });

  return (
    <group ref={group}>
      <primitive object={character} />
    </group>
  );
}
