import { Suspense, useCallback, useRef, useState } from 'react';

import { FollowCamera, type FollowRig } from './follow-camera';
import { Player } from './player';
import { createPlayerState, type PlayerMove } from './player-state';
import { useWalkWorld } from '@/hooks/use-walk-world';
import type {
  WalkPlacement,
  WalkSpawn,
  WalkWater,
} from '@/lib/world/collision';

type WalkerProps = {
  placements: WalkPlacement[];
  water: WalkWater[];
  /** Read once, on mount. */
  spawn: WalkSpawn;
  /** Called about 10 times a second with the player's position. */
  onPlayerMove?: (move: PlayerMove) => void;
  /** Called once colliders, ground surfaces and the animated avatar are loaded. */
  onReady?: () => void;
};

/**
 * A walkable place for the player, rendered inside an R3F <Canvas>: the avatar, its collisions and ground height.
 * Placements and water should be stable arrays (memoize them); a new array rebuilds the collision world.
 */
export function Walker({
  placements,
  water,
  spawn,
  onPlayerMove,
  onReady,
}: WalkerProps) {
  const world = useWalkWorld(placements, water);
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

  return (
    <>
      {world && (
        <Suspense fallback={null}>
          <Player
            world={world}
            placements={placements}
            playerRef={playerRef}
            steerable
            onReady={ready}
            onMove={onPlayerMove}
          />
        </Suspense>
      )}
      <FollowCamera playerRef={playerRef} rigRef={rigRef} />
    </>
  );
}
