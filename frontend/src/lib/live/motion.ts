/*
 * How a live citizen's body moves (10 §4.5): the feed's `motion` (what the body does) mapped through one table to
 * the Polyfork clip that plays (CLIP_NAMES in clips.mjs), how the body rests, what it holds and the procedural layer
 * on top; on the move, the gait clip paced to the drawn ground speed so the feet don't slip.
 *
 *   feed motion ─▶ MOTION_LOOKS[motion] ─▶ clip · pace · pose · prop · layer      (motionLook)
 *   drawn speed ─▶ gait clip (Walk, Walk formal, Run) · its time scale  (gaitOf)
 *
 * The feed sends `motion` once F1's spectator fields are on it (PR #58); a feed without them (an older run, a replay
 * recorded before) falls back to the activity and its label (`fallbackMotion`, the only label reading left).
 */
import type { Activity } from './live-contract';
import type { HandPropKind } from '@/lib/world/assets';
import { SEAT_HEIGHT } from '@/lib/world/rest-posture';

/** The feed's motion vocabulary (backend `app/sim/motion.py`). */
export const MOTIONS = [
  'idle',
  'walk',
  'jog',
  'run',
  'carry_walk',
  'stalk',
  'sit',
  'sit_ground',
  'lie',
  'inside',
  'gather_low',
  'gather_high',
  'pick_up',
  'chop',
  'mine',
  'pan',
  'farm',
  'fish',
  'craft',
  'eat',
  'drink',
  'talk',
  'trade',
  'gesture',
  'attack',
  'tend',
  'pray',
  'ring_bell',
] as const;

export type Motion = (typeof MOTIONS)[number];

/** How the feed says the body rests (backend `Posture`). */
export type FedPosture =
  'standing' | 'crouching' | 'sitting' | 'sitting_ground' | 'lying' | 'inside';

/** The gestures a citizen makes (backend `GestureKind`): the feed's `gestured` events name them. */
export const GESTURES = [
  'wave',
  'bow',
  'nod',
  'shake_head',
  'point',
  'laugh',
  'jump',
] as const;

export type GestureKind = (typeof GESTURES)[number];

/** What the feed says of a body besides its activity (optional: feeds before F1's fields don't carry them). */
export interface FedBody {
  motion?: Motion;
  posture?: FedPosture;
  /** The seat's, mat's or work slot's facing (degrees, the heading convention) while the body is on it. */
  slot_heading?: number | null;
  /**
   * How high the seat's top is (m, the slot's `height_m`: a bench 0.45, the loom's stool 0.3): a seat without it is a
   * bench's (`SEAT_HEIGHT`).
   */
  slot_height_m?: number | null;
}

/** The clips the live citizens use (a subset of Polyfork's CLIP_NAMES). */
export type NpcClip =
  | 'Idle'
  | 'Walk'
  | 'Walk formal'
  | 'Run'
  | 'Sitting'
  | 'Sit down'
  | 'Stand up'
  | 'Opening'
  | 'Crouch'
  | 'Planting'
  | 'Harvesting'
  | 'Pick up'
  | 'Chopping wood'
  | 'Holding torch'
  | 'Fixing'
  | 'Interact'
  | 'Eating'
  | 'Drinking'
  | 'Talking'
  | 'Agree'
  | 'Head shake'
  | 'Laughing'
  | 'Arms folded'
  | 'Pushing'
  | 'Punch'
  | 'Hard landing';

/** Every citizen loads these up front; the rest are fetched (once per page) when first needed. */
export const BASE_CLIPS: readonly NpcClip[] = ['Idle', 'Walk'];

/** The gaits: clips that play on the spot while the body is carried along its path. */
const GAITS: ReadonlySet<NpcClip> = new Set(['Walk', 'Walk formal', 'Run']);

/**
 * Clips that play on planted feet (the hips keep their captured sideways sway): every clip but the gaits and the
 * seated ones, which move the hips back onto the seat.
 */
export const isPlanted = (clip: string) => !GAITS.has(clip as NpcClip);

/**
 * How the body rests (`rest-posture.ts` lays it): on its feet, on a seat (`seated`, hips at the seat's height), on
 * the ground (`sitting`, legs out in front; `kneeling`, upright on the knees), on its back asleep or dead, or out
 * of sight indoors.
 */
export type BodyPose =
  | 'standing'
  | 'seated'
  | 'sitting'
  | 'kneeling'
  | 'sleeping'
  | 'lying'
  | 'inside';

/**
 * A procedural motion layered over the clip (`poses.ts`): the hunter's creep, a bow in prayer with the hands together,
 * a hand reaching to the ground and back (picking, tending a fire, knapping) or swirling a pan, both hands at work ahead passing the shuttle (weaving seated), a gesture.
 */
export type Layer =
  'stalk' | 'laden' | 'pray' | 'reach' | 'swirl' | 'weave' | GestureKind;

/** Things held that the asset pack has no model for, drawn from code (D133's stand-ins). */
type MadeProp = 'pan' | 'stone' | 'cup' | 'food' | 'pick' | 'rod';

/** What a citizen holds and where: in a hand, or on its back (a load). */
export interface HeldProp {
  kind: Exclude<HandPropKind, 'pick' | 'fishing_rod'> | MadeProp;
  at: 'left' | 'right' | 'back';
}

export interface MotionLook {
  motion: Motion;
  /** The clip played while the body stands still (moving, the gait plays: `gaitOf`). */
  clip: NpcClip;
  /** The clip's speed relative to its capture (mining swings slower, smithing faster). */
  pace: number;
  pose: BodyPose;
  /** Whether the clip is frozen on its first frame (sleepers and the dead lie still). */
  still: boolean;
  /** How high the seat is (m) for a seated body, else null. */
  seat: number | null;
  prop: HeldProp | null;
  layer: Layer | null;
  /**
   * Whether the look's own things in hand (a hunter's spear, a guard's yari, a cane) are put away: work with both
   * hands (picking, digging, farming, hammering) puts them down; walking, talking or keeping watch keeps them.
   */
  stow: boolean;
}

/** Who a body is, for the motions that differ by person (a smith's craft is not a toolmaker's). */
export interface Bearer {
  /** The citizen's look id (`citizen-looks.ts`). */
  look: string;
  region: 'town' | 'band_a' | 'band_b';
  /** Whether the look already holds a spear (a hunter's yari). */
  spear: boolean;
  /** Night where it stands (a guard holds a torch). */
  dark: boolean;
}

/** Looks that walk formally (the lord and his samurai) and that stand guard (arms folded, a torch at night). */
const FORMAL_LOOKS: ReadonlySet<string> = new Set([
  'town-lord',
  'town-samurai',
]);
const GUARD_LOOKS: ReadonlySet<string> = new Set([
  'town-ashigaru',
  'town-samurai',
]);
const SMITH_LOOKS: ReadonlySet<string> = new Set(['town-smith']);
const MERCHANT_LOOKS: ReadonlySet<string> = new Set(['town-merchant']);

type Entry = Partial<Omit<MotionLook, 'motion' | 'clip'>> & { clip: NpcClip };

const right = (kind: HeldProp['kind']): HeldProp => ({ kind, at: 'right' });
const left = (kind: HeldProp['kind']): HeldProp => ({ kind, at: 'left' });

/** The table of 10 §4.5: each motion's clip, pace, rest, prop and layer (the same for everyone). */
const TABLE: Record<Motion, Entry> = {
  idle: { clip: 'Idle' },
  // the moving motions stand idle once the drawn body stopped (moving, the gait plays)
  walk: { clip: 'Idle' },
  jog: { clip: 'Idle' },
  run: { clip: 'Idle' },
  // a load on the back, leaning into it (Polyfork's `Walk carrying` slips 6 cm a step at any pace)
  carry_walk: {
    clip: 'Idle',
    prop: { kind: 'sack', at: 'back' },
    layer: 'laden',
  },
  // a hunter crouches and creeps (the stalk layer bends the walk)
  stalk: { clip: 'Crouch', layer: 'stalk', prop: right('spear') },
  sit: { clip: 'Sitting', pose: 'seated' },
  sit_ground: { clip: 'Sitting', pose: 'sitting' },
  lie: { clip: 'Idle', pose: 'sleeping', still: true },
  inside: { clip: 'Opening', pose: 'inside' },
  gather_low: {
    clip: 'Crouch',
    prop: left('basket'),
    layer: 'reach',
    stow: true,
  },
  // berries and nuts are picked bent over the bush, both hands in it (a bush stands about waist high)
  gather_high: { clip: 'Harvesting', prop: left('basket'), stow: true },
  pick_up: { clip: 'Pick up', stow: true },
  chop: { clip: 'Chopping wood', prop: right('axe'), stow: true },
  mine: { clip: 'Chopping wood', pace: 0.8, prop: right('pick'), stow: true },
  pan: { clip: 'Crouch', prop: right('pan'), layer: 'swirl', stow: true },
  farm: { clip: 'Planting', prop: right('hoe'), stow: true },
  fish: { clip: 'Holding torch', prop: right('rod') },
  craft: { clip: 'Fixing', stow: true },
  eat: { clip: 'Eating', prop: right('food') },
  drink: { clip: 'Drinking', prop: right('cup') },
  talk: { clip: 'Talking' },
  trade: { clip: 'Interact', prop: left('coin_pouch') },
  gesture: { clip: 'Idle', layer: 'wave' },
  attack: { clip: 'Punch' },
  tend: { clip: 'Crouch', layer: 'reach', stow: true },
  // kneeling upright, bowing a little with the hands together before the chest
  pray: { clip: 'Idle', pose: 'kneeling', layer: 'pray' },
  ring_bell: { clip: 'Pushing', stow: true },
};

/**
 * The poses that rest the way each of the feed's postures says, the first the one a body takes when its motion rests
 * some other way (a crouch is on the feet: the clip crouches; a kneel is on the ground; the dead lie too).
 */
const FED_POSES: Record<FedPosture, readonly BodyPose[]> = {
  standing: ['standing'],
  crouching: ['standing'],
  sitting: ['seated'],
  sitting_ground: ['sitting', 'kneeling'],
  lying: ['sleeping', 'lying'],
  inside: ['inside'],
};
/** The plain clip of a body resting in each pose. */
const REST_CLIPS: Record<BodyPose, NpcClip> = {
  standing: 'Idle',
  seated: 'Sitting',
  sitting: 'Sitting',
  kneeling: 'Idle',
  sleeping: 'Idle',
  lying: 'Idle',
  inside: 'Opening',
};
/**
 * Work that goes on seated (10 §4.5): the weaver at the loom's stool passes the shuttle; any other motion seated
 * rests with the pose's plain clip. The lord holding court (`talk` on his seat) sits upright and waits: the feed's
 * `talk` there is his task, said whether or not anyone stands before him, so his seat shows no talking to nobody.
 */
const SEATED: Partial<Record<Motion, Entry>> = {
  craft: { clip: 'Sitting', layer: 'weave' },
};

/**
 * The look of `motion` for this bearer: the table's entry, with what differs by person (10 §4.5): a guard folds its
 * arms (a torch at night), band folk fish with a spear and knap crouching with a stone, the smith hammers at the
 * anvil, the merchant talks a sale, a spear-bearer thrusts instead of punching (and keeps its own spear), the dead
 * lie straight, a gesture names its kind. The feed's `posture` says where the body rests (on a seat at the slot's
 * height, on the ground, lying, inside): a motion the table rests some other way rests the feed's way, with that
 * pose's plain clip, unless it is work that goes on seated (the weaver at the loom weaves on its stool). Work with
 * both hands stows what the look itself holds (`stow`).
 */
export function motionLook(
  motion: Motion,
  bearer: Bearer,
  options: {
    dead?: boolean;
    gesture?: GestureKind | null;
    posture?: FedPosture | null;
    seat?: number | null;
  } = {},
): MotionLook {
  const entry = { ...TABLE[motion] };
  const band = bearer.region !== 'town';
  if (motion === 'idle' && GUARD_LOOKS.has(bearer.look))
    Object.assign(
      entry,
      bearer.dark
        ? { clip: 'Holding torch', prop: right('torch') }
        : { clip: 'Arms folded' },
    );
  if (motion === 'fish' && band) entry.prop = right('spear');
  if (motion === 'craft') {
    if (SMITH_LOOKS.has(bearer.look))
      Object.assign(entry, {
        clip: 'Chopping wood',
        pace: 1.2,
        prop: right('hammer'),
      });
    else if (band)
      Object.assign(entry, {
        clip: 'Crouch',
        prop: right('stone'),
        layer: 'reach',
      });
  }
  if (motion === 'trade' && MERCHANT_LOOKS.has(bearer.look))
    Object.assign(entry, { clip: 'Talking', prop: null });
  if (motion === 'attack' && bearer.spear)
    Object.assign(entry, { clip: 'Pushing' });
  const poses = options.posture && FED_POSES[options.posture];
  if (poses && !poses.includes(entry.pose ?? 'standing')) {
    const pose = poses[0];
    Object.assign(
      entry,
      { pose, clip: REST_CLIPS[pose], pace: 1, still: pose === 'sleeping' },
      pose === 'seated' ? SEATED[motion] : undefined,
    );
  }
  if (entry.pose === 'sleeping' && options.dead) entry.pose = 'lying';
  if (motion === 'gesture' && options.gesture) entry.layer = options.gesture;
  // a look that holds its own spear keeps it instead of being handed another
  if (entry.prop?.kind === 'spear' && bearer.spear) entry.prop = null;
  const pose = entry.pose ?? 'standing';
  return {
    motion,
    clip: entry.clip,
    pace: entry.pace ?? 1,
    pose,
    still: entry.still ?? false,
    seat: pose === 'seated' ? (options.seat ?? SEAT_HEIGHT) : null,
    prop: entry.prop ?? null,
    layer: entry.layer ?? null,
    stow: entry.stow ?? false,
  };
}

/**
 * Every clip a motion of the table can play at rest for any bearer (the tests load and check each): resting the way
 * the table says, or drawn in `pose` (the feed's posture laid it so: a weaver seated at the loom).
 */
export function motionClips(motion: Motion, pose?: BodyPose): NpcClip[] {
  const posture = pose
    ? (Object.keys(FED_POSES) as FedPosture[]).find((fed) =>
        FED_POSES[fed].includes(pose),
      )
    : undefined;
  const bearers: Bearer[] = [];
  for (const look of [
    'town-farmer',
    'town-ashigaru',
    'town-smith',
    'town-merchant',
  ])
    for (const dark of [false, true])
      for (const spear of [false, true])
        bearers.push({ look, region: 'town', spear, dark });
  bearers.push({
    look: 'band-a-hunter',
    region: 'band_a',
    spear: true,
    dark: false,
  });
  return [
    ...new Set(
      bearers.map((bearer) => motionLook(motion, bearer, { posture }).clip),
    ),
  ];
}

/** Ground speeds at which the gait changes (game m/s, 10 §4.5): jog from 1.9, run from 2.8. */
export const JOG_FROM = 1.9;
export const RUN_FROM = 2.8;
/** Below this the body stands (Polyfork's own threshold for a body of the baked height). */
const STILL_BELOW = 0.15;
/** The hips' height the clips were baked at (Polyfork `BAKED_HIP`). */
export const BAKED_HIP = 0.95;
/**
 * The ground speed each gait was captured at for a body of the baked hip height (m/s): the pace at which a planted
 * ankle slides least in stance (fitted to the clips; the `bodies` tests check the slip stays under 4 cm).
 */
export const CAPTURED_SPEED: Record<string, number> = {
  Walk: 1.45,
  'Walk formal': 0.87,
  Run: 3.4,
};

export interface Gait {
  clip: NpcClip;
  /** Clip speed that keeps a planted foot still under the body moving at the drawn ground speed. */
  timeScale: number;
}

/**
 * The gait for a body drawn moving at `speed` (game m/s, from its path: never the drawn speed on screen, so ×1 and
 * ×10 stay stride-locked) doing `motion`, whose hips stand `hips` m high: run from RUN_FROM, jog from JOG_FROM (the
 * Run cycle slowed: Polyfork's Jog is a bounding stride captured at 5.3 m/s), else a walk (formal for the lord and
 * his samurai). Null when it is standing.
 */
export function gaitOf(
  motion: Motion,
  speed: number,
  hips: number,
  look: string,
  /** Whether a clip is loaded yet (a gait still loading walks meanwhile). */
  has: (clip: NpcClip) => boolean = () => true,
): Gait | null {
  const scale = hips / BAKED_HIP;
  if (speed / scale < STILL_BELOW) return null;
  const wanted: NpcClip =
    speed >= JOG_FROM
      ? 'Run'
      : FORMAL_LOOKS.has(look) && motion === 'walk'
        ? 'Walk formal'
        : 'Walk';
  const clip = has(wanted) ? wanted : 'Walk';
  return { clip, timeScale: speed / (CAPTURED_SPEED[clip] * scale) };
}

/** Activities that map to one motion whatever the label. */
const ACTIVITY_MOTIONS: Record<
  Exclude<Activity, 'gathering' | 'working'>,
  Motion
> = {
  idle: 'idle',
  walking: 'walk',
  running: 'run',
  hunting: 'stalk',
  fishing: 'fish',
  tending_fire: 'tend',
  eating: 'eat',
  drinking: 'drink',
  talking: 'talk',
  resting: 'sit_ground',
  sleeping: 'lie',
  dead: 'lie',
};

/** What is gathered (the label names it) and how: picked high, dug or panned, else picked low. */
const GATHERED: [RegExp, Motion][] = [
  [/berr|nut|fruit/i, 'gather_high'],
  [/flint|obsidian|iron sand|ore|stone/i, 'mine'],
  [/gold/i, 'pan'],
];
/** Work tasks by their words (the engine's task phrases, e.g. "keeping watch", "trading at the market"). */
const WORKS: [RegExp, Motion][] = [
  [/watch|guard|patrol/i, 'idle'],
  [/trad|market|sell|buy/i, 'trade'],
  [/court|govern/i, 'talk'],
  [/pray/i, 'pray'],
  [/bell/i, 'ring_bell'],
  [/chop|fell|firewood/i, 'chop'],
  [/dig|iron sand/i, 'mine'],
  [/plant|sow|seed|paddies|rice field|farm/i, 'farm'],
  [/storehouse|carry|fill|haul|store/i, 'pick_up'],
  [/weav|loom|mend|sew|repair|knap|forg|smith|craft/i, 'craft'],
];

/**
 * The motion for a feed that doesn't send one (before F1's spectator fields): from the activity, and for gathering
 * and work from the label's words. Remove once every feed and recorded run carries `motion`.
 */
export function fallbackMotion(activity: Activity, label: string): Motion {
  if (activity === 'gathering')
    return GATHERED.find(([words]) => words.test(label))?.[1] ?? 'gather_low';
  if (activity === 'working')
    return WORKS.find(([words]) => words.test(label))?.[1] ?? 'craft';
  return ACTIVITY_MOTIONS[activity];
}

/** The motion a body is shown doing: the feed's, else the fallback from its activity. */
export const motionOf = (
  doing: FedBody & { activity: Activity; action_label: string },
): Motion => doing.motion ?? fallbackMotion(doing.activity, doing.action_label);
