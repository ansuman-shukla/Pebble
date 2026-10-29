import { expect, test } from '@playwright/test';

import {
  clockRate,
  isTimeLapse,
  timeLapseBadge,
  VISUAL_RATE_MAX,
  visualRate,
  windRate,
} from '../../src/lib/world/visual-rate';

/* The one rate rule every animated thing reads (no browser): clips like a sped-up film up to ×10, wind up to ×3. */

const CLOCKS = [0, 1, 10, 60, 600];

test('the clock rate is the speed, or nothing while paused', () => {
  expect(clockRate(60, false)).toBe(60);
  expect(clockRate(1, false)).toBe(1);
  expect(clockRate(60, true)).toBe(0);
  expect(clockRate(-5, false)).toBe(0);
});

test('clips speed up with the clock like a film, up to ×10', () => {
  // the body moves speed × rate real metres a second; the gait, paced to the game speed, plays × the same
  expect(VISUAL_RATE_MAX).toBe(10);
  expect(CLOCKS.map(visualRate)).toEqual([0, 1, 10, 10, 10]);
  expect(visualRate(3)).toBe(3);
  expect(visualRate(-1)).toBe(0);
});

test('wind sways faster with the clock, up to ×3', () => {
  expect(CLOCKS.map(windRate)).toEqual([0, 1, 3, 3, 3]);
  expect(windRate(2)).toBe(2);
  expect(windRate(-1)).toBe(0);
});

test('only clocks past ×10 are a time-lapse, and the badge says how fast', () => {
  expect(CLOCKS.map(isTimeLapse)).toEqual([false, false, false, true, true]);
  expect(isTimeLapse(10.5)).toBe(true);
  expect(CLOCKS.map(timeLapseBadge)).toEqual([
    null,
    null,
    null,
    'time-lapse ×60',
    'time-lapse ×600',
  ]);
});
