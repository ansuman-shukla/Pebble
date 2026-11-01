import { expect, test } from '@playwright/test';

import {
  DODGE_ARM,
  dodgeFor,
} from '../../src/components/world/globe/camera-dodge';

/* The follow camera round a citizen swings to the nearest clear boom (no browser). */

const WANTED = 0.35;

test('a clear wanted boom is kept as it is', () => {
  const asked: number[][] = [];
  const swing = dodgeFor(WANTED, DODGE_ARM, (yaw, pitch) => {
    asked.push([yaw, pitch]);
    return 6;
  });
  expect(swing).toEqual({ yaw: 0, pitch: 0 });
  expect(asked).toEqual([[0, WANTED]]);
});

test('a boom cut short turns round to the nearest clear side before it looks from above', () => {
  // an awning over the wanted side and both quarters next to it: clear from 1 rad round, and from overhead
  const reach = (yaw: number, pitch: number) =>
    Math.abs(yaw) >= 1 || pitch > 1.4 ? 6 : 0.4;
  expect(dodgeFor(WANTED, DODGE_ARM, reach)).toEqual({ yaw: 1, pitch: 0 });
});

test('a small change of pitch wins over a big turn: under the awning beats round the back', () => {
  const reach = (yaw: number, pitch: number) =>
    pitch < 0.1 || Math.abs(yaw) > 3 ? 6 : 0.4;
  const swing = dodgeFor(WANTED, DODGE_ARM, reach);
  expect(swing.yaw).toBe(0);
  expect(swing.pitch).toBeCloseTo(0.05 - WANTED, 9);
});

test('with nothing clear enough it takes the longest boom there is', () => {
  const reach = (yaw: number, pitch: number) =>
    yaw === -2.2 && pitch === 0.75 ? 2 : 0.5;
  const swing = dodgeFor(WANTED, DODGE_ARM, reach);
  expect(swing.yaw).toBe(-2.2);
  expect(swing.pitch).toBeCloseTo(0.75 - WANTED, 9);
});
