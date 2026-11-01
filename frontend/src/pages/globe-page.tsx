import { Canvas } from '@react-three/fiber';
import {
  type CSSProperties,
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
import { GlobeNodes } from '@/components/world/globe/nodes';
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
import { Minimap, type MinimapTown } from '@/components/world/globe/minimap';
import { EventFeed } from '@/components/world/globe/event-feed';
import { Scoreboard } from '@/components/world/globe/scoreboard';
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
import { TimeLapseTrails } from '@/components/world/globe/time-lapse-trails';
import { VolcanoSmoke } from '@/components/world/globe/volcano-smoke';
import { Waterfalls } from '@/components/world/globe/waterfalls';
import { ChipOverlay, ChipProjector } from '@/components/world/labels';
import { LivingProps, PropHooks } from '@/components/world/living-props';
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
import { useFlora } from '@/hooks/use-flora';
import { useFurniture } from '@/hooks/use-furniture';
import { useTown } from '@/hooks/use-town';
import { useWorld } from '@/hooks/use-world';
import type { Furniture, TownView, WorldView } from '@/lib/client/types.gen';
import { CLOCK_SPEEDS } from '@/lib/live/clock-speeds';
import { type FeedEntry, flightTarget } from '@/lib/live/event-feed';
import type { LiveCitizen } from '@/lib/live/live-contract';
import { feedMinutes } from '@/lib/live/live-state';
import { ShownDoings } from '@/lib/live/shown-doings';
import { BIOME_PROPS } from '@/lib/world/biome-props';
import type { FloraTable } from '@/lib/world/flora';
import { NodeStages } from '@/lib/world/node-stages';
import { type WaterholePool, waterholePools } from '@/lib/world/waterholes';
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
import { clockRate, isTimeLapse } from '@/lib/world/visual-rate';
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
/** ... and from camps and landmarks (decor only: nodes are drawn wherever the simulation has them). */
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
  /** The waterholes' pools (waterholes.ts). */
  pools: WaterholePool[];
  rivers: RiverLayout;
  scatter: Scatter;
  volcano: { frame: ReturnType<typeof tangentFrame>; summit: number } | null;
}

function buildPlanet(
  view: WorldView,
  town: TownView,
  flora: FloraTable,
): Planet {
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
    pools: waterholePools(view.places.features, terrain),
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
      flora,
      places: view.places,
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
  nodeStages: NodeStages;
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

const NO_FURNITURE: Furniture[] = [];

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
  nodeStages,
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
  const furniture = useFurniture().data ?? NO_FURNITURE;
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
        pools={planet.pools}
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
          furniture={furniture}
          terrain={terrain}
          sites={view.sites}
          places={view.places}
          rivers={planet.rivers}
          pools={planet.pools}
          nodeStages={nodeStages}
          onPlacementsReady={onPlacementsReady}
        />
        <GlobeSites
          sites={view.sites}
          terrain={terrain}
          furniture={furniture}
        />
        <BiomeScatter
          scatter={planet.scatter}
          focusRef={focusRef}
          radius={terrain.globe.radius}
        />
        <GlobeNodes
          scatter={planet.scatter}
          stages={nodeStages}
          focusRef={focusRef}
          radius={terrain.globe.radius}
        />
      </Suspense>
      <GlobeNpcs
        citizens={live.citizens}
        cues={live.cues}
        speed={live.speed}
        paused={live.paused}
        tickClock={live.tickClock}
        replay={replay}
        clockRef={clockRef}
        townLon={planet.town.lon}
        terrain={terrain}
        town={walkTown}
        labels={labels}
        doings={doings}
        peopleRef={peopleRef}
        views={npcViews}
        followId={followId}
        subjectRef={subjectRef}
      />
      <TimeLapseTrails
        views={npcViews}
        rate={clockRate(live.speed, live.paused)}
      />
      <GlobeAnimals
        animals={live.animals}
        speed={live.speed}
        paused={live.paused}
        replay={replay}
        terrain={terrain}
        views={animalViews}
      />
      <GlobeFires
        fires={live.fires}
        terrain={terrain}
        town={walkTown}
        views={fireViews}
      />
      <LivingProps
        clockRef={clockRef}
        peopleRef={peopleRef}
        fires={fireViews}
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
        timeLapse={isTimeLapse(clockRate(live.speed, live.paused))}
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
/** Where the toolbar ends on two lines (px), until measured, and the space between it and the panels below. */
const TOOLBAR_BOTTOM = 84;
const TOOLBAR_GAP = 12;

/** Where an element ends (px from its offset parent's top), followed as it resizes; `initial` until measured. */
function useBottomEdge(ref: RefObject<HTMLElement | null>, initial: number) {
  const [bottom, setBottom] = useState(initial);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setBottom(element.offsetTop + element.offsetHeight),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return bottom;
}

/** The citizen drawn nearest to `point` (the first in the list while nobody is drawn yet). */
function nearestDrawn(
  citizens: readonly LiveCitizen[],
  views: NpcViews,
  point: Vector3,
) {
  let nearest = citizens[0].id;
  let best = Infinity;
  for (const { id } of citizens) {
    const distance = views.get(id)?.pose.position.distanceTo(point) ?? Infinity;
    if (distance < best) [nearest, best] = [id, distance];
  }
  return nearest;
}

function GlobeWorld({
  view,
  town,
  flora,
}: {
  view: WorldView;
  town: TownView;
  flora: FloraTable;
}) {
  const [params] = useSearchParams();
  const planet = useMemo(
    () => buildPlanet(view, town, flora),
    [view, town, flora],
  );
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
  // the toolbar wraps onto more lines in narrow windows (and with the drop hint): panels hang below its real end
  const toolbarRef = useRef<HTMLDivElement>(null);
  const toolbarBottom = useBottomEdge(toolbarRef, TOOLBAR_BOTTOM);
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
  // node stocks and felled trees follow the feed (fixed features may have caps of their own)
  const [nodeStages] = useState(
    () =>
      new NodeStages(
        new Map(
          view.places.features.flatMap((feature) =>
            feature.cap == null ? [] : [[feature.id, feature.cap] as const],
          ),
        ),
      ),
  );
  const { listen } = feed;
  useEffect(
    () =>
      listen((message) => nodeStages.apply(message, performance.now() / 1000)),
    [listen, nodeStages],
  );
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
  const [feedOpen, setFeedOpen] = useState(true);
  const [minimapOpen, setMinimapOpen] = useState(true);
  const [scoreboardOpen, setScoreboardOpen] = useState(false);
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
  /** Lets go of whoever is followed and flies to near a unit direction. */
  const goNear = useCallback(
    (direction: Vector3) => {
      const api = dropRef.current;
      setFollowId(null);
      settle(api ? api.goNear(direction) : { ok: false, reason: 'loading' });
    },
    [settle],
  );
  const goToCitizen = useCallback(
    (id: string) => {
      const view = npcViews.get(id);
      if (view) goNear(view.pose.position.clone().normalize());
      else setFollowId(null);
    },
    [npcViews, goNear],
  );

  // the spectator keys (10-world-v1 §5.4): Tab cycles the selection, F follows it, G goes to it, Space pauses,
  // 1-4 pick the clock's speeds, I, L, M and B show or hide the inspector, the event feed, the minimap and the
  // scoreboard, Esc lets go of everything
  const clockLive = feed.status !== 'off';
  // the scoreboard reads the backend's run: live from it, or replayed
  const scoresShown = source === 'backend' || replayTick !== null;
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
        if (code === 'KeyL') setFeedOpen((open) => !open);
        if (code === 'KeyM') setMinimapOpen((open) => !open);
        if (code === 'KeyB' && scoresShown) setScoreboardOpen((open) => !open);
        if (clockLive && code === 'Space') setClock({ paused: !livePaused });
        const speed = CLOCK_SPEEDS[Number(code.replace('Digit', '')) - 1];
        if (clockLive && code.startsWith('Digit') && speed)
          setClock(speed.change);
      },
      [
        selectedId,
        follow,
        goToCitizen,
        clockLive,
        livePaused,
        setClock,
        scoresShown,
      ],
    ),
  );
  // Tab and Space belong to the scene here, not to focus moves or page scrolls; Tab (Shift+Tab back) cycles,
  // starting with nobody selected from the citizen drawn nearest where the camera looks (the followed one, if any)
  useEffect(() => {
    const claim = (event: KeyboardEvent) => {
      if (event.code !== 'Tab' && event.code !== 'Space') return;
      if (notForScene(event)) return;
      event.preventDefault();
      if (event.code !== 'Tab' || citizens.length === 0) return;
      const step = event.shiftKey ? -1 : 1;
      setSelectedId((current) => {
        const at = citizens.findIndex((citizen) => citizen.id === current);
        if (at !== -1)
          return citizens[(at + step + citizens.length) % citizens.length].id;
        return nearestDrawn(citizens, npcViews, focusRef.current);
      });
      setInspectorOpen(true);
    };
    window.addEventListener('keydown', claim);
    return () => window.removeEventListener('keydown', claim);
  }, [citizens, npcViews]);

  const { animals } = live;
  const feedSubjects = useMemo(
    () => ({
      animals: new Map(animals.map((animal) => [animal.id, animal.kind])),
    }),
    [animals],
  );
  // an entry flies to where it happened, else to its actor as drawn: a citizen or an animal
  const canFly = useCallback(
    (entry: FeedEntry) =>
      flightTarget(entry, { animals: animalViews, citizens: npcViews }) !==
      null,
    [npcViews, animalViews],
  );
  const flyTo = useCallback(
    (entry: FeedEntry) => {
      // the actor may be gone since ▶ was drawn: then nothing happens (a followed citizen stays followed)
      const target = flightTarget(entry, {
        animals: animalViews,
        citizens: npcViews,
      });
      if (target) goNear(target);
    },
    [animalViews, npcViews, goNear],
  );

  const minimapTown = useMemo(
    (): MinimapTown => ({
      siteId: 'town',
      placements: town.placements,
      water: townWater,
    }),
    [town, townWater],
  );

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
      style={
        {
          '--toolbar-bottom': `${toolbarBottom + TOOLBAR_GAP}px`,
          cursor: dropping && hover ? 'none' : undefined,
        } as CSSProperties
      }
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
        nodeStages={nodeStages}
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
      <PropHooks />
      {!ready && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="rounded-lg bg-white/80 px-3 py-2 text-sm shadow">
            Loading the world…
          </span>
        </div>
      )}
      <div
        ref={toolbarRef}
        className="absolute top-3 left-3 flex flex-wrap items-center gap-2 rounded-lg bg-white/80 p-2 text-sm shadow"
      >
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
        {scoresShown && (
          <Button
            size="sm"
            variant={scoreboardOpen ? 'default' : 'outline'}
            aria-pressed={scoreboardOpen}
            onClick={(event) => {
              setScoreboardOpen((open) => !open);
              event.currentTarget.blur();
            }}
          >
            scores
          </Button>
        )}
        <span>
          WASD move, Shift run, T travel (25 m/s), drag to look, wheel zoom, C
          camera
          {cameraMode === 'fly' && ', Q/E down/up'}
          {dropping && '. Click land to drop there, Esc cancels'}
        </span>
        {(clockLive || replay) && (
          <span className="basis-full" data-testid="spectator-keys">
            Tab select, F follow, G go to, I inspector
            {clockLive && ', L events'}, M minimap
            {scoresShown && ', B scoreboard'}
            {clockLive && ', Space pause, 1-4 speed'}, Esc let go
          </span>
        )}
      </div>
      {/* the right column: People on top, shrinking to what the minimap, clock and follow bar below leave */}
      <div className="pointer-events-none absolute top-(--toolbar-bottom) right-3 bottom-3 flex flex-col items-end gap-2 *:pointer-events-auto">
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
        <div className="pointer-events-none! mt-auto flex shrink-0 flex-col items-end gap-2 *:pointer-events-auto">
          {minimapOpen && ready && (
            <Minimap
              sites={goTo}
              terrain={planet.terrain}
              biomeNames={view.biome_names}
              town={minimapTown}
              citizens={live.citizens}
              animals={live.animals}
              fires={live.fires}
              views={npcViews}
              focusRef={focusRef}
              onGo={goNear}
            />
          )}
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
      </div>
      {feed.status !== 'off' && (
        <EventFeed
          listen={feed.listen}
          subjects={feedSubjects}
          canFly={canFly}
          open={feedOpen}
          onToggle={() => setFeedOpen((open) => !open)}
          onFly={flyTo}
        />
      )}
      {scoresShown && scoreboardOpen && (
        <Scoreboard
          at={replayTick}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id);
            setInspectorOpen(true);
          }}
          onClose={() => setScoreboardOpen(false)}
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
          className="absolute top-(--toolbar-bottom) left-1/2 -translate-x-1/2 rounded-lg bg-white/90 px-3 py-2 text-sm shadow"
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
  const flora = useFlora(world.data);
  const error = world.error ?? town.error ?? flora.error;
  if (error)
    return (
      <Message testId="world-error">
        <p className="font-medium">The world could not be loaded.</p>
        <p className="text-muted-foreground mt-1">
          Is the backend running on port 8100? ({error.message})
        </p>
      </Message>
    );
  if (!world.data || !town.data || !flora.data)
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
        Loading the world…
      </div>
    );
  return <GlobeWorld view={world.data} town={town.data} flora={flora.data} />;
}
