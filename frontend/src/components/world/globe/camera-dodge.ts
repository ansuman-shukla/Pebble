/*
 * The follow camera round a citizen (not the steered player): when something cuts its boom short (a stall's awning,
 * the eaves over them, a wall behind them), it swings round to the nearest clear boom instead of pulling in to their
 * face. Pure: `globe-cameras.tsx` measures the booms and eases the swing; the tests drive it directly.
 */

/** A boom shorter than this (or than the zoom, if less) is cut short... */
export const DODGE_ARM = 2.5;
/** ...so it tries these turns round the subject (radians)... */
const DODGE_YAWS = [
  0,
  0.5,
  -0.5,
  1,
  -1,
  1.6,
  -1.6,
  2.2,
  -2.2,
  2.8,
  -2.8,
  Math.PI,
];
/** ...at the wanted pitch, then just over the ground, then over the top (radians). */
const DODGE_PITCHES = [0.05, 0.75, 1.1, 1.45];
/** A radian of pitch weighs this many of turn: a view from the side beats one from straight above. */
const PITCH_COST = 2;

/** A turn round the subject and a pitch change, both radians. */
export interface Swing {
  yaw: number;
  pitch: number;
}

/**
 * The swing that gives the nearest boom of at least `good` metres from the wanted `pitch`: none if the wanted boom
 * is, else the first clear one by how far it turns and tilts (`reach(yaw, pitch)` = metres clear), else the longest
 * there is.
 */
export function dodgeFor(
  pitch: number,
  good: number,
  reach: (yaw: number, pitch: number) => number,
): Swing {
  const candidates = DODGE_YAWS.flatMap((yaw) =>
    [pitch, ...DODGE_PITCHES].map((to) => ({
      yaw,
      pitch: to - pitch,
      cost: Math.abs(yaw) + PITCH_COST * Math.abs(to - pitch),
    })),
  ).sort((a, b) => a.cost - b.cost);
  let best = candidates[0];
  let longest = -1;
  for (const candidate of candidates) {
    const metres = reach(candidate.yaw, pitch + candidate.pitch);
    if (metres >= good) return { yaw: candidate.yaw, pitch: candidate.pitch };
    if (metres > longest) [best, longest] = [candidate, metres];
  }
  return { yaw: best.yaw, pitch: best.pitch };
}
