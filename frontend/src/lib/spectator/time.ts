/*
 * Game time as spectators read it. Tick = 1 game minute; tick 0 is 08:00 town time on day 0
 * (`backend/app/sim/clock.py`).
 */

export const DAY_MINUTES = 24 * 60;
const START_MINUTE = 8 * 60;

/** Town day and "HH:MM" of a tick. */
export function townClock(tick: number): { day: number; time: string } {
  const minute = START_MINUTE + tick;
  const hours = Math.floor((minute % DAY_MINUTES) / 60);
  const minutes = minute % 60;
  return {
    day: Math.floor(minute / DAY_MINUTES),
    time: `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`,
  };
}

/** "day 3, 14:05" */
export function tickLabel(tick: number): string {
  const { day, time } = townClock(tick);
  return `day ${day}, ${time}`;
}

/** The first tick of a town day (day 0 starts at tick -480, so it clamps to 0). */
export function dayStartTick(day: number): number {
  return Math.max(0, day * DAY_MINUTES - START_MINUTE);
}

/** Reads a tick from a search param: a whole number ≥ 0, else null. */
export function parseTick(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) return null;
  return Number(value);
}
