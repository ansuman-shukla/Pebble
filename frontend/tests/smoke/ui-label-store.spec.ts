import { expect, test } from '@playwright/test';
import { Group, Vector3 } from 'three';

import { type LabelContent, LabelStore } from '../../src/lib/world/label-store';

/* The label store (no browser): bodies write anchors, the UI writes content, keyed by subject. */

const tag = (subject: string, text = subject): LabelContent => ({
  id: `npc-${subject}`,
  subject,
  kind: 'name',
  text,
});

const at = (x: number, y: number, z: number) => {
  const object = new Group();
  object.position.set(x, y, z);
  object.updateMatrixWorld();
  return object;
};

test('a label hangs lift metres above its anchor along up', () => {
  const flat = new LabelStore();
  flat.anchor('pip', at(1, 2, 3), 2);
  expect(flat.anchorPosition('pip', new Vector3())?.toArray()).toEqual([
    1, 4, 3,
  ]);
  const planet = new LabelStore((point, out) => out.copy(point).normalize());
  planet.anchor('pip', at(0, 0, 100), 1.5);
  expect(planet.anchorPosition('pip', new Vector3())?.toArray()).toEqual([
    0, 0, 101.5,
  ]);
});

test('the anchor follows its object as it moves', () => {
  const store = new LabelStore();
  const body = at(0, 0, 0);
  store.anchor('pip', body, 1);
  body.position.set(5, 0, 0);
  body.updateMatrixWorld();
  expect(store.anchorPosition('pip', new Vector3())?.toArray()).toEqual([
    5, 1, 0,
  ]);
});

test('a subject without an anchor has no position; removing the anchor takes it away', () => {
  const store = new LabelStore();
  expect(store.anchorPosition('pip', new Vector3())).toBeNull();
  const remove = store.anchor('pip', at(0, 0, 0));
  expect(store.anchorPosition('pip', new Vector3())).not.toBeNull();
  remove();
  expect(store.anchorPosition('pip', new Vector3())).toBeNull();
});

test('a later anchor replaces an earlier one, and removing the earlier one keeps the later', () => {
  const store = new LabelStore();
  const removeBody = store.anchor('pip', at(0, 0, 0), 2);
  store.anchor('pip', at(0, 1.6, 0), 0.3);
  removeBody();
  expect(store.anchorPosition('pip', new Vector3())?.y).toBeCloseTo(1.9);
});

test('each group replaces its own labels; the snapshot lists every group', () => {
  const store = new LabelStore();
  let emits = 0;
  store.subscribe(() => (emits += 1));
  store.describe('citizens', [tag('pip'), tag('nim')]);
  store.describe('lord', [tag('masanori')]);
  store.describe('citizens', [tag('pip', 'Pip · asleep')]);
  expect(emits).toBe(3);
  expect(store.getSnapshot()).toEqual([
    tag('pip', 'Pip · asleep'),
    tag('masanori'),
  ]);
});

test('removing a group drops only its labels, and a replaced group is not removed by its old cleanup', () => {
  const store = new LabelStore();
  const removeOld = store.describe('citizens', [tag('pip')]);
  const current = [tag('nim')];
  const removeCurrent = store.describe('citizens', current);
  const removeLord = store.describe('lord', [tag('masanori')]);
  removeOld();
  expect(store.getSnapshot()).toEqual([tag('nim'), tag('masanori')]);
  removeLord();
  expect(store.getSnapshot()).toEqual(current);
  removeCurrent();
  expect(store.getSnapshot()).toEqual([]);
});
