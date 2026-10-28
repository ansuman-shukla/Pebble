import { Suspense, useCallback, useMemo, useRef, useState } from 'react';

import { type CameraMode, nextCameraMode } from './camera-mode';
import { FlyCamera } from './fly-camera';
import { FollowCamera, type FollowRig } from './follow-camera';
import { OrbitCamera, type PlaceBounds } from './orbit-camera';
import { Player } from './player';
import { createPlayerState, type PlayerMove } from './player-state';
import { useKeys } from './use-keys';
import { useWalkWorld } from '@/hooks/use-walk-world';
import type {
  Point,
  WalkPlacement,
  WalkSpawn,
  WalkWater,
} from '@/lib/world/collision';

const BOUNDS_MARGIN = 10;

function placeBounds(
  placements: WalkPlacement[],
  water: WalkWater[],
): PlaceBounds {
  const points: Point[] = [
    ...placements.map(({ x, z }): Point => [x, z]),
    ...water.flatMap((area) => area.polygon),
  ];
  const xs = points.map(([x]) => x);
  const zs = points.map(([, z]) => z);
  const [minX, maxX, minZ, maxZ] = [
    Math.min(...xs, 0),
    Math.max(...xs, 0),
    Math.min(...zs, 0),
    Math.max(...zs, 0),
  ];
  return {
    center: [(minX + maxX) / 2, (minZ + maxZ) / 2],
    size: Math.max(maxX - minX, maxZ - minZ) + BOUNDS_MARGIN,
  };
}

type WalkerProps = {
  placements: WalkPlacement[];
  water: WalkWater[];
  /** Read once, on mount. */
  spawn: WalkSpawn;
  /** Controlled camera mode; leave unset to let the walker keep its own (starting in follow). */
  cameraMode?: CameraMode;
  /** Called when C asks for the next camera mode. */
  onCameraModeChange?: (mode: CameraMode) => void;
  /** Called about 10 times a second with the player's position. */
  onPlayerMove?: (move: PlayerMove) => void;
  /** Called once colliders, ground surfaces and the animated avatar are loaded. */
  onReady?: () => void;
};

/**
 * A walkable place for the player, rendered inside an R3F <Canvas>: the avatar, its collisions and ground height,
 * and the follow / orbit / fly cameras. Placements and water should be stable arrays (memoize them); a new
 * array rebuilds the collision world.
 */
export function Walker({
  placements,
  water,
  spawn,
  cameraMode,
  onCameraModeChange,
  onPlayerMove,
  onReady,
}: WalkerProps) {
  const world = useWalkWorld(placements, water);
  const bounds = useMemo(
    () => placeBounds(placements, water),
    [placements, water],
  );
  const [initial] = useState(() => {
    const player = createPlayerState(spawn);
    const rig: FollowRig = {
      yaw: player.heading + Math.PI,
      pitch: 0.35,
      distance: 6,
    };
    return { player, rig };
  });
  const playerRef = useRef(initial.player);
  const rigRef = useRef(initial.rig);
  const ready = useCallback(() => onReady?.(), [onReady]);

  const [ownMode, setOwnMode] = useState<CameraMode>('follow');
  const mode = cameraMode ?? ownMode;
  useKeys(
    useCallback(
      (code: string) => {
        if (code !== 'KeyC') return;
        const next = nextCameraMode(mode);
        setOwnMode(next);
        onCameraModeChange?.(next);
      },
      [mode, onCameraModeChange],
    ),
  );

  return (
    <>
      {world && (
        <Suspense fallback={null}>
          <Player
            world={world}
            placements={placements}
            playerRef={playerRef}
            steerable={mode === 'follow'}
            onReady={ready}
            onMove={onPlayerMove}
          />
        </Suspense>
      )}
      {mode === 'follow' && (
        <FollowCamera playerRef={playerRef} rigRef={rigRef} />
      )}
      {mode === 'orbit' && <OrbitCamera bounds={bounds} />}
      {mode === 'fly' && <FlyCamera />}
    </>
  );
}
