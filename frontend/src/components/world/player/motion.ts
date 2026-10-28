/* Shared walking constants and helpers for the flat and the globe player. */

export const WALK_SPEED = 1.4;
export const RUN_SPEED = 3.5;
/** Highest rise onto a walkable surface in one move; anything taller is a wall. */
export const MAX_STEP_UP = 0.5;
/** Ground probes start this far above the current ground. */
export const PROBE_HEIGHT = 1;
export const MAX_FRAME = 0.1;
export const MOVE_EVENT_INTERVAL = 0.1;

/** Frame-rate independent approach factor for exponential smoothing. */
export const smoothing = (rate: number, delta: number) =>
  1 - Math.exp(-rate * delta);
