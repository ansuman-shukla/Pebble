/*
 * The client's game clock until the simulation drives time (M5): 1 real second = 1 game minute (a day lasts 24
 * real minutes), starting at 08:00 town time. v0 has no axial tilt: the sun circles the planet in the equator's
 * plane, westward, and local time runs 4 game minutes ahead per degree of longitude east.
 */
import { Vector3 } from 'three';

const DAY_MINUTES = 24 * 60;
export const START_MINUTES = 8 * 60;
/** Game minutes per real second. */
export const NORMAL_RATE = 1;
export const FAST_RATE = 60;

const DEG = Math.PI / 180;

export interface GameClock {
  /** Town local time in game minutes since the start of day 0 (keeps counting past midnight). */
  minutes: number;
  rate: number;
}

export const createClock = (minutes = START_MINUTES): GameClock => ({
  minutes,
  rate: NORMAL_RATE,
});

/** "HH:MM" -> minutes, or null when it isn't a time of day. */
export function parseTime(text: string | null) {
  const match = text?.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const [hours, minutes] = [Number(match[1]), Number(match[2])];
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

/** Longitude (degrees) under the sun when the town (at `townLon`) shows `minutes`. */
const sunLongitude = (minutes: number, townLon: number) =>
  townLon + (12 - minutes / 60) * 15;

/** Unit vector towards the sun. */
export function sunDirection(
  minutes: number,
  townLon: number,
  target = new Vector3(),
) {
  const lon = sunLongitude(minutes, townLon) * DEG;
  return target.set(Math.sin(lon), 0, Math.cos(lon));
}

/** Local time of day (0 ≤ minutes < 1440) at longitude `lon` when the town shows `minutes`. */
export function localMinutes(minutes: number, townLon: number, lon: number) {
  const local = minutes + ((lon - townLon) / 15) * 60;
  return ((local % DAY_MINUTES) + DAY_MINUTES) % DAY_MINUTES;
}

export function formatTime(minutesOfDay: number) {
  const whole = Math.floor(minutesOfDay);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(Math.floor(whole / 60) % 24)}:${pad(whole % 60)}`;
}
