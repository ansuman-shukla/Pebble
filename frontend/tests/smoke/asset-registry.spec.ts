import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import manifest from '../../src/lib/world/asset-manifest.json' with { type: 'json' };
import { ANIMALS, PROPS } from '../../src/lib/world/assets';
import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { createCharacter } from '../../src/vendor/polyfork/humanoid.mjs';

const ROOT = path.resolve(import.meta.dirname, '../..');
const byId = new Map(manifest.assets.map((asset) => [asset.id, asset]));
const registryIds = new Set([
  ...Object.values(PROPS),
  ...Object.values(ANIMALS).map((animal) => animal.asset),
]);

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
