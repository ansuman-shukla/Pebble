/*
 * What the client knows of the live world: the latest frame of citizens, animals, fires and the clock, the recent
 * speech, and the recent gestures and blows bodies show (cues). Pure: the hook feeds it the entities answer and every
 * feed message.
 */
import type {
  LiveAnimal,
  LiveCitizen,
  LiveFire,
  LiveMessage,
} from './live-contract';
import { GESTURES, type GestureKind } from './motion';

/** How long a speech bubble stays up, ms. */
export const SPEECH_MS = 4000;
/** At most this many recent speech events are kept. */
const SPEECH_KEEP = 30;

export interface Speech {
  id: string;
  actorId: string;
  words: string;
  /** Client time (ms, performance.now) it arrived. */
  at: number;
}

/** At most this many recent cues are kept. */
const CUES_KEEP = 30;

/** Something a body shows once: a gesture (`gestured`) or a blow taken (`injured`: the hit reaction). */
export interface Cue {
  id: string;
  actorId: string;
  kind: GestureKind | 'hit';
  /** Client time (ms, performance.now) it arrived. */
  at: number;
}

export interface LiveState {
  runId: string | null;
  tick: number;
  day: number;
  time: string;
  speed: number;
  paused: boolean;
  citizens: LiveCitizen[];
  animals: LiveAnimal[];
  fires: LiveFire[];
  speech: Speech[];
  cues: Cue[];
}

export const EMPTY_LIVE: LiveState = {
  runId: null,
  tick: -1,
  day: 0,
  time: '08:00',
  speed: 1,
  paused: false,
  citizens: [],
  animals: [],
  fires: [],
  speech: [],
  cues: [],
};

export interface EntitiesAnswer {
  run_id: string;
  tick: number;
  day: number;
  time: string;
  citizens: LiveCitizen[];
  animals: LiveAnimal[];
  fires: LiveFire[];
}

/** `GET /api/v1/entities` (the first load, before the socket's snapshot). */
export function applyEntities(
  state: LiveState,
  view: EntitiesAnswer,
): LiveState {
  const sameRun = view.run_id === state.runId;
  if (sameRun && view.tick <= state.tick) return state;
  return {
    ...state,
    runId: view.run_id,
    tick: view.tick,
    day: view.day,
    time: view.time,
    citizens: view.citizens,
    animals: view.animals,
    fires: view.fires,
    speech: sameRun ? state.speech : [],
    cues: sameRun ? state.cues : [],
  };
}

const isGesture = (kind: unknown): kind is GestureKind =>
  GESTURES.includes(kind as GestureKind);

/** The cue an event shows on its actor's body, if any. */
function cueOf(
  event: Extract<LiveMessage, { type: 'event' }>['event'],
  now: number,
): Cue | null {
  if (!event.actor_id) return null;
  const kind =
    event.type === 'injured'
      ? 'hit'
      : event.type === 'gestured' && isGesture(event.payload.kind)
        ? event.payload.kind
        : null;
  return kind && { id: event.id, actorId: event.actor_id, kind, at: now };
}

export function applyMessage(
  state: LiveState,
  message: LiveMessage,
  now: number,
): LiveState {
  const sameRun = message.run_id === state.runId;
  if (message.type === 'event') {
    const { event } = message;
    if (!sameRun) return state;
    const cue = cueOf(event, now);
    if (cue && !state.cues.some(({ id }) => id === cue.id))
      return { ...state, cues: [...state.cues, cue].slice(-CUES_KEEP) };
    if (event.type !== 'said' || !event.actor_id) return state;
    const words = event.payload.words;
    if (
      typeof words !== 'string' ||
      state.speech.some(({ id }) => id === event.id)
    )
      return state;
    const speech = { id: event.id, actorId: event.actor_id, words, at: now };
    return { ...state, speech: [...state.speech, speech].slice(-SPEECH_KEEP) };
  }
  // a snapshot always resyncs; a tick only moves forward within the run it belongs to, except the extra tick a
  // speed or pause change sends (same tick: only the clock changes)
  if (message.type === 'tick' && sameRun) {
    if (message.tick < state.tick) return state;
    if (message.tick === state.tick)
      return { ...state, speed: message.speed, paused: message.paused };
  }
  return {
    runId: message.run_id,
    tick: message.tick,
    day: message.day,
    time: message.time,
    speed: message.speed,
    paused: message.paused,
    citizens: message.citizens,
    animals: message.animals,
    fires: message.fires,
    speech: sameRun ? state.speech : [],
    cues: sameRun ? state.cues : [],
  };
}

/** Drops speech older than SPEECH_MS (same state when nothing expired). */
export function pruneSpeech(state: LiveState, now: number): LiveState {
  const speech = state.speech.filter(({ at }) => now - at < SPEECH_MS);
  return speech.length === state.speech.length ? state : { ...state, speech };
}

/** The clock's speed in words: "paused", "real time" (×1, D65) or "×60". */
export const speedWords = ({
  speed,
  paused,
}: Pick<LiveState, 'speed' | 'paused'>) =>
  paused ? 'paused' : speed === 1 ? 'real time' : `×${speed}`;

/** Town time of the feed in game minutes since the start of day 0 (the sky's clock). */
export function feedMinutes(state: Pick<LiveState, 'day' | 'time'>) {
  const [hours, minutes] = state.time.split(':').map(Number);
  return state.day * 24 * 60 + hours * 60 + minutes;
}
