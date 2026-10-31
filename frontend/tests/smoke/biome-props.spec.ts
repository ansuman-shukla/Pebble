import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import manifest from '../../src/lib/world/asset-manifest.json' with { type: 'json' };
import { PROPS } from '../../src/lib/world/assets';
import {
  BIOME_NAMES,
  BIOME_PROPS,
  BLOCKING_KINDS,
  LANDMARK_KINDS,
  NODE_LOOK_KINDS,
} from '../../src/lib/world/biome-props';

const ROOT = path.resolve(import.meta.dirname, '../..');
const byId = new Map(manifest.assets.map((asset) => [asset.id, asset]));

// the globe contract: biome ids and the landmark kinds the backend world spec names
const CONTRACT_BIOMES = [
  'deep_ocean',
  'shallow_ocean',
  'beach',
  'grassland',
  'broadleaf_forest',
  'taiga',
  'wetland',
  'hills',
  'mountain',
  'savanna',
  'tundra',
  'snow',
  'ice',
  'lake',
  'volcanic',
];
const WATER_BIOMES = ['deep_ocean', 'shallow_ocean', 'lake'];
const CONTRACT_LANDMARKS = [
  'rock_spire',
  'boulder',
  'basalt_column',
  'lava_rock',
  'fumarole',
  'geyser',
  'hot_spring_pool',
  'obsidian',
  'giant_tree',
  'snowy_spruce',
  'ice_block',
];

function expectVendored(kind: string) {
  expect(Object.hasOwn(PROPS, kind), `${kind} is not a registry kind`).toBe(
    true,
  );
  const asset = byId.get(PROPS[kind as keyof typeof PROPS]);
  expect(asset, `${kind} missing from the manifest`).toBeDefined();
  const file = readFileSync(path.join(ROOT, asset!.files.glb.path));
  expect(createHash('sha256').update(file).digest('hex'), kind).toBe(
    asset!.files.glb.sha256,
  );
}

test('biome names follow the contract order and each has a scatter list', () => {
  expect([...BIOME_NAMES]).toEqual(CONTRACT_BIOMES);
  expect(Object.keys(BIOME_PROPS).sort()).toEqual([...CONTRACT_BIOMES].sort());
});

test('water biomes scatter nothing and every land biome scatters something', () => {
  for (const biome of BIOME_NAMES) {
    const entries = BIOME_PROPS[biome];
    if (WATER_BIOMES.includes(biome)) expect(entries, biome).toEqual([]);
    else expect(entries.length, biome).toBeGreaterThan(0);
  }
});

test('every scatter entry names a vendored kind once per biome with a sane density and scale', () => {
  for (const [biome, entries] of Object.entries(BIOME_PROPS)) {
    const kinds = entries.map((entry) => entry.kind);
    expect(new Set(kinds).size, `${biome} repeats a kind`).toBe(kinds.length);
    for (const { kind, perCell, scale } of entries) {
      expectVendored(kind);
      expect(perCell, `${biome}/${kind} perCell`).toBeGreaterThan(0);
      expect(perCell, `${biome}/${kind} perCell`).toBeLessThanOrEqual(12);
      expect(scale[0], `${biome}/${kind} scale`).toBeGreaterThan(0);
      expect(scale[0], `${biome}/${kind} scale`).toBeLessThanOrEqual(scale[1]);
    }
  }
});

test('no decor kind is usable or looks like a node', () => {
  const nodeAssets = new Set(NODE_LOOK_KINDS.map((kind) => PROPS[kind]));
  for (const [biome, entries] of Object.entries(BIOME_PROPS))
    for (const { kind } of entries) {
      expect(NODE_LOOK_KINDS, `${biome}/${kind}`).not.toContain(kind);
      expect(
        nodeAssets.has(PROPS[kind]),
        `${biome}/${kind} looks like a node`,
      ).toBe(false);
    }
  // reed clumps are the town's fixed reed nodes
  expect(
    Object.values(BIOME_PROPS)
      .flat()
      .map((entry) => entry.kind),
  ).not.toContain('reeds');
});

test('every node look is a vendored kind and blocks walking unless it is a soft plant', () => {
  for (const kind of NODE_LOOK_KINDS) expectVendored(kind);
  expect(NODE_LOOK_KINDS).toEqual(
    expect.arrayContaining([
      'oak_tree',
      'nut_tree',
      'berry_bush',
      'tree_stump',
      'flint_seam',
      'obsidian_field',
    ]),
  );
  expect(BLOCKING_KINDS).toEqual(
    expect.arrayContaining([
      'oak_tree',
      'berry_bush',
      'fallen_log',
      'tree_stump',
    ]),
  );
  for (const soft of [
    'root_patch',
    'reed_bed',
    'grass_tuft',
    'cattail',
  ] as const)
    expect(BLOCKING_KINDS).not.toContain(soft);
});

test('every landmark kind of the world spec is a vendored registry kind', () => {
  expect([...LANDMARK_KINDS].sort()).toEqual([...CONTRACT_LANDMARKS].sort());
  for (const kind of CONTRACT_LANDMARKS) expectVendored(kind);
});
