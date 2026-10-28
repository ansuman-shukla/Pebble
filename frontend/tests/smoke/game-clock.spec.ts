import { expect, test } from '@playwright/test';

import {
  formatTime,
  localMinutes,
  parseTime,
  sunDirection,
} from '../../src/lib/world/game-clock';
import { directionFromLatLon, tangentFrame } from '../../src/lib/world/globe';

/* The client game clock: the sun circles westward, noon where it stands overhead, local time by longitude. */

const TOWN_LON = 20;

test('the sun is overhead at local noon and rises in the east', () => {
  const town = directionFromLatLon(0, TOWN_LON);
  expect(sunDirection(12 * 60, TOWN_LON).angleTo(town)).toBeCloseTo(0, 9);
  const { east } = tangentFrame(town);
  const morning = sunDirection(8 * 60, TOWN_LON);
  expect(morning.dot(east)).toBeGreaterThan(0);
  // 4 hours before noon: 60° from the zenith on the equator
  expect((morning.angleTo(town) * 180) / Math.PI).toBeCloseTo(60, 9);
  expect(sunDirection(0, TOWN_LON).dot(town)).toBeCloseTo(-1, 9);
  expect(sunDirection(36 * 60, TOWN_LON).angleTo(town)).toBeCloseTo(0, 6);
});

test('local time runs ahead to the east and matches the sun', () => {
  expect(localMinutes(8 * 60, TOWN_LON, TOWN_LON)).toBe(8 * 60);
  expect(localMinutes(8 * 60, TOWN_LON, TOWN_LON + 15)).toBe(9 * 60);
  expect(localMinutes(1 * 60, TOWN_LON, TOWN_LON - 30)).toBe(23 * 60);
  expect(localMinutes(25 * 60, TOWN_LON, TOWN_LON)).toBe(60);
  for (const lon of [-170, -45, 0, 75, 160]) {
    const minutes = 10 * 60 + 7;
    const noonThere =
      12 * 60 - (localMinutes(minutes, TOWN_LON, lon) - minutes);
    expect(
      sunDirection(noonThere, TOWN_LON).angleTo(directionFromLatLon(0, lon)),
    ).toBeCloseTo(0, 6);
  }
});

test('times parse and format as HH:MM', () => {
  expect(parseTime('21:30')).toBe(21 * 60 + 30);
  expect(parseTime('7:05')).toBe(7 * 60 + 5);
  expect(parseTime('24:00')).toBeNull();
  expect(parseTime('12:60')).toBeNull();
  expect(parseTime('noon')).toBeNull();
  expect(parseTime(null)).toBeNull();
  expect(formatTime(21 * 60 + 30.9)).toBe('21:30');
  expect(formatTime(5)).toBe('00:05');
});
