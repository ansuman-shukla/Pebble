import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  type Crowd,
  type CrowdBody,
  GIVE,
  KEEP_M,
  newCrowdBody,
  separate,
} from '../../src/lib/live/separation';

/* Drawn bodies never pass through each other (no browser): walkers part as they meet, a crowd on one point spreads
 * out and holds still, sitters never move, and a clear body ends exactly on its spot. */

const R = 2000;
const FRAME = 1 / 60;
const PACE = 1.4;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number) => new Vector3(x / R, z / R, 1).normalize();
const metres = (a: Vector3, b: Vector3) => a.angleTo(b) * R;
const east = (spot: Vector3) => (spot.x / spot.z) * R;
const north = (spot: Vector3) => (spot.y / spot.z) * R;

/** Someone in the scene: where its track draws it `t` real seconds in, and how readily it gives way then. */
interface Actor {
  spot: (t: number) => [number, number];
  give: (t: number) => number;
}

/** Walks in a straight line from `from` to `to` at walking pace, then stands there. */
function walker(from: [number, number], to: [number, number]): Actor {
  const length = Math.hypot(to[0] - from[0], to[1] - from[1]);
  const arrive = length / PACE;
  return {
    spot: (t) => {
      const k = Math.min(t / arrive, 1);
      return [from[0] + (to[0] - from[0]) * k, from[1] + (to[1] - from[1]) * k];
    },
    give: (t) => (t < arrive ? GIVE.walking : GIVE.standing),
  };
}

const still = (
  spot: [number, number],
  give: number = GIVE.standing,
): Actor => ({
  spot: () => spot,
  give: () => give,
});

/**
 * Draws the scene frame by frame for `seconds` of real time at the clock's `rate` (0 paused; a function of the real
 * seconds gone for a clock that changes), everyone in turn as the globe does: the drawn and track spots.
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
          actor.give(t),
          delta,
          R,
        ).clone(),
      ),
    );
  }
  return { drawn, spots, bodies };
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
    [still([0, 0], GIVE.walking), still([0, 0], GIVE.standing)],
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
      still([0, 0], GIVE.resting),
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
    [still([0, 0], GIVE.resting), still([0, 0], GIVE.resting)],
    1,
  );
  expect(metres(drawn.at(-1)![0], drawn.at(-1)![1])).toBe(0);
});

test('someone who sits down while stepped aside settles onto the seat, not jumping', () => {
  const sitter: Actor = {
    spot: () => [0, 0],
    give: (t) => (t < 2 ? GIVE.standing : GIVE.resting),
  };
  const { drawn, spots } = play([sitter, still([0.2, 0])], 6);
  expect(
    metres(drawn[Math.round(1.9 / FRAME)][0], spots[0][0]),
  ).toBeGreaterThan(0.1);
  expect(biggestStep(drawn)).toBeLessThan(0.04);
  expect(metres(drawn.at(-1)![0], spots.at(-1)![0])).toBeLessThan(1e-6); // on its seat
});

test('a paused clock holds every drawn body where it is', () => {
  const { drawn } = play(
    [walker([-2, 0], [2, 0]), still([0, 0]), still([0, 0])],
    3,
    (real) => (real < 1 ? 1 : 0), // paused a second in, mid-parting
  );
  const pausedAt = drawn[Math.round(1.05 / FRAME)];
  expect(metres(pausedAt[1], pausedAt[2])).toBeGreaterThan(0.3); // parting...
  for (const frame of drawn.slice(Math.round(1.05 / FRAME)))
    frame.forEach((spot, i) => expect(metres(spot, pausedAt[i])).toBe(0)); // ...and held
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
