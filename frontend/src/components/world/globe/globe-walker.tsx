import { Suspense, useCallback, useMemo, useRef, useState } from 'react';
import type { Vector3 } from 'three';

import {
  CameraRange,
  GlobeFlyCamera,
  GlobeFollowCamera,
  GlobeOrbitCamera,
} from './globe-cameras';
import {
  type GlobeMove,
  GlobePlayer,
  type GlobePlayerState,
  type GlobeRig,
} from './globe-player';
import {
  type CameraMode,
  nextCameraMode,
} from '@/components/world/player/camera-mode';
import {
  groundHeight,
  useGroundProxies,
} from '@/components/world/player/ground';
import { MAX_STEP_UP, PROBE_HEIGHT } from '@/components/world/player/motion';
import { useKeys } from '@/components/world/player/use-keys';
import { useWalkWorld } from '@/hooks/use-walk-world';
import type {
  WalkPlacement,
  WalkWater,
  WalkWorld,
} from '@/lib/world/collision';
import type { GlobeTerrain, SiteMapping } from '@/lib/world/globe';
import { createGlobeWalk } from '@/lib/world/globe-walk';

/** The town on the globe as the walker needs it. */
export interface WalkTown {
  mapping: SiteMapping;
  /** Plateau height h0. */
  height: number;
  placements: WalkPlacement[];
  water: WalkWater[];
  /** Radius of the town's own ground disc (local metres). */
  groundRadius: number;
}

/** How far past its ground disc the town's collisions still apply. */
const CHART_MARGIN = 15;
const NO_PLACEMENTS: WalkPlacement[] = [];
const NO_WATER: WalkWater[] = [];

type GlobeWalkerProps = {
  terrain: GlobeTerrain;
  town: WalkTown | null;
  /** Read once, on mount. */
  start: { position: Vector3; facing: Vector3 };
  cameraMode: CameraMode;
  onCameraModeChange: (mode: CameraMode) => void;
  travel: boolean;
  /** Kept on the surface point the active camera looks after (for the sun and the props). */
  focusRef: React.RefObject<Vector3>;
  onPlayerMove?: (move: GlobeMove) => void;
  onReady?: () => void;
};

function GlobePlayerWithTown({
  terrain,
  town,
  world,
  ...props
}: Omit<
  GlobeWalkerProps,
  | 'cameraMode'
  | 'onCameraModeChange'
  | 'start'
  | 'focusRef'
  | 'onPlayerMove'
  | 'onReady'
> & {
  world: WalkWorld;
  playerRef: React.RefObject<GlobePlayerState>;
  rigRef: React.RefObject<GlobeRig>;
  steerable: boolean;
  onReady: () => void;
  onMove?: (move: GlobeMove) => void;
}) {
  const proxies = useGroundProxies(town?.placements ?? NO_PLACEMENTS);
  const walk = useMemo(
    () =>
      createGlobeWalk(
        terrain,
        town && {
          mapping: town.mapping,
          world,
          height: town.height,
          groundRadius: town.groundRadius,
          chartRadius: town.groundRadius + CHART_MARGIN,
          groundAt: (point, fromY) =>
            groundHeight(world, proxies, point, fromY),
          maxStepUp: MAX_STEP_UP,
          probeHeight: PROBE_HEIGHT,
        },
      ),
    [terrain, town, world, proxies],
  );
  return <GlobePlayer walk={walk} radius={terrain.globe.radius} {...props} />;
}

/**
 * The player on the planet inside an R3F <Canvas>: the avatar, walking (with the town's collisions inside the
 * town) and the follow / orbit / fly cameras; C cycles them.
 */
export function GlobeWalker({
  terrain,
  town,
  start,
  cameraMode,
  onCameraModeChange,
  travel,
  focusRef,
  onPlayerMove,
  onReady,
}: GlobeWalkerProps) {
  const radius = terrain.globe.radius;
  const world = useWalkWorld(
    town?.placements ?? NO_PLACEMENTS,
    town?.water ?? NO_WATER,
  );
  const [initial] = useState(() => {
    const player: GlobePlayerState = {
      position: start.position.clone(),
      facing: start.facing.clone(),
      ground: town?.height ?? 0,
    };
    const rig: GlobeRig = {
      heading: start.facing.clone(),
      pitch: 0.35,
      distance: 6,
    };
    return { player, rig };
  });
  const playerRef = useRef(initial.player);
  const rigRef = useRef(initial.rig);
  const ready = useCallback(() => onReady?.(), [onReady]);
  const handover = useCallback(
    () => onCameraModeChange('follow'),
    [onCameraModeChange],
  );

  useKeys(
    useCallback(
      (code: string) => {
        if (code === 'KeyC') onCameraModeChange(nextCameraMode(cameraMode));
      },
      [cameraMode, onCameraModeChange],
    ),
  );

  return (
    <>
      <CameraRange radius={radius} />
      {world && (
        <Suspense fallback={null}>
          <GlobePlayerWithTown
            terrain={terrain}
            town={town}
            world={world}
            travel={travel}
            playerRef={playerRef}
            rigRef={rigRef}
            steerable={cameraMode === 'follow'}
            onReady={ready}
            onMove={onPlayerMove}
          />
        </Suspense>
      )}
      {cameraMode === 'follow' && (
        <GlobeFollowCamera
          playerRef={playerRef}
          rigRef={rigRef}
          focusRef={focusRef}
        />
      )}
      {cameraMode === 'orbit' && (
        <GlobeOrbitCamera
          radius={radius}
          terrain={terrain}
          playerRef={playerRef}
          focusRef={focusRef}
          onHandover={handover}
        />
      )}
      {cameraMode === 'fly' && (
        <GlobeFlyCamera radius={radius} terrain={terrain} focusRef={focusRef} />
      )}
    </>
  );
}
