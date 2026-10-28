import { Canvas } from '@react-three/fiber';
import {
  memo,
  type RefObject,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { useSearchParams } from 'react-router';
import { Matrix4, Vector3 } from 'three';

import { Button } from '@/components/ui/button';
import { BiomeScatter } from '@/components/world/globe/biome-scatter';
import {
  type DropApi,
  type DropResult,
  type DropTarget,
  type GoToSite,
} from '@/components/world/globe/globe-drop';
import {
  GoToMenu,
  Pegman,
  PEGMAN_DRAG,
  DropPin,
} from '@/components/world/globe/globe-explore-ui';
import { GlobeNpcs, type NpcViews } from '@/components/world/globe/globe-npcs';
import { GlobeSites, GlobeTown } from '@/components/world/globe/globe-sites';
import { GlobeSky } from '@/components/world/globe/globe-sky';
import {
  GlobeSurface,
  type TerrainHole,
} from '@/components/world/globe/globe-surface';
import type {
  GlobeMove,
  GlobePlayerState,
} from '@/components/world/globe/globe-player';
import { GlobeWalker } from '@/components/world/globe/globe-walker';
import {
  LiveClock,
  NpcHooks,
  PeoplePanel,
} from '@/components/world/globe/live-ui';
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
import { type LiveFeed, useLiveCitizens } from '@/hooks/use-live-citizens';
import { useTown } from '@/hooks/use-town';
import { useWorld } from '@/hooks/use-world';
import type { TownView, WorldView } from '@/lib/client/types.gen';
import { feedMinutes } from '@/lib/live/live-state';
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
import { clipWater } from '@/lib/world/ground-shape';
import type { LabelStore } from '@/lib/world/label-store';
import { createScatter, type Scatter } from '@/lib/world/scatter';
import type { WalkTown } from '@/lib/world/walk-charts';

/*
 * The planet at /: terrain, ocean, rivers, sites and the castle town, a sun on the game clock, and the player
 * walking out of the town into the wild, among the live citizens. `?mock=1` uses the dev/test mock world,
 * `?mockLive=1` the dev/test mock feed; `?at=lat,lon[,bearing]` starts the player somewhere else (bearing in
 * degrees clockwise from north); `?time=HH:MM` sets the starting town time (while no feed is live).
 */

/** The town's own ground disc (local metres): inside the 230 m plateau, around the ±160 m town. */
const TOWN_GROUND_RADIUS = 225;
/** Props keep this far from the town anchor (the plateau and its blend). */
const TOWN_CLEARING = 300;
/** ... and from camps and landmarks. */
const SITE_CLEARING = 45;
/** The readout names a camp or landmark within this many metres of its anchor (the town: its clearing). */
const SITE_NEARBY = 100;
const LABEL_DISTANCE = 40;

interface Start {
  position: Vector3;
  facing: Vector3;
}

interface PlanetSite {
  id: string;
  name: string;
  direction: Vector3;
  /** Metres from the anchor within which the player is "at" the site. */
  reach: number;
}

interface Planet {
  view: WorldView;
  sites: PlanetSite[];
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
    sites: view.sites.map((candidate) => ({
      id: candidate.id,
      name: candidate.name,
      direction: new Vector3(...candidate.anchor.position),
      reach: candidate.kind === 'town' ? TOWN_CLEARING : SITE_NEARBY,
    })),
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

/** The site the player stands at, if any. */
function siteAt(planet: Planet, move: GlobeMove): PlanetSite | null {
  const here = new Vector3(move.x, move.y, move.z).normalize();
  const radius = planet.terrain.globe.radius;
  return (
    planet.sites.find(
      (site) => here.angleTo(site.direction) * radius < site.reach,
    ) ?? null
  );
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
  live: LiveFeed['state'];
  peopleRef: RefObject<Map<string, Vector3>>;
  npcViews: NpcViews;
  followId: string | null;
  subjectRef: RefObject<GlobePlayerState>;
  start: Start;
  dropRef: RefObject<DropApi | null>;
  goTo: GoToSite[];
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
  onStats: (stats: ModeStats) => void;
};

type ModeStats = RenderStats & { mode: CameraMode };

const GlobeScene = memo(function GlobeScene({
  planet,
  town,
  walkTown,
  live,
  peopleRef,
  npcViews,
  followId,
  subjectRef,
  start,
  dropRef,
  goTo,
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
          water={walkTown.water}
          mapping={planet.town.mapping}
          groundRadius={TOWN_GROUND_RADIUS}
          grass={planet.town.grass}
          onPlacementsReady={onPlacementsReady}
        />
        <GlobeSites sites={view.sites} terrain={terrain} />
        <BiomeScatter
          scatter={planet.scatter}
          focusRef={focusRef}
          radius={terrain.globe.radius}
        />
      </Suspense>
      <GlobeNpcs
        citizens={live.citizens}
        tick={live.tick}
        speech={live.speech}
        terrain={terrain}
        town={walkTown}
        labels={labels}
        peopleRef={peopleRef}
        views={npcViews}
        followId={followId}
        subjectRef={subjectRef}
      />
      <GlobeWalker
        terrain={terrain}
        town={walkTown}
        sites={view.sites}
        scatter={planet.scatter}
        start={start}
        dropRef={dropRef}
        goTo={goTo}
        peopleRef={peopleRef}
        subjectRef={followId ? subjectRef : null}
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

/** The "Go to" sites: the town at its spawn by the main gate, then every camp and landmark. */
function goToSites(planet: Planet, town: TownView): GoToSite[] {
  const radius = planet.terrain.globe.radius;
  return planet.view.sites.map((site) => ({
    id: site.id,
    name: site.name,
    mapping: anchorMapping(site.anchor, radius),
    spawn: site.kind === 'town' ? startFor(planet, town, null) : null,
  }));
}

const DROP_MESSAGES: Record<
  Exclude<DropResult, { ok: true }>['reason'],
  string
> = {
  water: "That's water. Pick a spot on land.",
  miss: 'Pick a spot on the planet.',
  loading: 'Still loading, try again in a moment.',
};
/** How long a drop message stays up, ms. */
const MESSAGE_MS = 4000;
/** A press that moves less than this (px) is a click, not a drag. */
const CLICK_SLOP = 6;

function GlobeWorld({ view, town }: { view: WorldView; town: TownView }) {
  const [params] = useSearchParams();
  const planet = useMemo(() => buildPlanet(view), [view]);
  const at = params.get('at');
  const [start] = useState(() => startFor(planet, town, at));
  // the stream runs on past the ground disc; outside it the terrain's own water rules
  const townWater = useMemo(
    () => clipWater(town.water, TOWN_GROUND_RADIUS),
    [town],
  );
  const walkTown = useMemo(
    (): WalkTown => ({
      mapping: planet.town.mapping,
      height: planet.town.height,
      placements: town.placements,
      water: townWater,
      groundRadius: TOWN_GROUND_RADIUS,
    }),
    [planet, town, townWater],
  );
  const goTo = useMemo(() => goToSites(planet, town), [planet, town]);
  const dropRef = useRef<DropApi | null>(null);
  const [dropping, setDropping] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const press = useRef<{ x: number; y: number } | null>(null);
  /** Where the pin hovers while dropping (client pixels) and what is under it. */
  const [hover, setHover] = useState<{
    x: number;
    y: number;
    target: DropTarget;
  } | null>(null);
  const hoverAt = useCallback((clientX: number, clientY: number) => {
    const target = dropRef.current?.probe(clientX, clientY) ?? null;
    setHover({ x: clientX, y: clientY, target });
  }, []);

  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(null), MESSAGE_MS);
    return () => window.clearTimeout(timer);
  }, [message]);

  /** Shows the outcome of a drop; a successful one goes into `?at=` so the spot can be shared. */
  const settle = useCallback((result: DropResult) => {
    if (!result.ok) {
      setMessage(DROP_MESSAGES[result.reason]);
      return;
    }
    setMessage(null);
    setDropping(false);
    setHover(null);
    // replace the URL in place (commas kept readable); `?at=` is only read on load
    const rest = window.location.search
      .slice(1)
      .split('&')
      .filter((part) => part && !part.startsWith('at='))
      .join('&');
    const spot = [
      result.lat.toFixed(5),
      result.lon.toFixed(5),
      Math.round(result.bearing) % 360,
    ].join(',');
    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}?at=${spot}${rest ? `&${rest}` : ''}`,
    );
  }, []);
  const dropAtScreen = useCallback(
    (clientX: number, clientY: number) => {
      const api = dropRef.current;
      settle(
        api ? api.atScreen(clientX, clientY) : { ok: false, reason: 'loading' },
      );
    },
    [settle],
  );
  const goToSite = useCallback(
    (id: string) => {
      const api = dropRef.current;
      settle(api ? api.goTo(id) : { ok: false, reason: 'loading' });
    },
    [settle],
  );
  const labels = useLabelStore();
  const [startTime] = useState(
    () => parseTime(params.get('time')) ?? START_MINUTES,
  );
  const clockRef = useRef(createClock(startTime));
  // the engine's citizens live on the real world; the mock world has only the mock feed
  const feed = useLiveCitizens(view, {
    source: params.has('mockLive')
      ? 'mock'
      : params.has('mock')
        ? 'off'
        : 'backend',
    startMinute: startTime,
  });
  const live = feed.state;
  const feedLive = feed.status === 'live' && live.runId !== null;
  const peopleRef = useRef(new Map<string, Vector3>());
  const [npcViews] = useState<NpcViews>(() => new Map());
  const subjectRef = useRef<GlobePlayerState>({
    position: new Vector3(),
    facing: new Vector3(),
    ground: 0,
  });
  const [followId, setFollowId] = useState<string | null>(null);
  const [peopleOpen, setPeopleOpen] = useState(false);
  const followed = live.citizens.find((citizen) => citizen.id === followId);
  const focusRef = useRef(start.position.clone());
  const [player, setPlayer] = useState<GlobeMove | null>(null);
  const [minutes, setMinutes] = useState(startTime);
  const [fastTime, setFastTime] = useState(false);
  const [travel, setTravel] = useState(false);
  const [walkReady, setWalkReady] = useState(false);
  const [placementsReady, setPlacementsReady] = useState(false);
  const [cameraMode, setCameraMode] = useState<CameraMode>('follow');
  const [stats, setStats] = useState<ModeStats | null>(null);
  const markWalkReady = useCallback(() => setWalkReady(true), []);
  const markPlacementsReady = useCallback(() => setPlacementsReady(true), []);
  const ready = walkReady && placementsReady;

  // a live feed drives the sky: engine time, running at the engine's speed (game minutes per real second)
  useEffect(() => {
    if (!feedLive) return;
    const clock = clockRef.current;
    clock.minutes = feedMinutes(live);
    clock.rate = live.paused ? 0 : live.speed;
  }, [feedLive, live]);
  useEffect(() => {
    if (!feedLive) clockRef.current.rate = fastTime ? FAST_RATE : NORMAL_RATE;
  }, [feedLive, fastTime]);

  const changeCameraMode = useCallback((mode: CameraMode) => {
    setCameraMode(mode);
    if (mode !== 'follow') setFollowId(null);
  }, []);
  const follow = useCallback((id: string) => {
    setFollowId(id);
    setCameraMode('follow');
  }, []);
  const goToCitizen = useCallback(
    (id: string) => {
      const view = npcViews.get(id);
      const api = dropRef.current;
      setFollowId(null);
      if (!view) return;
      settle(
        api
          ? api.goNear(view.pose.position.clone().normalize())
          : { ok: false, reason: 'loading' },
      );
    },
    [npcViews, settle],
  );

  useKeys(
    useCallback((code: string) => {
      if (code === 'KeyT') setTravel((on) => !on);
      if (code === 'Escape') {
        setDropping(false);
        setFollowId(null);
      }
    }, []),
  );

  const localTime = player
    ? localMinutes(minutes, planet.town.lon, player.lon)
    : null;
  const biome = player ? view.biome_names[player.biome] : null;
  const site = player ? siteAt(planet, player) : null;

  return (
    <div
      className="relative h-full w-full"
      data-testid="world"
      data-world-ready={ready}
      data-follow={followId ?? undefined}
      data-live-status={feed.status}
      data-live-connects={feed.connects}
      data-live-tick={live.tick}
      data-player-x={player && round(player.x)}
      data-player-y={player && round(player.y)}
      data-player-z={player && round(player.z)}
      data-player-ground={player && round(player.ground)}
      data-player-lat={player && player.lat.toFixed(5)}
      data-player-lon={player && player.lon.toFixed(5)}
      data-player-biome={biome}
      data-player-site={site?.id}
      data-town-x={player?.town && round(player.town.x)}
      data-town-z={player?.town && round(player.town.z)}
      data-camera-mode={cameraMode}
      data-camera-distance={player && round(player.cameraDistance)}
      data-camera={player?.camera.map((value) => value.toFixed(4)).join(',')}
      data-camera-arm={player && player.arm.toFixed(2)}
      data-camera-flying={player?.flying}
      data-dropping={dropping}
      data-game-minutes={Math.floor(minutes)}
      data-travel={travel}
      data-draw-calls={stats?.calls}
      data-draw-calls-mode={stats?.mode}
      data-triangles={stats?.triangles}
      style={dropping && hover ? { cursor: 'none' } : undefined}
      onPointerMove={(event) => {
        if (dropping && event.target instanceof HTMLCanvasElement)
          hoverAt(event.clientX, event.clientY);
        else if (hover) setHover(null);
      }}
      onPointerLeave={() => setHover(null)}
      onPointerDown={(event) => {
        press.current = { x: event.clientX, y: event.clientY };
      }}
      onPointerUp={(event) => {
        const from = press.current;
        press.current = null;
        if (
          dropping &&
          from &&
          event.target instanceof HTMLCanvasElement &&
          Math.hypot(event.clientX - from.x, event.clientY - from.y) <
            CLICK_SLOP
        )
          dropAtScreen(event.clientX, event.clientY);
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes(PEGMAN_DRAG)) {
          event.preventDefault();
          event.dataTransfer.dropEffect = 'move';
          hoverAt(event.clientX, event.clientY);
        }
      }}
      onDragLeave={() => setHover(null)}
      onDrop={(event) => {
        if (!event.dataTransfer.types.includes(PEGMAN_DRAG)) return;
        event.preventDefault();
        setHover(null);
        dropAtScreen(event.clientX, event.clientY);
      }}
    >
      <GlobeScene
        planet={planet}
        town={town}
        walkTown={walkTown}
        live={live}
        peopleRef={peopleRef}
        npcViews={npcViews}
        followId={followId}
        subjectRef={subjectRef}
        start={start}
        dropRef={dropRef}
        goTo={goTo}
        labels={labels}
        clockRef={clockRef}
        focusRef={focusRef}
        cameraMode={cameraMode}
        travel={travel}
        ready={ready}
        onCameraModeChange={changeCameraMode}
        onPlayerMove={setPlayer}
        onTick={setMinutes}
        onWalkReady={markWalkReady}
        onPlacementsReady={markPlacementsReady}
        onStats={setStats}
      />
      <LabelOverlay store={labels} />
      <NpcHooks citizens={live.citizens} views={npcViews} focusRef={focusRef} />
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
              changeCameraMode(mode);
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
        {!feedLive && (
          <Button
            size="sm"
            variant={fastTime ? 'default' : 'outline'}
            aria-pressed={fastTime}
            onClick={(event) => {
              setFastTime((fast) => !fast);
              event.currentTarget.blur();
            }}
          >
            time ×60
          </Button>
        )}
        <Pegman
          active={dropping}
          onToggle={() => {
            setDropping((on) => !on);
            setMessage(null);
          }}
        />
        <GoToMenu sites={goTo} onPick={goToSite} />
        {feed.status !== 'off' && (
          <Button
            size="sm"
            variant={peopleOpen ? 'default' : 'outline'}
            aria-pressed={peopleOpen}
            onClick={(event) => {
              setPeopleOpen((open) => !open);
              event.currentTarget.blur();
            }}
          >
            people
          </Button>
        )}
        <span>
          WASD move, Shift run, T travel (25 m/s), drag to look, wheel zoom, C
          camera
          {cameraMode === 'fly' && ', Q/E down/up'}
          {dropping && '. Click land to drop there, Esc cancels'}
        </span>
      </div>
      <div className="absolute right-3 bottom-3 flex flex-col items-end gap-2">
        {feed.status !== 'off' && (
          <LiveClock
            state={live}
            status={feed.status}
            onChange={feed.setClock}
          />
        )}
        {followed && (
          <div className="flex items-center gap-2 rounded-lg bg-white/80 p-1 pl-2 text-sm shadow">
            following {followed.name}
            <Button
              size="sm"
              variant="outline"
              onClick={(event) => {
                setFollowId(null);
                event.currentTarget.blur();
              }}
            >
              stop following
            </Button>
          </div>
        )}
      </div>
      {peopleOpen && (
        <PeoplePanel
          citizens={live.citizens}
          followId={followId}
          onFollow={follow}
          onGoTo={goToCitizen}
        />
      )}
      {hover && <DropPin {...hover} />}
      {message && (
        <div
          role="status"
          className="absolute top-16 left-1/2 -translate-x-1/2 rounded-lg bg-white/90 px-3 py-2 text-sm shadow"
        >
          {message}
        </div>
      )}
      {player && (
        <div className="absolute bottom-3 left-3 rounded-lg bg-white/80 px-2 py-1 font-mono text-xs shadow">
          {localTime !== null && formatTime(localTime)} ·{' '}
          {Math.abs(player.lat).toFixed(2)}°{player.lat >= 0 ? 'N' : 'S'}{' '}
          {Math.abs(player.lon).toFixed(2)}°{player.lon >= 0 ? 'E' : 'W'} ·{' '}
          {biome?.replace('_', ' ')}
          {site && ` · ${site.name}`}
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
