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
} from '@/lib/client/types.gen';

export type LiveCitizen = CitizenEntity;

/** An animal of the feed (a registry kind of `assets.ts` `ANIMALS`). */
export type LiveAnimal = AnimalEntity;

export type AnimalActivity = AnimalEntity['activity'];

/** A camp's fire pit, a town fire basket or a campfire made anywhere. */
export type LiveFire = FireEntity;

export type Activity = CitizenEntity['activity'];

/** A `snapshot` (on connect) or a `tick` (each engine tick, and once more on a speed or pause change). */
export type LiveFrame = LiveState;

export type LiveEventMessage = LiveEvent;

export type LiveMessage = LiveLiveSchemaResponse;

/**
 * How long a tick lasts in real milliseconds at a clock speed. The engine's `speed` is ticks (game minutes) per
 * real second (`backend/app/engine.py`), so ×1 is a tick a second; a slower clock gives longer ticks.
 */
export const tickMs = (speed: number) => 1000 / speed;

/** WebSocket close codes of `/api/v1/live`. */
export const LIVE_CLOSE = {
  /** There is no run yet: try again later. */
  noRun: 4404,
  /** A newer run started: reconnect at once and take its snapshot. */
  newRun: 1012,
} as const;
