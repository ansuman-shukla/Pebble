import { Canvas, useFrame } from '@react-three/fiber';
import { memo, Suspense, useCallback, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { LabelOverlay, LabelProjector } from '@/components/world/labels';
import {
  CAMERA_MODES,
  type CameraMode,
} from '@/components/world/player/camera-mode';
import type { PlayerMove } from '@/components/world/player/player-state';
import { Walker } from '@/components/world/player/walker';
import { TownCitizens } from '@/components/world/town/town-citizens';
import { TownGround } from '@/components/world/town/town-ground';
import { TownPlacements } from '@/components/world/town/town-placements';
import { TownSky } from '@/components/world/town/town-sky';
import { useLabelStore } from '@/hooks/use-label-store';
import { useTown } from '@/hooks/use-town';
import type { TownView } from '@/lib/client/types.gen';
import type { LabelStore } from '@/lib/world/label-store';

/** Citizen names show only this close to the camera, so the town isn't covered in labels. */
const LABEL_DISTANCE = 40;
/** Frames rendered after everything is ready before the renderer's counters are sampled. */
const STATS_AFTER_FRAMES = 30;

interface RenderStats {
  calls: number;
  triangles: number;
}

/** Samples the renderer's draw calls and triangles once, after `active` has held for a few frames. */
function RenderStatsProbe({
  active,
  onSample,
}: {
  active: boolean;
  onSample: (stats: RenderStats) => void;
}) {
  const frames = useRef(0);
  // useFrame runs before the frame renders, so gl.info still holds the previous frame's counts
  useFrame(({ gl }) => {
    if (!active || frames.current < 0) return;
    frames.current += 1;
    if (frames.current < STATS_AFTER_FRAMES) return;
    frames.current = -1;
    const { calls, triangles } = gl.info.render;
    onSample({ calls, triangles });
  });
  return null;
}

type TownSceneProps = {
  town: TownView;
  labels: LabelStore;
  cameraMode: CameraMode;
  ready: boolean;
  onCameraModeChange: (mode: CameraMode) => void;
  onPlayerMove: (move: PlayerMove) => void;
  onWalkReady: () => void;
  onPlacementsReady: () => void;
  onCitizenReady: (id: string) => void;
  onStats: (stats: RenderStats) => void;
};

const TownScene = memo(function TownScene({
  town,
  labels,
  cameraMode,
  ready,
  onCameraModeChange,
  onPlayerMove,
  onWalkReady,
  onPlacementsReady,
  onCitizenReady,
  onStats,
}: TownSceneProps) {
  return (
    <Canvas
      flat
      shadows="percentage"
      camera={{ fov: 50, near: 0.1, far: 1500 }}
      gl={{ preserveDrawingBuffer: true }}
    >
      <TownSky />
      <TownGround areas={town.areas} water={town.water} />
      <Suspense fallback={null}>
        <TownPlacements
          placements={town.placements}
          onReady={onPlacementsReady}
        />
      </Suspense>
      <TownCitizens
        citizens={town.citizens}
        labels={labels}
        onReady={onCitizenReady}
      />
      <Walker
        placements={town.placements}
        water={town.water}
        spawn={town.spawn}
        cameraMode={cameraMode}
        onCameraModeChange={onCameraModeChange}
        onPlayerMove={onPlayerMove}
        onReady={onWalkReady}
      />
      <LabelProjector store={labels} maxDistance={LABEL_DISTANCE} />
      <RenderStatsProbe active={ready} onSample={onStats} />
    </Canvas>
  );
});

const round = (value: number) => value.toFixed(2);

function TownWorld({ town }: { town: TownView }) {
  const labels = useLabelStore();
  const [player, setPlayer] = useState<PlayerMove | null>(null);
  const [walkReady, setWalkReady] = useState(false);
  const [placementsReady, setPlacementsReady] = useState(false);
  const [citizensReady, setCitizensReady] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [cameraMode, setCameraMode] = useState<CameraMode>('follow');
  const [stats, setStats] = useState<RenderStats | null>(null);
  const markWalkReady = useCallback(() => setWalkReady(true), []);
  const markPlacementsReady = useCallback(() => setPlacementsReady(true), []);
  const markCitizenReady = useCallback(
    (id: string) => setCitizensReady((ready) => new Set(ready).add(id)),
    [],
  );
  const ready = walkReady && placementsReady;

  return (
    <div
      className="relative h-full w-full"
      data-testid="world"
      data-world-ready={ready}
      data-citizens-ready={citizensReady.size}
      data-player-x={player && round(player.x)}
      data-player-y={player && round(player.y)}
      data-player-z={player && round(player.z)}
      data-draw-calls={stats?.calls}
      data-triangles={stats?.triangles}
    >
      <TownScene
        town={town}
        labels={labels}
        cameraMode={cameraMode}
        ready={ready}
        onCameraModeChange={setCameraMode}
        onPlayerMove={setPlayer}
        onWalkReady={markWalkReady}
        onPlacementsReady={markPlacementsReady}
        onCitizenReady={markCitizenReady}
        onStats={setStats}
      />
      <LabelOverlay store={labels} />
      {!ready && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="rounded-lg bg-white/80 px-3 py-2 text-sm shadow">
            Loading the town…
          </span>
        </div>
      )}
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
      {player && (
        <div className="absolute bottom-3 left-3 rounded-lg bg-white/80 px-2 py-1 font-mono text-xs shadow">
          x {player.x.toFixed(1)} z {player.z.toFixed(1)}
        </div>
      )}
    </div>
  );
}

export function WorldPage() {
  const town = useTown();
  if (town.isError)
    return (
      <div
        className="flex h-full items-center justify-center p-6"
        data-testid="world-error"
      >
        <div className="max-w-sm rounded-lg border p-4 text-sm">
          <p className="font-medium">The town could not be loaded.</p>
          <p className="text-muted-foreground mt-1">
            Is the backend running on port 8100? ({town.error.message})
          </p>
        </div>
      </div>
    );
  if (!town.data)
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
        Loading the town…
      </div>
    );
  return <TownWorld town={town.data} />;
}
