/*
 * What the globe's citizen labels say, from the live feed: a chip each (activity icon, name, what they do in
 * words, a need ring) and a bubble for the latest thing each speaker said.
 */
import type { Activity, LiveCitizen } from '@/lib/live/live-contract';
import type { Speech } from '@/lib/live/live-state';
import { activityWords } from '@/lib/live/npc-activity';
import type { ChipIcon, LabelContent, NeedRing } from '@/lib/world/label-store';

const ACTIVITY_ICONS: Record<Activity, ChipIcon> = {
  idle: 'stand',
  walking: 'walk',
  running: 'run',
  sleeping: 'sleep',
  resting: 'rest',
  gathering: 'gather',
  eating: 'eat',
  drinking: 'drink',
  working: 'work',
  hunting: 'hunt',
  fishing: 'fish',
  tending_fire: 'fire',
  talking: 'talk',
  dead: 'dead',
};

/** The body words (`sim/bodies.py` body_words) that ring a chip: hurt (red) wins over hungry or thirsty (orange). */
const HURT_WORDS = new Set(['close to death', 'weak and aching']);
const NEED_WORDS = new Set([
  'starving',
  'hungry',
  'terribly thirsty',
  'thirsty',
]);

function needRing(state: readonly string[]): NeedRing | undefined {
  if (state.some((word) => HURT_WORDS.has(word))) return 'hurt';
  if (state.some((word) => NEED_WORDS.has(word))) return 'need';
  return undefined;
}

export function citizenLabels(
  citizens: readonly LiveCitizen[],
  speech: readonly Speech[],
): LabelContent[] {
  const latest = new Map<string, Speech>();
  for (const said of speech) latest.set(said.actorId, said);
  return [
    ...citizens.map((citizen): LabelContent => ({
      id: `npc-${citizen.id}`,
      subject: citizen.id,
      kind: 'name',
      text: citizen.name,
      detail: activityWords(citizen),
      icon: ACTIVITY_ICONS[citizen.activity],
      ring: needRing(citizen.state),
    })),
    ...[...latest.values()].map((said): LabelContent => ({
      id: `say-${said.actorId}`,
      subject: said.actorId,
      kind: 'speech',
      text: said.words,
    })),
  ];
}
