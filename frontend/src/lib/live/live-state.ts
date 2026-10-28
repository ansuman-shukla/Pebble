/*
 * What the client knows of the live world: the latest frame of citizens and the clock, and the recent speech.
 * Pure: the hook feeds it the entities answer and every feed message.
 */
import {
  type LiveCitizen,
  type LiveMessage,
  normalizeCitizen,
  type RawCitizen,
} from './live-contract';

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

export interface LiveState {
  runId: string | null;
  tick: number;
  day: number;
  time: string;
  speed: number;
  paused: boolean;
  citizens: LiveCitizen[];
  speech: Speech[];
}

export const EMPTY_LIVE: LiveState = {
  runId: null,
  tick: -1,
  day: 0,
  time: '08:00',
  speed: 1,
  paused: false,
  citizens: [],
  speech: [],
};

/** The citizens of a frame, each normalized against what was known of it (for derived fields). */
function citizensOf(state: LiveState, raws: RawCitizen[], sameRun: boolean) {
  const known = new Map(
    sameRun ? state.citizens.map((citizen) => [citizen.id, citizen]) : [],
  );
  return raws.map((raw) => normalizeCitizen(raw, known.get(raw.id)));
}

export interface EntitiesAnswer {
  run_id: string;
  tick: number;
  day: number;
  time: string;
  citizens: RawCitizen[];
}

/** `GET /api/v1/entities` (the first load, and every poll while there is no socket). */
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
    citizens: citizensOf(state, view.citizens, sameRun),
    speech: sameRun ? state.speech : [],
  };
}

export function applyMessage(
  state: LiveState,
  message: LiveMessage,
  now: number,
): LiveState {
  const sameRun = message.run_id === state.runId;
  if (message.type === 'event') {
    const { event } = message;
    if (!sameRun || event.type !== 'said' || !event.actor_id) return state;
    const words = event.payload.words;
    if (
      typeof words !== 'string' ||
      state.speech.some(({ id }) => id === event.id)
    )
      return state;
    const speech = { id: event.id, actorId: event.actor_id, words, at: now };
    return { ...state, speech: [...state.speech, speech].slice(-SPEECH_KEEP) };
  }
  // a snapshot always resyncs; a tick only moves forward within the run it belongs to
  if (message.type === 'tick' && sameRun && message.tick <= state.tick)
    return state;
  return {
    runId: message.run_id,
    tick: message.tick,
    day: message.day,
    time: message.time,
    speed: message.speed,
    paused: message.paused,
    citizens: citizensOf(state, message.citizens, sameRun),
    speech: sameRun ? state.speech : [],
  };
}

/** Drops speech older than SPEECH_MS (same state when nothing expired). */
export function pruneSpeech(state: LiveState, now: number): LiveState {
  const speech = state.speech.filter(({ at }) => now - at < SPEECH_MS);
  return speech.length === state.speech.length ? state : { ...state, speech };
}

/** Town time of the feed in game minutes since the start of day 0 (the sky's clock). */
export function feedMinutes(state: Pick<LiveState, 'day' | 'time'>) {
  const [hours, minutes] = state.time.split(':').map(Number);
  return state.day * 24 * 60 + hours * 60 + minutes;
}
