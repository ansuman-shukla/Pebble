/*
 * How a live citizen's activity shows: which Polyfork clip plays (CLIP_NAMES in the fetched clips.mjs), how the
 * body lies (sleeping and dead people lie on their back) and what the label says in words.
 */
import type { Activity, LiveCitizen } from './live-contract';

/** The clips the live NPCs use (a subset of Polyfork's CLIP_NAMES). */
export type NpcClip =
  | 'Idle'
  | 'Walk'
  | 'Sitting'
  | 'Eating'
  | 'Drinking'
  | 'Talking'
  | 'Harvesting'
  | 'Planting'
  | 'Pick up'
  | 'Chopping wood'
  | 'Arms folded'
  | 'Fixing';

/** Every NPC loads these up front; activity clips are fetched (once per page) when first needed. */
export const BASE_CLIPS: readonly NpcClip[] = ['Idle', 'Walk'];

/** Every clip but the gait is a standing one (the type keeps the list complete). */
const STANDING: Record<Exclude<NpcClip, 'Walk'>, true> = {
  Idle: true,
  Sitting: true,
  Eating: true,
  Drinking: true,
  Talking: true,
  Harvesting: true,
  Planting: true,
  'Pick up': true,
  'Chopping wood': true,
  'Arms folded': true,
  Fixing: true,
};

/** The standing clips play on planted feet; the gait plays on the spot. */
export const PLANTED_CLIPS: ReadonlySet<string> = new Set(
  Object.keys(STANDING),
);

type NpcPose = 'standing' | 'sitting' | 'lying';

export interface NpcLook {
  clip: NpcClip;
  pose: NpcPose;
  /** Whether the clip is frozen on its first frame (the dead). */
  still: boolean;
}

const WOOD = /wood|log|branch|timber/i;
const PLANTING = /plant|sow|seed/i;
const PICKING = /root|reed|nut|stone|flint|stick|pebble/i;
/** Work labels (the engine's task words, e.g. "keeping watch", "trading at the market") and their clips. */
const WORK_CLIPS: [RegExp, NpcClip][] = [
  [/watch|guard|patrol/i, 'Arms folded'],
  [/trad|market|court|sell/i, 'Talking'],
  [/weav|loom|mend|sew|repair/i, 'Fixing'],
  [/storehouse|carry|fill|haul/i, 'Pick up'],
  [WOOD, 'Chopping wood'],
  [PLANTING, 'Planting'],
];

/** The work clip for what someone gathers or works at (from the action label). */
function workClip(activity: 'gathering' | 'working', label: string): NpcClip {
  if (activity === 'working')
    return WORK_CLIPS.find(([words]) => words.test(label))?.[1] ?? 'Harvesting';
  if (WOOD.test(label) || PICKING.test(label)) return 'Pick up';
  return 'Harvesting';
}

const STANDING_CLIPS: Record<
  Exclude<Activity, 'gathering' | 'working'>,
  NpcLook
> = {
  idle: { clip: 'Idle', pose: 'standing', still: false },
  walking: { clip: 'Walk', pose: 'standing', still: false },
  eating: { clip: 'Eating', pose: 'standing', still: false },
  drinking: { clip: 'Drinking', pose: 'standing', still: false },
  talking: { clip: 'Talking', pose: 'standing', still: false },
  resting: { clip: 'Sitting', pose: 'sitting', still: false },
  sleeping: { clip: 'Idle', pose: 'lying', still: false },
  dead: { clip: 'Idle', pose: 'lying', still: true },
};

export function npcLook(
  citizen: Pick<LiveCitizen, 'activity' | 'action_label'>,
): NpcLook {
  const { activity, action_label: label } = citizen;
  if (activity === 'gathering' || activity === 'working')
    return { clip: workClip(activity, label), pose: 'standing', still: false };
  return STANDING_CLIPS[activity];
}

/**
 * What someone is doing, in words ("tending the rice paddies", "walking to the well"). Work labels are the
 * engine's task phrases already; walk labels are a place ("the well") or a direction ("to the north").
 */
export function activityWords(
  citizen: Pick<LiveCitizen, 'activity' | 'action_label' | 'cause_of_death'>,
): string {
  const { activity, action_label: label, cause_of_death: cause } = citizen;
  const with_ = (verb: string, joint = ' ') =>
    label ? `${verb}${joint}${label}` : verb;
  switch (activity) {
    case 'idle':
      return 'standing about';
    case 'walking':
      return with_('walking', label.startsWith('to ') ? ' ' : ' to ');
    case 'sleeping':
      return 'asleep';
    case 'resting':
      return with_('resting', ' by ');
    case 'gathering':
      return with_('gathering');
    case 'working':
      return label || 'working';
    case 'eating':
      return with_('eating');
    case 'drinking':
      return with_('drinking', ' at ');
    case 'talking':
      return with_('talking', ' to ');
    case 'dead':
      return cause ? `dead (${cause})` : 'dead';
  }
}
