import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  advance,
  citizenPath,
  headingAt,
  joinAt,
  pathLength,
  pointAt,
  walking,
  walkPath,
} from '../../src/lib/live/walk-path';

/* Walking a streamed route between ticks (no browser): along the corners, at the feed's speed, joined smoothly. */

const R = 2000;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number) =>
  new Vector3(x / R, z / R, 1).normalize().toArray();
/** Metres east / north of the chart's centre of a direction. */
const local = (unit: Vector3) => {
  const flat = unit.clone().divideScalar(unit.z);
  return [flat.x * R, flat.y * R];
};

// an L around a building corner: 30 m east, then 40 m north
const L = [at(0, 0), at(30, 0), at(30, 40)];

test('a walker moves along the route at its speed, round the corner, and stops at the end', () => {
  const path = walkPath(L, 1, R);
  expect(pathLength(path)).toBeCloseTo(70, 1);
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

test('the heading is the leg being walked', () => {
  const path = walkPath(L, 1.5, R);
  const going = new Vector3();
  advance(path, 10);
  const east = headingAt(path, going)!.normalize();
  expect(east.x).toBeGreaterThan(0.99);
  advance(path, 15); // 37.5 m: on the second leg
  const north = headingAt(path, going)!.normalize();
  expect(north.y).toBeGreaterThan(0.99);
  expect(headingAt(walkPath([at(0, 0)], 0, R), going)).toBeNull();
});

test('a new tick joins the path where the walker is drawn, without stepping back', () => {
  // drawn 2 m into the second leg (the engine is 1 m behind): carry on from there
  const ahead = walkPath(L, 1.5, R);
  const off = joinAt(ahead, new Vector3(...at(30, 2)), R);
  expect(off).toBeLessThan(1e-3);
  expect(ahead.along).toBeCloseTo(32, 1);
  // drawn a little behind the engine's spot: start there, the offset closes the gap
  const behind = walkPath(L, 1.5, R);
  expect(joinAt(behind, new Vector3(...at(-1.5, 0)), R)).toBeCloseTo(1.5, 2);
  expect(behind.along).toBe(0);
  // drawn beside the route: the nearest spot on it
  const beside = walkPath(L, 1.5, R);
  expect(joinAt(beside, new Vector3(...at(12, 0.5)), R)).toBeCloseTo(0.5, 2);
  expect(beside.along).toBeCloseTo(12, 1);
});

test('a citizen walks the feed route while walking on, else stands where the feed says', () => {
  const position = { unit: at(5, 5) as [number, number, number] };
  const route = L.map((unit) => ({
    unit: unit as [number, number, number],
    height_m: 8,
  }));
  const walker = citizenPath({ position, route, speed_mps: 1.2 }, R);
  expect(walker.points).toHaveLength(3);
  expect(walker.speed).toBe(1.2);
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
