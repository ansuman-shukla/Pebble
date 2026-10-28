import { expect, type Locator, type Page, test } from '@playwright/test';
import { Quaternion, Vector3 } from 'three';

import {
  buildTerrain,
  cellDirection,
  decodeWorld,
  tangentFrame,
  WATER_BIOMES,
} from '../../src/lib/world/globe';
import { createMockWorld } from '../../src/lib/world/mock-world';
import { atParam, directionOf, openGlobe, sample } from './globe-helpers';

/*
 * A player who stands still in the follow view stands calmly: the avatar keeps its spot and its facing, plays
 * Idle, and its feet stay planted (Polyfork's Idle played on the spot pinned the hips while the legs kept the
 * captured weight shift, so the feet slid ~18 cm from side to side). On /?mock=1, at the town spawn and on a slope.
 * From the first frame on, too: a frame that came before the player was set on the ground eased it up the slope as
 * if it walked, and that speed played Walk for a moment (#19).
 */

const view = createMockWorld();
const terrain = buildTerrain(decodeWorld(view));
const R = view.radius_m;
const STAND = 3_000;
/** The Idle's own foot motion with planted feet stays near 1 cm; the pinned hips slid them 5-18 cm in 3 s. */
const FOOT_DRIFT = 0.025;

/** Rise per metre of the terrain across 6 m around a direction (the steeper of east-west and north-south). */
function slopeAt(direction: Vector3) {
  const { east, north } = tangentFrame(direction);
  const at = (dx: number, dz: number) =>
    terrain.heightAt(
      direction
        .clone()
        .multiplyScalar(R)
        .addScaledVector(east, dx)
        .addScaledVector(north, dz),
    );
  return (
    Math.max(Math.abs(at(3, 0) - at(-3, 0)), Math.abs(at(0, 3) - at(0, -3))) / 6
  );
}

/** A dry 20-35° slope in the wild near the town, facing across it. */
function slope() {
  const town = new Vector3(...view.sites[0].anchor.position);
  const { globe } = terrain;
  const direction = new Vector3();
  for (let cell = 0; cell < globe.cellCount; cell++) {
    if (WATER_BIOMES.has(globe.biomes[cell]) || globe.heights[cell] < 2)
      continue;
    cellDirection(globe, cell, direction);
    const distance = direction.angleTo(town) * R;
    if (distance < 400 || distance > 3000) continue;
    const grade = slopeAt(direction);
    if (grade > 0.36 && grade < 0.7)
      return atParam(direction, tangentFrame(direction).east);
  }
  throw new Error('no slope near the town');
}

interface Pose {
  position: Vector3;
  quaternion: Quaternion;
  clip: string | null;
  feet: Vector3[];
}

async function pose(world: Locator): Promise<Pose> {
  const [avatar, clip, feet] = await Promise.all(
    ['avatar', 'avatar-clip', 'avatar-feet'].map((name) =>
      world.getAttribute(`data-${name}`),
    ),
  );
  const [x, y, z, qx, qy, qz, qw] = (avatar ?? '').split(',').map(Number);
  const f = (feet ?? '').split(',').map(Number);
  return {
    position: new Vector3(x, y, z),
    // rounded to 4 decimals: unnormalized, two copies of one rotation would differ by ~1°
    quaternion: new Quaternion(qx, qy, qz, qw).normalize(),
    clip,
    feet: [new Vector3(f[0], f[1], f[2]), new Vector3(f[3], f[4], f[5])],
  };
}

/**
 * Records every avatar pose and clip the page reports from its first frame, as the world element's attributes
 * change (a string: the tests' TypeScript has no DOM types).
 */
const RECORD_AVATAR = `
  const reported = (window.reportedAvatar = []);
  new MutationObserver((records) => {
    for (const { target } of records)
      reported.push([target.getAttribute('data-avatar') ?? '', target.getAttribute('data-avatar-clip')]);
  }).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-avatar', 'data-avatar-clip'] });
`;

interface RecordingWindow {
  reportedAvatar: [string, string | null][];
}

/** Lets the player stand for STAND ms in the follow view and checks it stood calmly, since its first frame. */
async function standsCalmly(page: Page, world: Locator) {
  await expect(world).toHaveAttribute('data-camera-mode', 'follow');
  await expect(world).toHaveAttribute('data-camera-flying', 'false');
  await expect(world).toHaveAttribute('data-avatar-clip', 'Idle');
  const poses: Pose[] = [];
  for (let elapsed = 0; elapsed < STAND; elapsed += 100) {
    poses.push(await pose(world));
    await page.waitForTimeout(100);
  }
  const [first] = poses;
  const moved = Math.max(
    ...poses.map(({ position }) => position.distanceTo(first.position)),
  );
  const turned = Math.max(
    ...poses.map(({ quaternion }) => quaternion.angleTo(first.quaternion)),
  );
  const slid = Math.max(
    ...poses.flatMap(({ feet }) =>
      feet.map((foot, side) =>
        Math.hypot(foot.x - first.feet[side].x, foot.z - first.feet[side].z),
      ),
    ),
  );
  expect(poses.length).toBeGreaterThan(20);
  expect(new Set(poses.map(({ clip }) => clip))).toEqual(new Set(['Idle']));
  expect(moved).toBeLessThan(0.01);
  expect((turned * 180) / Math.PI).toBeLessThan(0.5);
  expect(slid).toBeLessThan(FOOT_DRIFT);

  const reported = await page.evaluate(
    () => (globalThis as unknown as RecordingWindow).reportedAvatar,
  );
  const since = reported.map(([avatar]) => {
    const [x, y, z] = avatar.split(',').map(Number);
    return new Vector3(x, y, z).distanceTo(first.position);
  });
  expect(reported.length).toBeGreaterThan(0); // the DOM changes only when the pose does
  expect(Math.max(...since)).toBeLessThan(0.01);
  expect(
    new Set(reported.flatMap(([, clip]) => (clip === null ? [] : [clip]))),
  ).toEqual(new Set(['Idle']));
}

test.describe.configure({ timeout: 120_000 });

test('the player stands still at the town spawn with planted feet', async ({
  page,
}) => {
  const errors: string[] = [];
  await page.addInitScript({ content: RECORD_AVATAR });
  const world = await openGlobe(page, errors, '?mock=1');
  expect((await sample(world)).site).toBe('town');
  await standsCalmly(page, world);
  expect(errors).toEqual([]);
});

test('the player stands still on a slope with planted feet', async ({
  page,
}) => {
  const errors: string[] = [];
  await page.addInitScript({ content: RECORD_AVATAR });
  const world = await openGlobe(page, errors, `?mock=1&at=${slope()}`);
  expect(slopeAt(directionOf(await sample(world)))).toBeGreaterThan(0.3);
  await standsCalmly(page, world);
  expect(errors).toEqual([]);
});
