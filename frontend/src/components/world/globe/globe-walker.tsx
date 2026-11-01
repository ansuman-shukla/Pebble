import { useThree } from '@react-three/fiber';
import {
  type ComponentProps,
  type RefObject,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
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
import { type GlobeTerrain, tangent, tangentFrame } from '@/lib/world/globe';
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
  /** The clock runs past ×10 (the orbit camera rises to see the trails). */
  timeLapse: boolean;
  /** Kept on the surface point the active camera looks after (for the sun and the props). */
  focusRef: RefObject<Vector3>;
  /** Filled with the drop / go-to controls once the walk is ready. */
  dropRef: RefObject<DropApi | null>;
  goTo: GoToSite[];
  /** Where the citizens' feet are (they are solid to the player). */
  peopleRef: RefObject<Map<string, Vector3>>;
  /** While set, the follow camera follows this pose (a citizen's) instead of the player, who stands still. */
  subjectRef: RefObject<GlobePlayerState> | null;
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
  peopleRef,
  ...props
}: Pick<
  GlobeWalkerProps,
  'terrain' | 'town' | 'sites' | 'scatter' | 'travel' | 'peopleRef'
> & {
  colliders: ReadonlyMap<string, ColliderFile>;
  walkRef: RefObject<GlobeWalk | null>;
  playerRef: RefObject<GlobePlayerState>;
  rigRef: RefObject<GlobeRig>;
  viewRigRef: RefObject<GlobeRig>;
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
    return createGlobeWalk(terrain, charts, wild, peopleRef);
  }, [terrain, town, sites, scatter, colliders, proxies, peopleRef]);
  useEffect(() => {
    walkRef.current = walk;
    return () => {
      walkRef.current = null;
    };
  }, [walk, walkRef]);
  return <GlobePlayer walk={walk} radius={terrain.globe.radius} {...props} />;
}

/** The follow camera around a citizen: it flies over from the current view, then orbits them as they move. */
function SubjectCamera({
  subjectRef,
  rigRef,
  ...props
}: Omit<ComponentProps<typeof GlobeFollowCamera>, 'playerRef'> & {
  subjectRef: RefObject<GlobePlayerState>;
}) {
  const camera = useThree((state) => state.camera);
  useLayoutEffect(() => {
    const rig = rigRef.current;
    const up = subjectRef.current.position.clone().normalize();
    // look at them the way the camera looks now
    tangent(
      rig.heading.copy(camera.getWorldDirection(new Vector3())),
      up,
      tangentFrame(up).north,
    );
    rig.settled = true;
    rig.flight = null;
  }, [rigRef, subjectRef, camera]);
  return (
    <GlobeFollowCamera
      playerRef={subjectRef}
      rigRef={rigRef}
      dodge
      {...props}
    />
  );
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
  timeLapse,
  focusRef,
  dropRef,
  goTo,
  peopleRef,
  subjectRef,
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
    return {
      player,
      rig,
      subjectRig: { ...rig, heading: rig.heading.clone() },
    };
  });
  const playerRef = useRef(initial.player);
  const rigRef = useRef(initial.rig);
  const subjectRigRef = useRef(initial.subjectRig);
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
            peopleRef={peopleRef}
            travel={travel}
            playerRef={playerRef}
            rigRef={rigRef}
            viewRigRef={subjectRef ? subjectRigRef : rigRef}
            steerable={cameraMode === 'follow' && !subjectRef}
            following={cameraMode === 'follow' && !subjectRef}
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
      {cameraMode === 'follow' && subjectRef && (
        <SubjectCamera
          key="subject"
          terrain={terrain}
          subjectRef={subjectRef}
          rigRef={subjectRigRef}
          walkRef={walkRef}
          focusRef={focusRef}
        />
      )}
      {cameraMode === 'follow' && !subjectRef && (
        <GlobeFollowCamera
          key="player"
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
          timeLapse={timeLapse}
          onHandover={handover}
        />
      )}
      {cameraMode === 'fly' && (
        <GlobeFlyCamera radius={radius} terrain={terrain} focusRef={focusRef} />
      )}
    </>
  );
}
