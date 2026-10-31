import { expect, test } from '@playwright/test';

import type { LiveMessage } from '../../src/lib/live/live-contract';
import {
  isSapling,
  isStump,
  NodeStages,
} from '../../src/lib/world/node-stages';
import {
  FULL_STAGE,
  nodeStage,
  ROW_WIDTH,
  StageTexture,
} from '../../src/lib/world/staged-material';

/*
 * Node stages (10 §1.1): a node's stock as drawn (pieces, level, growth, tint) per kind, and the client's record of
 * stocks, felled trees and gathers from the live feed.
 */

test('a berry bush shows round(8 × stock / cap) eighths of its fruit pieces', () => {
  // 9 fruit pieces on the vendored bush
  expect(nodeStage('berry_bush', 1, 9).pieces).toBe(9);
  expect(nodeStage('berry_bush', 11 / 12, 9).pieces).toBe(8); // 7.33 → 7 eighths → 7.875 → 8
  expect(nodeStage('berry_bush', 6 / 12, 9).pieces).toBe(5); // 4 eighths → 4.5 → 5
  expect(nodeStage('berry_bush', 1 / 12, 9).pieces).toBe(1); // 0.67 → 1 eighth
  // eighths first, then pieces: 5/12 → 3 eighths → 3.375 → 3 (not 3.75 → 4), 2/12 → 1 eighth → 1 (not 2)
  expect(nodeStage('berry_bush', 5 / 12, 9).pieces).toBe(3);
  expect(nodeStage('berry_bush', 2 / 12, 9).pieces).toBe(1);
  expect(nodeStage('berry_bush', 0.5 / 12, 9).pieces).toBe(0); // 0.33 → 0
  expect(nodeStage('berry_bush', 0, 9).pieces).toBe(0);
  // an 8-piece model shows exactly the eighths
  expect(nodeStage('berry_bush', 3 / 12, 8).pieces).toBe(2);
  // fruit only: the bush stays whole
  expect(nodeStage('berry_bush', 0, 9)).toMatchObject({
    level: 1,
    growth: 1,
    tint: 0,
  });
});

test('root patches thin and turn to dug earth, reeds are cut down to stubble, piles and heaps shrink', () => {
  expect(nodeStage('root_patch', 1, 11)).toEqual({ ...FULL_STAGE, pieces: 11 });
  expect(nodeStage('root_patch', 3 / 8, 11)).toEqual({
    ...FULL_STAGE,
    pieces: 5,
  });
  expect(nodeStage('root_patch', 0, 11)).toEqual({
    ...FULL_STAGE,
    pieces: 0,
    tint: 1,
  });
  expect(nodeStage('reed_bed', 1, 0).growth).toBe(1);
  expect(nodeStage('reed_bed', 9 / 20, 0).growth).toBeCloseTo(0.6, 9); // ⌈2.25⌉ = 3 of 5
  expect(nodeStage('reed_bed', 1 / 20, 0).growth).toBeCloseTo(0.2, 9);
  expect(nodeStage('reed_bed', 0, 0).growth).toBeCloseTo(0.12, 9);
  expect(nodeStage('deadwood', 4 / 6, 0)).toEqual({
    ...FULL_STAGE,
    level: 4 / 6,
  });
  expect(nodeStage('deadwood', 0, 0).level).toBe(0);
  for (const seam of ['flint_seam', 'obsidian_field']) {
    expect(nodeStage(seam, 1, 0).growth).toBe(1);
    expect(nodeStage(seam, 0.76, 0).growth).toBe(1);
    expect(nodeStage(seam, 0.75, 0).growth).toBe(0.75);
    expect(nodeStage(seam, 0.51, 0).growth).toBe(0.75);
    expect(nodeStage(seam, 0.5, 0).growth).toBe(0.5);
    expect(nodeStage(seam, 0.01, 0).growth).toBe(0.5);
    expect(nodeStage(seam, 0, 0).growth).toBe(0.2);
  }
  // out-of-range stock is clamped; kinds without a drawn stage are full
  expect(nodeStage('deadwood', 1.4, 0).level).toBe(1);
  expect(nodeStage('tree', 0, 0)).toEqual(FULL_STAGE);
});

test('a stage texture keeps one row per instance, full until set', () => {
  const rows = new StageTexture(4);
  expect(rows.get(3)).toEqual(FULL_STAGE);
  rows.set(2, { pieces: 3, level: 0.5, growth: 0.75, tint: 1 });
  expect(rows.get(2)).toEqual({ pieces: 3, level: 0.5, growth: 0.75, tint: 1 });
  expect(rows.get(1)).toEqual(FULL_STAGE);
  // rows lie ROW_WIDTH to a line: 6000 rows fit a 64 × 94 texture, far under WebGL's 4096 a side
  expect([rows.texture.image.width, rows.texture.image.height]).toEqual([
    ROW_WIDTH,
    1,
  ]);
  const big = new StageTexture(6000);
  expect([big.texture.image.width, big.texture.image.height]).toEqual([64, 94]);
  big.set(5999, { pieces: 1, level: 1, growth: 1, tint: 0 });
  expect(big.get(5999).pieces).toBe(1);
  expect(big.get(5998)).toEqual(FULL_STAGE);
  const pieces = rows.chunk(0.97, true);
  expect(pieces.defines).toEqual({ STAGE_PIECES: '' });
  expect(pieces.uniforms.stageHeight.value).toBe(0.97);
  expect(rows.chunk(1, false).defines).toEqual({});
});

const RUN = 'run-1';
let tick = 0;
function event(
  type: string,
  actor: string | null,
  payload: Record<string, unknown>,
) {
  tick += 1;
  return {
    type: 'event',
    run_id: RUN,
    tick,
    event: {
      id: `e${tick}`,
      type,
      actor_id: actor,
      payload,
      line: type,
      importance: 0,
      position: null,
    },
  } as unknown as LiveMessage;
}
const snapshot = (run: string) =>
  ({ type: 'snapshot', run_id: run, tick: 1 }) as unknown as LiveMessage;
const changed = (
  node: string,
  kind: string,
  after: number,
  extra: Record<string, unknown> = {},
) =>
  event('node_changed', 'tek', {
    node,
    kind,
    item: 'x',
    before: after + 1,
    after,
    stage: 'some',
    ...extra,
  });

test('node_changed sets the stock share by the kind cap, a feature cap or the payload cap', () => {
  const stages = new NodeStages(new Map([['b_shore:flint_seam', 10]]));
  stages.apply(snapshot(RUN), 0);
  expect(stages.state('flora:1')).toBeUndefined();
  stages.apply(changed('flora:1', 'berry_bush', 6), 0);
  expect(stages.state('flora:1')).toEqual({ fill: 0.5, stage: 'some' });
  stages.apply(changed('flora:2', 'reed_bed', 5), 0);
  expect(stages.state('flora:2')!.fill).toBe(0.25);
  stages.apply(changed('b_shore:flint_seam', 'flint_seam', 5), 0);
  expect(stages.state('b_shore:flint_seam')!.fill).toBe(0.5);
  stages.apply(changed('flora:3', 'deadwood', 3, { cap: 4 }), 0);
  expect(stages.state('flora:3')!.fill).toBe(0.75);
  stages.apply(changed('flora:4', 'berry_bush', 99), 0);
  expect(stages.state('flora:4')!.fill).toBe(1);
  expect(() => stages.apply(changed('x', 'mystery', 3), 0)).toThrow(
    /no stock cap/,
  );
});

test('a felled tree falls along its heading and stays a stump until it is a sapling', () => {
  const stages = new NodeStages();
  stages.apply(snapshot(RUN), 0);
  const before = stages.version;
  stages.apply(
    event('tree_felled', 'tek', { node: 'flora:7', yaw_deg: 90, logs: 10 }),
    12.5,
  );
  expect(stages.version).toBeGreaterThan(before);
  expect(stages.fellAt('flora:7')).toBe(12.5);
  // heading 90 (east) = bearing 90°
  expect(stages.fallBearing('flora:7')).toBeCloseTo(Math.PI / 2, 9);
  expect(stages.state('flora:7')).toEqual({ fill: 0, stage: 'stump' });
  stages.apply(
    event('tree_felled', 'tek', { node: 'flora:8', yaw_deg: 0, logs: 10 }),
    1,
  );
  expect(stages.fallBearing('flora:8')).toBeCloseTo(Math.PI, 9); // heading 0 faces south
  stages.apply(event('tree_felled', 'tek', { node: 'flora:9', logs: 10 }), 1);
  expect(stages.fallBearing('flora:9')).toBeNull();
  // the stump stays felled through stock changes, until it grows back
  stages.apply(changed('flora:7', 'tree', 0, { stage: 'a stump' }), 20);
  expect(stages.fellAt('flora:7')).toBe(12.5);
  stages.apply(changed('flora:7', 'tree', 1, { stage: 'a sapling' }), 30);
  expect(stages.fellAt('flora:7')).toBeUndefined();
  expect(isSapling(stages.state('flora:7')!.stage)).toBe(true);
  expect(isStump('stump')).toBe(true);
  expect(isStump(null)).toBe(false);
});

test('a gather at a node marks it worked until its actor finishes, is interrupted or dies; felling ends it', () => {
  const stages = new NodeStages();
  stages.apply(snapshot(RUN), 0);
  const start = (actor: string, node: string) =>
    event('action_started', actor, {
      number: 1,
      action: 'gather',
      args: { item: 'wood' },
      label: 'a tree',
      target: { kind: 'node', id: node, name: 'an oak' },
    });
  stages.apply(start('tek', 'flora:5'), 0);
  stages.apply(start('ama', 'flora:6'), 0);
  expect(stages.worked('flora:5')).toBe(true);
  // the actor's next action replaces the old work
  stages.apply(start('tek', 'flora:9'), 0);
  expect(stages.worked('flora:5')).toBe(false);
  expect(stages.worked('flora:9')).toBe(true);
  stages.apply(
    event('action_finished', 'tek', {
      number: 1,
      action: 'gather',
      outcome: 'done',
    }),
    0,
  );
  expect(stages.worked('flora:9')).toBe(false);
  expect(stages.worked('flora:6')).toBe(true);
  stages.apply(
    event('action_interrupted', 'ama', {
      number: 1,
      action: 'gather',
      outcome: 'x',
    }),
    0,
  );
  expect(stages.worked('flora:6')).toBe(false);
  stages.apply(start('kaz', 'flora:4'), 0);
  stages.apply(event('died', 'kaz', {}), 0);
  expect(stages.worked('flora:4')).toBe(false);
  stages.apply(start('kaz', 'flora:3'), 0);
  stages.apply(
    event('tree_felled', 'kaz', { node: 'flora:3', yaw_deg: 0, logs: 10 }),
    0,
  );
  expect(stages.worked('flora:3')).toBe(false);
  // other targets and other events change nothing
  const version = stages.version;
  stages.apply(
    event('action_started', 'tek', {
      number: 2,
      action: 'walk_to',
      args: {},
      label: 'x',
      target: { kind: 'place', id: 'well', name: 'the well' },
    }),
    0,
  );
  stages.apply(event('said', 'tek', { words: 'hi' }), 0);
  stages.apply(event('action_finished', 'nobody', { number: 1 }), 0);
  expect(stages.version).toBe(version);
});

test('an unrelated next action ends the shake (the live feed never sends action_interrupted)', () => {
  const stages = new NodeStages();
  stages.apply(snapshot(RUN), 0);
  const started = (
    actor: string,
    action: string,
    target: Record<string, unknown> | null,
  ) =>
    event('action_started', actor, {
      number: 1,
      action,
      args: {},
      label: 'x',
      target,
    });
  stages.apply(
    started('tek', 'gather', { kind: 'node', id: 'flora:5', name: 'an oak' }),
    0,
  );
  stages.apply(
    started('ama', 'gather', { kind: 'node', id: 'flora:6', name: 'an oak' }),
    0,
  );
  expect(stages.worked('flora:5')).toBe(true);
  // tek's chop was interrupted (not sent); his next action walks somewhere
  stages.apply(
    started('tek', 'walk_to', { kind: 'place', id: 'well', name: 'the well' }),
    0,
  );
  expect(stages.worked('flora:5')).toBe(false);
  expect(stages.worked('flora:6')).toBe(true);
  // an action without a target ends it too
  stages.apply(started('ama', 'rest', null), 0);
  expect(stages.worked('flora:6')).toBe(false);
});

test('changes are told by node, so a drawing re-draws only for its own nodes', () => {
  const stages = new NodeStages();
  stages.apply(snapshot(RUN), 0);
  const start = stages.version;
  expect(stages.changedSince(start)).toEqual([]);
  stages.apply(changed('flora:1', 'berry_bush', 3), 0);
  stages.apply(
    event('tree_felled', 'tek', { node: 'flora:2', yaw_deg: 0, logs: 10 }),
    0,
  );
  stages.apply(
    event('action_started', 'ama', {
      number: 1,
      action: 'gather',
      args: {},
      label: 'x',
      target: { kind: 'node', id: 'flora:3', name: 'x' },
    }),
    0,
  );
  stages.apply(
    event('action_started', 'ama', {
      number: 2,
      action: 'gather',
      args: {},
      label: 'x',
      target: { kind: 'node', id: 'flora:4', name: 'x' },
    }),
    0,
  );
  expect(stages.changedSince(start)).toEqual([
    'flora:1',
    'flora:2',
    'flora:3',
    'flora:3',
    'flora:4',
  ]);
  // events that touch no node keep the version
  const version = stages.version;
  stages.apply(event('said', 'tek', { words: 'hi' }), 0);
  stages.apply(
    event('action_started', 'kaz', {
      number: 1,
      action: 'rest',
      args: {},
      label: 'x',
      target: null,
    }),
    0,
  );
  stages.apply(
    event('action_finished', 'kaz', {
      number: 1,
      action: 'rest',
      outcome: 'done',
    }),
    0,
  );
  expect(stages.version).toBe(version);
  // a reset changes every node; so does a gap longer than what is remembered
  stages.reset();
  expect(stages.changedSince(version)).toBeNull();
  const after = stages.version;
  for (let i = 0; i < 300; i++)
    stages.apply(changed(`flora:${i}`, 'berry_bush', 1), 0);
  expect(stages.changedSince(after)).toBeNull();
  expect(stages.changedSince(stages.version - 2)).toEqual([
    'flora:298',
    'flora:299',
  ]);
});

test('a snapshot of another run starts every node full again', () => {
  const stages = new NodeStages();
  stages.apply(snapshot(RUN), 0);
  stages.apply(changed('flora:1', 'berry_bush', 0), 0);
  stages.apply(
    event('tree_felled', 'tek', { node: 'flora:2', yaw_deg: 0, logs: 10 }),
    0,
  );
  stages.apply(snapshot(RUN), 0);
  expect(stages.state('flora:1')).toBeDefined();
  stages.apply(snapshot('run-2'), 0);
  expect(stages.state('flora:1')).toBeUndefined();
  expect(stages.fellAt('flora:2')).toBeUndefined();
});
