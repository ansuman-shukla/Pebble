import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  advance,
  citizenPath,
  groundSpeed,
  headingAt,
  joinAt,
  passedBetween,
  pointAt,
  snapMetres,
  walking,
  walkPath,
} from '../../src/lib/live/walk-path';

/* Walking a streamed route between ticks (no browser): along the corners, by its times, joined smoothly. */

const R = 2000;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number) =>
  new Vector3(x / R, z / R, 1).normalize().toArray();
/** Metres east / north of the chart's centre of a direction. */
const local = (unit: Vector3) => {
  const flat = unit.clone().divideScalar(unit.z);
  return [flat.x * R, flat.y * R];
};

// an L around a building corner: 30 m east in 30 s, then 40 m north in 40 s
const L = [at(0, 0), at(30, 0), at(30, 40)];
const L_TIMES = [0, 30, 70];

test('a walker moves along the route by its times, round the corner, and stops at the end', () => {
  const path = walkPath(L, L_TIMES, R);
  const spot = new Vector3();
  const seen: number[][] = [];
  for (let second = 0; second < 60; second++) {
    seen.push(local(pointAt(path, spot)));
    advance(path, 1);
  }
  // every drawn spot is on one of the two legs: never inside the corner
  for (const [x, z] of seen) {
    const onFirst = Math.abs(z) < 1e-3 && x > -1e-3 && x < 30 + 1e-3;
    const onSecond = Math.abs(x - 30) < 1e-3 && z > -1e-3 && z < 40 + 1e-3;
    expect(onFirst || onSecond, `${x}, ${z}`).toBe(true);
  }
  expect(seen[10]).toEqual([expect.closeTo(10, 1), expect.closeTo(0, 3)]); // 10 s at 1 m/s
  expect(seen[45]).toEqual([expect.closeTo(30, 3), expect.closeTo(15, 1)]);
  expect(walking(path)).toBe(true);
  advance(path, 11);
  expect(walking(path)).toBe(false); // 71 s: at the end, and it stays there
  advance(path, 30);
  expect(local(pointAt(path, spot))).toEqual([
    expect.closeTo(30, 2),
    expect.closeTo(40, 2),
  ]);
});

test('a frame that walks round the corner passes it: the corners walked between two moments', () => {
  const path = walkPath(L, L_TIMES, R);
  const corners = (from: number, to: number) =>
    passedBetween(path, from, to).map((unit) =>
      local(unit).map((metres) => Math.round(metres)),
    );
  expect(corners(10, 50)).toEqual([[30, 0]]); // round the corner
  expect(corners(0, 30)).toEqual([]); // up to it: the body is there, not past it
  expect(corners(30, 70)).toEqual([]); // from it on to the end
  expect(corners(-1, 71)).toEqual([
    [0, 0],
    [30, 0],
    [30, 40],
  ]);
  expect(corners(50, 50)).toEqual([]); // standing
});

test('the ground speed is the leg being walked: slower where the times say so, 0 once there', () => {
  // grass then forest: 30 m in 20 s (1.5 m/s), then 40 m in 40 s (1 m/s)
  const path = walkPath(L, [0, 20, 60], R);
  advance(path, 10);
  expect(groundSpeed(path)).toBeCloseTo(1.5, 2);
  expect(local(pointAt(path, new Vector3()))[0]).toBeCloseTo(15, 1);
  advance(path, 20); // 30 s: 10 s into the second leg
  expect(groundSpeed(path)).toBeCloseTo(1, 2);
  expect(local(pointAt(path, new Vector3()))[1]).toBeCloseTo(10, 1);
  advance(path, 30);
  expect(groundSpeed(path)).toBe(0);
  expect(groundSpeed(walkPath([at(0, 0)], [0], R))).toBe(0);
});

test('the heading is the leg being walked', () => {
  const path = walkPath(L, L_TIMES, R);
  const going = new Vector3();
  advance(path, 10);
  const east = headingAt(path, going)!.normalize();
  expect(east.x).toBeGreaterThan(0.99);
  advance(path, 27); // 37 s: on the second leg
  const north = headingAt(path, going)!.normalize();
  expect(north.y).toBeGreaterThan(0.99);
  expect(headingAt(walkPath([at(0, 0)], [0], R), going)).toBeNull();
});

test('a new tick joins the path where the walker is drawn, without stepping back', () => {
  // drawn 2 m into the second leg: carry on from there (the second leg takes 40 s for 40 m)
  const ahead = walkPath(L, L_TIMES, R);
  const off = joinAt(ahead, new Vector3(...at(30, 2)), R);
  expect(off).toBeLessThan(1e-3);
  expect(ahead.time).toBeCloseTo(32, 1);
  // drawn a little behind the path's start: start there, the offset closes the gap
  const behind = walkPath(L, L_TIMES, R);
  expect(joinAt(behind, new Vector3(...at(-1.5, 0)), R)).toBeCloseTo(1.5, 2);
  expect(behind.time).toBe(0);
  // drawn beside the route: the nearest spot on it
  const beside = walkPath(L, L_TIMES, R);
  expect(joinAt(beside, new Vector3(...at(12, 0.5)), R)).toBeCloseTo(0.5, 2);
  expect(beside.time).toBeCloseTo(12, 1);
});

const position = { unit: at(5, 5) as [number, number, number] };
const route = (times: (number | null)[]) =>
  L.map((unit, k) => ({
    unit: unit as [number, number, number],
    height_m: 8,
    t_s: times[k],
  }));

test('a mover walks the feed route by its times, else stands where the feed says', () => {
  const walker = citizenPath(
    { position, route: route([0, 21.6, 60]), speed_mps: 1.389 },
    R,
  );
  expect(walker.points).toHaveLength(3);
  expect(walker.times).toEqual([0, 21.6, 60]);
  advance(walker, 60); // a tick later: at the step's end, where the next tick's route starts
  expect(local(pointAt(walker, new Vector3()))).toEqual([
    expect.closeTo(30, 2),
    expect.closeTo(40, 2),
  ]);
  const stander = citizenPath({ position, route: [], speed_mps: 0 }, R);
  expect(stander.points).toHaveLength(1);
  expect(local(pointAt(stander, new Vector3()))).toEqual([
    expect.closeTo(5, 3),
    expect.closeTo(5, 3),
  ]);
  advance(stander, 60);
  expect(walking(stander)).toBe(false);
  expect(local(pointAt(stander, new Vector3()))[0]).toBeCloseTo(5, 3);
});

test('a route recorded before routes were timed is walked at its speed', () => {
  const old = citizenPath(
    { position, route: route([null, null, null]), speed_mps: 2 },
    R,
  );
  expect(old.times.map((t) => Math.round(t * 10) / 10)).toEqual([0, 15, 35]);
  advance(old, 20);
  expect(groundSpeed(old)).toBeCloseTo(2, 2);
});

test('only a walker drawn far off its new path resyncs, farther at faster clocks', () => {
  expect(snapMetres(0, 1)).toBe(30); // standing: anything past 30 m is a resync
  expect(snapMetres(1.4, 1)).toBe(30);
  expect(snapMetres(1.4, 10)).toBe(35); // 2.5 s of drawn walking at ×10
  expect(snapMetres(1.4, 600)).toBeCloseTo(2100, 6);
});
