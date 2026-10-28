import { Canvas } from '@react-three/fiber';
import {
  memo,
  type RefObject,
  Suspense,
  useCallback,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useSearchParams } from 'react-router';
import { Matrix4, Vector3 } from 'three';

import { Button } from '@/components/ui/button';
import { BiomeScatter } from '@/components/world/globe/biome-scatter';
import { GlobeSites, GlobeTown } from '@/components/world/globe/globe-sites';
import { GlobeSky } from '@/components/world/globe/globe-sky';
import {
  GlobeSurface,
  type TerrainHole,
} from '@/components/world/globe/globe-surface';
import type { GlobeMove } from '@/components/world/globe/globe-player';
import {
  GlobeWalker,
  type WalkTown,
} from '@/components/world/globe/globe-walker';
import { VolcanoSmoke } from '@/components/world/globe/volcano-smoke';
import { LabelOverlay, LabelProjector } from '@/components/world/labels';
import {
  CAMERA_MODES,
  type CameraMode,
} from '@/components/world/player/camera-mode';
import { useKeys } from '@/components/world/player/use-keys';
import {
  type RenderStats,
  RenderStatsProbe,
} from '@/components/world/render-stats';
import { useLabelStore } from '@/hooks/use-label-store';
import { useTown } from '@/hooks/use-town';
import { useWorld } from '@/hooks/use-world';
import type { TownView } from '@/lib/client/types.gen';
import { BIOME_PROPS } from '@/lib/world/biome-props';
import {
  FAST_RATE,
  formatTime,
  type GameClock,
  createClock,
  localMinutes,
  NORMAL_RATE,
  parseTime,
  START_MINUTES,
} from '@/lib/world/game-clock';
import {
  anchorMapping,
  buildTerrain,
  decodeWorld,
  directionFromLatLon,
  type GlobeTerrain,
  latLonFromDirection,
  type SiteMapping,
  tangentFrame,
} from '@/lib/world/globe';
import { biomeColor } from '@/lib/world/globe-mesh';
import type { LabelStore } from '@/lib/world/label-store';
import { createScatter, type Scatter } from '@/lib/world/scatter';
import type { WorldView } from '@/lib/world/world-view';

/*
 * The planet at /: terrain, ocean, rivers, sites and the castle town, a sun on the game clock, and the player
 * walking out of the town into the wild. `?mock=1` uses the dev/test mock world; `?at=lat,lon[,bearing]` starts
 * the player somewhere else (bearing in degrees clockwise from north); `?time=HH:MM` sets the starting town time.
 */

/** The town's own ground disc (local metres): inside the 230 m plateau, around the ±160 m town. */
const TOWN_GROUND_RADIUS = 225;
/** Props keep this far from the town anchor (the plateau and its blend). */
const TOWN_CLEARING = 300;
/** ... and from camps and landmarks. */
const SITE_CLEARING = 45;
const LABEL_DISTANCE = 40;

interface Start {
  position: Vector3;
  facing: Vector3;
}

interface Planet {
  view: WorldView;
  terrain: GlobeTerrain;
  town: { mapping: SiteMapping; height: number; lon: number; grass: string };
  hole: TerrainHole;
  scatter: Scatter;
  volcano: { frame: ReturnType<typeof tangentFrame>; summit: number } | null;
}

function buildPlanet(view: WorldView): Planet {
  const globe = decodeWorld(view);
  const terrain = buildTerrain(globe);
  const site = view.sites.find((candidate) => candidate.kind === 'town');
  if (!site) throw new Error('the world has no town site');
  const up = new Vector3(...site.anchor.position);
  const height = site.anchor.height_m;
  const volcano = view.sites.find(
    (candidate) => candidate.id === 'smoking_mountain',
  );
  return {
    view,
    terrain,
    town: {
      mapping: anchorMapping(site.anchor, globe.radius),
      height,
      lon: latLonFromDirection(up).lon,
      grass: biomeColor(view.biome_names[globe.biomes[site.cell]]),
    },
    hole: {
      up,
      angle: Math.atan(TOWN_GROUND_RADIUS / (globe.radius + height)),
    },
    scatter: createScatter({
      terrain,
      seed: view.seed,
      frequency: view.frequency,
      biomeNames: view.biome_names,
      table: BIOME_PROPS,
      clearings: view.sites.map((candidate) => ({
        direction: new Vector3(...candidate.anchor.position),
        radius: candidate.kind === 'town' ? TOWN_CLEARING : SITE_CLEARING,
      })),
      rivers: view.rivers.map((river) => river.cells),
    }),
    volcano: volcano
      ? {
          frame: tangentFrame(new Vector3(...volcano.anchor.position)),
          summit: globe.radius + volcano.anchor.height_m,
        }
      : null,
  };
}

/** The town spawn mapped onto the planet, or `?at=lat,lon[,bearing]`. */
function startFor(planet: Planet, town: TownView, at: string | null): Start {
  const radius = planet.terrain.globe.radius;
  const parts = at?.split(',').map(Number) ?? [];
  if (parts.length >= 2 && parts.every(Number.isFinite)) {
    const [lat, lon, bearing = 0] = parts;
    const direction = directionFromLatLon(lat, lon);
    const { east, north } = tangentFrame(direction);
    const angle = (bearing * Math.PI) / 180;
    return {
      position: direction.multiplyScalar(radius),
      facing: north
        .multiplyScalar(Math.cos(angle))
        .addScaledVector(east, Math.sin(angle)),
    };
  }
  const { mapping } = planet.town;
  const { x, z, heading_deg } = town.spawn;
  const basis = mapping.basis(x, z, new Matrix4());
  const heading = (heading_deg * Math.PI) / 180;
  return {
    position: mapping.toWorld(x, 0, z, new Vector3()),
    facing: new Vector3()
      .setFromMatrixColumn(basis, 0)
      .multiplyScalar(Math.sin(heading))
      .addScaledVector(
        new Vector3().setFromMatrixColumn(basis, 2),
        Math.cos(heading),
      ),
  };
}

type GlobeSceneProps = {
  planet: Planet;
  town: TownView;
  walkTown: WalkTown;
  start: Start;
  labels: LabelStore;
  clockRef: RefObject<GameClock>;
  focusRef: RefObject<Vector3>;
  cameraMode: CameraMode;
  travel: boolean;
  ready: boolean;
  onCameraModeChange: (mode: CameraMode) => void;
  onPlayerMove: (move: GlobeMove) => void;
  onTick: (minutes: number) => void;
  onWalkReady: () => void;
  onPlacementsReady: () => void;
  onCitizenReady: (id: string) => void;
  onStats: (stats: ModeStats) => void;
};

type ModeStats = RenderStats & { mode: CameraMode };

const GlobeScene = memo(function GlobeScene({
  planet,
  town,
  walkTown,
  start,
  labels,
  clockRef,
  focusRef,
  cameraMode,
  travel,
  ready,
  onCameraModeChange,
  onPlayerMove,
  onTick,
  onWalkReady,
  onPlacementsReady,
  onCitizenReady,
  onStats,
}: GlobeSceneProps) {
  const { view, terrain } = planet;
  const rivers = useMemo(() => view.rivers.map((river) => river.cells), [view]);
  const sampleStats = useCallback(
    (sample: RenderStats) => onStats({ ...sample, mode: cameraMode }),
    [onStats, cameraMode],
  );
  return (
    <Canvas
      flat
      shadows="percentage"
      camera={{
        fov: 50,
        near: 0.1,
        far: 3000,
        position: start.position.clone().multiplyScalar(1.01),
      }}
      gl={{ preserveDrawingBuffer: true }}
    >
      <GlobeSky
        clockRef={clockRef}
        townLon={planet.town.lon}
        radius={terrain.globe.radius}
        focusRef={focusRef}
        onTick={onTick}
      />
      <GlobeSurface
        terrain={terrain}
        biomeNames={view.biome_names}
        rivers={rivers}
        hole={planet.hole}
      />
      {planet.volcano && (
        <VolcanoSmoke
          frame={planet.volcano.frame}
          summit={planet.volcano.summit}
        />
      )}
      <Suspense fallback={null}>
        <GlobeTown
          town={town}
          mapping={planet.town.mapping}
          groundRadius={TOWN_GROUND_RADIUS}
          grass={planet.town.grass}
          labels={labels}
          onPlacementsReady={onPlacementsReady}
          onCitizenReady={onCitizenReady}
        />
        <GlobeSites sites={view.sites} terrain={terrain} />
        <BiomeScatter
          scatter={planet.scatter}
          focusRef={focusRef}
          radius={terrain.globe.radius}
        />
      </Suspense>
      <GlobeWalker
        terrain={terrain}
        town={walkTown}
        start={start}
        cameraMode={cameraMode}
        onCameraModeChange={onCameraModeChange}
        travel={travel}
        focusRef={focusRef}
        onPlayerMove={onPlayerMove}
        onReady={onWalkReady}
      />
      <LabelProjector store={labels} maxDistance={LABEL_DISTANCE} />
      <RenderStatsProbe
        key={cameraMode}
        active={ready}
        onSample={sampleStats}
      />
    </Canvas>
  );
});

const round = (value: number) => value.toFixed(2);

function GlobeWorld({ view, town }: { view: WorldView; town: TownView }) {
  const [params] = useSearchParams();
  const planet = useMemo(() => buildPlanet(view), [view]);
  const at = params.get('at');
  const [start] = useState(() => startFor(planet, town, at));
  const walkTown = useMemo(
    (): WalkTown => ({
      mapping: planet.town.mapping,
      height: planet.town.height,
      placements: town.placements,
      water: town.water,
      groundRadius: TOWN_GROUND_RADIUS,
    }),
    [planet, town],
  );
  const labels = useLabelStore();
  const [startTime] = useState(
    () => parseTime(params.get('time')) ?? START_MINUTES,
  );
  const clockRef = useRef(createClock(startTime));
  const focusRef = useRef(start.position.clone());
  const [player, setPlayer] = useState<GlobeMove | null>(null);
  const [minutes, setMinutes] = useState(startTime);
  const [fastTime, setFastTime] = useState(false);
  const [travel, setTravel] = useState(false);
  const [walkReady, setWalkReady] = useState(false);
  const [placementsReady, setPlacementsReady] = useState(false);
  const [citizensReady, setCitizensReady] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [cameraMode, setCameraMode] = useState<CameraMode>('follow');
  const [stats, setStats] = useState<ModeStats | null>(null);
  const markWalkReady = useCallback(() => setWalkReady(true), []);
  const markPlacementsReady = useCallback(() => setPlacementsReady(true), []);
  const markCitizenReady = useCallback(
    (id: string) => setCitizensReady((ready) => new Set(ready).add(id)),
    [],
  );
  const ready = walkReady && placementsReady;

  const toggleFastTime = useCallback(() => {
    setFastTime((fast) => {
      clockRef.current.rate = fast ? NORMAL_RATE : FAST_RATE;
      return !fast;
    });
  }, []);
  useKeys(
    useCallback((code: string) => {
      if (code === 'KeyT') setTravel((on) => !on);
    }, []),
  );

  const localTime = player
    ? localMinutes(minutes, planet.town.lon, player.lon)
    : null;
  const biome = player ? view.biome_names[player.biome] : null;

  return (
    <div
      className="relative h-full w-full"
      data-testid="world"
      data-world-ready={ready}
      data-citizens-ready={citizensReady.size}
      data-player-x={player && round(player.x)}
      data-player-y={player && round(player.y)}
      data-player-z={player && round(player.z)}
      data-player-ground={player && round(player.ground)}
      data-player-lat={player && player.lat.toFixed(5)}
      data-player-lon={player && player.lon.toFixed(5)}
      data-player-biome={biome}
      data-town-x={player?.town && round(player.town.x)}
      data-town-z={player?.town && round(player.town.z)}
      data-camera-mode={cameraMode}
      data-camera-distance={player && round(player.cameraDistance)}
      data-game-minutes={Math.floor(minutes)}
      data-travel={travel}
      data-draw-calls={stats?.calls}
      data-draw-calls-mode={stats?.mode}
      data-triangles={stats?.triangles}
    >
      <GlobeScene
        planet={planet}
        town={town}
        walkTown={walkTown}
        start={start}
        labels={labels}
        clockRef={clockRef}
        focusRef={focusRef}
        cameraMode={cameraMode}
        travel={travel}
        ready={ready}
        onCameraModeChange={setCameraMode}
        onPlayerMove={setPlayer}
        onTick={setMinutes}
        onWalkReady={markWalkReady}
        onPlacementsReady={markPlacementsReady}
        onCitizenReady={markCitizenReady}
        onStats={setStats}
      />
      <LabelOverlay store={labels} />
      {!ready && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="rounded-lg bg-white/80 px-3 py-2 text-sm shadow">
            Loading the world…
          </span>
        </div>
      )}
      <div className="absolute top-3 left-3 flex flex-wrap items-center gap-2 rounded-lg bg-white/80 p-2 text-sm shadow">
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
        <Button
          size="sm"
          variant={travel ? 'default' : 'outline'}
          aria-pressed={travel}
          onClick={(event) => {
            setTravel((on) => !on);
            event.currentTarget.blur();
          }}
        >
          travel
        </Button>
        <Button
          size="sm"
          variant={fastTime ? 'default' : 'outline'}
          aria-pressed={fastTime}
          onClick={(event) => {
            toggleFastTime();
            event.currentTarget.blur();
          }}
        >
          time ×60
        </Button>
        <span>
          WASD move, Shift run, T travel (25 m/s), drag to look, wheel zoom, C
          camera
          {cameraMode === 'fly' && ', Q/E down/up'}
        </span>
      </div>
      {player && (
        <div className="absolute bottom-3 left-3 rounded-lg bg-white/80 px-2 py-1 font-mono text-xs shadow">
          {localTime !== null && formatTime(localTime)} ·{' '}
          {Math.abs(player.lat).toFixed(2)}°{player.lat >= 0 ? 'N' : 'S'}{' '}
          {Math.abs(player.lon).toFixed(2)}°{player.lon >= 0 ? 'E' : 'W'} ·{' '}
          {biome?.replace('_', ' ')}
          {player.town &&
            ` · town ${player.town.x.toFixed(0)}, ${player.town.z.toFixed(0)}`}
        </div>
      )}
    </div>
  );
}

function Message({
  testId,
  children,
}: {
  testId?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex h-full items-center justify-center p-6"
      data-testid={testId}
    >
      <div className="max-w-sm rounded-lg border p-4 text-sm">{children}</div>
    </div>
  );
}

export function GlobePage() {
  const world = useWorld();
  const town = useTown();
  const error = world.error ?? town.error;
  if (error)
    return (
      <Message testId="world-error">
        <p className="font-medium">The world could not be loaded.</p>
        <p className="text-muted-foreground mt-1">
          Is the backend running on port 8100? ({error.message})
        </p>
      </Message>
    );
  if (!world.data || !town.data)
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
        Loading the world…
      </div>
    );
  return <GlobeWorld view={world.data} town={town.data} />;
}
