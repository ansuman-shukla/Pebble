import { useFrame } from '@react-three/fiber';
import {
  Suspense,
  useCallback,
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { type Group, Matrix4, Vector3 } from 'three';

import { type AnimalGait, AnimalModel } from '@/components/world/animal-model';
import { MAX_FRAME, smoothing } from '@/components/world/player/motion';
import {
  type AnimalActivity,
  type LiveAnimal,
  tickMs,
} from '@/lib/live/live-contract';
import {
  type GlobeTerrain,
  tangentFrame,
  WATER_BIOMES,
} from '@/lib/world/globe';

/*
 * The animals on the planet, where the live feed says they are. Like the citizens, each glides from where it was
 * drawn to its new position over one tick at the feed's speed and turns smoothly to its heading. Land animals
 * stand on the rendered ground; fish and sharks swim just under the water's surface the feed gives (sea level or
 * a lake's), ducks float on water and walk on land. Models load only within NEAR metres of the camera.
 */

/** Models within this distance of the camera (they hide past HIDE). */
const NEAR = 400;
const HIDE = 420;
/** Far animals skip placing themselves on the ground every frame. */
const SKIP_PLACING = HIDE + 150;
const TURN_RATE = 6;
const MIN_GLIDE = 16;
/** How far under the surface swimmers are drawn. */
const DEPTH: Partial<Record<LiveAnimal['kind'], number>> = {
  fish: 0.3,
  shark: 0.9,
};

const GAITS: Record<AnimalActivity, AnimalGait> = {
  idle: 'idle',
  grazing: 'idle',
  alert: 'idle',
  frozen: 'idle',
  pouncing: 'idle',
  attacking: 'idle',
  feeding: 'idle',
  drinking: 'idle',
  floating: 'idle',
  sleeping: 'idle',
  dead: 'idle',
  remains: 'idle',
  walking: 'move',
  prowling: 'move',
  stalking: 'move',
  swimming: 'move',
  trotting: 'run',
  running: 'run',
  fleeing: 'run',
  hunting: 'run',
  chasing: 'run',
};

const basis = new Matrix4();
const side = new Vector3();

/** What the page and the tests can read of a drawn animal (mutated every frame). */
interface AnimalView {
  id: string;
  kind: LiveAnimal['kind'];
  activity: AnimalActivity;
  /** World position of its feet (or its body, for swimmers). */
  position: Vector3;
  /** Within reach of the camera: shown and animated. */
  near: boolean;
  /** The clip playing ('' until the model is loaded or while it is far). */
  clip: string;
}

export type AnimalViews = Map<string, AnimalView>;

interface Track {
  from: Vector3;
  to: Vector3;
  start: number;
  duration: number;
  yaw: number;
}

const wrapAngle = (angle: number) =>
  Math.atan2(Math.sin(angle), Math.cos(angle));

/** How high the animal is drawn above sea level at the direction. */
function heightOf(
  animal: LiveAnimal,
  terrain: GlobeTerrain,
  direction: Vector3,
) {
  const depth = DEPTH[animal.kind];
  if (depth !== undefined) return animal.position.height_m - depth;
  if (animal.kind === 'duck' && WATER_BIOMES.has(terrain.biomeAt(direction)))
    return animal.position.height_m;
  return terrain.heightAt(direction);
}

function Animal({
  animal,
  terrain,
  interval,
  views,
}: {
  animal: LiveAnimal;
  terrain: GlobeTerrain;
  interval: number;
  views: AnimalViews;
}) {
  const radius = terrain.globe.radius;
  const group = useRef<Group>(null);
  const [mounted, setMounted] = useState(false);
  const trackRef = useRef<Track>({
    from: new Vector3(...animal.position.unit),
    to: new Vector3(...animal.position.unit),
    start: 0,
    duration: 1,
    yaw: (animal.heading_deg * Math.PI) / 180,
  });
  const viewRef = useRef<AnimalView>({
    id: animal.id,
    kind: animal.kind,
    activity: animal.activity,
    position: new Vector3(),
    near: false,
    clip: '',
  });
  const direction = useRef(new Vector3());

  const glide = useEffectEvent((next: LiveAnimal) => {
    const track = trackRef.current;
    const now = performance.now();
    const t = Math.min((now - track.start) / track.duration, 1);
    track.from.lerp(track.to, t).normalize();
    track.to.set(...next.position.unit);
    track.start = now;
    track.duration = interval;
    viewRef.current.activity = next.activity;
  });
  useLayoutEffect(() => glide(animal), [animal]);

  useEffect(() => {
    views.set(animal.id, viewRef.current);
    return () => {
      views.delete(animal.id);
    };
  }, [animal.id, views]);

  const onClip = useCallback((clip: string) => {
    viewRef.current.clip = viewRef.current.near ? clip : '';
  }, []);

  useFrame(({ camera }, frameDelta) => {
    const body = group.current;
    if (!body) return;
    const track = trackRef.current;
    const view = viewRef.current;
    const t = Math.min((performance.now() - track.start) / track.duration, 1);
    const at = direction.current.lerpVectors(track.from, track.to, t);
    at.normalize();
    const rough = view.position.copy(at).multiplyScalar(radius);
    if (camera.position.distanceTo(rough) > SKIP_PLACING) {
      body.visible = view.near = false;
      view.clip = '';
      return;
    }
    const height = heightOf(animal, terrain, at);
    view.position.copy(at).multiplyScalar(radius + height);
    const wanted = (animal.heading_deg * Math.PI) / 180;
    track.yaw +=
      wrapAngle(wanted - track.yaw) *
      smoothing(TURN_RATE, Math.min(frameDelta, MAX_FRAME));
    const { east, south, up } = tangentFrame(at);
    const facing = east
      .multiplyScalar(Math.sin(track.yaw))
      .addScaledVector(south, Math.cos(track.yaw));
    body.position.copy(view.position);
    basis.makeBasis(side.crossVectors(up, facing), up, facing);
    body.quaternion.setFromRotationMatrix(basis);
    const wasNear = view.near;
    view.near =
      camera.position.distanceTo(view.position) < (wasNear ? HIDE : NEAR);
    body.visible = view.near;
    if (!view.near) view.clip = '';
    if (view.near && !mounted) setMounted(true);
  });

  const dead = animal.activity === 'dead';
  return (
    <group ref={group} visible={false}>
      {mounted && (
        <group rotation-z={dead ? Math.PI / 2 : 0} position-y={dead ? 0.1 : 0}>
          <Suspense fallback={null}>
            <AnimalModel
              kind={animal.kind}
              gait={GAITS[animal.activity]}
              still={dead}
              onClip={onClip}
            />
          </Suspense>
        </group>
      )}
    </group>
  );
}

/** Inside the Canvas: every live animal, drawn where the feed says (models only near the camera). */
export function GlobeAnimals({
  animals,
  speed,
  terrain,
  views,
}: {
  animals: LiveAnimal[];
  /** The feed's speed (ticks per real second): how long glides between frames take. */
  speed: number;
  terrain: GlobeTerrain;
  /** Filled with what is drawn of each animal. */
  views: AnimalViews;
}) {
  const interval = speed > 0 ? Math.max(tickMs(speed), MIN_GLIDE) : tickMs(1);
  return (
    <>
      {animals.map((animal) => (
        <Animal
          key={animal.id}
          animal={animal}
          terrain={terrain}
          interval={interval}
          views={views}
        />
      ))}
    </>
  );
}

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
        .map((v) => `${v.id}:${v.activity}:${v.clip}`)
        .join(' ');
      element.dataset.nearPositions = near
        .map((v) => `${v.id}:${v.position.toArray().map((n) => n.toFixed(3))}`)
        .join(' ');
    }, 100);
    return () => window.clearInterval(timer);
  }, [views]);
  return <div ref={root} hidden data-testid="animals" data-animals={0} />;
}
