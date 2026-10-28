import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import { type Group, type Mesh, Vector3 } from 'three';

import { groundHeight, useGroundProxies } from './ground';
import type { PlayerMove, PlayerState } from './player-state';
import {
  axis,
  BACK,
  FORWARD,
  isRunning,
  LEFT,
  RIGHT,
  useKeys,
} from './use-keys';
import {
  type Point,
  resolveMove,
  type WalkPlacement,
  type WalkWorld,
} from '@/lib/world/collision';
import { VISITOR_LOOK } from '@/lib/world/visitor-look';
import { animate, type CharacterAnimation } from '@/vendor/polyfork/clips.mjs';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

const WALK_SPEED = 1.4;
const RUN_SPEED = 3.5;
/** Highest rise onto a walkable surface in one move; anything taller is a wall. */
const MAX_STEP_UP = 0.5;
/** Ground probes start this far above the current ground. */
const PROBE_HEIGHT = 1;
const MAX_FRAME = 0.1;
const MOVE_EVENT_INTERVAL = 0.1;

/** Frame-rate independent approach factor for exponential smoothing. */
const smoothing = (rate: number, delta: number) => 1 - Math.exp(-rate * delta);

function shortestTurn(from: number, to: number) {
  const turn = (to - from) % (Math.PI * 2);
  return turn > Math.PI
    ? turn - Math.PI * 2
    : turn < -Math.PI
      ? turn + Math.PI * 2
      : turn;
}

type PlayerProps = {
  world: WalkWorld;
  placements: WalkPlacement[];
  playerRef: RefObject<PlayerState>;
  /** Whether the keyboard steers the player (only in the follow camera). */
  steerable: boolean;
  onReady: () => void;
  onMove?: (move: PlayerMove) => void;
};

export function Player({
  world,
  placements,
  playerRef,
  steerable,
  onReady,
  onMove,
}: PlayerProps) {
  const proxies = useGroundProxies(placements);
  const keys = useKeys();
  const group = useRef<Group>(null);
  const character = useMemo(() => createCharacter(VISITOR_LOOK), []);
  const animation = useRef<CharacterAnimation | null>(null);
  const motion = useRef({ ground: 0, speed: 0, sinceEvent: Infinity });
  const forward = useMemo(() => new Vector3(), []);

  useEffect(() => {
    let mounted = true;
    animate(character).then((loaded) => {
      if (!mounted) return;
      animation.current = loaded;
      onReady();
    });
    return () => {
      mounted = false;
      animation.current = null;
      character.traverse((object) => (object as Mesh).geometry?.dispose());
    };
  }, [character, onReady]);

  useEffect(() => {
    const { position } = playerRef.current;
    const ground = groundHeight(
      world,
      proxies,
      [position.x, position.z],
      PROBE_HEIGHT,
    );
    motion.current.ground = ground;
    position.y = ground;
  }, [world, proxies, playerRef]);

  useFrame(({ camera }, frameDelta) => {
    const delta = Math.min(frameDelta, MAX_FRAME);
    const current = motion.current;
    const player = playerRef.current;
    const { position } = player;
    const from: Point = [position.x, position.z];
    let to = from;

    const ahead = steerable ? axis(keys.current, BACK, FORWARD) : 0;
    const aside = steerable ? axis(keys.current, LEFT, RIGHT) : 0;
    if (ahead || aside) {
      camera.getWorldDirection(forward);
      forward.setY(0).normalize();
      const dx = forward.x * ahead - forward.z * aside;
      const dz = forward.z * ahead + forward.x * aside;
      const length = Math.hypot(dx, dz);
      const step =
        ((isRunning(keys.current) ? RUN_SPEED : WALK_SPEED) * delta) / length;
      const probe = (point: Point) =>
        groundHeight(world, proxies, point, current.ground + PROBE_HEIGHT);
      to = resolveMove(
        world,
        from,
        [from[0] + dx * step, from[1] + dz * step],
        current.ground,
        (point) => probe(point) - current.ground <= MAX_STEP_UP,
      );
      player.heading +=
        shortestTurn(player.heading, Math.atan2(dx, dz)) * smoothing(12, delta);
      current.ground = probe(to);
    }

    position.x = to[0];
    position.z = to[1];
    position.y += (current.ground - position.y) * smoothing(14, delta);
    const speed = Math.hypot(to[0] - from[0], to[1] - from[1]) / delta;
    current.speed += (speed - current.speed) * smoothing(10, delta);

    group.current?.position.copy(position);
    group.current?.rotation.set(0, player.heading, 0);
    animation.current?.locomotion(current.speed);
    animation.current?.update(delta);

    current.sinceEvent += frameDelta;
    if (onMove && current.sinceEvent >= MOVE_EVENT_INTERVAL) {
      current.sinceEvent = 0;
      onMove({
        x: position.x,
        y: position.y,
        z: position.z,
        heading_deg: (player.heading * 180) / Math.PI,
      });
    }
  });

  return (
    <group ref={group}>
      <primitive object={character} />
    </group>
  );
}
