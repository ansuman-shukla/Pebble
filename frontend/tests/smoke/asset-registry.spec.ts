import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import manifest from '../../src/lib/world/asset-manifest.json' with { type: 'json' };
import {
  ANIMALS,
  HAND_PROPS,
  type HandProp,
  type HandPropKind,
  PROPS,
  type PropKind,
} from '../../src/lib/world/assets';
import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { KIT_LOOKS } from '../../src/lib/world/kit-looks';
import { VISITOR_LOOK } from '../../src/lib/world/visitor-look';
import { createCharacter } from '../../src/vendor/polyfork/humanoid.mjs';

const ROOT = path.resolve(import.meta.dirname, '../..');
const byId = new Map(manifest.assets.map((asset) => [asset.id, asset]));
const registryIds = new Set([
  ...Object.values(PROPS),
  ...Object.values(ANIMALS).map((animal) => animal.asset),
  ...Object.values(HAND_PROPS).flatMap((prop) =>
    'asset' in prop ? [prop.asset] : [],
  ),
]);

/** Names of the meshes a character is built from (`body` + `attach-<slot>-mesh` per garment). */
function meshNames(config: Parameters<typeof createCharacter>[0]) {
  const names: string[] = [];
  createCharacter(config).traverse((object) => {
    if ((object as { isMesh?: boolean }).isMesh) names.push(object.name);
  });
  return names.sort();
}

function glbNodeNames(id: string) {
  const glb = readFileSync(path.join(ROOT, byId.get(id)!.files.glb.path));
  const json = JSON.parse(
    glb.subarray(20, 20 + glb.readUInt32LE(12)).toString('utf8'),
  ) as { nodes: { name?: string }[] };
  return json.nodes.map((node) => node.name ?? '');
}

test('every registry kind resolves to a vendored file matching its pinned hash', () => {
  for (const id of registryIds) {
    const asset = byId.get(id);
    expect(asset, `${id} missing from the manifest`).toBeDefined();
    const file = readFileSync(path.join(ROOT, asset!.files.glb.path));
    expect(createHash('sha256').update(file).digest('hex'), id).toBe(
      asset!.files.glb.sha256,
    );
  }
});

// the kinds World v1 (docs/design/10-world-v1.md) draws and the model each one must be (findings 2026-10-29)
const WORLD_V1_KINDS: Partial<Record<PropKind, string>> = {
  berry_bush: 'berry-bush-ee4812',
  root_patch: 'taro-plant-8c0493',
  reed_bed: 'totora-reed-bed-36d78f',
  nut_tree: 'broadleaf-oak-997c22',
  tree_stump: 'tree-stump-ec3f48',
  fallen_log: 'fallen-log-1685fb',
  driftwood: 'driftwood-log-90340b',
  dead_tree: 'dead-tree-6795fa',
  flint_seam: 'ballast-heap-2fb138',
  obsidian_field: 'lava-rock-pile-d56d19',
  rice_paddy: 'rice-paddy-tile-dc727e',
  cave_mouth: 'smuggler-cave-mouth-69a07e',
  bone_scatter: 'bone-scatter-90313d',
  signpost: 'trail-signpost-bd29a7',
  log_bridge: 'log-plank-bridge-a5f74f',
  boundary_stone: 'garden-rock-2d3b51',
  banner: 'nobori-banner-ae4d88',
  cairn: 'pipi-horeko-cairn-f5db4b',
  market_stall: 'market-stall-94937d',
  forge: 'blacksmith-forge-09fa85',
  anvil: 'anvil-1286cb',
  chest: 'timber-crate-ba0739',
  grain_sack: 'grain-sack-401d96',
  coin_pouch: 'coin-pouch-be4dd8',
  drying_rack: 'hasa-rice-drying-rack-d545bc',
  camp_drying_rack: 'drying-net-rack-93ec3b',
  sleeping_mat: 'straw-pile-ebd54d',
  field_barricade: 'field-barricade-a646b9',
  bell_tower: 'temple-bell-tower-745387',
  storehouse: 'kura-storehouse-5c9631',
};
const WORLD_V1_HAND_PROPS: Record<HandPropKind, HandProp> = {
  axe: { asset: 'hand-axe-cee9e7' },
  hoe: { asset: 'garden-hoe-3974ad' },
  hammer: { asset: 'hammer-fa3e51' },
  torch: { asset: 'torch-stake-d82a2c' },
  spear: { asset: 'yari-spear-e72c1f' },
  basket: { asset: 'kete-reed-basket-6ca36c' },
  coin_pouch: { asset: 'coin-pouch-be4dd8' },
  sack: { asset: 'grain-sack-401d96' },
  pick: { wardrobe: 'pick' },
  fishing_rod: { wardrobe: 'fishing-rod' },
};

test('every World v1 kind and hand prop draws its chosen, pinned model', () => {
  for (const [kind, id] of Object.entries(WORLD_V1_KINDS)) {
    expect(PROPS[kind as PropKind], kind).toBe(id);
    expect(byId.get(id)?.files.glb.path, kind).toBeDefined();
  }
  expect(HAND_PROPS).toEqual(WORLD_V1_HAND_PROPS);
  for (const prop of Object.values(HAND_PROPS))
    if ('asset' in prop) expect(byId.get(prop.asset), prop.asset).toBeDefined();
});

test('wardrobe hand props are items the pinned humanoid engine carries in the right hand', () => {
  const wardrobeProps = Object.values(HAND_PROPS).flatMap((prop) =>
    'wardrobe' in prop ? [prop.wardrobe] : [],
  );
  expect(wardrobeProps.length).toBeGreaterThan(0);
  for (const item of wardrobeProps) {
    const config = {
      ...KIT_LOOKS.farmer,
      wear: { ...KIT_LOOKS.farmer.wear, righthand: item },
    };
    expect(meshNames(config), item).toContain('attach-righthand-mesh');
  }
});

// the garments each kit character wears in its module: dropping or moving one must fail
const KIT_LOOK_SLOTS: Record<keyof typeof KIT_LOOKS, string[]> = {
  buddhist_monk: [
    'hair',
    'coat',
    'bottom',
    'feet',
    'neck',
    'hands',
    'righthand',
  ],
  ashigaru: [
    'hair',
    'hat',
    'top',
    'coat',
    'bottom',
    'feet',
    'hands',
    'righthand',
  ],
  farmer: ['hair', 'hat', 'top', 'bottom', 'feet', 'neck'],
};

test('kit looks build rigged humanoids wearing every garment of their kit character', () => {
  expect(Object.keys(KIT_LOOKS).sort()).toEqual(
    Object.keys(KIT_LOOK_SLOTS).sort(),
  );
  for (const [id, slots] of Object.entries(KIT_LOOK_SLOTS)) {
    const config = KIT_LOOKS[id as keyof typeof KIT_LOOKS];
    expect(Object.keys(config.wear).sort(), id).toEqual([...slots].sort());
    expect(meshNames(config), id).toEqual(
      ['body', ...slots.map((slot) => `attach-${slot}-mesh`)].sort(),
    );
  }
  expect(KIT_LOOKS.buddhist_monk.wear.neck).toMatchObject({ name: 'kesa' });
  expect(KIT_LOOKS.ashigaru.wear.coat).toMatchObject({ name: 'do-maru' });
  expect(KIT_LOOKS.farmer.wear.neck).toMatchObject({ name: 'mino' });
});

test('the berry bush drops its fruit piece by piece (parts named fruit-N)', () => {
  const fruit = glbNodeNames(PROPS.berry_bush).filter((name) =>
    /^fruit-\d+$/.test(name),
  );
  expect(fruit.length).toBeGreaterThanOrEqual(8);
});

test('every pinned asset is used by the registry', () => {
  const unused = manifest.assets.filter((asset) => !registryIds.has(asset.id));
  expect(unused.map((asset) => asset.id)).toEqual([]);
});

test('animal recolours name colours that exist in the asset palette', () => {
  for (const [kind, animal] of Object.entries(ANIMALS)) {
    if (!animal.recolor) continue;
    const params = JSON.parse(
      readFileSync(
        path.join(ROOT, byId.get(animal.asset)!.files.params.path),
        'utf8',
      ),
    ) as { params: Record<string, { type: string; default: string }> };
    const palette = Object.values(params.params)
      .filter((knob) => knob.type === 'color')
      .map((knob) => knob.default.toLowerCase());
    for (const from of Object.keys(animal.recolor)) {
      expect(palette, `${kind}: ${from}`).toContain(from.toLowerCase());
    }
  }
});

test('the 22 citizens are split 11 town, 6 band A, 5 band B with unique looks', () => {
  const ids = CITIZEN_LOOKS.map((look) => look.id);
  expect(new Set(ids).size).toBe(22);
  const count = (region: string) =>
    CITIZEN_LOOKS.filter((look) => look.region === region).length;
  expect([count('town'), count('band_a'), count('band_b')]).toEqual([11, 6, 5]);
});

test('every citizen look builds a rigged humanoid', () => {
  for (const look of CITIZEN_LOOKS) {
    const character = createCharacter(look.config);
    const bones = new Set<string>();
    character.traverse((object) => {
      if ((object as { isBone?: boolean }).isBone) bones.add(object.name);
    });
    for (const bone of [
      'Hips',
      'Spine2',
      'LeftForeArm',
      'RightUpLeg',
      'Head',
    ]) {
      expect(bones.has(bone), `${look.id}: ${bone}`).toBe(true);
    }
  }
});

test('the visitor look builds a humanoid wearing every garment it names', () => {
  const slots = Object.keys(VISITOR_LOOK.wear);
  expect(slots).toEqual(
    expect.arrayContaining(['hat', 'top', 'bottom', 'feet']),
  );
  expect(meshNames(VISITOR_LOOK)).toEqual(
    ['body', ...slots.map((slot) => `attach-${slot}-mesh`)].sort(),
  );
});
