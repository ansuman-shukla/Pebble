import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import manifest from '../../src/lib/world/asset-manifest.json' with { type: 'json' };
import {
  ANIMALS,
  HAND_PROPS,
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

// the kinds and props World v1 (docs/design/10-world-v1.md) draws: nodes, dens, roads, markers, stores, stations
const WORLD_V1_KINDS: PropKind[] = [
  'berry_bush',
  'root_patch',
  'reed_bed',
  'nut_tree',
  'tree_stump',
  'fallen_log',
  'driftwood',
  'dead_tree',
  'flint_seam',
  'obsidian_field',
  'rice_paddy',
  'cave_mouth',
  'bone_scatter',
  'signpost',
  'log_bridge',
  'boundary_stone',
  'banner',
  'cairn',
  'market_stall',
  'forge',
  'anvil',
  'chest',
  'grain_sack',
  'coin_pouch',
  'drying_rack',
  'camp_drying_rack',
  'sleeping_mat',
  'field_barricade',
  'bell_tower',
  'storehouse',
];
const WORLD_V1_HAND_PROPS: HandPropKind[] = [
  'axe',
  'hoe',
  'hammer',
  'torch',
  'spear',
  'basket',
  'coin_pouch',
  'sack',
  'pick',
  'fishing_rod',
];

test('every World v1 kind and hand prop with a model resolves to a pinned asset', () => {
  for (const kind of WORLD_V1_KINDS) {
    const id = PROPS[kind];
    expect(byId.get(id)?.files.glb.path, kind).toBeDefined();
  }
  for (const kind of WORLD_V1_HAND_PROPS) {
    const prop = HAND_PROPS[kind];
    if ('asset' in prop)
      expect(byId.get(prop.asset)?.files.glb.path, kind).toBeDefined();
  }
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

test('kit looks build rigged humanoids wearing every garment they name', () => {
  expect(Object.keys(KIT_LOOKS).sort()).toEqual(
    ['ashigaru', 'buddhist_monk', 'farmer'].sort(),
  );
  for (const [id, config] of Object.entries(KIT_LOOKS)) {
    const slots = Object.keys(config.wear);
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

test('the 15 citizens are split 6 town, 5 band A, 4 band B with unique looks', () => {
  const ids = CITIZEN_LOOKS.map((look) => look.id);
  expect(new Set(ids).size).toBe(15);
  const count = (region: string) =>
    CITIZEN_LOOKS.filter((look) => look.region === region).length;
  expect([count('town'), count('band_a'), count('band_b')]).toEqual([6, 5, 4]);
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
