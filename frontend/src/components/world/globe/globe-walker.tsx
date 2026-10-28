import {
  type RefObject,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Vector3 } from 'three';

import {
  CameraRange,
  GlobeFlyCamera,
  GlobeFollowCamera,
  GlobeOrbitCamera,
} from './globe-cameras';
import { type DropApi, GlobeDrop, type GoToSite } from './globe-drop';
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
import { useColliders } from '@/hooks/use-walk-world';
import type { Site } from '@/lib/client/types.gen';

import { type ColliderFile, colliderIdsOf } from '@/lib/world/collision';
import { type GlobeTerrain } from '@/lib/world/globe';
import { createGlobeWalk, type GlobeWalk } from '@/lib/world/globe-walk';
import type { Scatter } from '@/lib/world/scatter';
import {
  BLOCKING_SCATTER_ASSETS,
  createWildBlockers,
  siteCharts,
  townChart,
  type WalkTown,
} from '@/lib/world/walk-charts';

type GlobeWalkerProps = {
  terrain: GlobeTerrain;
  town: WalkTown;
  /** Camps and landmarks (their placements block). */
  sites: Site[];
  scatter: Scatter;
  /** Read once, on mount. */
  start: { position: Vector3; facing: Vector3 };
  cameraMode: CameraMode;
  onCameraModeChange: (mode: CameraMode) => void;
  travel: boolean;
  /** Kept on the surface point the active camera looks after (for the sun and the props). */
  focusRef: RefObject<Vector3>;
  /** Filled with the drop / go-to controls once the walk is ready. */
  dropRef: RefObject<DropApi | null>;
  goTo: GoToSite[];
  onPlayerMove?: (move: GlobeMove) => void;
  onReady?: () => void;
};

function WalkingPlayer({
  terrain,
  town,
  sites,
  scatter,
  colliders,
  walkRef,
  ...props
}: Pick<
  GlobeWalkerProps,
  'terrain' | 'town' | 'sites' | 'scatter' | 'travel'
> & {
  colliders: ReadonlyMap<string, ColliderFile>;
  walkRef: RefObject<GlobeWalk | null>;
  playerRef: RefObject<GlobePlayerState>;
  rigRef: RefObject<GlobeRig>;
  steerable: boolean;
  following: boolean;
  onReady: () => void;
  onMove?: (move: GlobeMove) => void;
}) {
  const proxies = useGroundProxies(town.placements);
  const walk = useMemo(() => {
    const radius = terrain.globe.radius;
    const wild = createWildBlockers(scatter, colliders, radius);
    const charts = [
      townChart(town, colliders, {
        heightAt: (world, point, fromY) =>
          groundHeight(world, proxies, point, fromY),
        maxStepUp: MAX_STEP_UP,
        probeHeight: PROBE_HEIGHT,
      }),
      ...siteCharts(terrain, sites, colliders, wild),
    ];
    return createGlobeWalk(terrain, charts, wild);
  }, [terrain, town, sites, scatter, colliders, proxies]);
  useEffect(() => {
    walkRef.current = walk;
    return () => {
      walkRef.current = null;
    };
  }, [walk, walkRef]);
  return <GlobePlayer walk={walk} radius={terrain.globe.radius} {...props} />;
}

/**
 * The player on the planet inside an R3F <Canvas>: the avatar, walking (with collisions in the town, at camps
 * and landmarks and against scattered props), the follow / orbit / fly cameras (C cycles them) and dropping
 * the player anywhere.
 */
export function GlobeWalker({
  terrain,
  town,
  sites,
  scatter,
  start,
  cameraMode,
  onCameraModeChange,
  travel,
  focusRef,
  dropRef,
  goTo,
  onPlayerMove,
  onReady,
}: GlobeWalkerProps) {
  const radius = terrain.globe.radius;
  const ids = useMemo(
    () => [
      ...colliderIdsOf(town.placements),
      ...sites.flatMap((site) => colliderIdsOf(site.placements ?? [])),
      ...BLOCKING_SCATTER_ASSETS,
    ],
    [town, sites],
  );
  const colliders = useColliders(ids);
  const [initial] = useState(() => {
    const player: GlobePlayerState = {
      position: start.position.clone(),
      facing: start.facing.clone(),
      ground: town.height,
    };
    const rig: GlobeRig = {
      heading: start.facing.clone(),
      pitch: 0.35,
      distance: 6,
      lift: 0,
      arm: 6,
      flight: null,
      settled: false,
    };
    return { player, rig };
  });
  const playerRef = useRef(initial.player);
  const rigRef = useRef(initial.rig);
  const walkRef = useRef<GlobeWalk | null>(null);
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
      {colliders && (
        <Suspense fallback={null}>
          <WalkingPlayer
            terrain={terrain}
            town={town}
            sites={sites}
            scatter={scatter}
            colliders={colliders}
            walkRef={walkRef}
            travel={travel}
            playerRef={playerRef}
            rigRef={rigRef}
            steerable={cameraMode === 'follow'}
            following={cameraMode === 'follow'}
            onReady={ready}
            onMove={onPlayerMove}
          />
        </Suspense>
      )}
      <GlobeDrop
        terrain={terrain}
        walkRef={walkRef}
        playerRef={playerRef}
        rigRef={rigRef}
        dropRef={dropRef}
        goTo={goTo}
        onCameraModeChange={onCameraModeChange}
      />
      {cameraMode === 'follow' && (
        <GlobeFollowCamera
          terrain={terrain}
          playerRef={playerRef}
          rigRef={rigRef}
          walkRef={walkRef}
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
