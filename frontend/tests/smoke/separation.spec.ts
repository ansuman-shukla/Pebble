import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  type Crowd,
  type CrowdBody,
  GIVE,
  giveOf,
  KEEP_M,
  newCrowdBody,
  separate,
  standsUntilBack,
} from '../../src/lib/live/separation';

/* Drawn bodies never pass through each other (no browser): walkers and runners part as they meet, a crowd on one
 * point spreads out and holds still, sitters never move, nobody slides seated, bodies out of sight leave the crowd,
 * and a clear body ends exactly on its spot. */

const R = 2000;
const FRAME = 1 / 60;
const PACE = 1.4;
const RUN = 3.5;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number) => new Vector3(x / R, z / R, 1).normalize();
const metres = (a: Vector3, b: Vector3) => a.angleTo(b) * R;
const east = (spot: Vector3) => (spot.x / spot.z) * R;
const north = (spot: Vector3) => (spot.y / spot.z) * R;

/** Someone in the scene: where its track draws it `t` seconds in, the posture it takes then and whether it moves. */
interface Actor {
  spot: (t: number) => [number, number];
  posture: (t: number) => string;
  moving: (t: number) => boolean;
}

/** Walks (or runs, at `pace`) in a straight line from `from` to `to`, then stands there. */
function walker(
  from: [number, number],
  to: [number, number],
  pace = PACE,
): Actor {
  const length = Math.hypot(to[0] - from[0], to[1] - from[1]);
  const arrive = length / pace;
  return {
    spot: (t) => {
      const k = Math.min(t / arrive, 1);
      return [from[0] + (to[0] - from[0]) * k, from[1] + (to[1] - from[1]) * k];
    },
    posture: () => 'standing',
    moving: (t) => t < arrive,
  };
}

/** Stays on one spot in one posture (`moving`: drawn walking on the spot, giving way like a walker). */
const still = (
  spot: [number, number],
  posture = 'standing',
  moving = false,
): Actor => ({
  spot: () => spot,
  posture: () => posture,
  moving: () => moving,
});

/**
 * Draws the scene frame by frame for `seconds` of real time at the clock's `rate` (0 paused; a function of the real
 * seconds gone for a clock that changes), everyone in turn as the globe does: the drawn and track spots, and the
 * posture each is shown in (one about to sit stands until back on its spot).
 */
function play(
  actors: Actor[],
  seconds: number,
  rate: number | ((real: number) => number) = 1,
) {
  const crowd: Crowd = new Set();
  const bodies: CrowdBody[] = actors.map((_, i) => {
    const body = newCrowdBody(`actor-${i}`);
    crowd.add(body);
    return body;
  });
  const drawn: Vector3[][] = [];
  const spots: Vector3[][] = [];
  const shown: string[][] = [];
  let now = actors.map((actor) => actor.posture(0));
  let t = 0;
  for (let frame = 0; frame <= Math.round(seconds / FRAME); frame++) {
    const delta =
      FRAME * (typeof rate === 'number' ? rate : rate(frame * FRAME));
    t += delta;
    spots.push(actors.map((actor) => at(...actor.spot(t))));
    drawn.push(
      actors.map((actor, i) =>
        separate(
          crowd,
          bodies[i],
          at(...actor.spot(t)),
          giveOf(actor.posture(t), actor.moving(t)),
          delta,
          R,
        ).clone(),
      ),
    );
    now = actors.map((actor, i) => {
      const next = actor.posture(t);
      const hold =
        now[i] === 'standing' &&
        standsUntilBack(bodies[i], next !== 'standing');
      return hold ? now[i] : next;
    });
    shown.push(now);
  }
  return { drawn, spots, shown, bodies };
}

/** The closest any two are drawn over the whole scene (metres). */
function closest(drawn: Vector3[][]) {
  let least = Infinity;
  for (const frame of drawn)
    for (let i = 0; i < frame.length; i++)
      for (let j = i + 1; j < frame.length; j++)
        least = Math.min(least, metres(frame[i], frame[j]));
  return least;
}

/** The longest anyone is drawn moving in one frame (metres). */
function biggestStep(drawn: Vector3[][]) {
  let most = 0;
  for (let k = 1; k < drawn.length; k++)
    for (let i = 0; i < drawn[k].length; i++)
      most = Math.max(most, metres(drawn[k - 1][i], drawn[k][i]));
  return most;
}

test('two walkers meeting head-on on one line sidestep right of their way and pass at least 0.6 m apart', () => {
  const { drawn, spots } = play(
    [walker([-10, 0], [10, 0]), walker([10, 0], [-10, 0])],
    16,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(0.6);
  expect(biggestStep(drawn)).toBeLessThan(0.04); // at ×1 and 60 fps a pace is 0.023 m a frame
  // as they meet (7.1 s) the one walking east is drawn south of the line (its right), the other north
  const meeting = drawn[Math.round(10 / PACE / FRAME)];
  expect(north(meeting[0])).toBeLessThan(-0.25);
  expect(north(meeting[1])).toBeGreaterThan(0.25);
  // stepping across their way, not shoved back along it
  for (const [k, frame] of drawn.entries())
    frame.forEach((spot, i) =>
      expect(Math.abs(east(spot) - east(spots[k][i]))).toBeLessThan(0.1),
    );
  // and they end exactly where they were going
  drawn
    .at(-1)!
    .forEach((spot, i) =>
      expect(metres(spot, spots.at(-1)![i])).toBeLessThan(1e-6),
    );
});

test('at ×10 the film runs ten times faster: walkers meeting head-on still pass at least 0.6 m apart', () => {
  const { drawn, spots } = play(
    [walker([-10, 0], [10, 0]), walker([10, 0], [-10, 0])],
    1.6,
    10,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(0.6);
  drawn
    .at(-1)!
    .forEach((spot, i) =>
      expect(metres(spot, spots.at(-1)![i])).toBeLessThan(1e-6),
    );
});

test('two walkers crossing at a right angle pass at least 0.6 m apart and end on their spots', () => {
  const { drawn, spots } = play(
    [walker([-10, 0], [10, 0]), walker([0, -10], [0, 10])],
    16,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(0.6);
  expect(biggestStep(drawn)).toBeLessThan(0.04);
  drawn
    .at(-1)!
    .forEach((spot, i) =>
      expect(metres(spot, spots.at(-1)![i])).toBeLessThan(1e-6),
    );
});

test('a walker passing someone who stands still goes round them, and both end where they stand', () => {
  const { drawn, spots } = play(
    [walker([-10, 0.1], [10, 0.1]), still([0, 0])],
    16,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(0.6);
  expect(biggestStep(drawn)).toBeLessThan(0.04);
  // the walker gives way most: the one standing steps aside less
  const offsets = (i: number) =>
    Math.max(...drawn.map((frame, k) => metres(frame[i], spots[k][i])));
  expect(offsets(0)).toBeGreaterThan(offsets(1));
  drawn
    .at(-1)!
    .forEach((spot, i) =>
      expect(metres(spot, spots.at(-1)![i])).toBeLessThan(1e-6),
    );
});

const AROUND = (count: number, distance: number) =>
  Array.from({ length: count }, (_, i): [number, number] => [
    distance * Math.cos((2 * Math.PI * i) / count),
    distance * Math.sin((2 * Math.PI * i) / count),
  ]);

test('five walking up to one point spread round it, never closer than 0.6 m, and then stand still', () => {
  const { drawn, spots } = play(
    AROUND(5, 10).map((from) => walker(from, [0, 0])),
    20,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(0.6);
  expect(biggestStep(drawn)).toBeLessThan(0.04);
  const end = drawn.at(-1)!;
  for (const spot of end)
    expect(metres(spot, spots.at(-1)![0])).toBeLessThan(1); // round the point, close by
  // settled: nobody drifts any more
  const before = drawn[drawn.length - 1 - Math.round(2 / FRAME)];
  end.forEach((spot, i) => expect(metres(spot, before[i])).toBeLessThan(1e-3));
});

test('five drawn on one point from the start part within a second and hold apart', () => {
  const { drawn } = play(
    AROUND(5, 0).map(() => still([0, 0])),
    3,
  );
  expect(closest(drawn.slice(Math.round(1 / FRAME)))).toBeGreaterThanOrEqual(
    0.6,
  );
  expect(closest(drawn.slice(-1))).toBeGreaterThanOrEqual(KEEP_M - 0.02);
  expect(biggestStep(drawn)).toBeLessThan(0.04);
});

test('two on one point part by how readily each gives way: a walker steps further than someone standing', () => {
  const { drawn, spots } = play(
    [still([0, 0], 'standing', true), still([0, 0])],
    3,
  );
  const [walking, standing] = drawn
    .at(-1)!
    .map((spot, i) => metres(spot, spots.at(-1)![i]));
  expect(walking + standing).toBeGreaterThanOrEqual(KEEP_M - 0.02);
  expect(walking / standing).toBeGreaterThan(1.4);
});

test('a sitter is never moved: walkers coming to its very spot stop round it', () => {
  const { drawn, spots } = play(
    [
      still([0, 0], 'seated'),
      ...AROUND(3, 8).map((from) => walker(from, [0, 0])),
    ],
    15,
  );
  for (const [k, frame] of drawn.entries())
    expect(metres(frame[0], spots[k][0])).toBe(0);
  expect(closest(drawn)).toBeGreaterThanOrEqual(0.6);
});

test('two sitters on one spot are left alone (only the sim can part them)', () => {
  const { drawn } = play(
    [still([0, 0], 'sitting'), still([0, 0], 'sleeping')],
    1,
  );
  expect(metres(drawn.at(-1)![0], drawn.at(-1)![1])).toBe(0);
});

test('someone who sits down while stepped aside stands until back on the seat, then sits: never sliding seated', () => {
  const sitter: Actor = {
    spot: () => [0, 0],
    posture: (t) => (t < 2 ? 'standing' : 'seated'),
    moving: () => false,
  };
  const { drawn, spots, shown } = play([sitter, still([0.2, 0])], 6);
  const stepped = Math.round(1.9 / FRAME);
  expect(metres(drawn[stepped][0], spots[0][0])).toBeGreaterThan(0.1); // stepped aside...
  expect(shown[Math.round(2.05 / FRAME)][0]).toBe('standing'); // ...so it stands on a moment
  expect(biggestStep(drawn)).toBeLessThan(0.04);
  const seated = shown.flatMap((postures, k) =>
    postures[0] === 'seated' ? [k] : [],
  );
  expect(seated.length).toBeGreaterThan(0); // it does sit
  for (const k of seated) expect(metres(drawn[k][0], spots[k][0])).toBe(0); // exactly on its seat while seated
  expect(seated[0]).toBeLessThan(Math.round(3 / FRAME)); // within a second
  // the one standing beside it is clear of it once it sits
  expect(metres(drawn.at(-1)![0], drawn.at(-1)![1])).toBeGreaterThanOrEqual(
    KEEP_M - 0.02,
  );
});

test('a paused clock (or a replayed moment) parts bodies on one spot at once, then holds everything', () => {
  const { drawn } = play(
    [walker([-2, 0], [2, 0]), still([0, 0]), still([0, 0])],
    3,
    (real) => (real < 0.1 ? 1 : 0), // paused just after they start parting
  );
  const pausedAt = Math.round(0.1 / FRAME);
  expect(metres(drawn[pausedAt - 1][1], drawn[pausedAt - 1][2])).toBeLessThan(
    0.5,
  ); // still parting...
  const parted = drawn[pausedAt + Math.round(0.5 / FRAME)];
  expect(closest([parted])).toBeGreaterThanOrEqual(KEEP_M - 0.02); // ...apart at once
  for (const frame of drawn.slice(pausedAt + Math.round(0.5 / FRAME)))
    frame.forEach((spot, i) =>
      expect(metres(spot, parted[i])).toBeLessThan(1e-6),
    ); // ...and held
});

test('a replayed moment of two on one spot draws them apart from its first frames', () => {
  const { drawn } = play([still([0, 0]), still([0, 0])], 0.2, 0);
  expect(metres(drawn.at(-1)![0], drawn.at(-1)![1])).toBeGreaterThanOrEqual(
    KEEP_M - 0.02,
  );
});

test('a body out of sight (inside a house) leaves the crowd: nobody steps round it, and it is drawn on its spot', () => {
  const { drawn, spots } = play([still([0, 0], 'inside'), still([0, 0])], 2);
  for (const [k, frame] of drawn.entries())
    frame.forEach((spot, i) => expect(metres(spot, spots[k][i])).toBe(0));
});

test('a body left clear eases back onto its spot, about two-thirds of the way in half a second, then exactly', () => {
  const leaves: Actor = {
    spot: () => [0, 0],
    posture: (t) => (t < 2 ? 'standing' : 'inside'),
    moving: () => false,
  };
  const { drawn, spots } = play([leaves, still([0, 0])], 5);
  const off = (s: number) =>
    metres(drawn[Math.round(s / FRAME)][1], spots[0][1]);
  expect(off(2)).toBeGreaterThan(0.3); // stepped aside while the other stood there
  expect(off(2.5)).toBeLessThan(off(2) * 0.5);
  expect(off(5)).toBe(0);
});

test('who gives way by posture: walking most, standing less, any other posture never; out of sight not at all', () => {
  expect(giveOf('standing', true)).toBe(GIVE.walking);
  expect(giveOf('standing', false)).toBe(GIVE.standing);
  expect(GIVE.walking).toBeGreaterThan(GIVE.standing);
  for (const posture of [
    'seated',
    'sitting',
    'sitting_ground',
    'sleeping',
    'lying',
    'crouching',
    'some-new-pose',
  ]) {
    expect(giveOf(posture, false)).toBe(0);
    expect(giveOf(posture, true)).toBe(0);
  }
  expect(giveOf('inside', false)).toBeNull();
  expect(giveOf('hidden', true)).toBeNull();
});

test('two runners meeting head-on pass at least 0.7 m apart and end on their spots', () => {
  const { drawn, spots } = play(
    [walker([-15, 0], [15, 0], RUN), walker([15, 0], [-15, 0], RUN)],
    12,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(KEEP_M);
  drawn
    .at(-1)!
    .forEach((spot, i) =>
      expect(metres(spot, spots.at(-1)![i])).toBeLessThan(1e-6),
    );
});

test('a walker and a runner meeting head-on pass at least 0.7 m apart', () => {
  const { drawn } = play(
    [walker([-15, 0], [15, 0], RUN), walker([10, 0], [-15, 0])],
    12,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(KEEP_M);
});

test('a runner overtaking a walker on its line goes round it', () => {
  const { drawn } = play(
    [walker([-10, 0], [20, 0], RUN), walker([0, 0], [20, 0])],
    12,
  );
  expect(closest(drawn)).toBeGreaterThanOrEqual(0.6);
});

test('walkers far apart are drawn exactly on their spots', () => {
  const { drawn, spots } = play(
    [walker([-10, 5], [10, 5]), walker([10, -5], [-10, -5])],
    15,
  );
  for (const [k, frame] of drawn.entries())
    frame.forEach((spot, i) =>
      expect(metres(spot, spots[k][i])).toBeLessThan(1e-9),
    );
  expect(east(drawn.at(-1)![0])).toBeCloseTo(10, 6);
});
