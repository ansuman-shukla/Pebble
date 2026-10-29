import { expect, test } from '@playwright/test';
import { Matrix4, Vector3 } from 'three';

import { propViews, propWorld } from '../../src/lib/world/prop-motion';
import {
  puffAt,
  SMOULDER,
  SmokeCloud,
  smokiness,
  type SmokingFire,
} from '../../src/lib/world/smoke';

/* Smoke and sparks over the live fires (no browser): who smokes, for how long, and what two draw calls carry. */

test('a burning fire smokes by its strength; a fire that went out smoulders 20 game minutes', () => {
  expect(SMOULDER).toBe(20);
  expect(smokiness(true, 1, -Infinity, 0)).toBe(1);
  expect(smokiness(true, 0, -Infinity, 0)).toBe(0.5);
  expect(smokiness(false, 0, 100, 100)).toBe(0.5);
  expect(smokiness(false, 0, 100, 110)).toBeCloseTo(0.25, 6);
  expect(smokiness(false, 0, 100, 119.9)).toBeGreaterThan(0);
  expect(smokiness(false, 0, 100, 120)).toBe(0);
  expect(smokiness(false, 0, -Infinity, 100)).toBe(0);
});

test('a puff rises, grows, fades in quickly and out slowly', () => {
  expect(puffAt(0)).toEqual({ rise: 0, size: 0.25, alpha: 0 });
  expect(puffAt(0.15).alpha).toBeCloseTo(0.85, 6);
  expect(puffAt(0.5)).toEqual({ rise: 0.5, size: 0.8, alpha: 0.5 });
  expect(puffAt(1).alpha).toBe(0);
});

const R = 2000;
const fireAt = (east: number, lit: boolean): SmokingFire => ({
  lit,
  strength: lit ? 1 : 0,
  position: new Vector3(east, 0, R),
});

test('the cloud carries every fire within 300 m in two objects, puffs drifting up from each', () => {
  propWorld.rate = 1;
  propWorld.minutes = 600;
  const cloud = new SmokeCloud();
  const camera = new Vector3(0, 0, R + 2);
  const fires = new Map([
    ['near', fireAt(10, true)],
    ['far', fireAt(400, true)],
    ['cold', fireAt(-20, false)],
  ]);
  cloud.frame(camera, fires);
  // only the near fire: the far one is beyond reach, the cold one was never seen burning
  expect(cloud.puffs.count).toBe(10);
  expect(cloud.puffs.visible).toBe(true);
  expect(cloud.sparks.geometry.drawRange.count).toBe(8);
  expect([propViews.puffs, propViews.sparks]).toEqual([10, 8]);
  const matrix = new Matrix4();
  const at = new Vector3();
  for (let i = 0; i < cloud.puffs.count; i++) {
    cloud.puffs.getMatrixAt(i, matrix);
    at.setFromMatrixPosition(matrix);
    // above the fire (up is +z here), within a few metres of it
    expect(at.z - R).toBeGreaterThan(0.3);
    expect(at.distanceTo(fires.get('near')!.position)).toBeLessThan(7);
  }

  // the near fire goes out: it smoulders (no sparks) until 20 game minutes later
  fires.set('near', fireAt(10, false));
  cloud.frame(camera, fires);
  expect(cloud.puffs.count).toBe(10);
  expect(cloud.sparks.visible).toBe(false);
  propWorld.minutes = 619;
  cloud.frame(camera, fires);
  expect(cloud.puffs.count).toBe(10);
  propWorld.minutes = 621;
  cloud.frame(camera, fires);
  expect(cloud.puffs.count).toBe(0);
  expect(cloud.puffs.visible).toBe(false);
  cloud.dispose();
  expect([propViews.puffs, propViews.sparks]).toEqual([0, 0]);
});
