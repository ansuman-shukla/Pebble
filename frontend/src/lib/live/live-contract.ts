/*
 * The live feed's shapes as the client uses them: the backend's generated models (`GET /api/v1/live/schema`,
 * `WS /api/v1/live`, `GET /api/v1/entities`) under the names the live modules use.
 */
import type {
  AnimalEntity,
  CitizenEntity,
  FireEntity,
  LiveEvent,
  LiveLiveSchemaResponse,
  LiveState,
  StackEntity,
} from '@/lib/client/types.gen';

export type LiveCitizen = CitizenEntity;

/** An animal of the feed (a registry kind of `assets.ts` `ANIMALS`). */
export type LiveAnimal = AnimalEntity;

export type AnimalActivity = AnimalEntity['activity'];

/** A camp's fire pit, a town fire basket or a campfire made anywhere. */
export type LiveFire = FireEntity;

/** Things lying on the ground (an item kind, how many): a felled tree's logs, meat left at remains, goods put down. */
export type LiveStack = StackEntity;

export type Activity = CitizenEntity['activity'];

/** A `snapshot` (on connect) or a `tick` (each engine tick, and once more on a speed or pause change). */
export type LiveFrame = LiveState;

export type LiveEventMessage = LiveEvent;

export type LiveMessage = LiveLiveSchemaResponse;

/** Game seconds per tick (one game minute). */
export const TICK_SECONDS = 60;

/**
 * How long a tick lasts in real milliseconds at a clock speed. The engine's `speed` is game seconds per real second
 * (`backend/app/engine.py`, D65): ×1 is real time, a tick a real minute; ×600 a tick every 0.1 s.
 */
export const tickMs = (speed: number) => (TICK_SECONDS * 1000) / speed;

/** WebSocket close codes of `/api/v1/live`. */
export const LIVE_CLOSE = {
  /** There is no run yet: try again later. */
  noRun: 4404,
  /** A newer run started or the run's history was rewritten: reconnect at once for a fresh snapshot. */
  resync: 1012,
} as const;
