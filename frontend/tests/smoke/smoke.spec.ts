import { expect, test } from '@playwright/test';
import {
  type DataTexture,
  Matrix4,
  type MeshLambertMaterial,
  type PointsMaterial,
  Vector3,
} from 'three';

import { propViews, propWorld } from '../../src/lib/world/prop-motion';
import {
  puffAt,
  SMOULDER,
  SmokeCloud,
  smokiness,
  sparkGlow,
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

test('a puff is born thin and narrow over the flame, thickens as it rises and spreads, and fades', () => {
  expect(puffAt(0)).toEqual({ rise: 0, size: 0.2, alpha: 0, glow: 1 });
  // thin while it is at the height of people round the fire (the first third of its rise)
  expect(puffAt(0.1).alpha).toBeLessThan(0.3);
  expect(puffAt(0.2).alpha).toBeLessThan(0.5);
  expect(puffAt(0.35).alpha).toBeCloseTo(0.65, 6);
  expect(puffAt(0.5)).toMatchObject({ rise: 0.5, size: 0.8, alpha: 0.5 });
  expect(puffAt(1).alpha).toBe(0);
  // the flame lights it from below: brightest just over the flame, gone by the top
  expect(puffAt(0.1).glow).toBeGreaterThan(0.7);
  expect(puffAt(0.5).glow).toBeLessThan(0.15);
  expect(puffAt(1).glow).toBe(0);
});

test('a spark flares up at once and dies away as it rises', () => {
  expect(sparkGlow(0)).toBe(0);
  expect(sparkGlow(0.1)).toBeCloseTo(0.9, 6);
  expect(sparkGlow(0.5)).toBeCloseTo(0.5, 6);
  expect(sparkGlow(1)).toBe(0);
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
  // round glowing sparks, each as bright as its age: a sprite bright at the centre and dark at the rim
  const glows = cloud.sparks.geometry.getAttribute('color');
  const ages = Array.from({ length: 8 }, (_, i) => glows.getX(i));
  expect(new Set(ages.map((glow) => glow.toFixed(3))).size).toBeGreaterThan(4);
  for (const glow of ages) {
    expect(glow).toBeGreaterThanOrEqual(0);
    expect(glow).toBeLessThanOrEqual(1);
  }
  const sprite = (cloud.sparks.material as PointsMaterial).map as DataTexture;
  const { data, width } = sprite.image;
  const alphaAt = (x: number, y: number) => data![(y * width + x) * 4 + 3];
  expect(alphaAt(width / 2, width / 2)).toBeGreaterThan(200);
  expect(alphaAt(0, 0)).toBe(0);
  expect(alphaAt(0, width / 2)).toBeLessThan(10);
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

  // a fire gone from the feed is forgotten: back out, it was never seen burning and doesn't smoulder
  fires.set('near', fireAt(10, true));
  cloud.frame(camera, fires);
  fires.set('near', fireAt(10, false));
  cloud.frame(camera, fires);
  expect(cloud.puffs.count).toBe(10);
  fires.delete('near');
  cloud.frame(camera, fires);
  fires.set('near', fireAt(10, false));
  cloud.frame(camera, fires);
  expect(cloud.puffs.count).toBe(0);
  cloud.dispose();
  expect([propViews.puffs, propViews.sparks]).toEqual([0, 0]);
});

test('smoke over a burning fire is lit by its flame low down and thin at the height of people round it; a cold one is unlit', () => {
  propWorld.rate = 1;
  propWorld.minutes = 600;
  const cloud = new SmokeCloud();
  const camera = new Vector3(0, 0, R + 2);
  const fires = new Map([['camp', fireAt(0, true)]]);
  const glows = () => {
    const glow = cloud.puffs.geometry.getAttribute('puffGlow');
    const alpha = cloud.puffs.geometry.getAttribute('puffAlpha');
    const matrix = new Matrix4();
    const at = new Vector3();
    return Array.from({ length: cloud.puffs.count }, (_, i) => {
      cloud.puffs.getMatrixAt(i, matrix);
      return {
        height: at.setFromMatrixPosition(matrix).z - R,
        glow: glow.getX(i),
        alpha: alpha.getX(i),
      };
    });
  };
  let seen: ReturnType<typeof glows> = [];
  // a few moments of the puffs' cycle
  for (const clip of [0, 1.3, 2.9, 4.4]) {
    propWorld.clipTime = clip;
    cloud.frame(camera, fires);
    seen = seen.concat(glows());
  }
  const low = seen.filter(({ height }) => height < 1.2);
  const high = seen.filter(({ height }) => height > 3);
  expect(low.length).toBeGreaterThan(3);
  expect(high.length).toBeGreaterThan(3);
  for (const puff of low) {
    expect(puff.glow).toBeGreaterThan(0.4);
    expect(puff.alpha).toBeLessThan(0.5);
  }
  for (const puff of high) expect(puff.glow).toBeLessThan(0.2);
  // the shader adds the flame's light to the puff's colour
  const material = cloud.puffs.material as MeshLambertMaterial;
  const shader = {
    vertexShader: '#include <common>\n#include <begin_vertex>',
    fragmentShader: '#include <common>\n#include <opaque_fragment>',
  };
  material.onBeforeCompile(shader as never, undefined as never);
  expect(shader.fragmentShader).toContain('vPuffGlow');
  expect(shader.vertexShader).toContain('attribute float puffGlow');
  // gone out, it smoulders unlit
  fires.set('camp', fireAt(0, false));
  cloud.frame(camera, fires);
  expect(glows().every(({ glow }) => glow === 0)).toBe(true);
  cloud.dispose();
});

test('the hearths smoke from their chimneys with the fires, in the same two draw calls', () => {
  propWorld.rate = 1;
  propWorld.minutes = 600;
  const cloud = new SmokeCloud();
  const camera = new Vector3(0, 0, R + 2);
  const chimneys = new Map([['forge:chimney', fireAt(20, true)]]);
  cloud.frame(camera, new Map([['camp', fireAt(0, true)]]), chimneys);
  expect(cloud.puffs.count).toBe(20);
  // the hearth cools out of the feed's sight: its chimney smoulders, then stops
  chimneys.set('forge:chimney', fireAt(20, false));
  cloud.frame(camera, new Map(), chimneys);
  expect(cloud.puffs.count).toBe(10);
  propWorld.minutes = 621;
  cloud.frame(camera, new Map(), chimneys);
  expect(cloud.puffs.count).toBe(0);
  cloud.dispose();
});
