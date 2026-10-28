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
  | 'Chopping wood';

/** Every NPC loads these up front; activity clips are fetched (once per page) when first needed. */
export const BASE_CLIPS: readonly NpcClip[] = ['Idle', 'Walk'];

type NpcPose = 'standing' | 'sitting' | 'lying';

export interface NpcLook {
  clip: NpcClip;
  pose: NpcPose;
  /** Whether the clip is frozen on its first frame (the dead). */
  still: boolean;
}

const WOOD = /wood|log|branch|timber/i;
const PLANTING = /plant|sow|seed/i;
const PICKING = /root|reed|nut|stone|flint|stick/i;

/** The work clip for what someone gathers or works at (from the action label). */
function workClip(activity: 'gathering' | 'working', label: string): NpcClip {
  if (WOOD.test(label))
    return activity === 'working' ? 'Chopping wood' : 'Pick up';
  if (PLANTING.test(label)) return 'Planting';
  if (activity === 'gathering' && PICKING.test(label)) return 'Pick up';
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

/** What someone is doing, in words ("working the rice fields", "walking to the well"). */
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
      return with_('walking', ' to ');
    case 'sleeping':
      return 'asleep';
    case 'resting':
      return with_('resting', ' by ');
    case 'gathering':
      return with_('gathering');
    case 'working':
      return with_('working');
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
