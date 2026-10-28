import { useGLTF } from '@react-three/drei';
import { Canvas } from '@react-three/fiber';
import { memo, Suspense, useCallback, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import {
  CAMERA_MODES,
  type CameraMode,
} from '@/components/world/player/camera-mode';
import type { PlayerMove } from '@/components/world/player/player-state';
import { Walker } from '@/components/world/player/walker';
import { assetBaseY, assetUrl } from '@/lib/world/assets';
import {
  assetIdForKind,
  type Point,
  type WalkPlacement,
  type WalkSpawn,
  type WalkWater,
} from '@/lib/world/collision';
import { openDoors } from '@/lib/world/doors';
import { groundShape } from '@/lib/world/ground-shape';

/*
 * A tiny hand-written yard for developing and testing the walker: a plaster wall with a gatehouse in the gap,
 * a moat north of it crossed by a bridge, a townhouse, a well and two cherry trees.
 */
const WALL_X = [4, 6, 8, 10, 12, 14, 16, 18, 20].flatMap((x) => [-x, x]);
const PLACEMENTS: WalkPlacement[] = [
  ...WALL_X.map((x): WalkPlacement => ({
    id: `wall-${x}`,
    kind: 'plaster_wall',
    x,
    z: -10,
    rotation_deg: 0,
    walk: 'solid',
  })),
  {
    id: 'gate',
    kind: 'castle_gatehouse',
    x: 0,
    z: -10,
    rotation_deg: 0,
    walk: 'solid',
  },
  {
    id: 'townhouse',
    kind: 'townhouse',
    x: 10,
    z: 0,
    rotation_deg: 270,
    walk: 'solid',
  },
  {
    id: 'bridge',
    kind: 'moat_bridge',
    x: 0,
    z: -19,
    rotation_deg: 90,
    walk: 'surface',
  },
  { id: 'well', kind: 'well', x: -8, z: 2, rotation_deg: 0, walk: 'solid' },
  {
    id: 'cherry-1',
    kind: 'cherry_tree',
    x: -4,
    z: 5,
    rotation_deg: 0,
    walk: 'solid',
  },
  {
    id: 'cherry-2',
    kind: 'cherry_tree',
    x: -15,
    z: -3,
    rotation_deg: 90,
    walk: 'solid',
  },
];
const MOAT: Point[] = [
  [-30, -22],
  [30, -22],
  [30, -16],
  [-30, -16],
];
const WATER: WalkWater[] = [{ polygon: MOAT }];
// the water surface reaches under the banks so the sky never shows through the ground's edge
const MOAT_SURFACE: Point[] = [
  [-31, -23],
  [31, -23],
  [31, -15],
  [-31, -15],
];
const SPAWN: WalkSpawn = { x: 0, z: 8, heading_deg: 180 };
const GROUND_HALF = 40;
const WATER_Y = -0.4;

function Ground() {
  const ground = useMemo(
    () =>
      groundShape(
        [
          [-GROUND_HALF, -GROUND_HALF],
          [GROUND_HALF, -GROUND_HALF],
          [GROUND_HALF, GROUND_HALF],
          [-GROUND_HALF, GROUND_HALF],
        ],
        WATER.map((water) => water.polygon),
      ),
    [],
  );
  const water = useMemo(() => groundShape(MOAT_SURFACE), []);
  return (
    <>
      <mesh geometry={ground} rotation-x={-Math.PI / 2}>
        <meshStandardMaterial color="#9fb37a" />
      </mesh>
      <mesh geometry={water} rotation-x={-Math.PI / 2} position-y={WATER_Y}>
        <meshStandardMaterial color="#4f86a8" />
      </mesh>
    </>
  );
}

function PlacementModel({ placement }: { placement: WalkPlacement }) {
  const id = assetIdForKind(placement.kind);
  const { scene } = useGLTF(assetUrl(id));
  const model = useMemo(() => {
    const copy = scene.clone(true);
    openDoors(copy, id);
    return copy;
  }, [scene, id]);
  return (
    <primitive
      object={model}
      position={[placement.x, assetBaseY(id), placement.z]}
      rotation-y={(placement.rotation_deg * Math.PI) / 180}
    />
  );
}

type SandboxSceneProps = {
  cameraMode: CameraMode;
  onCameraModeChange: (mode: CameraMode) => void;
  onPlayerMove: (move: PlayerMove) => void;
  onReady: () => void;
};

const SandboxScene = memo(function SandboxScene({
  cameraMode,
  onCameraModeChange,
  onPlayerMove,
  onReady,
}: SandboxSceneProps) {
  return (
    <Canvas
      flat
      camera={{ fov: 50, near: 0.1, far: 400 }}
      gl={{ preserveDrawingBuffer: true }}
    >
      <color attach="background" args={['#cfe3ef']} />
      <hemisphereLight args={['#ffffff', '#8a7a5a', 1.6]} />
      <directionalLight position={[20, 30, 15]} intensity={2.2} />
      <Ground />
      <Suspense fallback={null}>
        {PLACEMENTS.map((placement) => (
          <PlacementModel key={placement.id} placement={placement} />
        ))}
      </Suspense>
      <Walker
        placements={PLACEMENTS}
        water={WATER}
        spawn={SPAWN}
        cameraMode={cameraMode}
        onCameraModeChange={onCameraModeChange}
        onPlayerMove={onPlayerMove}
        onReady={onReady}
      />
    </Canvas>
  );
});

const round = (value: number) => value.toFixed(2);

export function WalkSandboxPage() {
  const [player, setPlayer] = useState<PlayerMove | null>(null);
  const [ready, setReady] = useState(false);
  const [cameraMode, setCameraMode] = useState<CameraMode>('follow');
  const markReady = useCallback(() => setReady(true), []);

  return (
    <div
      className="relative h-full w-full"
      data-testid="walk-sandbox"
      data-walk-ready={ready}
      data-player-x={player && round(player.x)}
      data-player-y={player && round(player.y)}
      data-player-z={player && round(player.z)}
    >
      <SandboxScene
        cameraMode={cameraMode}
        onCameraModeChange={setCameraMode}
        onPlayerMove={setPlayer}
        onReady={markReady}
      />
      <div className="absolute top-3 left-3 flex items-center gap-2 rounded-lg bg-white/80 p-2 text-sm shadow">
        {CAMERA_MODES.map((mode) => (
          <Button
            key={mode}
            size="sm"
            variant={mode === cameraMode ? 'default' : 'ghost'}
            aria-pressed={mode === cameraMode}
            onClick={(event) => {
              setCameraMode(mode);
              // hand the keyboard back to the scene (key presses on buttons are ignored)
              event.currentTarget.blur();
            }}
          >
            {mode}
          </Button>
        ))}
        <span>
          WASD move, Shift run, drag to look, C camera
          {cameraMode === 'fly' && ', Q/E down/up'}
        </span>
      </div>
    </div>
  );
}
