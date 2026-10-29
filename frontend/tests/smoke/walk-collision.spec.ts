import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import manifest from '../../src/lib/world/asset-manifest.json' with { type: 'json' };
import { PROPS, type PropKind } from '../../src/lib/world/assets';
import {
  blocksBody,
  buildWalkWorld,
  type ColliderFile,
  isWater,
  placeParts,
  type Point,
  resolveMove,
  type Shape,
  type WalkPlacement,
  type WalkWater,
} from '../../src/lib/world/collision';
import {
  isProcedural,
  PROCEDURAL_PROPS,
} from '../../src/lib/world/procedural-props';

const ROOT = path.resolve(import.meta.dirname, '../..');
const byId = new Map(manifest.assets.map((asset) => [asset.id, asset]));

function colliders(placements: WalkPlacement[]) {
  const files = new Map<string, ColliderFile>();
  for (const { kind } of placements) {
    if (!Object.hasOwn(PROPS, kind)) continue;
    const id = PROPS[kind as PropKind];
    if (files.has(id)) continue;
    if (isProcedural(id)) {
      files.set(id, PROCEDURAL_PROPS[id].colliders);
      continue;
    }
    const file = path.join(ROOT, byId.get(id)!.files.colliders.path);
    files.set(id, JSON.parse(readFileSync(file, 'utf8')) as ColliderFile);
  }
  return files;
}

let counter = 0;
const place = (
  kind: string,
  x: number,
  z: number,
  rotation_deg: WalkPlacement['rotation_deg'] = 0,
  walk: WalkPlacement['walk'] = 'solid',
): WalkPlacement => ({ id: `p${counter++}`, kind, x, z, rotation_deg, walk });

function world(placements: WalkPlacement[], water: WalkWater[] = []) {
  return buildWalkWorld(placements, water, colliders(placements));
}

const move = (
  placements: WalkPlacement[],
  from: Point,
  to: Point,
  water: WalkWater[] = [],
) => resolveMove(world(placements, water), from, to, 0);

function expectAt([x, z]: Point, [expectedX, expectedZ]: Point) {
  expect(x).toBeCloseTo(expectedX, 6);
  expect(z).toBeCloseTo(expectedZ, 6);
}

const wall = [-2, 0, 2].map((x) => place('plaster_wall', x, 0));

test('walking straight at a wall stops at its face', () => {
  const [x, z] = move(wall, [0, 2], [0, -2]);
  // the wall coping reaches z = 0.32; the player radius is 0.3
  expect(z).toBeGreaterThan(0.6);
  expect(z).toBeLessThan(0.66);
  expect(x).toBeCloseTo(0, 5);
});

test('walking diagonally into a wall slides along it', () => {
  const [x, z] = move(wall, [0, 1], [-1.5, -1]);
  // the coping's bevelled ends catch a little at each joint between segments
  expect(x).toBeLessThan(-1.4);
  expect(z).toBeGreaterThan(0.6);
  expect(z).toBeLessThan(0.66);
});

test('the loom drawn from code blocks its 1.2 x 0.8 m frame and nothing beside it', () => {
  const loom = [place('loom', 0, 0)];
  // the frame's front reaches z = 0.4; the player radius is 0.3
  expect(move(loom, [0, 2], [0, -2])[1]).toBeCloseTo(0.7, 2);
  expectAt(move(loom, [1, 2], [1, -2]), [1, -2]);
});

test('a wall placed with rotation 90 blocks along x instead', () => {
  const turned = [place('plaster_wall', 0, 0, 90)];
  expect(move(turned, [2, 0], [-2, 0])[0]).toBeGreaterThan(0.6);
  expect(move(turned, [2, 2], [-2, 2])[0]).toBeCloseTo(-2, 5);
});

test('parts are placed with the three.js rotation.y convention', () => {
  // a model's +z (its front) turns to +x at 90 degrees, to -z at 180 and to -x at 270
  const front: [number, number, number][] = [
    [0, 0, 1],
    [0.1, 1, 1],
    [-0.1, 2, 1],
  ];
  const tip = (rotation_deg: WalkPlacement['rotation_deg']) => {
    const [shape] = placeParts(
      place('well', 10, 20, rotation_deg),
      [front],
      -1,
    );
    expect([shape.minY, shape.maxY]).toEqual([-1, 1]);
    const { minX, maxX, minZ, maxZ } = shape.box;
    return [(minX + maxX) / 2, (minZ + maxZ) / 2] as Point;
  };
  expectAt(tip(0), [10, 21]);
  expectAt(tip(90), [11, 20]);
  expectAt(tip(180), [10, 19]);
  expectAt(tip(270), [9, 20]);
});

test('the gatehouse passage is open but its pillars and flanks block', () => {
  const gate = [place('castle_gatehouse', 0, 0)];
  expectAt(move(gate, [0, 4], [0, -4]), [0, -4]);
  // the opened door leaves stand against the passage walls, so the passage stays almost 2 m wide
  expect(move(gate, [0.6, 4], [0.6, -4])[1]).toBeCloseTo(-4, 5);
  expect(move(gate, [-0.6, 4], [-0.6, -4])[1]).toBeCloseTo(-4, 5);
  // the stone flank (x 1.33..3) stops the player at the road face
  expect(move(gate, [2, 4], [2, -4])[1]).toBeGreaterThan(1.7);
  // inside the passage: a pillar (x 1.05..1.33) and an opened leaf (x 1.0..1.1) stop a sideways walk
  expect(move(gate, [0, 0.8], [2, 0.8])[0]).toBeCloseTo(0.75, 2);
  expect(move(gate, [0, 0], [2, 0])[0]).toBeCloseTo(0.7, 2);
});

test('a gatehouse turned 90 degrees has its passage along x', () => {
  const gate = [place('castle_gatehouse', 10, 5, 90)];
  expectAt(move(gate, [14, 5], [6, 5]), [6, 5]);
  expect(move(gate, [14, 7], [6, 7])[0]).toBeGreaterThan(11.7);
});

test('canopies and roofs do not block, only the trunk does', () => {
  const tree = [place('cherry_tree', 0, 0)];
  expectAt(move(tree, [1.5, 4], [1.5, -4]), [1.5, -4]);
  // the round trunk deflects the player sideways but never lets it through
  expect(move(tree, [0, 4], [0, -4])[1]).toBeGreaterThan(-1);
});

test('a part blocks only where it overlaps the body band above the ground', () => {
  const beam: Shape = {
    placementId: 'beam',
    polygon: [
      [0, 0],
      [1, 0],
      [1, 1],
    ],
    minY: 2.1,
    maxY: 2.4,
    box: { minX: 0, minZ: 0, maxX: 1, maxZ: 1 },
  };
  expect(blocksBody(beam, 0)).toBe(false);
  expect(blocksBody(beam, 1)).toBe(true);
  expect(blocksBody({ ...beam, minY: 0, maxY: 0.25 }, 0)).toBe(false);
});

const moat: WalkWater = {
  polygon: [
    [-10, -3],
    [10, -3],
    [10, 3],
    [-10, 3],
  ],
};

test('water blocks and the player slides along the bank', () => {
  const [, z] = move([], [0, 5], [0, -5], [moat]);
  expect(z).toBeGreaterThan(3);
  expect(z).toBeLessThan(3.2);
  const [x, bankZ] = move([], [0, 4], [3, 2], [moat]);
  expect(x).toBeCloseTo(3, 5);
  expect(bankZ).toBeGreaterThan(3);
});

test('a bridge footprint makes the water under it walkable', () => {
  const bridge = [place('moat_bridge', 0, 0, 90, 'surface')];
  const bridged = world(bridge, [moat]);
  expect(isWater(bridged, [0, 0])).toBe(false);
  expect(isWater(bridged, [0.8, -2.5])).toBe(false);
  expect(isWater(bridged, [1.5, 0])).toBe(true);
  expect(isWater(world([], [moat]), [0, 0])).toBe(true);
  expectAt(move(bridge, [0, 6], [0, -6], [moat]), [0, -6]);
  expect(move(bridge, [3, 6], [3, -6], [moat])[1]).toBeGreaterThan(3);
});

test('holes in the water are dry land', () => {
  const ring = {
    ...moat,
    holes: [moat.polygon.map(([x, z]) => [x / 2, z / 2] as Point)],
  };
  expect(isWater(world([], [ring]), [0, 0])).toBe(false);
  expect(isWater(world([], [ring]), [7, 0])).toBe(true);
});

test('surface and none placements never block', () => {
  for (const walk of ['surface', 'none'] as const) {
    expectAt(
      move([place('townhouse', 0, 0, 0, walk)], [0, 4], [0, -4]),
      [0, -4],
    );
  }
  expect(move([place('townhouse', 0, 0)], [0, 4], [0, -4])[1]).toBeGreaterThan(
    2.2,
  );
});

test('an unknown kind fails fast', () => {
  expect(() => world([place('spaceship', 0, 0)])).toThrow(
    'unknown prop kind spaceship',
  );
  expect(() => world([place('toString', 0, 0, 0, 'none')])).toThrow(
    'unknown prop kind toString',
  );
});
