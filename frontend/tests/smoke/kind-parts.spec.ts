import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import {
  type AnimationClip,
  type BufferGeometry,
  type Material,
  Matrix4,
  type Mesh,
  type Object3D,
  Vector3,
} from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import { kindModel, movingLooks } from '../../src/components/world/kind-parts';
import { PROPS } from '../../src/lib/world/assets';
import { leafMove } from '../../src/lib/world/doors';
import {
  isProcedural,
  proceduralScene,
} from '../../src/lib/world/procedural-props';
import { PartMoves, sampleClip } from '../../src/lib/world/prop-motion';

/*
 * Kind models from the real vendored GLBs (no browser): one part per material (a model draws in one call), the
 * parts that move kept addressable by `partIndex`, the loop baked, doors and fires found by their node names.
 */

const ROOT = path.resolve(import.meta.dirname, '../..');

interface Gltf {
  scene: Object3D;
  animations: AnimationClip[];
}

const loaded = new Map<string, Promise<Gltf>>();

function load(id: string): Promise<Gltf> {
  if (isProcedural(id))
    return Promise.resolve({ scene: proceduralScene(id), animations: [] });
  let gltf = loaded.get(id);
  if (!gltf) {
    const file = readFileSync(
      path.join(ROOT, 'public/assets/polyfork', id, `${id}.glb`),
    );
    const data = file.buffer.slice(
      file.byteOffset,
      file.byteOffset + file.byteLength,
    );
    gltf = new Promise((resolve, reject) =>
      new GLTFLoader().parse(data, '', resolve, reject),
    );
    loaded.set(id, gltf);
  }
  return gltf;
}

async function model(id: string, moving = true) {
  const { scene, animations } = await load(id);
  return kindModel(scene, id, moving ? animations : []);
}

/** The model's sub-meshes and their materials, as the GLB has them. */
async function subMeshes(id: string) {
  const meshes: Mesh[] = [];
  (await load(id)).scene.traverse((object) => {
    if ((object as Mesh).isMesh) meshes.push(object as Mesh);
  });
  return meshes;
}

/** The partIndex values the geometry's vertices carry, counted. */
function partIndices(geometry: BufferGeometry) {
  const counts = new Map<number, number>();
  const attribute = geometry.getAttribute('partIndex');
  for (let i = 0; i < attribute.count; i++)
    counts.set(attribute.getX(i), (counts.get(attribute.getX(i)) ?? 0) + 1);
  return counts;
}

const cacheKey = (material: Material) => material.customProgramCacheKey();

// the forge's fire has an image texture, which the loader can't decode outside a browser
const TEXTURED = new Set([PROPS.forge]);

test('every model draws in one call per material, however many sub-meshes it has', async () => {
  test.setTimeout(60_000);
  let subMeshCount = 0;
  let partCount = 0;
  for (const id of new Set(Object.values(PROPS))) {
    if (TEXTURED.has(id)) continue;
    const meshes = await subMeshes(id);
    const materials = new Set(meshes.map((mesh) => mesh.material));
    const { parts } = await model(id);
    expect(parts.length, id).toBe(materials.size);
    subMeshCount += meshes.length;
    partCount += parts.length;
  }
  expect(partCount).toBeLessThan(subMeshCount * 0.6);
});

test('the mill wheel turns: its loop moves the wheel and nothing else', async () => {
  const wheel = await model(PROPS.water_wheel);
  expect(wheel.parts).toHaveLength(1);
  const [part] = wheel.parts;
  expect(part.moving).toEqual([{ node: 'wheel', clip: 0 }]);
  expect(wheel.clip!.duration).toBeCloseTo(9, 5);
  const [frame, rim] = await subMeshes(PROPS.water_wheel);
  expect(partIndices(part.geometry)).toEqual(
    new Map([
      [0, frame.geometry.attributes.position.count],
      [1, rim.geometry.attributes.position.count],
    ]),
  );
  // a rigid turn about its hub (the `wheel` node, about 2 m up): 40° a second (a turn in 9 s)
  const { scene } = await load(PROPS.water_wheel);
  scene.updateMatrixWorld(true);
  const hub = scene.getObjectByName('wheel')!.getWorldPosition(new Vector3());
  const rimPoint = hub.clone().add(new Vector3(0, 1.4, 0));
  const at = (time: number) =>
    rimPoint
      .clone()
      .applyMatrix4(sampleClip(wheel.clip!, 0, time, new Matrix4()));
  const radius = at(0).distanceTo(hub);
  expect(radius).toBeCloseTo(1.4, 6);
  for (const time of [0, 3.3, 7.1]) {
    expect(at(time).distanceTo(hub)).toBeCloseTo(radius, 3);
    expect(at(time).distanceTo(at(time + 1))).toBeCloseTo(
      2 * radius * Math.sin(Math.PI / 9),
      2,
    );
  }
  // drawn still (no animations: the wild scatter), the wheel merges with the frame
  const still = await model(PROPS.water_wheel, false);
  expect(still.parts[0].moving).toEqual([]);
  expect(still.parts[0].geometry.getAttribute('partIndex')).toBeUndefined();
  expect(still.clip).toBeNull();
});

test("a tree's crown parts loop inside its one part and it sways in the wind", async () => {
  const pine = await model(PROPS.sculpted_pine);
  expect(pine.parts).toHaveLength(1);
  expect(pine.parts[0].moving.map(({ node }) => node)).toEqual(
    ['a', 'b', 'c', 'd', 'e', 'f'].map((letter) => `foliage-sway-${letter}`),
  );
  expect(pine.parts[0].moving.map(({ clip }) => clip)).toEqual([
    0, 1, 2, 3, 4, 5,
  ]);
  expect(cacheKey(pine.parts[0].material)).toMatch(/-wind$/);
  expect(pine.parts[0].wind).toEqual({
    sway: 0.15,
    height: expect.any(Number),
  });
  const looks = movingLooks(pine.parts[0], new PartMoves(6, 3));
  expect(cacheKey(looks.material)).toMatch(/-part-moves-wind$/);
  expect(cacheKey(looks.depthMaterial)).toMatch(/-part-moves-wind$/);
  // a building neither sways nor loops
  const keep = await model(PROPS.castle_keep);
  expect(keep.parts[0].wind).toBeNull();
  expect(keep.parts[0].depthMaterial).toBeUndefined();
});

test('a banner merges with its pole and its cloth waves from the pole edge', async () => {
  const banner = await model(PROPS.banner);
  expect(banner.parts).toHaveLength(1);
  const [part] = banner.parts;
  expect(part.moving).toEqual([]);
  expect(part.wind?.sway).toBe(0);
  expect(part.wind?.clothNormal?.toArray()).toEqual([0, 0, 1]);
  expect(cacheKey(part.material)).toMatch(/-wind-cloth$/);
  const cloth = part.geometry.getAttribute('windCloth');
  const position = part.geometry.getAttribute('position');
  const [standard] = await subMeshes(PROPS.banner);
  let still = 0;
  let free = 0;
  for (let i = 0; i < cloth.count; i++) {
    const weight = cloth.getX(i);
    if (weight === 0) still++;
    // nothing below the cloth (the pole's foot, 0-1.1 m) waves; the fully free vertices are its far edge
    if (position.getY(i) < 1.1) expect(weight).toBe(0);
    if (weight > 0.98) {
      expect(position.getX(i)).toBeGreaterThan(0.6);
      free++;
    }
  }
  // the pole and its crossbar stay put, a cloth vertex waves (all but its pole edge)
  expect(still).toBeGreaterThanOrEqual(
    standard.geometry.attributes.position.count,
  );
  expect(still).toBeLessThan(cloth.count);
  expect(free).toBeGreaterThan(0);
});

test('house doors are found by name and swing inwards about their hinges', async () => {
  const house = await model(PROPS.townhouse);
  expect(house.parts).toHaveLength(1);
  expect(house.parts[0].moving).toEqual([
    { node: 'door-r', clip: null },
    { node: 'door-l', clip: null },
  ]);
  const doorway = house.doorway!;
  expect(doorway.centre.toArray()).toEqual([0, 0, 1.15]);
  const right = doorway.leaves.find(({ node }) => node === 'door-r')!;
  const left = doorway.leaves.find(({ node }) => node === 'door-l')!;
  // door-r hangs at x 0.65 with its free edge at x 0.02: open, the free edge has swung in (-z), the hinge stays
  const freeEdge = new Vector3(0.02, 1, 1.15);
  const open = freeEdge.clone().applyMatrix4(leafMove(right, 1, new Matrix4()));
  expect(open.z).toBeLessThan(1.15 - 0.55);
  expect(open.x).toBeGreaterThan(0.5);
  const hinge = new Vector3(0.65, 1, 1.15);
  expect(
    hinge
      .clone()
      .applyMatrix4(leafMove(right, 1, new Matrix4()))
      .distanceTo(hinge),
  ).toBeLessThan(1e-6);
  expect(left.openYaw).toBeCloseTo(-right.openYaw, 6);
  const shut = freeEdge.clone().applyMatrix4(leafMove(right, 0, new Matrix4()));
  expect(shut.distanceTo(freeEdge)).toBeLessThan(1e-6);
  // the gatehouse's leaves stand open for good: merged still, no doorway
  const gate = await model(PROPS.castle_gatehouse);
  expect(gate.doorway).toBeNull();
  expect(gate.parts[0].moving).toEqual([]);
});

test("fires' flame and fuel, the stall's crates and the chest's lid stay addressable", async () => {
  expect((await model(PROPS.fire_pit)).parts[0].moving).toEqual([
    { node: 'flame', clip: null },
  ]);
  expect((await model(PROPS.fire_basket)).parts[0].moving).toEqual([
    { node: 'fuel', clip: null },
  ]);
  expect((await model(PROPS.market_stall)).parts[0].moving).toEqual([
    { node: 'crates', clip: null },
  ]);
  expect((await model(PROPS.chest)).parts[0].moving).toEqual([
    { node: 'lid', clip: null },
  ]);
  // the reed torch's flame both loops and hides when out
  const torch = await model(PROPS.reed_torch);
  expect(torch.parts[0].moving.every(({ node }) => node === 'flame')).toBe(
    true,
  );
  expect(torch.parts[0].moving.map(({ clip }) => clip)).toEqual([0, 1, 2, 3]);
});

test('skinned plants are drawn at rest: their bones are not followed', async () => {
  const reeds = await model(PROPS.reed_bed);
  for (const part of reeds.parts) {
    expect(part.moving).toEqual([]);
    expect(part.geometry.getAttribute('skinIndex')).toBeUndefined();
  }
  expect(reeds.clip).toBeNull();
  expect(reeds.parts[0].wind?.sway).toBe(0.08);
});

test('models are built once per scene and shared', async () => {
  expect(await model(PROPS.cherry_tree)).toBe(await model(PROPS.cherry_tree));
  expect(await model(PROPS.cherry_tree, false)).not.toBe(
    await model(PROPS.cherry_tree),
  );
});

test("stage pieces carry their rank: the berry bush's 9 fruit, the taro's 11 leaves, none on an oak", async () => {
  const ranksOf = async (kind: keyof typeof PROPS) => {
    const { scene } = await load(PROPS[kind]);
    const built = kindModel(scene, PROPS[kind]);
    const ranks = new Set<number>();
    let unranked = 0;
    for (const part of built.parts) {
      const attribute = part.geometry.getAttribute('stagePiece');
      if (!attribute) continue;
      for (let i = 0; i < attribute.count; i++) {
        const rank = attribute.getX(i);
        if (rank === 0) unranked += 1;
        else ranks.add(rank);
      }
    }
    return {
      pieces: built.pieces,
      ranks: [...ranks].sort((a, b) => a - b),
      unranked,
    };
  };
  const bush = await ranksOf('berry_bush');
  expect(bush.pieces).toBe(9);
  expect(bush.ranks).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
  // the bush itself is no piece
  expect(bush.unranked).toBeGreaterThan(100);
  const taro = await ranksOf('root_patch');
  expect(taro.pieces).toBe(11);
  expect(taro.ranks).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
  expect(taro.unranked).toBeGreaterThan(0);
  const oak = await ranksOf('oak_tree');
  expect(oak).toEqual({ pieces: 0, ranks: [], unranked: 0 });
});
