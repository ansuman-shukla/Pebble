/*
 * The spectator's event feed (10-world-v1 §5.4): every live event as one line with an importance 0-3 (0 hidden),
 * newest first, repeats merged ("Tek fished ×3"), a group's chatter folded ("Band B greet each other and chat ×12"),
 * filtered to People, Danger or Economy. The line, importance and position come from the backend's line registry
 * (`observability/lines.py`).
 */
import { Vector3 } from 'three';

import type { LiveAnimal, LiveEventMessage } from './live-contract';
import type { Region } from '@/lib/spectator/words';
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
    'chatter',
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
  /** Whose chatter it is (greetings, gestures, small talk: speech and gestures of importance 1), else null. */
  chatter: Region | null;
  /** A fold of chatter (type `chatter`): what each folded event said, newest first; else empty. */
  folded: readonly { type: string; line: string }[];
}

/** Entries kept. */
export const FEED_KEEP = 60;
/** A repeat merges into an entry among this many newest. */
const MERGE_WITHIN = 6;
/** A group's chatter folds into its chatter among this many newest entries... */
const FOLD_WITHIN = 8;
/** ...said at most this many ticks (game minutes) before. */
export const FOLD_TICKS = 20;
/** The routine social events: a fold of them stands for the lot, so a band waking up doesn't bury the feed. */
const CHATTER: ReadonlySet<string> = new Set(['said', 'gestured']);
const FOLKS: Record<Region, string> = {
  town: 'Townsfolk',
  band_a: 'Band A',
  band_b: 'Band B',
};

/** Who the feed knows as animals, and each citizen's group (by id). */
export interface FeedSubjects {
  animals: ReadonlyMap<string, LiveAnimal['kind']>;
  groups: ReadonlyMap<string, Region>;
}

/** One feed entry for a live event, or null when it is hidden (importance 0). */
export function feedEntry(
  message: LiveEventMessage,
  subjects: FeedSubjects,
): FeedEntry | null {
  const { event } = message;
  if (event.importance <= 0) return null;
  const group =
    event.actor_id === null ? undefined : subjects.groups.get(event.actor_id);
  return {
    id: event.id,
    ids: [event.id],
    tick: message.tick,
    time: townClock(message.tick).time,
    type: event.type,
    actorId: event.actor_id,
    animal: event.actor_id !== null && subjects.animals.has(event.actor_id),
    line: event.line,
    importance: event.importance,
    position: event.position?.unit ?? null,
    count: 1,
    chatter:
      group !== undefined && CHATTER.has(event.type) && event.importance <= 1
        ? group
        : null,
    folded: [],
  };
}

/** What a fold of chatter says: who, and whether they greet, chat or both. */
function foldLine(group: Region, folded: readonly { type: string }[]): string {
  const greet = folded.some(({ type }) => type === 'gestured');
  const chat = folded.some(({ type }) => type === 'said');
  const doing =
    greet && chat
      ? 'greet each other and chat'
      : greet
        ? 'greet each other'
        : 'chat';
  return `${FOLKS[group]} ${doing}`;
}

/** The newest words of a fold (speech before gestures), shown after its line. */
export const foldDetail = (entry: FeedEntry) =>
  (entry.folded.find(({ type }) => type === 'said') ?? entry.folded[0])?.line ??
  null;

/** `entry` (chatter of `old`'s group) folded into `old`. */
function fold(old: FeedEntry, entry: FeedEntry): FeedEntry {
  const before = old.folded.length > 0 ? old.folded : [old];
  const folded = [{ type: entry.type, line: entry.line }, ...before];
  return {
    ...entry,
    ids: [...old.ids, entry.id],
    type: 'chatter',
    line: foldLine(entry.chatter!, folded),
    count: old.count + 1,
    folded: folded.map(({ type, line }) => ({ type, line })),
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
  if (entry.chatter !== null) {
    const into = entries
      .slice(0, FOLD_WITHIN)
      .findIndex(
        (old) =>
          old.chatter === entry.chatter && entry.tick - old.tick <= FOLD_TICKS,
      );
    if (into === -1) return [entry, ...entries].slice(0, FEED_KEEP);
    return [
      fold(entries[into], entry),
      ...entries.filter((_, index) => index !== into),
    ];
  }
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

/** What is drawn now, by id: animals at their feet, citizens at their pose. */
interface DrawnActors {
  animals: ReadonlyMap<string, { position: Vector3 }>;
  citizens: ReadonlyMap<string, { pose: { position: Vector3 } }>;
}

/**
 * Where ▶ flies for an entry: the spot it happened, else its actor as drawn (an animal or a citizen, a direction
 * from the planet's centre); null with nowhere to go (an actor not drawn, e.g. gone since the feed was drawn).
 */
export function flightTarget(
  entry: FeedEntry,
  { animals, citizens }: DrawnActors,
): Vector3 | null {
  if (entry.position) return new Vector3(...entry.position);
  if (entry.actorId === null) return null;
  const drawn =
    animals.get(entry.actorId)?.position ??
    citizens.get(entry.actorId)?.pose.position;
  return drawn ? drawn.clone().normalize() : null;
}
