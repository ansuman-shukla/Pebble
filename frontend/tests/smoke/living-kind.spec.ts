import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import { type AnimationClip, Matrix4, type Object3D, Vector3 } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import { kindModel } from '../../src/components/world/kind-parts';
import { LivingKind } from '../../src/components/world/living-kind';
import type { TownPlacement } from '../../src/lib/client/types.gen';
import { PROPS } from '../../src/lib/world/assets';
import { FLAT_MAPPING } from '../../src/lib/world/local-mapping';
import {
  advanceProps,
  dressPart,
  propViews,
  propWorld,
} from '../../src/lib/world/prop-motion';

/*
 * Placements of one kind living (no browser, real GLBs on the flat town mapping): loops play for the nearest
 * instances within the budget and the mill wheel always, doors swing for people passing, cold fires and turned-off
 * dressing hide their parts.
 */

const ROOT = path.resolve(import.meta.dirname, '../..');

async function load(id: string) {
  const file = readFileSync(
    path.join(ROOT, 'public/assets/polyfork', id, `${id}.glb`),
  );
  const gltf = await new Promise<{
    scene: Object3D;
    animations: AnimationClip[];
  }>((resolve, reject) =>
    new GLTFLoader().parse(
      file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength),
      '',
      resolve,
      reject,
    ),
  );
  return kindModel(gltf.scene, id, gltf.animations);
}

const placement = (
  id: string,
  kind: string,
  x: number,
  z: number,
): TownPlacement => ({
  id,
  kind,
  x,
  z,
  rotation_deg: 0,
  footprint: { x: 1, z: 1 },
  walk: 'solid',
});

async function living(
  kind: keyof typeof PROPS,
  spots: [string, number, number][],
) {
  const placements = spots.map(([id, x, z]) => placement(id, kind, x, z));
  const placed = placements.map((spot) =>
    FLAT_MAPPING.matrix(spot.x, 0, spot.z, 0, new Matrix4()),
  );
  return new LivingKind(
    `test-${kind}`,
    kind,
    await load(PROPS[kind]),
    placements,
    placed,
  );
}

/** Runs frames of 1/30 s from `start` for `seconds`, with the camera at `camera`. */
let clock = 0;
function run(kinds: LivingKind[], seconds: number, camera = new Vector3()) {
  for (let t = 0; t < seconds; t += 1 / 30) {
    clock += 1 / 30;
    advanceProps(clock);
    for (const kind of kinds) kind.frame(camera, clock, 1 / 30);
  }
}

const isRest = (matrix: Matrix4) => matrix.equals(new Matrix4());
const isHidden = (matrix: Matrix4) =>
  matrix.elements.every((value, i) => (i === 15 ? value === 1 : value === 0));

test.beforeEach(() => {
  propWorld.rate = 1;
  propWorld.people = new Map();
  propWorld.fires = new Map();
  propWorld.dressing = new Map();
});

test('a door swings open for someone walking in and shuts after; standing still at it keeps it shut', async () => {
  const houses = await living('townhouse', [
    ['house-a', 0, 0],
    ['house-b', 20, 0],
  ]);
  const walker = new Vector3(0, 0, 6);
  const idler = new Vector3(20, 0, 2);
  propWorld.people = new Map([
    ['walker', walker],
    ['idler', idler],
  ]);
  run([houses], 0.5);
  // the walker heads for house-a's door (z 1.15); the idler stands in front of house-b's
  for (let step = 0; step < 60; step++) {
    walker.z -= 0.05;
    run([houses], 1 / 30);
  }
  expect([...propViews.openDoors]).toContain('house-a');
  run([houses], 1);
  expect(propViews.openDoors.has('house-a')).toBe(true);
  expect(propViews.openDoors.has('house-b')).toBe(false);
  const [moves] = houses.moves;
  const leaf = moves.get(0, 0, new Matrix4());
  expect(isRest(leaf)).toBe(false);
  expect(isRest(moves.get(1, 0, new Matrix4()))).toBe(true);
  // they go in and stand inside: the door shuts behind them
  walker.z = 0;
  run([houses], 2.5);
  expect(propViews.openDoors.has('house-a')).toBe(false);
  expect(isRest(moves.get(0, 0, new Matrix4()))).toBe(true);
  houses.dispose();
});

test('a paused clock holds a door where it is', async () => {
  const houses = await living('townhouse', [['house-c', 0, 0]]);
  const walker = new Vector3(0, 0, 3);
  propWorld.people = new Map([['walker', walker]]);
  run([houses], 0.3);
  propWorld.rate = 0;
  walker.z = 2;
  run([houses], 1);
  expect(propViews.openDoors.has('house-c')).toBe(false);
  propWorld.rate = 1;
  run([houses], 0.3);
  expect(propViews.openDoors.has('house-c')).toBe(true);
  houses.dispose();
});

test("a cold fire's fuel hides and shows again when it is lit; turned-off dressing hides", async () => {
  const baskets = await living('fire_basket', [
    ['gate-w', 0, 0],
    ['gate-e', 9, 0],
  ]);
  const fire = { lit: false, position: new Vector3(0, 1, 0) };
  propWorld.fires = new Map([['gate-w', fire]]);
  run([baskets], 0.5);
  const [moves] = baskets.moves;
  expect(isHidden(moves.get(0, 0, new Matrix4()))).toBe(true);
  // no fire known at the other basket: as authored
  expect(isRest(moves.get(1, 0, new Matrix4()))).toBe(true);
  expect(propViews.hidden.has('gate-w:fuel')).toBe(true);
  fire.lit = true;
  run([baskets], 0.5);
  expect(isRest(moves.get(0, 0, new Matrix4()))).toBe(true);
  expect(propViews.hidden.has('gate-w:fuel')).toBe(false);
  baskets.dispose();

  const stalls = await living('market_stall', [['stall', 0, 0]]);
  run([stalls], 0.5);
  expect(isRest(stalls.moves[0].get(0, 0, new Matrix4()))).toBe(true);
  dressPart('stall', 'crates', false);
  run([stalls], 0.5);
  expect(isHidden(stalls.moves[0].get(0, 0, new Matrix4()))).toBe(true);
  dressPart('stall', 'crates', true);
  run([stalls], 0.5);
  expect(isRest(stalls.moves[0].get(0, 0, new Matrix4()))).toBe(true);
  stalls.dispose();
});

test('loops play for the nearest 64 within 120 m; the mill wheel turns wherever the camera is', async () => {
  const fence = await living(
    'bamboo_fence',
    Array.from({ length: 90 }, (_, i): [string, number, number] => [
      `fence-${i}`,
      i * 2,
      0,
    ]),
  );
  const wheel = await living('water_wheel', [['wheel', 5000, 0]]);
  run([fence, wheel], 0.5);
  const playing = (key: string) => propViews.playing.get(key)?.count;
  // posts 0-59 are within 120 m of the camera at the origin, and all fit the budget
  expect(playing('test-bamboo_fence')).toBe(60);
  expect(playing('test-water_wheel')).toBe(1);
  const angle = () => propViews.turns.get('wheel')!;
  const before = angle();
  run([fence, wheel], 0.5);
  expect(angle()).not.toBeCloseTo(before, 3);
  // moved to the middle of the fence: 64 of its posts play, the nearest
  run([fence, wheel], 0.5, new Vector3(90, 0, 0));
  expect(playing('test-bamboo_fence')).toBe(64);
  expect(propViews.turns.has('fence-45')).toBe(true);
  expect(propViews.turns.has('fence-0')).toBe(false);
  expect(isRest(fence.moves[0].get(45, 0, new Matrix4()))).toBe(false);
  fence.dispose();
  wheel.dispose();
  expect(propViews.playing.has('test-bamboo_fence')).toBe(false);
});
