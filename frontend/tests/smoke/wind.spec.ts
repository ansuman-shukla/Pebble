import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import { PROPS } from '../../src/lib/world/assets';
import {
  CLOTH_WAVE_M,
  clothWeights,
  setWind,
  SWAY_M,
  swayOf,
  windAt,
  windChunk,
  windOffset,
  windUniforms,
} from '../../src/lib/world/wind';

/* The wind of the day, the sway of plants and the wave of banners (no browser; `windOffset` is the shader's formula). */

const across = new Vector3(1, 0, 0);
/** The largest offset of `point` over a few seconds of wind at full strength. */
function biggest(
  point: Vector3,
  profile: Parameters<typeof windOffset>[1],
  cloth = 0,
  strength = 1,
) {
  let most = 0;
  for (let time = 0; time < 12; time += 0.05)
    most = Math.max(
      most,
      windOffset(
        point,
        profile,
        { time, strength, across, phase: 0.3 },
        cloth,
      ).length(),
    );
  return most;
}

test('plants sway by kind as much as the bible says, banners and buildings not', () => {
  expect(SWAY_M).toEqual({ tree: 0.15, bamboo: 0.25, crop: 0.08, grass: 0.05 });
  expect(swayOf(PROPS.cherry_tree)).toBe('tree');
  expect(swayOf(PROPS.sculpted_pine)).toBe('tree');
  expect(swayOf(PROPS.bamboo)).toBe('bamboo');
  expect(swayOf(PROPS.rice_paddy)).toBe('crop');
  expect(swayOf(PROPS.reed_bed)).toBe('crop');
  expect(swayOf(PROPS.grass_tuft)).toBe('grass');
  expect(swayOf(PROPS.banner)).toBeUndefined();
  expect(swayOf(PROPS.townhouse)).toBeUndefined();
  expect(swayOf(PROPS.water_wheel)).toBeUndefined();
});

test("a plant's foot stays put and its top leans up to its sway, downwind", () => {
  const tree = { sway: SWAY_M.tree, height: 7 };
  expect(biggest(new Vector3(0.3, 0, 0.2), tree)).toBe(0);
  const top = biggest(new Vector3(0, 7, 0), tree);
  expect(top).toBeGreaterThan(0.149);
  expect(top).toBeLessThanOrEqual(0.15);
  // half way up it leans a quarter as much; a weaker wind leans it less
  expect(biggest(new Vector3(0, 3.5, 0), tree)).toBeCloseTo(top / 4, 3);
  expect(biggest(new Vector3(0, 7, 0), tree, 0, 0.5)).toBeCloseTo(top / 2, 3);
  const offset = windOffset(new Vector3(0, 7, 0), tree, {
    time: 1,
    strength: 1,
    across,
    phase: 0,
  });
  expect(offset.y).toBe(0);
  expect(offset.x).toBeGreaterThanOrEqual(0);
});

test('a banner waves at its free edge, not at the pole, and keeps waving in a calm', () => {
  // the nobori's cloth: x from the pole (-0.04) out to 0.66, thin in z, 1.15-3.12 m up
  const positions = [
    [-0.04, 1.15, 0.06],
    [-0.04, 3.12, -0.05],
    [0.31, 2, 0],
    [0.66, 1.15, -0.05],
    [0.66, 3.12, 0.06],
  ].flat();
  const { weights, normal } = clothWeights(positions);
  expect([...weights].map((weight) => +weight.toFixed(3))).toEqual([
    0, 0, 0.5, 1, 1,
  ]);
  expect(normal.toArray()).toEqual([0, 0, 1]);
  const banner = { sway: 0, height: 3.2, clothNormal: normal };
  const edge = new Vector3(0.66, 2, 0);
  expect(biggest(new Vector3(-0.04, 2, 0), banner, 0)).toBe(0);
  expect(biggest(edge, banner, 1)).toBeCloseTo(CLOTH_WAVE_M, 3);
  expect(biggest(edge, banner, 1, 0)).toBeCloseTo(0.35 * CLOTH_WAVE_M, 3);
  // the wave runs along the cloth: the free edge and the middle are out of step
  const at = (point: Vector3, cloth: number) =>
    windOffset(point, banner, { time: 2, strength: 1, across, phase: 0 }, cloth)
      .z;
  expect(at(edge, 1)).not.toBeCloseTo(2 * at(new Vector3(0.31, 2, 0), 0.5), 2);
});

test('the wind turns and changes strength over the day, the same for everyone', () => {
  const samples = Array.from({ length: 48 }, (_, i) => windAt(i * 30));
  for (const { strength } of samples) {
    expect(strength).toBeGreaterThanOrEqual(0.25);
    expect(strength).toBeLessThanOrEqual(1);
  }
  const strengths = samples.map(({ strength }) => strength);
  expect(Math.max(...strengths) - Math.min(...strengths)).toBeGreaterThan(0.2);
  const angles = samples.map(({ angle }) => angle);
  expect(Math.max(...angles) - Math.min(...angles)).toBeGreaterThan(0.5);
  // smooth: half a minute changes it by a hair
  expect(Math.abs(windAt(600).strength - windAt(600.5).strength)).toBeLessThan(
    0.01,
  );
  expect(windAt(777)).toEqual(windAt(777));
});

test('the wind blows across the ground where the camera is', () => {
  for (const up of [
    new Vector3(0.16, 0.62, 0.77).normalize(),
    new Vector3(0, 1, 0),
    new Vector3(1, 0, 0),
  ]) {
    setWind(500, 3, up);
    const direction = windUniforms.windDirection.value;
    expect(direction.length()).toBeCloseTo(1, 6);
    expect(direction.dot(up)).toBeCloseTo(0, 6);
  }
  setWind(500, 3);
  expect(windUniforms.windDirection.value.y).toBe(0);
  expect(windUniforms.windStrength.value).toBe(windAt(500).strength);
  expect(windUniforms.windTime.value).toBe(3);
});

test('the shader chunk carries the shared sky and the model profile', () => {
  const tree = windChunk({ sway: 0.15, height: 7 });
  expect(tree.key).toBe('wind');
  expect(tree.uniforms.windTime).toBe(windUniforms.windTime);
  expect(tree.uniforms.windSway.value).toBe(0.15);
  expect(tree.uniforms.windHeight.value).toBe(7);
  expect(tree.defines).toEqual({});
  const banner = windChunk({
    sway: 0,
    height: 3.2,
    clothNormal: new Vector3(0, 0, 1),
  });
  expect(banner.key).toBe('wind-cloth');
  expect(banner.defines).toEqual({ WIND_CLOTH: '' });
  expect(banner.uniforms.windClothWave.value).toBe(CLOTH_WAVE_M);
});
