/*
 * How fast things move on screen for the clock (10 §4.2.2-3, D83): the one rate rule every animated thing reads.
 * Bodies cover the ground at the clock's full rate (game seconds per real second), but clips and procedural motion
 * (gaits, work, transitions, prop clips, smoke, doors, a tree's fall) play like a sped-up film only up to ×10:
 * beyond it a walk cycle would last a few frames, so legs keep that cadence and bodies glide. Gaits are picked from
 * the game speed, never the drawn speed, so ×1 and ×10 stay stride-locked. Wind sways at most ×3. Above ×10 the
 * globe is in time-lapse: trails and a badge say so.
 */

/** Clips and procedural motion play at most this many times their natural speed. */
export const VISUAL_RATE_MAX = 10;
/** Wind sway plays at most this many times its natural speed. */
const WIND_RATE_MAX = 3;

const clamp = (rate: number, max: number) => Math.min(Math.max(rate, 0), max);

/** The clock's rate: game seconds per real second, 0 while paused. */
export const clockRate = (speed: number, paused: boolean) =>
  paused ? 0 : Math.max(speed, 0);

/**
 * How many times its natural speed a clip or procedural motion plays at the clock's `rate`: a walk at ×10 covers
 * ten times the ground with ten times the steps (feet stay planted); past ×10 the cadence stays.
 */
export const visualRate = (rate: number) => clamp(rate, VISUAL_RATE_MAX);

/** How many times its natural speed wind sway plays at the clock's `rate`. */
export const windRate = (rate: number) => clamp(rate, WIND_RATE_MAX);

/** Whether the clock runs past what clips can show (fast-forward mode: trails and the badge). */
export const isTimeLapse = (rate: number) => rate > VISUAL_RATE_MAX;

/** The clock badge's words in time-lapse ("time-lapse ×60"), else null. */
export const timeLapseBadge = (rate: number) =>
  isTimeLapse(rate) ? `time-lapse ×${rate}` : null;
