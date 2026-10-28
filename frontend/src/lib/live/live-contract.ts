/*
 * THE SWAP POINT for the live feed (contract: `.runtime/briefs/live-contract.md`, "Live feed").
 *
 * Until the backend publishes the live message models and the extended CitizenEntity in its OpenAPI schema, the
 * types below mirror the contract by hand and `normalizeCitizen` fills the fields today's `GET /api/v1/entities`
 * doesn't send yet (heading_deg, activity, role, region). Once the backend lands:
 *   1. `pnpm update-openapi`, then replace the hand-written types with the generated ones
 *      (`CitizenEntity`, the `LiveMessage` union) from `@/lib/client/types.gen`;
 *   2. drop the fallbacks in `normalizeCitizen` (keep it as the one place raw entities enter the client);
 *   3. set `LIVE_SOCKET = true` so `/` opens the WebSocket instead of polling `GET /api/v1/entities`.
 */
import { Vector3, type Vector3Tuple } from 'three';

import type { CitizenEntity as EntityToday } from '@/lib/client/types.gen';
import { CITIZEN_LOOKS, type Region } from '@/lib/world/citizen-looks';
import { tangentFrame } from '@/lib/world/globe';

/** Whether the backend serves `/api/v1/live` (WebSocket). Until it does, the real feed polls the entities. */
export const LIVE_SOCKET = false;

export type Activity =
  | 'idle'
  | 'walking'
  | 'sleeping'
  | 'resting'
  | 'gathering'
  | 'eating'
  | 'drinking'
  | 'working'
  | 'talking'
  | 'dead';

/** CitizenEntity as the contract extends it. */
export type LiveCitizen = EntityToday & {
  /** Facing: yaw in the local tangent frame, 0 = south (+z local), 180 = north (the town's convention). */
  heading_deg: number;
  activity: Activity;
  role: string;
  region: Region;
};

interface LiveEvent {
  id: string;
  type: string;
  actor_id: string | null;
  payload: Record<string, unknown>;
}

export interface LiveFrame {
  type: 'snapshot' | 'tick';
  run_id: string;
  tick: number;
  day: number;
  time: string;
  speed: number;
  paused: boolean;
  citizens: LiveCitizen[];
}

export interface LiveEventMessage {
  type: 'event';
  run_id: string;
  tick: number;
  event: LiveEvent;
}

export type LiveMessage = LiveFrame | LiveEventMessage;

/** A raw entity from the backend: today's fields, the new ones possibly missing. */
export type RawCitizen = EntityToday & Partial<LiveCitizen>;

const LOOKS = new Map(CITIZEN_LOOKS.map((look) => [look.id, look]));

/** What today's engine action names mean as an activity (only used while the backend doesn't send one). */
const ACTION_ACTIVITY: Record<string, Activity> = {
  walk_to: 'walking',
  follow: 'walking',
  gather: 'gathering',
  work: 'working',
  eat: 'eating',
  drink: 'drinking',
  say: 'talking',
  rest: 'resting',
  sleep: 'sleeping',
};

function activityOf(raw: RawCitizen): Activity {
  if (raw.activity) return raw.activity;
  if (!raw.alive) return 'dead';
  if (raw.asleep) return 'sleeping';
  return (raw.action ? ACTION_ACTIVITY[raw.action] : undefined) ?? 'idle';
}

/** Heading (contract convention) from one unit position to the next, or null when it didn't move. */
function headingOfMove(from: Vector3Tuple, to: Vector3Tuple): number | null {
  const start = new Vector3(...from);
  const move = new Vector3(...to).sub(start);
  if (move.length() < 1e-7) return null;
  const { east, north } = tangentFrame(start);
  return (Math.atan2(move.dot(east), -move.dot(north)) * 180) / Math.PI;
}

/**
 * The one place raw entities enter the client: fills what the backend doesn't send yet (see above). Without a
 * heading the citizen faces the way it moved since `previous` (or keeps the previous heading).
 */
export function normalizeCitizen(
  raw: RawCitizen,
  previous?: LiveCitizen,
): LiveCitizen {
  const look = LOOKS.get(raw.look);
  const moved =
    previous && headingOfMove(previous.position.unit, raw.position.unit);
  return {
    ...raw,
    heading_deg: raw.heading_deg ?? moved ?? previous?.heading_deg ?? 0,
    activity: activityOf(raw),
    role: raw.role ?? look?.role ?? '',
    region: raw.region ?? look?.region ?? 'town',
  };
}
