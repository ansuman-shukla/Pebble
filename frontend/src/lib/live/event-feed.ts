/*
 * The spectator's event feed (10-world-v1 §5.4): every live event as one line with an importance 0-3 (0 hidden),
 * newest first, repeats merged ("Tek fished ×3"), filtered to People, Danger or Economy. The line, importance and
 * position come from the backend's line registry (F1's `line`/`importance`/`position`); until an event carries
 * them, the few types the feed delivers today get a plain line here.
 */
import type { LiveAnimal, LiveEventMessage } from './live-contract';
import { townClock } from '@/lib/spectator/time';

export type FeedFilter = 'all' | 'people' | 'danger' | 'economy';

export const FEED_FILTERS: { filter: FeedFilter; label: string }[] = [
  { filter: 'all', label: 'All' },
  { filter: 'people', label: 'People' },
  { filter: 'danger', label: 'Danger' },
  { filter: 'economy', label: 'Economy' },
];

/** Which filters an event type shows under (besides All). */
const KINDS: Record<Exclude<FeedFilter, 'all'>, ReadonlySet<string>> = {
  people: new Set([
    'said',
    'gestured',
    'goal_set',
    'standing_changed',
    'leader_changed',
    'bell_rang',
    'tended',
    'accused',
    'judged',
    'released',
    'sentence_served',
  ]),
  danger: new Set([
    'died',
    'injured',
    'stole',
    'trespassed',
    'seized',
    'confined',
    'judged',
  ]),
  economy: new Set([
    'bought',
    'sold',
    'crafted',
    'spoiled',
    'tool_broke',
    'tax_assessed',
    'tax_paid',
    'tax_overdue',
    'ledger',
    'prices_changed',
    'node_changed',
    'tree_felled',
  ]),
};

export interface FeedEntry {
  /** The newest merged event's id. */
  id: string;
  /** Every merged event's id, so a resend of any of them adds nothing. */
  ids: readonly string[];
  tick: number;
  /** Town "HH:MM" of `tick`. */
  time: string;
  type: string;
  actorId: string | null;
  /** The actor is an animal: its doings are no danger to people. */
  animal: boolean;
  line: string;
  importance: number;
  /** Where it happened (a unit direction), when the event says. */
  position: [number, number, number] | null;
  /** How many repeats it stands for (shown as "×3"). */
  count: number;
}

/** Entries kept. */
export const FEED_KEEP = 60;
/** A repeat merges into an entry among this many newest. */
const MERGE_WITHIN = 6;

type Detail = LiveEventMessage['event'] & {
  line?: string;
  importance?: number;
  position?: { unit: [number, number, number] } | null;
};

/** Who the feed can name: citizens by name, animals by kind (both by id). */
export interface FeedSubjects {
  names: ReadonlyMap<string, string>;
  animals: ReadonlyMap<string, LiveAnimal['kind']>;
}

/** "A boar", "An elk", "A polar bear". */
function anAnimal(kind: LiveAnimal['kind']) {
  const words = kind.replaceAll('_', ' ');
  return `${/^[aeiou]/.test(words) ? 'An' : 'A'} ${words}`;
}

/** The line and importance of today's feed events that don't carry their own yet. */
function fallback(
  event: Detail,
  { names, animals }: FeedSubjects,
): { line: string; importance: number } {
  const who = (event.actor_id && names.get(event.actor_id)) ?? 'Someone';
  const animal = event.actor_id ? animals.get(event.actor_id) : undefined;
  const { payload } = event;
  switch (event.type) {
    case 'died':
      if (animal)
        return {
          line:
            payload.cause === 'hunted'
              ? `${anAnimal(animal)} was hunted`
              : typeof payload.cause === 'string'
                ? `${anAnimal(animal)} died (${payload.cause})`
                : `${anAnimal(animal)} died`,
          importance: 2,
        };
      return {
        line:
          typeof payload.cause === 'string'
            ? `${who} died (${payload.cause})`
            : `${who} died`,
        importance: 3,
      };
    case 'said':
      return { line: `${who}: “${String(payload.words)}”`, importance: 1 };
    case 'action_started':
    case 'action_finished':
      return { line: '', importance: 0 };
    default:
      return {
        line: `${who}: ${event.type.replaceAll('_', ' ')}`,
        importance: 1,
      };
  }
}

/** One feed entry for a live event, or null when it is hidden (importance 0). */
export function feedEntry(
  message: LiveEventMessage,
  subjects: FeedSubjects,
): FeedEntry | null {
  const event = message.event as Detail;
  const plain = fallback(event, subjects);
  const importance = event.importance ?? plain.importance;
  if (importance <= 0) return null;
  return {
    id: event.id,
    ids: [event.id],
    tick: message.tick,
    time: townClock(message.tick).time,
    type: event.type,
    actorId: event.actor_id,
    animal: event.actor_id !== null && subjects.animals.has(event.actor_id),
    line: event.line ?? plain.line,
    importance,
    position: event.position?.unit ?? null,
    count: 1,
  };
}

const sameStory = (a: FeedEntry, b: FeedEntry) =>
  a.type === b.type && a.actorId === b.actorId && a.line === b.line;

/** The feed with `entry` on top: a repeat of a recent entry merges into it (counted, moved up), oldest dropped. */
export function addEntry(
  entries: readonly FeedEntry[],
  entry: FeedEntry,
): FeedEntry[] {
  if (entries.some((old) => old.ids.includes(entry.id))) return [...entries];
  const at = entries
    .slice(0, MERGE_WITHIN)
    .findIndex((old) => sameStory(old, entry));
  if (at === -1) return [entry, ...entries].slice(0, FEED_KEEP);
  const merged = {
    ...entry,
    ids: [...entries[at].ids, entry.id],
    count: entries[at].count + 1,
  };
  return [merged, ...entries.filter((_, index) => index !== at)];
}

/** Danger is about people: an animal's death (hunted, killed) shows under All only. */
export const shows = (entry: FeedEntry, filter: FeedFilter) =>
  filter === 'all' ||
  (KINDS[filter].has(entry.type) && !(entry.animal && filter === 'danger'));
