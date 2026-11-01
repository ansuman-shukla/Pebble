import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import { type AnimationClip, Matrix4, type Object3D, Vector3 } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import { kindModel } from '../../src/components/world/kind-parts';
import {
  EMBERS,
  hearthHeat,
  LivingKind,
} from '../../src/components/world/living-kind';
import type { TownPlacement } from '../../src/lib/client/types.gen';
import { PROPS } from '../../src/lib/world/assets';
import { FLAT_MAPPING } from '../../src/lib/world/local-mapping';
import {
  advanceProps,
  clipPhase,
  dressPart,
  propViews,
  propWorld,
  sampleClip,
} from '../../src/lib/world/prop-motion';

/*
 * Placements of one kind living (no browser, real GLBs on the flat town mapping): loops play for the nearest
 * instances within the budget and the mill wheel always, doors swing for people passing, cold fires and turned-off
 * dressing hide their parts, the forge burns while the smith works at it and cools after.
 */

const ROOT = path.resolve(import.meta.dirname, '../..');

/**
 * A GLB without its image textures (the forge's fire has one, which the loader can't decode outside a browser): the
 * same nodes and meshes, each material in its own colours.
 */
function withoutImages(glb: Buffer): Buffer {
  const jsonLength = glb.readUInt32LE(12);
  const json = JSON.parse(glb.subarray(20, 20 + jsonLength).toString()) as {
    images?: unknown;
    textures?: unknown;
    samplers?: unknown;
    materials?: { pbrMetallicRoughness?: { baseColorTexture?: unknown } }[];
  };
  if (!json.images) return glb;
  delete json.images;
  delete json.textures;
  delete json.samplers;
  for (const material of json.materials ?? [])
    delete material.pbrMetallicRoughness?.baseColorTexture;
  let text = JSON.stringify(json);
  text += ' '.repeat((4 - (text.length % 4)) % 4);
  const chunk = Buffer.from(text);
  const header = Buffer.alloc(20);
  header.write('glTF', 0);
  header.writeUInt32LE(2, 4);
  const rest = glb.subarray(20 + jsonLength);
  header.writeUInt32LE(20 + chunk.length + rest.length, 8);
  header.writeUInt32LE(chunk.length, 12);
  header.writeUInt32LE(0x4e4f534a, 16);
  return Buffer.concat([header, chunk, rest]);
}

async function load(id: string) {
  const file = withoutImages(
    readFileSync(path.join(ROOT, 'public/assets/polyfork', id, `${id}.glb`)),
  );
  const gltf = await new Promise<{
    scene: Object3D;
    animations: AnimationClip[];
  }>((resolve, reject) =>
    new GLTFLoader().parse(new Uint8Array(file).buffer, '', resolve, reject),
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
  // the prop clock is shared by every test in this worker: start it afresh
  propWorld.elapsed = Number.NaN;
  propWorld.rate = 1;
  propWorld.people = new Map();
  propWorld.crafters = new Set();
  propWorld.fires = new Map();
  propWorld.chimneys = new Map();
  propWorld.dressing = new Map();
});

test('a door swings open for someone walking in and shuts after; standing at it or passing along the front keeps it shut', async () => {
  const houses = await living('townhouse', [
    ['house-a', 0, 0],
    ['house-b', 20, 0],
    ['house-d', 40, 0],
  ]);
  const walker = new Vector3(0, 0, 6);
  const idler = new Vector3(20, 0, 2);
  const stroller = new Vector3(36, 0, 2);
  propWorld.people = new Map([
    ['walker', walker],
    ['idler', idler],
    ['stroller', stroller],
  ]);
  run([houses], 0.5);
  // the walker heads for house-a's door (z 1.15); the idler stands in front of house-b's; the stroller walks
  // along house-d's front, across its doorway
  let strolledOpen = false;
  for (let step = 0; step < 60; step++) {
    walker.z -= 0.05;
    stroller.x += 0.13;
    run([houses], 1 / 30);
    strolledOpen ||= propViews.openDoors.has('house-d');
  }
  expect(strolledOpen).toBe(false);
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
  // one look at who passes is shared by the worker's tests: someone new, first seen standing here
  propWorld.people = new Map([['late-walker', walker]]);
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

test("a rack's sheaves sway with its loop, and stay hidden while its dressing is off", async () => {
  const racks = await living('drying_rack', [['farm-rack', 0, 0]]);
  const [moves] = racks.moves;
  run([racks], 0.5);
  expect(isRest(moves.get(0, 0, new Matrix4()))).toBe(false);
  dressPart('farm-rack', 'sheaf-row-1', false);
  run([racks], 1);
  expect(isHidden(moves.get(0, 0, new Matrix4()))).toBe(true);
  expect(isHidden(moves.get(0, 1, new Matrix4()))).toBe(false);
  dressPart('farm-rack', 'sheaf-row-1', true);
  run([racks], 0.5);
  expect(isHidden(moves.get(0, 0, new Matrix4()))).toBe(false);
  racks.dispose();
});

test('a tree crown sways on wind time (at most ×3) and the mill wheel turns on clip time (up to ×10)', async () => {
  const cherry = await living('cherry_tree', [['cherry', 0, 0]]);
  const wheel = await living('water_wheel', [['mill', 5, 0]]);
  propWorld.clipTime = 0;
  propWorld.windTime = 0;
  propWorld.rate = 60;
  run([cherry, wheel], 1);
  expect(propWorld.clipTime).toBeCloseTo(10, 3);
  expect(propWorld.windTime).toBeCloseTo(3, 3);
  /** The move the first looping sub-mesh of `kind` should have `time` seconds into its loop. */
  const expected = async (
    kind: keyof typeof PROPS,
    id: string,
    time: number,
  ) => {
    const model = await load(PROPS[kind]);
    const clip = model.clip!;
    const index = model.parts.find(({ moving }) => moving.length > 0)!.moving[0]
      .clip!;
    return sampleClip(
      clip,
      index,
      time + clipPhase(id, clip.duration),
      new Matrix4(),
    );
  };
  const close = (actual: Matrix4, wanted: Matrix4) =>
    actual.elements.forEach((value, i) =>
      expect(value).toBeCloseTo(wanted.elements[i], 4),
    );
  const crown = cherry.moves[0].get(0, 0, new Matrix4());
  expect(isRest(crown)).toBe(false);
  close(crown, await expected('cherry_tree', 'cherry', 3));
  close(
    wheel.moves[0].get(0, 0, new Matrix4()),
    await expected('water_wheel', 'mill', 10),
  );
  cherry.dispose();
  wheel.dispose();
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

test('a hearth is 1 while worked, its embers cooling to 0 over 30 game minutes; cold if never worked', () => {
  expect(EMBERS).toBe(30);
  expect(hearthHeat(600, 600)).toBe(1);
  expect(hearthHeat(600, 615)).toBeCloseTo(0.5, 6);
  expect(hearthHeat(600, 629.9)).toBeGreaterThan(0);
  expect(hearthHeat(600, 630)).toBe(0);
  expect(hearthHeat(-Infinity, 600)).toBe(0);
  // a clock gone back before the work (a replay scrubbed earlier) knows nothing of it
  expect(hearthHeat(600, 590)).toBe(0);
});

test('the forge burns while the smith crafts at its anvil, its fire dying down after, and smokes from its chimney', async () => {
  const forges = await living('forge', [['forge', 0, 0]]);
  const fire = () => {
    const slot = forges.moves.findIndex((moves) => moves.parts > 0);
    return forges.moves[slot].get(0, 0, new Matrix4());
  };
  const chimney = () => propWorld.chimneys.get('forge:chimney')!;
  const smith = new Vector3(0.8, 0, 2.8);
  propWorld.people = new Map([
    ['tetsu', smith],
    ['aiko', new Vector3(9, 0, 0)],
  ]);
  propWorld.minutes = 600;
  // nobody works it (the weaver crafts at her loom 9 m off): cold, its fire gone, no smoke
  propWorld.crafters = new Set(['aiko']);
  run([forges], 0.5);
  expect(isHidden(fire())).toBe(true);
  expect(propViews.hearths.get('forge')).toBe(0);
  expect(chimney().lit).toBe(false);
  // the smith hammers at the anvil: it burns, its fire as made, smoke from the chimney's top
  propWorld.crafters = new Set(['aiko', 'tetsu']);
  run([forges], 0.5);
  expect(isRest(fire())).toBe(true);
  expect(propViews.hearths.get('forge')).toBe(1);
  expect(chimney()).toMatchObject({ lit: true, strength: 1 });
  expect(
    chimney().position.distanceTo(new Vector3(-1.5, 3.96, -1)),
  ).toBeLessThan(0.01);
  // he stops: the embers cool, the fire shrinks about its base (still in the hearth), the smoke thins
  propWorld.crafters = new Set(['aiko']);
  propWorld.minutes += 15;
  run([forges], 0.5);
  const cooling = fire();
  expect(isRest(cooling) || isHidden(cooling)).toBe(false);
  const base = new Vector3(-1.45, 0.55, -0.45);
  expect(base.clone().applyMatrix4(cooling).distanceTo(base)).toBeLessThan(
    1e-4,
  );
  expect(new Vector3().setFromMatrixScale(cooling).x).toBeCloseTo(0.675, 1);
  expect(chimney().strength).toBeCloseTo(0.5, 1);
  // half an hour after: out
  propWorld.minutes += 16;
  run([forges], 0.5);
  expect(isHidden(fire())).toBe(true);
  expect(chimney().lit).toBe(false);
  forges.dispose();
  expect(propWorld.chimneys.has('forge:chimney')).toBe(false);
  expect(propViews.hearths.has('forge')).toBe(false);
});
