/*
 * How a live animal is drawn (10 §4.2, §4.6; D144-D146). Like a citizen, it walks the timed path its tick streamed
 * (`walk-path.ts`), one tick behind the sim, and keeps the moving activity it was shown until the drawn body reaches
 * the end of that path: a deer caught at the end of its flight runs there, then falls; a wolf runs in, then pounces.
 * What it is shown doing picks a baked clip and a procedural layer on top of it:
 *
 *   frame ─▶ track ─▶ shown activity + drawn ground speed + gait
 *                      ├─▶ clip: idle / move / run, played at drawn speed ÷ the clip's own stride speed (no slip)
 *                      └─▶ layer: graze, alert, prowl, stalk, flee, frozen, pounce, bite, rear, feed, drink, sleep,
 *                                 dead, remains ─▶ bones (head, jaw, ears, crouch with feet planted, folded legs)
 *                                                  and body (pounce arc, rear about the hind feet, roll onto its side)
 *
 * Clips and layers run at their natural speed × `visualRate` (the caller's clock), so ×1 and ×10 stay stride-locked.
 * Every quadruped of the asset pack shares one rig (Hips ▸ Spine ▸ Chest ▸ Neck ▸ Head ▸ Jaw/ears, four three-joint
 * legs ending in a `…Foot`, bones at rest along +Z forward, +Y up); fish and sharks have no feet and swim at the
 * clip's own pace. Pure but for three.js objects: `globe-animals.tsx` and `animal-model.tsx` drive it, the tests
 * drive it directly.
 */
import {
  type AnimationClip,
  AnimationMixer,
  type Bone,
  Matrix4,
  type Object3D,
  Quaternion,
  Vector3,
} from 'three';

import {
  advance,
  carriedOn,
  citizenPath,
  groundSpeed,
  joinAt,
  pointAt,
  snapMetres,
  walkPath,
  type WalkPath,
} from './walk-path';
import { TICK_SECONDS } from './live-contract';
import type { AnimalEntity, RoutePoint } from '@/lib/client/types.gen';

export type AnimalActivity = AnimalEntity['activity'];
export type AnimalGait = AnimalEntity['gait'];
type AnimalKind = AnimalEntity['kind'];

/** The baked clip a body plays: standing (floating), walking (swimming), running (swimming fast). */
export type AnimalClip = 'idle' | 'move' | 'run';

/** The procedural motion laid over the clip. */
export type AnimalLayer =
  | 'none'
  | 'prowl'
  | 'stalk'
  | 'flee'
  | 'graze'
  | 'alert'
  | 'frozen'
  | 'pounce'
  | 'bite'
  | 'rear'
  | 'feed'
  | 'drink'
  | 'sleep'
  | 'dead'
  | 'remains';

interface ActivityLook {
  /** An activity of the move: shown while the drawn body walks its path. */
  moving: boolean;
  layer: AnimalLayer;
  /** Drawn with the running clip whatever the gait says. */
  run?: boolean;
}

const ACTIVITIES: Record<AnimalActivity, ActivityLook> = {
  idle: { moving: false, layer: 'none' },
  grazing: { moving: false, layer: 'graze' },
  alert: { moving: false, layer: 'alert' },
  walking: { moving: true, layer: 'none' },
  trotting: { moving: true, layer: 'none', run: true },
  running: { moving: true, layer: 'none', run: true },
  fleeing: { moving: true, layer: 'flee', run: true },
  frozen: { moving: false, layer: 'frozen' },
  prowling: { moving: true, layer: 'prowl' },
  stalking: { moving: true, layer: 'stalk' },
  hunting: { moving: true, layer: 'none' }, // v0's approach: the gait says stalk or run
  chasing: { moving: true, layer: 'none', run: true },
  pouncing: { moving: false, layer: 'pounce' },
  attacking: { moving: false, layer: 'bite' },
  feeding: { moving: false, layer: 'feed' },
  drinking: { moving: false, layer: 'drink' },
  floating: { moving: false, layer: 'none' },
  swimming: { moving: true, layer: 'none' },
  sleeping: { moving: false, layer: 'sleep' },
  dead: { moving: false, layer: 'dead' },
  remains: { moving: false, layer: 'remains' },
};

/** Kinds that attack by rearing up before they bite. */
const REARS: ReadonlySet<AnimalKind> = new Set(['bear', 'polar_bear']);
/** Kinds whose every move is a hop (their walk clip barely lifts a foot). */
const HOPS: ReadonlySet<AnimalKind> = new Set(['rabbit', 'hare']);

/** The layer drawn for what an animal is shown doing. */
export function layerOf(
  kind: AnimalKind,
  activity: AnimalActivity,
  gait: AnimalGait,
): AnimalLayer {
  const { layer } = ACTIVITIES[activity];
  if (layer === 'bite' && REARS.has(kind)) return 'rear';
  if (layer === 'none' && gait === 'stalk') return 'stalk';
  return layer;
}

/** The clip for a body drawn at `speed` (game m/s) walking a path walked at `gait`. */
export function clipOf(
  kind: AnimalKind,
  activity: AnimalActivity,
  gait: AnimalGait,
  speed: number,
): AnimalClip {
  if (speed <= 0) return 'idle';
  if (HOPS.has(kind)) return 'run';
  return gait === 'run' || gait === 'trot' || ACTIVITIES[activity].run
    ? 'run'
    : 'move';
}

/**
 * How many times its natural speed a gait clip plays so the feet keep still on the ground: the drawn ground speed
 * over the clip's own (its planted feet's backward speed, `strideSpeed`); swimmers' clips play at their own pace.
 */
export const paceOf = (speed: number, natural: number | null) =>
  natural ? speed / natural : 1;

// --- the track: where the body is drawn and what it is shown doing ---

/** What a feed frame says of an animal's place, move and doing. */
interface Streamed {
  position: { unit: [number, number, number] };
  route: RoutePoint[];
  speed_mps: number;
  heading_deg: number;
  activity: AnimalActivity;
  gait: AnimalGait;
}

/** How fast the drawn spot eases onto a new tick's path when it is a little off (1/s). */
const CATCH_UP_RATE = 3;
/** A resync fades the body out where it was drawn and in on its path over this long (real seconds). */
const FADE_S = 0.3;

export interface AnimalTrack {
  /** The path the feed streamed for this tick (one point when standing) and how far along it the animal is. */
  path: WalkPath;
  /** Drawn spot minus the spot on the path (unit-sphere vector), easing to zero after a new tick. */
  offset: Vector3;
  /** A resync under way: where the body was drawn (it fades out there) and real seconds since it began. */
  fade: { from: Vector3; elapsed: number } | null;
  /** How opaque the body is drawn (below 1 only while fading). */
  opacity: number;
  /** What the latest frame says: its activity and the gait its path was walked at. */
  activity: AnimalActivity;
  gait: AnimalGait;
  /** What it is shown doing instead while the drawn body walks to where the frame says it is (moving). */
  held: AnimalActivity | null;
  /** What it was shown doing when the frame came: kept until the body sets off on the frame's path... */
  before: AnimalActivity;
  /** ...at this many game seconds along it (Infinity when the path doesn't move). */
  departs: number;
  /** Where the latest frame says it is (a unit direction). */
  at: Vector3;
}

/** The moving activity shown for a body that moved before it was seen doing anything moving. */
const MOVING_BY_GAIT: Record<AnimalGait, AnimalActivity> = {
  walk: 'walking',
  trot: 'trotting',
  run: 'running',
  stalk: 'stalking',
  swim: 'swimming',
};

/** Spots closer than this (metres) are one spot. */
const SAME_SPOT_M = 1e-3;
/** A new path starting within this of the drawn body (metres) starts from its beginning. */
const START_M = 1;

/** Activities a body doesn't walk out of: a routeless move from them is a respawn elsewhere (a resync), not a walk. */
const LYING_STILL: ReadonlySet<AnimalActivity> = new Set(['dead', 'remains']);

/**
 * The path a frame says to draw: its route, or, in a feed that streams no animal routes (from before them, 10
 * §4.2.1), a straight walk over the tick from where the last frame put it, so its moves are still walked, never
 * jumped. In a feed that does, a move without a route is a jump (a skip, a respawn): a resync.
 */
function animalPath(
  animal: Streamed,
  track: AnimalTrack,
  radius: number,
  routeless: boolean,
) {
  const now = new Vector3(...animal.position.unit).normalize();
  if (
    !routeless ||
    animal.route.length >= 2 ||
    LYING_STILL.has(track.activity) ||
    track.at.angleTo(now) * radius <= SAME_SPOT_M
  )
    return citizenPath(animal, radius);
  const path = walkPath(
    [track.at.toArray(), now.toArray()],
    [0, TICK_SECONDS],
    radius,
  );
  path.arrive = TICK_SECONDS;
  return path;
}

const runs = (activity: AnimalActivity, gait: AnimalGait) =>
  Boolean(ACTIVITIES[activity].run) || gait === 'run' || gait === 'trot';

/**
 * What to show while the body walks to a frame's spot: nothing new if the frame moves on, else the move it was shown
 * on if the path keeps its pace (a stalk stays a stalk), else the path's gait (the stalk breaking into a run).
 */
function heldFor(next: Streamed, shown: AnimalActivity | null) {
  if (ACTIVITIES[next.activity].moving) return null;
  return shown &&
    ACTIVITIES[shown].moving &&
    runs(shown, 'walk') === runs(next.activity, next.gait)
    ? shown
    : MOVING_BY_GAIT[next.gait];
}

/** Game seconds along a path at which it starts moving (after a wait at its start); Infinity standing. */
function departure(path: WalkPath) {
  const { points, times } = path;
  for (let k = 0; k < points.length - 1; k++)
    if (points[k].angleTo(points[k + 1]) > 0) return times[k];
  return Infinity;
}

/**
 * An animal first seen is drawn like any other, one tick behind: where its tick's move began, walking it. A replayed
 * moment (`now`), which no tick follows, draws it where the frame says it is.
 */
export function newAnimalTrack(
  animal: Streamed,
  radius: number,
  now = false,
): AnimalTrack {
  const path = citizenPath(animal, radius);
  if (now) path.time = path.arrive;
  const held = heldFor(animal, null);
  return {
    path,
    offset: new Vector3(),
    fade: null,
    opacity: 1,
    activity: animal.activity,
    gait: animal.gait,
    held,
    before: held ?? animal.activity,
    departs: departure(path),
    at: new Vector3(...animal.position.unit).normalize(),
  };
}

/**
 * What the animal is shown doing now: what it was doing until it sets off on its path, the move while on its way, the
 * frame's activity once there (a deer grazes until it bolts, flees, and falls where it is caught).
 */
export function shownActivity(track: AnimalTrack): AnimalActivity {
  const { path } = track;
  if (path.time >= path.arrive) return track.activity;
  if (path.time < track.departs) return track.before;
  return track.held ?? track.activity;
}

const onPath = (track: AnimalTrack, out: Vector3) =>
  pointAt(track.path, out).add(track.offset).normalize();

/**
 * Puts a new frame's path under the animal, joined where it is drawn now (no jump, no step back); far off, a resync
 * fades it out and in. `rate` is the clock (game seconds per real second); `routeless`: the feed streams no animal
 * routes.
 */
export function followAnimal(
  track: AnimalTrack,
  animal: Streamed,
  radius: number,
  rate: number,
  routeless = false,
) {
  const next = animalPath(animal, track, radius, routeless);
  const shown = shownActivity(track);
  track.held = heldFor(animal, shown);
  track.before = shown;
  track.activity = animal.activity;
  track.gait = animal.gait;
  track.at.set(...animal.position.unit).normalize();
  const carried = carriedOn(track.path, next, radius);
  if (carried) {
    track.path = carried;
    track.departs = departure(carried);
    return;
  }
  const drawn = onPath(track, new Vector3());
  const limit = snapMetres(groundSpeed(track.path), rate);
  // normally the new path starts about where the body is drawn: it starts there (eased on), even if the path waits
  // a while before moving (joining at the nearest spot would skip the wait)
  const start = drawn.angleTo(next.points[0]) * radius;
  const off = start <= START_M ? start : joinAt(next, drawn, radius);
  track.path = next;
  track.departs = departure(next);
  if (off <= limit) {
    track.offset.subVectors(drawn, pointAt(next, new Vector3()));
    return;
  }
  track.offset.set(0, 0, 0);
  track.fade = { from: track.fade?.from ?? drawn, elapsed: 0 };
}

/**
 * Moves the animal on by `delta` real seconds at the clock's `rate`; returns where the body is drawn (a unit
 * direction into `out`) and updates its opacity.
 */
export function moveAnimal(
  track: AnimalTrack,
  delta: number,
  rate: number,
  out: Vector3,
) {
  advance(track.path, delta * rate);
  track.offset.multiplyScalar(Math.exp(-CATCH_UP_RATE * delta));
  onPath(track, out);
  const { fade } = track;
  if (!fade) return out;
  fade.elapsed += delta;
  const half = FADE_S / 2;
  track.opacity = Math.min(Math.abs(fade.elapsed - half) / half, 1);
  if (fade.elapsed >= FADE_S) track.fade = null;
  return fade.elapsed < half ? out.copy(fade.from) : out;
}

// --- layers: what the bones and the body do on top of the clip ---

export interface LayerPose {
  /** 0..1: how far the neck lowers from its own rest towards pointing REACH_DOWN below level (and the chest bows):
   * 1 puts a grazer's muzzle in the grass whatever its build. */
  reach: number;
  /** Radians the neck and the head bow on top (negative: raised), the jaw opens and the ears prick forward
   * (negative: back). */
  neck: number;
  head: number;
  jaw: number;
  ears: number;
  /** Share of its hip height the body sinks, feet kept where they stand (stalking, freezing). */
  crouch: number;
  /** 0..1: legs folded under a body lying on its belly (asleep). */
  fold: number;
  /** Metres the body rises off the ground (a pounce's leap). */
  lift: number;
  /** Radians the body rears up about its hind feet. */
  rear: number;
  /** Radians it has rolled onto its side (dead). */
  roll: number;
  /** How much bigger than at rest the chest is drawn (breathing asleep). */
  breathe: number;
  /** The clip holds still (no idle sway: frozen, asleep, dead). */
  still: boolean;
}

const DEG = Math.PI / 180;
/** How far below level a fully lowered neck points, and how far the chest bows with it (radians). */
const REACH_DOWN = 60 * DEG;
const REACH_CHEST = 12 * DEG;
/** Share of the hip height a sleeper's hips sink to lie on its belly. */
const LIE_DROP = 0.55;
/** A pounce's leap: how long it lasts (natural seconds) and how high it goes (metres). */
export const POUNCE_S = 0.5;
const POUNCE_M = 0.5;
/** A death's fall onto the side (natural seconds). */
export const FALL_S = 0.8;
/** A bear's rear-and-bite cycle (natural seconds). */
const REAR_CYCLE_S = 3;

const REST: LayerPose = {
  reach: 0,
  neck: 0,
  head: 0,
  jaw: 0,
  ears: 0,
  crouch: 0,
  fold: 0,
  lift: 0,
  rear: 0,
  roll: 0,
  breathe: 0,
  still: false,
};

/** 0 → 1 → 0 at `hz` (starts closed). */
const pulse = (t: number, hz: number) =>
  0.5 - 0.5 * Math.cos(2 * Math.PI * hz * t);
const wave = (t: number, hz: number) => Math.sin(2 * Math.PI * hz * t);

/** How far up a bear is in its rear-and-bite cycle (0 on all fours, 1 fully up). */
function rearShare(t: number) {
  const u = (t % REAR_CYCLE_S) / REAR_CYCLE_S;
  if (u < 0.2) return u / 0.2;
  if (u < 0.6) return 1;
  if (u < 0.75) return (0.75 - u) / 0.15;
  return 0;
}

/** The layer's pose `t` natural seconds after it began showing. */
export function layerPose(layer: AnimalLayer, t: number): LayerPose {
  switch (layer) {
    case 'graze': // muzzle down in the grass, chewing at 2 Hz
      return { ...REST, reach: 1, head: 25 * DEG, jaw: 0.15 * pulse(t, 2) };
    case 'alert': // head up, ears forward, facing the threat (its heading)
      return { ...REST, neck: -20 * DEG, head: -10 * DEG, ears: 25 * DEG };
    case 'prowl':
      return { ...REST, reach: 0.2, head: -5 * DEG };
    case 'stalk': // hips 20 % lower, head low and level, eyes on the prey
      return {
        ...REST,
        crouch: 0.2,
        reach: 0.45,
        head: -25 * DEG,
        ears: 15 * DEG,
      };
    case 'flee':
      return { ...REST, neck: -8 * DEG, ears: -35 * DEG };
    case 'frozen': // pressed low, ears flat, not a twitch
      return {
        ...REST,
        crouch: 0.15,
        reach: 0.3,
        ears: -40 * DEG,
        still: true,
      };
    case 'pounce': {
      const share = Math.min(t / POUNCE_S, 1);
      return {
        ...REST,
        lift: POUNCE_M * Math.sin(Math.PI * share),
        crouch: share < 1 ? 0 : 0.15,
        reach: 0.3,
        jaw: 0.4,
      };
    }
    case 'bite': {
      const lunge = pulse(t, 1.5);
      return {
        ...REST,
        crouch: 0.1,
        reach: 0.35 + 0.25 * lunge,
        head: 10 * DEG,
        jaw: 0.45 * lunge,
      };
    }
    case 'rear': {
      const up = rearShare(t);
      const biting = up === 0 ? pulse(t, (1 / REAR_CYCLE_S) * 4) : 0;
      return {
        ...REST,
        rear: 50 * DEG * up,
        neck: -15 * DEG * up,
        reach: 0.5 * biting,
        jaw: 0.3 * up + 0.45 * biting,
      };
    }
    case 'feed': // head down at the carcass, tearing
      return {
        ...REST,
        crouch: 0.1,
        reach: 0.9,
        head: (20 + 10 * wave(t, 1)) * DEG,
        jaw: 0.25 * pulse(t, 1.5),
      };
    case 'drink':
      return {
        ...REST,
        crouch: 0.12,
        reach: 1,
        head: 30 * DEG,
        jaw: 0.08 * pulse(t, 3),
      };
    case 'sleep': // on its belly, legs folded, head down, breathing slowly
      return {
        ...REST,
        fold: 1,
        reach: 0.6,
        head: 20 * DEG,
        ears: -20 * DEG,
        breathe: 0.015 * wave(t, 0.25),
        still: true,
      };
    case 'dead': // falls onto its side (gravity: slow, then fast), the head lolling
      return {
        ...REST,
        roll: (Math.PI / 2) * Math.min((t / FALL_S) ** 2, 1),
        reach: 0.3,
        head: 10 * DEG,
        still: true,
      };
    case 'remains':
      return { ...REST, still: true };
    default:
      return REST;
  }
}

const NUMERIC = [
  'reach',
  'neck',
  'head',
  'jaw',
  'ears',
  'crouch',
  'fold',
  'lift',
  'rear',
  'roll',
  'breathe',
] as const;

/** Eases `pose` (changed in place) a share `k` of the way to `target`; stillness follows the target at once. */
export function blendPose(pose: LayerPose, target: LayerPose, k: number) {
  for (const key of NUMERIC) pose[key] += (target[key] - pose[key]) * k;
  pose.still = target.still;
  return pose;
}

const restPose = (): LayerPose => ({ ...REST });

/** What the globe asks of a live animal's model each frame, and what the model reports back. */
export interface AnimalDrive {
  clip: AnimalClip;
  /** Drawn ground speed (game metres per game second): the gait clip is paced to it. */
  speed: number;
  layer: AnimalLayer;
  /** How many times their natural speed clips and layers play (`visualRate`; 0 paused). */
  rate: number;
  /** Reported: the clip playing, how many times its natural speed, the blended layer pose. */
  clipName: string;
  pace: number;
  pose: LayerPose;
}

export const newDrive = (): AnimalDrive => ({
  clip: 'idle',
  speed: 0,
  layer: 'none',
  rate: 1,
  clipName: '',
  pace: 1,
  pose: restPose(),
});

// --- the rig: bones, the body's size, its natural stride ---

interface Leg {
  /** Hip (or shoulder) to ankle, the joints that bend to keep the foot where it stands. */
  joints: Bone[];
  foot: Bone;
  /** Front leg (folds back under the chest) or hind leg (folds forward under the belly). */
  front: boolean;
}

export interface AnimalRig {
  root: Object3D;
  hips: Bone | null;
  chest: Bone | null;
  neck: Bone | null;
  head: Bone | null;
  jaw: Bone | null;
  ears: Bone[];
  legs: Leg[];
  /** At rest, in the root's frame: the hips' height, the body's half width and centre height, the hind feet's z, and
   * how far above level the neck points (radians, neck to head). */
  hipHeight: number;
  halfWidth: number;
  centreY: number;
  hindZ: number;
  neckRise: number;
  /** The bones a layer bends, with what the clip last set them to (the mixer only writes a bone when its clip value
   * changes, so a bent bone must be put back before the next update or the bend would pile up). */
  bent: { bone: Bone; position: Vector3; quaternion: Quaternion }[];
}

const isBone = (object: Object3D | undefined): object is Bone =>
  Boolean(object && (object as Bone).isBone);

function boneNamed(root: Object3D, name: string) {
  const found = root.getObjectByName(name);
  return isBone(found) ? found : null;
}

/** The rig of a freshly loaded (rest-posed) animal model. */
export function rigOf(root: Object3D): AnimalRig {
  root.updateMatrixWorld(true);
  const toRoot = new Matrix4().copy(root.matrixWorld).invert();
  const local = (object: Object3D) =>
    object.getWorldPosition(new Vector3()).applyMatrix4(toRoot);
  const feet: Bone[] = [];
  root.traverse((object) => {
    if (isBone(object) && /Foot$/.test(object.name)) feet.push(object);
  });
  const hips = boneNamed(root, 'Hips');
  const hipsAt = hips ? local(hips) : new Vector3();
  const footZ = feet.map((foot) => local(foot).z);
  const middle = footZ.length
    ? (Math.max(...footZ) + Math.min(...footZ)) / 2
    : 0;
  const legs = feet.map((foot, k) => {
    const joints: Bone[] = [];
    let joint = foot.parent;
    while (isBone(joint ?? undefined)) {
      joints.unshift(joint as Bone);
      if (/UpLeg$/.test((joint as Bone).name)) break;
      joint = (joint as Bone).parent;
    }
    return { joints, foot, front: footZ[k] > middle };
  });
  const hind = legs.filter((leg) => !leg.front).map((leg) => local(leg.foot).z);
  // the body's size from its skinned meshes' rest bounds
  const min = new Vector3(Infinity, Infinity, Infinity);
  const max = new Vector3(-Infinity, -Infinity, -Infinity);
  root.traverse((object) => {
    const mesh = object as Object3D & {
      geometry?: {
        boundingBox: { min: Vector3; max: Vector3 } | null;
        computeBoundingBox(): void;
      };
    };
    if (!mesh.geometry) return;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    const box = mesh.geometry.boundingBox;
    if (!box) return;
    const toLocal = new Matrix4().multiplyMatrices(toRoot, object.matrixWorld);
    for (const corner of [box.min, box.max]) {
      const at = corner.clone().applyMatrix4(toLocal);
      min.min(at);
      max.max(at);
    }
  });
  const sized = Number.isFinite(min.x);
  const neck = boneNamed(root, 'Neck');
  const head = boneNamed(root, 'Head');
  const jaw = boneNamed(root, 'Jaw');
  const ears = ['LeftEar', 'RightEar'].flatMap(
    (name) => boneNamed(root, name) ?? [],
  );
  const chest = boneNamed(root, 'Chest');
  const neckToHead =
    neck && head ? local(head).sub(local(neck)) : new Vector3(0, 0, 1);
  const bent = [
    hips,
    chest,
    neck,
    head,
    jaw,
    ...ears,
    ...legs.flatMap((leg) => leg.joints),
  ]
    .filter((bone): bone is Bone => bone !== null)
    .map((bone) => ({
      bone,
      position: new Vector3(),
      quaternion: new Quaternion(),
    }));
  return {
    root,
    hips,
    chest,
    neck,
    head,
    jaw,
    ears,
    legs,
    bent,
    hipHeight: hipsAt.y,
    halfWidth: sized ? (max.x - min.x) / 2 : 0,
    centreY: sized ? (max.y + min.y) / 2 : hipsAt.y,
    hindZ: hind.length ? hind.reduce((a, b) => a + b, 0) / hind.length : 0,
    neckRise: Math.atan2(neckToHead.y, neckToHead.z),
  };
}

/** A foot this close to its lowest (metres, or 1.5 % of the hip height for small animals) touches the ground. */
const CONTACT_M = 0.005;

/**
 * The ground speed a gait clip shows at its natural rate (root units per second): how fast its planted feet move
 * back under the body over a stance (a foot within CONTACT_M of its lowest is planted); where its feet
 * disagree, the speed at which the worst stance drifts least. Null without feet (swimmers).
 * Poses the model while it measures: call it before the model's own mixer runs.
 */
export function strideSpeed(
  rig: AnimalRig,
  clip: AnimationClip,
  samples = 960,
) {
  if (rig.legs.length === 0) return null;
  const { root } = rig;
  const mixer = new AnimationMixer(root);
  mixer.clipAction(clip).play();
  const toRoot = new Matrix4();
  const at = new Vector3();
  const tracks = rig.legs.map(() => [] as Vector3[]);
  const step = clip.duration / samples;
  for (let k = 0; k <= samples; k++) {
    mixer.setTime(k * step);
    root.updateMatrixWorld(true);
    toRoot.copy(root.matrixWorld).invert();
    rig.legs.forEach((leg, n) =>
      tracks[n].push(
        leg.foot.getWorldPosition(at).applyMatrix4(toRoot).clone(),
      ),
    );
  }
  mixer.stopAllAction();
  mixer.uncacheRoot(root);
  const band = Math.min(CONTACT_M, 0.015 * rig.hipHeight);
  const stances = tracks.flatMap((track) => stancesOf(track, band, step));
  if (stances.length === 0) return null;
  // the clip's feet don't all move back at quite the same speed: the pace whose worst stance slips least
  const speeds = stances.map(({ speed }) => speed);
  const [low, high] = [Math.min(...speeds), Math.max(...speeds)];
  const worst = (pace: number) =>
    Math.max(
      ...stances.map(({ speed, seconds }) => Math.abs(pace - speed) * seconds),
    );
  let best = low;
  for (let k = 1; k <= 200; k++) {
    const pace = low + ((high - low) * k) / 200;
    if (worst(pace) < worst(best)) best = pace;
  }
  return best;
}

/**
 * A foot's stances over one loop of a clip sampled every `step` seconds (the last sample is the first again): how fast
 * it moves back from touching down to lifting off and for how long. A foot that never lifts is one long stance.
 */
function stancesOf(track: Vector3[], band: number, step: number) {
  const samples = track.length - 1;
  const lowest = Math.min(...track.map((spot) => spot.y));
  const down = (k: number) => track[k % samples].y < lowest + band;
  const stance = (first: number, last: number) => ({
    speed:
      (track[first % samples].z - track[last % samples].z) /
      ((last - first) * step),
    seconds: (last - first) * step,
  });
  const lifted = Array.from({ length: samples }, (_, k) => k).find(
    (k) => !down(k),
  );
  if (lifted === undefined) return [stance(0, samples - 1)];
  const stances: { speed: number; seconds: number }[] = [];
  let first: number | null = null;
  for (let k = lifted; k <= lifted + samples; k++) {
    if (down(k)) {
      first ??= k;
      continue;
    }
    if (first !== null && k - 1 - first >= 2)
      stances.push(stance(first, k - 1));
    first = null;
  }
  return stances;
}

// --- posing: bones after the clip, then the body ---

const X_AXIS = new Vector3(1, 0, 0);
const turn = new Quaternion();
const parentTurn = new Quaternion();
const toRootM = new Matrix4();
const lateral = new Vector3();

/** Rotates a bone by `angle` about the root's lateral axis (`lateral`, world space). */
function pitchBone(bone: Bone, angle: number) {
  bone.parent?.getWorldQuaternion(parentTurn);
  turn.setFromAxisAngle(lateral, angle);
  // parentWorld⁻¹ · turn · parentWorld · local
  bone.quaternion.premultiply(
    parentTurn.clone().invert().multiply(turn).multiply(parentTurn),
  );
  bone.updateMatrixWorld(true);
}

const argYZ = (v: Vector3) => Math.atan2(v.y, v.z);
const wrap = (angle: number) => Math.atan2(Math.sin(angle), Math.cos(angle));
/** A knee bent less than this from straight (radians) bends the leg's own way: front knees back, hind knees forward. */
const STRAIGHT = 0.02;

const hip = new Vector3();
const knee = new Vector3();
const foot = new Vector3();
const toHip = new Vector3();
const toFoot = new Vector3();

/** Where a bone is in the root's frame (written into `out`). */
const rootSpot = (bone: Bone, out: Vector3) =>
  bone.getWorldPosition(out).applyMatrix4(toRootM);

/**
 * Bends a leg in the body's own plane so its foot reaches `target` (root frame): its knee (second joint) opens or
 * closes to the hip-to-target distance by the law of cosines, then its hip swings the foot onto the target. The joints
 * below the knee keep their clip pose.
 */
function reach(leg: Leg, target: Vector3) {
  if (leg.joints.length < 2) return;
  const [upper, middle] = leg.joints;
  rootSpot(upper, hip);
  rootSpot(middle, knee);
  rootSpot(leg.foot, foot);
  const thigh = Math.hypot(knee.y - hip.y, knee.z - hip.z);
  const shin = Math.hypot(foot.y - knee.y, foot.z - knee.z);
  const span = Math.min(
    Math.max(
      Math.hypot(target.y - hip.y, target.z - hip.z),
      Math.abs(thigh - shin) + 1e-4,
    ),
    thigh + shin - 1e-4,
  );
  toHip.subVectors(hip, knee);
  toFoot.subVectors(foot, knee);
  const bend = wrap(argYZ(toFoot) - argYZ(toHip));
  const side =
    Math.PI - Math.abs(bend) < STRAIGHT
      ? leg.front
        ? -1
        : 1
      : Math.sign(bend);
  const wanted = Math.acos(
    (thigh ** 2 + shin ** 2 - span ** 2) / (2 * thigh * shin),
  );
  // rotating about +X by θ turns arg(z + iy) back by θ
  pitchBone(middle, Math.abs(bend) * side - wanted * side);
  rootSpot(leg.foot, foot);
  pitchBone(
    upper,
    argYZ(toFoot.subVectors(foot, hip)) - argYZ(toHip.subVectors(target, hip)),
  );
}

/**
 * Lays the layer's bone pose over what the clip just set: sinks the hips with the feet kept where they stood (or
 * folded under the body), bows the neck and head, opens the jaw, turns the ears and breathes.
 */
export function poseBones(rig: AnimalRig, pose: LayerPose) {
  const { root, hips } = rig;
  for (const { bone, position, quaternion } of rig.bent) {
    position.copy(bone.position);
    quaternion.copy(bone.quaternion);
  }
  root.updateMatrixWorld(true);
  lateral.copy(X_AXIS).transformDirection(root.matrixWorld);
  toRootM.copy(root.matrixWorld).invert();
  const sink = pose.crouch + LIE_DROP * pose.fold;
  const planting = hips && sink > 1e-3;
  const targets = planting
    ? rig.legs.map((leg) => {
        const spot = leg.foot
          .getWorldPosition(new Vector3())
          .applyMatrix4(toRootM);
        // folded: front feet tuck back under the chest, hind feet forward under the belly
        spot.z += (leg.front ? -1 : 1) * 0.35 * rig.hipHeight * pose.fold;
        return spot;
      })
    : [];
  if (planting) {
    hips.position.y -= sink * rig.hipHeight;
    hips.updateMatrixWorld(true);
  }
  if (rig.chest && pose.reach) pitchBone(rig.chest, REACH_CHEST * pose.reach);
  const bow = pose.neck + pose.reach * (rig.neckRise + REACH_DOWN);
  if (rig.neck && bow) pitchBone(rig.neck, bow);
  if (rig.head && pose.head) pitchBone(rig.head, pose.head);
  if (rig.jaw && pose.jaw) pitchBone(rig.jaw, pose.jaw);
  for (const ear of rig.ears) if (pose.ears) pitchBone(ear, pose.ears);
  if (rig.chest) rig.chest.scale.setScalar(1 + pose.breathe);
  rig.legs.forEach((leg, k) => {
    if (planting) reach(leg, targets[k]);
  });
}

/** Puts the bent bones back where the clip set them: call it before every mixer update. */
export function unbendBones(rig: AnimalRig) {
  for (const { bone, position, quaternion } of rig.bent) {
    bone.position.copy(position);
    bone.quaternion.copy(quaternion);
  }
}

const lift = new Matrix4();
const step = new Matrix4();

/**
 * The body's pose as a matrix in the model's frame (feet at the origin): risen by the leap, reared up about the hind
 * feet, rolled onto its side about the body's centre and resting on its flank.
 */
export function bodyMatrix(
  pose: LayerPose,
  rig: Pick<AnimalRig, 'halfWidth' | 'centreY' | 'hindZ'>,
  out: Matrix4,
) {
  const { roll, rear } = pose;
  const { halfWidth, centreY, hindZ } = rig;
  out.makeTranslation(0, pose.lift, 0);
  if (rear) {
    out.multiply(step.makeTranslation(0, 0, hindZ));
    out.multiply(step.makeRotationX(-rear));
    out.multiply(step.makeTranslation(0, 0, -hindZ));
  }
  if (roll) {
    out.multiply(
      lift.makeTranslation(
        0,
        centreY * Math.cos(roll) + halfWidth * Math.sin(roll),
        0,
      ),
    );
    out.multiply(step.makeRotationZ(roll));
    out.multiply(step.makeTranslation(0, -centreY, 0));
  }
  return out;
}

/** Steepest the body pitches to the slope under it (radians). */
const MAX_PITCH = 25 * DEG;

/**
 * How far the body pitches nose-up (radians, negative nose-down) on ground `front` and `back` metres high under its
 * front and hind feet, `length` metres apart.
 */
export const slopePitch = (front: number, back: number, length: number) =>
  Math.min(Math.max(Math.atan2(front - back, length), -MAX_PITCH), MAX_PITCH);
