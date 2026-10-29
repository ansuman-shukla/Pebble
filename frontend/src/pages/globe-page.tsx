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
import {
  AnimalHooks,
  type AnimalViews,
  GlobeAnimals,
} from '@/components/world/globe/globe-animals';
import {
  FireHooks,
  type FireViews,
  GlobeFires,
} from '@/components/world/globe/globe-fires';
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
  CitizenPicker,
  Inspector,
  type PickAt,
} from '@/components/world/globe/inspector';
import { ReplayBadge } from '@/components/world/globe/replay-badge';
import {
  CitizenLabels,
  LiveClock,
  NpcHooks,
  PeoplePanel,
} from '@/components/world/globe/live-ui';
import { VolcanoSmoke } from '@/components/world/globe/volcano-smoke';
import { Waterfalls } from '@/components/world/globe/waterfalls';
import { ChipOverlay, ChipProjector } from '@/components/world/labels';
import {
  CAMERA_MODES,
  type CameraMode,
} from '@/components/world/player/camera-mode';
import { notForScene, useKeys } from '@/components/world/player/use-keys';
import {
  type RenderStats,
  RenderStatsProbe,
} from '@/components/world/render-stats';
import { useLabelStore } from '@/hooks/use-label-store';
import { type LiveFeed, useLiveCitizens } from '@/hooks/use-live-citizens';
import {
  parseReplayTick,
  useReplayCitizens,
} from '@/hooks/use-replay-citizens';
import { useTown } from '@/hooks/use-town';
import { useWorld } from '@/hooks/use-world';
import type { TownView, WorldView } from '@/lib/client/types.gen';
import { CLOCK_SPEEDS } from '@/lib/live/clock-speeds';
import { feedMinutes } from '@/lib/live/live-state';
import { ShownDoings } from '@/lib/live/shown-doings';
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
import { clipWater, TOWN_WATER_Y } from '@/lib/world/ground-shape';
import type { LabelStore, UpAt } from '@/lib/world/label-store';
import {
  type RiverLayout,
  riverLayout,
  streamChannels,
} from '@/lib/world/river-courses';
import { createScatter, type Scatter } from '@/lib/world/scatter';
import type { WalkTown } from '@/lib/world/walk-charts';

/*
 * The planet at /: terrain, ocean, rivers, sites and the castle town, a sun on the game clock, and the player
 * walking out of the town into the wild, among the live citizens. `?mock=1` uses the dev/test mock world,
 * `?mockLive=1` the dev/test mock feed; `?at=lat,lon[,bearing]` starts the player somewhere else (bearing in
 * degrees clockwise from north); `?time=HH:MM` sets the starting town time (while no feed is live); `?tick=N`
 * shows the citizens as they were at tick N (feed off, clock stopped); `?follow=id` follows a citizen on load.
 */

/** The town's own ground disc (local metres): inside the 230 m plateau, around the ±160 m town. */
const TOWN_GROUND_RADIUS = 225;
/** Props keep this far from the town anchor (the plateau and its blend). */
const TOWN_CLEARING = 300;
/** ... and from camps and landmarks. */
const SITE_CLEARING = 45;
/** The readout names a camp or landmark within this many metres of its anchor (the town: its clearing). */
const SITE_NEARBY = 100;
/** How often the footer and the clock re-read where the camera looks (ms). */
const PLACE_MS = 250;
/** Labels lift away from the planet's centre. */
const PLANET_UP: UpAt = (at, out) => out.copy(at).normalize();

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
  rivers: RiverLayout;
  scatter: Scatter;
  volcano: { frame: ReturnType<typeof tangentFrame>; summit: number } | null;
}

function buildPlanet(view: WorldView, town: TownView): Planet {
  const globe = decodeWorld(view);
  const terrain = buildTerrain(globe);
  const site = view.sites.find((candidate) => candidate.kind === 'town');
  if (!site) throw new Error('the world has no town site');
  const up = new Vector3(...site.anchor.position);
  const height = site.anchor.height_m;
  const volcano = view.sites.find(
    (candidate) => candidate.id === 'smoking_mountain',
  );
  const hole = {
    up,
    angle: Math.atan(TOWN_GROUND_RADIUS / (globe.radius + height)),
  };
  const mapping = anchorMapping(site.anchor, globe.radius);
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
      mapping,
      height,
      lon: latLonFromDirection(up).lon,
      grass: biomeColor(view.biome_names[globe.biomes[site.cell]]),
    },
    hole,
    // the town lays its own ground and water: a river passing it runs through its stream, others stop at it
    rivers: riverLayout(
      terrain,
      view.rivers.map((river) => river.cells),
      {
        hole,
        channels: streamChannels(town.water, mapping, height, TOWN_WATER_Y),
      },
    ),
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

/** The site at a world point, if any. */
function siteAt(
  planet: Planet,
  point: { x: number; y: number; z: number },
): PlanetSite | null {
  const here = new Vector3(point.x, point.y, point.z).normalize();
  const radius = planet.terrain.globe.radius;
  return (
    planet.sites.find(
      (site) => here.angleTo(site.direction) * radius < site.reach,
    ) ?? null
  );
}

/** Where the camera looks: the place the footer describes and whose local time the clock shows (audit F19, F20). */
interface CameraPlace {
  lat: number;
  lon: number;
  biome: string;
  site: PlanetSite | null;
  /** Town local metres on the town's ground disc. */
  town: { x: number; z: number } | null;
  /** The longitude its local time is told at: a site's anchor (one time across the site), else the spot's. */
  clockLon: number;
}

function placeAt(planet: Planet, point: Vector3): CameraPlace {
  const direction = point.clone().normalize();
  const { lat, lon } = latLonFromDirection(direction);
  const local = planet.town.mapping.toLocal(point, new Vector3());
  const site = siteAt(planet, point);
  return {
    lat,
    lon,
    biome: planet.view.biome_names[planet.terrain.biomeAt(direction)],
    site,
    clockLon: site ? latLonFromDirection(site.direction).lon : lon,
    town:
      Math.hypot(local.x, local.z) < TOWN_GROUND_RADIUS
        ? { x: local.x, z: local.z }
        : null,
  };
}

const samePlace = (a: CameraPlace | null, b: CameraPlace) =>
  a !== null &&
  a.site === b.site &&
  a.biome === b.biome &&
  a.lat.toFixed(2) === b.lat.toFixed(2) &&
  a.lon.toFixed(2) === b.lon.toFixed(2) &&
  a.town?.x.toFixed(0) === b.town?.x.toFixed(0) &&
  a.town?.z.toFixed(0) === b.town?.z.toFixed(0);

/** The camera's place, re-read every PLACE_MS from the point it looks at. */
function useCameraPlace(planet: Planet, focusRef: RefObject<Vector3>) {
  const [place, setPlace] = useState<CameraPlace | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const next = placeAt(planet, focusRef.current);
      setPlace((current) => (samePlace(current, next) ? current : next));
    }, PLACE_MS);
    return () => window.clearInterval(timer);
  }, [planet, focusRef]);
  return place;
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
  /** `live` is a replayed moment (`?tick=`). */
  replay: boolean;
  peopleRef: RefObject<Map<string, Vector3>>;
  npcViews: NpcViews;
  animalViews: AnimalViews;
  fireViews: FireViews;
  followId: string | null;
  /** Selected and followed: their chips stay whole. */
  pinned: readonly string[];
  pickRef: RefObject<PickAt | null>;
  subjectRef: RefObject<GlobePlayerState>;
  start: Start;
  dropRef: RefObject<DropApi | null>;
  goTo: GoToSite[];
  labels: LabelStore;
  doings: ShownDoings;
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
  onWaterfalls: () => void;
};

type ModeStats = RenderStats & { mode: CameraMode };

const GlobeScene = memo(function GlobeScene({
  planet,
  town,
  walkTown,
  live,
  replay,
  peopleRef,
  npcViews,
  animalViews,
  fireViews,
  followId,
  pinned,
  pickRef,
  subjectRef,
  start,
  dropRef,
  goTo,
  labels,
  doings,
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
  onWaterfalls,
}: GlobeSceneProps) {
  const { view, terrain } = planet;
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
        rivers={planet.rivers}
        hole={planet.hole}
      />
      <Waterfalls
        terrain={terrain}
        falls={planet.rivers.falls}
        onMounted={onWaterfalls}
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
        speed={live.speed}
        paused={live.paused}
        replay={replay}
        terrain={terrain}
        town={walkTown}
        labels={labels}
        doings={doings}
        peopleRef={peopleRef}
        views={npcViews}
        followId={followId}
        subjectRef={subjectRef}
      />
      <GlobeAnimals
        animals={live.animals}
        speed={live.speed}
        terrain={terrain}
        views={animalViews}
      />
      <GlobeFires
        fires={live.fires}
        terrain={terrain}
        town={walkTown}
        views={fireViews}
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
      <ChipProjector store={labels} pinned={pinned} />
      <CitizenPicker views={npcViews} pickRef={pickRef} />
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
  const planet = useMemo(() => buildPlanet(view, town), [view, town]);
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
  const labels = useLabelStore(PLANET_UP);
  const [startTime] = useState(
    () => parseTime(params.get('time')) ?? START_MINUTES,
  );
  const clockRef = useRef(createClock(startTime));
  // `?tick=N` replays a past moment (the feed stays off); `?follow=id` follows a citizen once they are drawn
  const replayTick = parseReplayTick(params.get('tick'));
  const replay = useReplayCitizens(replayTick);
  // the engine's citizens live on the real world; the mock world has only the mock feed
  const source =
    replayTick !== null
      ? 'off'
      : params.has('mockLive')
        ? 'mock'
        : params.has('mock')
          ? 'off'
          : 'backend';
  const feed = useLiveCitizens(view, { source });
  const live = replay ?? feed.state;
  const feedLive =
    live.runId !== null && (replay !== null || feed.status === 'live');
  const peopleRef = useRef(new Map<string, Vector3>());
  const [npcViews] = useState<NpcViews>(() => new Map());
  const [doings] = useState(() => new ShownDoings());
  const [animalViews] = useState<AnimalViews>(() => new Map());
  const [fireViews] = useState<FireViews>(() => new Map());
  const subjectRef = useRef<GlobePlayerState>({
    position: new Vector3(),
    facing: new Vector3(),
    ground: 0,
  });
  const [followId, setFollowId] = useState<string | null>(null);
  const [pendingFollow, setPendingFollow] = useState(() =>
    params.get('follow'),
  );
  const [peopleOpen, setPeopleOpen] = useState(false);
  const followed = live.citizens.find((citizen) => citizen.id === followId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = live.citizens.find((citizen) => citizen.id === selectedId);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const pinned = useMemo(
    () => [...new Set([selectedId, followId])].filter((id) => id !== null),
    [selectedId, followId],
  );
  const pickRef = useRef<PickAt | null>(null);
  const focusRef = useRef(start.position.clone());
  const [player, setPlayer] = useState<GlobeMove | null>(null);
  const [minutes, setMinutes] = useState(startTime);
  const [fastTime, setFastTime] = useState(false);
  const [travel, setTravel] = useState(false);
  const [walkReady, setWalkReady] = useState(false);
  const [placementsReady, setPlacementsReady] = useState(false);
  const [cameraMode, setCameraMode] = useState<CameraMode>('follow');
  const [stats, setStats] = useState<ModeStats | null>(null);
  const [waterfallsShown, setWaterfallsShown] = useState(false);
  const markWaterfalls = useCallback(() => setWaterfallsShown(true), []);
  const markWalkReady = useCallback(() => setWalkReady(true), []);
  const markPlacementsReady = useCallback(() => setPlacementsReady(true), []);
  const ready = walkReady && placementsReady;

  // a live feed drives the sky: engine time, set on each tick (other feed changes would pull it back to the tick's
  // minute) and running at the engine's speed (game seconds per real second; the sky's clock counts game minutes)
  const { day: feedDay, time: feedTime, paused: feedPaused, speed } = live;
  useEffect(() => {
    if (feedLive)
      clockRef.current.minutes = feedMinutes({ day: feedDay, time: feedTime });
  }, [feedLive, feedDay, feedTime]);
  useEffect(() => {
    if (feedLive) clockRef.current.rate = feedPaused ? 0 : speed / 60;
  }, [feedLive, feedPaused, speed]);
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
  if (
    pendingFollow !== null &&
    ready &&
    live.citizens.some((citizen) => citizen.id === pendingFollow)
  ) {
    setPendingFollow(null);
    follow(pendingFollow);
  }
  // going somewhere stops following (audit F18)
  const goToSite = useCallback(
    (id: string) => {
      const api = dropRef.current;
      setFollowId(null);
      settle(api ? api.goTo(id) : { ok: false, reason: 'loading' });
    },
    [settle],
  );
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

  // the spectator keys (10-world-v1 §5.4): Tab cycles the selection, F follows it, G goes to it, Space pauses,
  // 1-4 pick the clock's speeds, I shows or hides the inspector, Esc lets go of everything
  const clockLive = feed.status !== 'off';
  const { paused: livePaused, citizens } = live;
  const { setClock } = feed;
  useKeys(
    useCallback(
      (code: string) => {
        if (code === 'KeyT') setTravel((on) => !on);
        if (code === 'Escape') {
          setDropping(false);
          setFollowId(null);
          setSelectedId(null);
        }
        if (code === 'KeyF' && selectedId) follow(selectedId);
        if (code === 'KeyG' && selectedId) goToCitizen(selectedId);
        if (code === 'KeyI') setInspectorOpen((open) => !open);
        if (clockLive && code === 'Space') setClock({ paused: !livePaused });
        const speed = CLOCK_SPEEDS[Number(code.replace('Digit', '')) - 1];
        if (clockLive && code.startsWith('Digit') && speed)
          setClock(speed.change);
      },
      [selectedId, follow, goToCitizen, clockLive, livePaused, setClock],
    ),
  );
  // Tab and Space belong to the scene here, not to focus moves or page scrolls; Tab (Shift+Tab back) cycles
  useEffect(() => {
    const claim = (event: KeyboardEvent) => {
      if (event.code !== 'Tab' && event.code !== 'Space') return;
      if (notForScene(event)) return;
      event.preventDefault();
      if (event.code !== 'Tab' || citizens.length === 0) return;
      const step = event.shiftKey ? -1 : 1;
      setSelectedId((current) => {
        const at = citizens.findIndex((citizen) => citizen.id === current);
        const next =
          at === -1
            ? step > 0
              ? 0
              : citizens.length - 1
            : (at + step + citizens.length) % citizens.length;
        return citizens[next].id;
      });
      setInspectorOpen(true);
    };
    window.addEventListener('keydown', claim);
    return () => window.removeEventListener('keydown', claim);
  }, [citizens]);

  // the footer and the clock describe where the camera looks, not where the hidden avatar stands (F19, F20)
  const place = useCameraPlace(planet, focusRef);
  const localTime = place
    ? localMinutes(minutes, planet.town.lon, place.clockLon)
    : null;
  const biome = player ? view.biome_names[player.biome] : null;
  const site = player ? siteAt(planet, player) : null;
  const siteClock =
    place && localTime !== null && place.site?.id !== 'town'
      ? { name: place.site?.name ?? 'here', time: formatTime(localTime) }
      : null;

  return (
    <div
      className="relative h-full w-full"
      data-testid="world"
      data-world-ready={ready}
      data-follow={followId ?? undefined}
      data-selected={selectedId ?? undefined}
      data-camera-site={place?.site?.id}
      data-live-status={feed.status}
      data-live-connects={feed.connects}
      data-live-tick={live.tick}
      data-replay-tick={replayTick ?? undefined}
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
      data-avatar={player?.avatar.map((value) => value.toFixed(4)).join(',')}
      data-avatar-clip={player?.clip ?? undefined}
      data-avatar-feet={player?.feet.map((value) => value.toFixed(4)).join(',')}
      data-dropping={dropping}
      data-game-minutes={minutes.toFixed(3)}
      data-travel={travel}
      data-draw-calls={stats?.calls}
      data-draw-calls-mode={stats?.mode}
      data-triangles={stats?.triangles}
      data-water-time={stats?.waterTime.toFixed(2)}
      data-waterfalls={
        waterfallsShown
          ? planet.rivers.falls
              .map((fall) => {
                const { lat, lon } = latLonFromDirection(fall.lip);
                return `${lat.toFixed(4)},${lon.toFixed(4)}`;
              })
              .join(';')
          : undefined
      }
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
        const click =
          from !== null &&
          event.target instanceof HTMLCanvasElement &&
          Math.hypot(event.clientX - from.x, event.clientY - from.y) <
            CLICK_SLOP;
        if (!click) return;
        if (dropping) dropAtScreen(event.clientX, event.clientY);
        else {
          // a click on a body selects them, a click elsewhere lets go
          setSelectedId(
            pickRef.current?.(event.clientX, event.clientY) ?? null,
          );
          setInspectorOpen(true);
        }
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
        replay={replay !== null}
        peopleRef={peopleRef}
        npcViews={npcViews}
        animalViews={animalViews}
        fireViews={fireViews}
        followId={followId}
        pinned={pinned}
        pickRef={pickRef}
        subjectRef={subjectRef}
        start={start}
        dropRef={dropRef}
        goTo={goTo}
        labels={labels}
        doings={doings}
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
        onWaterfalls={markWaterfalls}
      />
      <ChipOverlay
        store={labels}
        onPick={(id) => {
          setSelectedId(id);
          setInspectorOpen(true);
        }}
      />
      <CitizenLabels
        store={labels}
        citizens={live.citizens}
        doings={doings}
        speech={live.speech}
      />
      <NpcHooks citizens={live.citizens} views={npcViews} focusRef={focusRef} />
      <AnimalHooks views={animalViews} />
      <FireHooks views={fireViews} />
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
        {(feed.status !== 'off' || replay) && (
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
        {clockLive && (
          <span className="basis-full" data-testid="spectator-keys">
            Tab select, F follow, G go to, I inspector, Space pause, 1-4 speed,
            Esc let go
          </span>
        )}
      </div>
      <div className="absolute right-3 bottom-3 flex flex-col items-end gap-2">
        {replay && <ReplayBadge state={replay} />}
        {feed.status !== 'off' && (
          <LiveClock
            state={live}
            status={feed.status}
            onChange={feed.setClock}
            site={siteClock}
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
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id);
            setInspectorOpen(true);
          }}
          onFollow={follow}
          onGoTo={goToCitizen}
        />
      )}
      {selected && inspectorOpen && (
        <Inspector
          citizen={selected}
          details={source === 'backend' || replayTick !== null}
          at={replayTick}
          following={selected.id === followId}
          onFollow={() =>
            selected.id === followId ? setFollowId(null) : follow(selected.id)
          }
          onGoTo={() => goToCitizen(selected.id)}
          onClose={() => setSelectedId(null)}
        />
      )}
      {hover && <DropPin {...hover} />}
      {message && (
        <div
          role="status"
          className="absolute top-24 left-1/2 -translate-x-1/2 rounded-lg bg-white/90 px-3 py-2 text-sm shadow"
        >
          {message}
        </div>
      )}
      {place && (
        <div
          className="absolute bottom-3 left-3 rounded-lg bg-white/80 px-2 py-1 font-mono text-xs shadow"
          data-testid="camera-place"
        >
          {localTime !== null && formatTime(localTime)} ·{' '}
          {Math.abs(place.lat).toFixed(2)}°{place.lat >= 0 ? 'N' : 'S'}{' '}
          {Math.abs(place.lon).toFixed(2)}°{place.lon >= 0 ? 'E' : 'W'} ·{' '}
          {place.biome.replace('_', ' ')}
          {place.site && ` · ${place.site.name}`}
          {place.town &&
            ` · town ${place.town.x.toFixed(0)}, ${place.town.z.toFixed(0)}`}
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
