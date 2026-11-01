import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import {
  memo,
  Suspense,
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { type Group, Matrix4, Vector3 } from 'three';
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js';

import { AnimalModel } from '@/components/world/animal-model';
import { MAX_FRAME, smoothing } from '@/components/world/player/motion';
import {
  type AnimalActivity,
  type AnimalDrive,
  type AnimalTrack,
  clipOf,
  followAnimal,
  layerOf,
  moveAnimal,
  newAnimalTrack,
  newDrive,
  shownActivity,
  slopePitch,
  wantedYaw,
} from '@/lib/live/animal-motion';
import type { LiveAnimal } from '@/lib/live/live-contract';
import { groundSpeed } from '@/lib/live/walk-path';
import { ANIMALS, assetSize, assetUrl, PROPS } from '@/lib/world/assets';
import {
  type GlobeTerrain,
  tangentFrame,
  WATER_BIOMES,
} from '@/lib/world/globe';
import { clockRate, visualRate } from '@/lib/world/visual-rate';

/*
 * The animals on the planet, where the live feed says they are. Like the citizens, each walks the timed path its
 * tick streamed (`route`, from where it stood when the tick began), one tick behind the sim, with game seconds
 * passing at the clock's speed, facing the way it goes (its heading standing), and keeps the moving activity it was
 * shown until it gets where the tick says: a caught deer falls where its flight ends, a wolf pounces where its run
 * ends (`animal-motion.ts`). Its gait clip is paced to the ground it covers and its activity lays a procedural layer
 * over the clip (grazing heads down, alert heads up, a stalk low, a pounce's leap, a bite, a bear rearing, feeding,
 * drinking, asleep on folded legs, dead on its side); remains are drawn as scattered bones. Land animals stand on the
 * rendered ground, pitched to its slope; fish and sharks swim just under the water's surface the feed gives (sea
 * level or a lake's), ducks float on water and walk on land. Models load only within NEAR metres of the camera.
 */

/** Models within this distance of the camera (they hide past HIDE). */
const NEAR = 400;
const HIDE = 420;
/** Far animals skip placing themselves on the ground every frame. */
const SKIP_PLACING = HIDE + 150;
const TURN_RATE = 6;
/** How far under the surface swimmers are drawn. */
const DEPTH: Partial<Record<LiveAnimal['kind'], number>> = {
  fish: 0.3,
  shark: 0.9,
};
/** The bone scatter is this long (metres) at scale 1; remains are drawn about their animal's length. */
const BONES = PROPS.bone_scatter;
const BONES_LENGTH = assetSize(BONES).z;

const basis = new Matrix4();
const side = new Vector3();
const probe = new Vector3();

/** What the page and the tests can read of a drawn animal (mutated every frame). */
interface AnimalView {
  id: string;
  kind: LiveAnimal['kind'];
  /** What it is shown doing (the move's activity while it walks to where the feed says it is). */
  activity: AnimalActivity;
  /** World position of its feet (or its body, for swimmers) and the way it faces (unit, on the ground's plane). */
  position: Vector3;
  facing: Vector3;
  /** Within reach of the camera: shown and animated. */
  near: boolean;
  /** What its model was told and reports: clip ('' until loaded or while far), layer, pace, pose. */
  drive: AnimalDrive;
  /** Drawn as scattered bones. */
  remains: boolean;
  /** Nose-up pitch to the slope under it (radians). */
  pitch: number;
}

export type AnimalViews = Map<string, AnimalView>;

const wrapAngle = (angle: number) =>
  Math.atan2(Math.sin(angle), Math.cos(angle));

/** Swimmers and floating ducks keep level with the water; land animals follow the ground. */
function onWater(
  animal: LiveAnimal,
  terrain: GlobeTerrain,
  direction: Vector3,
) {
  return (
    DEPTH[animal.kind] !== undefined ||
    (animal.kind === 'duck' && WATER_BIOMES.has(terrain.biomeAt(direction)))
  );
}

/** How high the animal is drawn above sea level at the direction. */
function heightOf(
  animal: LiveAnimal,
  terrain: GlobeTerrain,
  direction: Vector3,
) {
  const depth = DEPTH[animal.kind] ?? 0;
  if (onWater(animal, terrain, direction))
    return animal.position.height_m - depth;
  return terrain.heightAt(direction);
}

function Bones({ length }: { length: number }) {
  const { scene } = useGLTF(assetUrl(BONES));
  const model = useMemo(() => clone(scene), [scene]);
  const scale = Math.min(Math.max(length / BONES_LENGTH, 0.3), 1.6);
  return <primitive object={model} scale={scale} />;
}

// memo: a tick keeps an unchanged animal's object (`live-state.ts`), so only the animals it changed render again
const Animal = memo(function Animal({
  animal,
  terrain,
  rate,
  routeless,
  replay,
  views,
}: {
  animal: LiveAnimal;
  terrain: GlobeTerrain;
  /** The clock: game seconds per real second (0 paused). */
  rate: number;
  /** The feed streams no animal routes (from before them): moves are walked straight over the tick. */
  routeless: boolean;
  replay: boolean;
  views: AnimalViews;
}) {
  const radius = terrain.globe.radius;
  const spec = ANIMALS[animal.kind];
  const length = assetSize(spec.asset).z * (spec.scale ?? 1);
  const group = useRef<Group>(null);
  const tilt = useRef<Group>(null);
  const living = useRef<Group>(null);
  const bones = useRef<Group>(null);
  const [mounted, setMounted] = useState(false);
  const [remains, setRemains] = useState(animal.activity === 'remains');
  const [firstTrack] = useState(() => newAnimalTrack(animal, radius, replay));
  const trackRef = useRef<AnimalTrack>(firstTrack);
  const yaw = useRef((animal.heading_deg * Math.PI) / 180);
  const driveRef = useRef<AnimalDrive>(newDrive());
  const viewRef = useRef<AnimalView>({
    id: animal.id,
    kind: animal.kind,
    activity: shownActivity(firstTrack),
    position: new Vector3(),
    facing: new Vector3(),
    near: false,
    drive: newDrive(),
    remains: false,
    pitch: 0,
  });
  const scratch = useMemo(() => ({ direction: new Vector3() }), []);

  // every new frame: the move it streams, joined where the animal is drawn
  const onFrame = useEffectEvent((next: LiveAnimal) =>
    followAnimal(trackRef.current, next, radius, rate, routeless),
  );
  useLayoutEffect(() => onFrame(animal), [animal]);

  useEffect(() => {
    viewRef.current.drive = driveRef.current; // what its model is told and reports
    views.set(animal.id, viewRef.current);
    return () => {
      views.delete(animal.id);
    };
  }, [animal.id, views]);

  useFrame(({ camera }, frameDelta) => {
    const body = group.current;
    if (!body) return;
    const delta = Math.min(frameDelta, MAX_FRAME);
    const track = trackRef.current;
    const view = viewRef.current;
    const at = moveAnimal(track, delta, rate, scratch.direction);
    const shown = shownActivity(track);
    view.activity = shown;
    const rough = view.position.copy(at).multiplyScalar(radius);
    if (camera.position.distanceTo(rough) > SKIP_PLACING) {
      body.visible = view.near = false;
      return;
    }
    const height = heightOf(animal, terrain, at);
    view.position.copy(at).multiplyScalar(radius + height);
    const { east, south, up } = tangentFrame(at);
    const wanted = wantedYaw(
      track,
      east,
      south,
      yaw.current,
      animal.heading_deg,
    );
    // turning is procedural motion: sped up with the clock like the clips (frozen paused)
    yaw.current +=
      wrapAngle(wanted - yaw.current) *
      smoothing(TURN_RATE, delta * visualRate(rate));
    const facing = east
      .multiplyScalar(Math.sin(yaw.current))
      .addScaledVector(south, Math.cos(yaw.current));
    view.facing.copy(facing);
    body.position.copy(view.position);
    basis.makeBasis(side.crossVectors(up, facing), up, facing);
    body.quaternion.setFromRotationMatrix(basis);
    const wasNear = view.near;
    view.near =
      camera.position.distanceTo(view.position) < (wasNear ? HIDE : NEAR);
    body.visible = view.near && track.opacity >= 0.5;
    if (!view.near) return;
    if (!mounted) setMounted(true);
    // pitched to the ground under its front and hind feet
    const ahead = (metres: number) =>
      terrain.heightAt(
        probe
          .copy(at)
          .addScaledVector(facing, metres / radius)
          .normalize(),
      );
    view.pitch = onWater(animal, terrain, at)
      ? 0
      : slopePitch(ahead(length / 2), ahead(-length / 2), length);
    if (tilt.current) tilt.current.rotation.x = -view.pitch;
    const speed = groundSpeed(track.path);
    const { drive } = view;
    drive.speed = speed;
    drive.clip = clipOf(animal.kind, shown, track.gait, speed);
    drive.layer = layerOf(animal.kind, shown, track.gait);
    drive.rate = visualRate(rate);
    view.remains = drive.layer === 'remains';
    if (view.remains !== remains) setRemains(view.remains);
    if (living.current) living.current.visible = !view.remains;
    if (bones.current) bones.current.visible = view.remains;
  });

  return (
    <group ref={group} visible={false}>
      {mounted && (
        <group ref={tilt}>
          <group ref={living}>
            <Suspense fallback={null}>
              <AnimalModel kind={animal.kind} driveRef={driveRef} />
            </Suspense>
          </group>
          {remains && (
            <group ref={bones}>
              <Suspense fallback={null}>
                <Bones length={length} />
              </Suspense>
            </group>
          )}
        </group>
      )}
    </group>
  );
});

/** The animals are drawn in this many groups (each animal always in the same one, by its id). */
const GROUPS = 64;

function groupOf(id: string) {
  let hash = 0;
  for (let k = 0; k < id.length; k++) hash = (hash * 31 + id.charCodeAt(k)) | 0;
  return Math.abs(hash) % GROUPS;
}

interface GroupProps {
  animals: LiveAnimal[];
  terrain: GlobeTerrain;
  rate: number;
  routeless: boolean;
  replay: boolean;
  views: AnimalViews;
}

const sameGroup = (before: GroupProps, after: GroupProps) =>
  before.animals.length === after.animals.length &&
  before.animals.every((animal, index) => animal === after.animals[index]) &&
  before.terrain === after.terrain &&
  before.rate === after.rate &&
  before.routeless === after.routeless &&
  before.replay === after.replay &&
  before.views === after.views;

// a group none of whose animals a tick changed (`live-state.ts` keeps their objects) isn't drawn again at all
const AnimalGroup = memo(function AnimalGroup({
  animals,
  ...props
}: GroupProps) {
  return animals.map((animal) => (
    <Animal key={animal.id} animal={animal} {...props} />
  ));
}, sameGroup);

/** Inside the Canvas: every live animal, drawn where the feed says (models only near the camera). */
export function GlobeAnimals({
  animals,
  speed,
  paused,
  replay = false,
  terrain,
  views,
}: {
  animals: LiveAnimal[];
  /** The feed's clock: game seconds per real second, and whether it is paused. */
  speed: number;
  paused: boolean;
  /** The animals of a replayed moment (`?tick=`), which no tick follows. */
  replay?: boolean;
  terrain: GlobeTerrain;
  /** Filled with what is drawn of each animal. */
  views: AnimalViews;
}) {
  // a feed that has streamed an animal's route streams them all (a later routeless move is a jump)
  const [routed, setRouted] = useState(false);
  if (!routed && animals.some((animal) => animal.route.length > 1))
    setRouted(true);
  const groups = useMemo(() => {
    const grouped = Array.from({ length: GROUPS }, (): LiveAnimal[] => []);
    for (const animal of animals) grouped[groupOf(animal.id)].push(animal);
    return grouped;
  }, [animals]);
  return groups.map((group, index) => (
    <AnimalGroup
      key={index}
      animals={group}
      terrain={terrain}
      rate={clockRate(speed, paused)}
      routeless={!routed}
      replay={replay}
      views={views}
    />
  ));
}

const fixed = (value: number, digits = 2) => value.toFixed(digits);

/** Hidden DOM hooks for tests: what is drawn of the animals, refreshed every 0.1 s. */
export function AnimalHooks({ views }: { views: AnimalViews }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const element = root.current;
      if (!element) return;
      const near = [...views.values()].filter((view) => view.near);
      element.dataset.animals = String(views.size);
      element.dataset.animalsNear = String(near.length);
      element.dataset.nearKinds = [...new Set(near.map((v) => v.kind))]
        .sort()
        .join(',');
      element.dataset.nearClips = near
        .map((v) => `${v.id}:${v.activity}:${v.drive.clipName}`)
        .join(' ');
      // layer, clip pace, drawn speed (m/s), roll and lift of the body, slope pitch; remains drawn as bones
      element.dataset.nearMotion = near
        .map(
          ({ id, drive, pitch, remains }) =>
            `${id}:${remains ? 'bones' : drive.layer}:${fixed(drive.pace)}:${fixed(drive.speed)}:${fixed(drive.pose.roll)}:${fixed(drive.pose.lift)}:${fixed(pitch)}`,
        )
        .join(' ');
      element.dataset.nearPositions = near
        .map((v) => `${v.id}:${v.position.toArray().map((n) => fixed(n, 3))}`)
        .join(' ');
      element.dataset.nearFacing = near
        .map((v) => `${v.id}:${v.facing.toArray().map((n) => fixed(n, 3))}`)
        .join(' ');
    }, 100);
    return () => window.clearInterval(timer);
  }, [views]);
  return <div ref={root} hidden data-testid="animals" data-animals={0} />;
}
