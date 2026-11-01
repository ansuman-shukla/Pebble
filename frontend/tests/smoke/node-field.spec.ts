import { expect, test } from '@playwright/test';
import {
  BoxGeometry,
  InstancedMesh,
  Matrix4,
  MeshBasicMaterial,
  Vector3,
} from 'three';

import type { PropKind } from '../../src/lib/world/assets';
import { directionFromLatLon, tangentFrame } from '../../src/lib/world/globe';
import type { LiveMessage } from '../../src/lib/live/live-contract';
import {
  FALL_SECONDS,
  NodeField,
  type NodeLook,
  SAPLING_SCALE,
} from '../../src/lib/world/node-field';
import { NodeStages } from '../../src/lib/world/node-stages';
import type { NodeInstance, Scatter } from '../../src/lib/world/scatter';
import { StageTexture } from '../../src/lib/world/staged-material';

/*
 * The node field without a browser: what each node draws as its stage changes (a picked bush, a chopped tree that
 * shakes, falls along its bearing for 2 s and leaves a stump, a sapling), in which tier, and how far. Its logs are
 * a ground stack (ground-stacks.spec.ts).
 */

const R = 2000;
const FOCUS = directionFromLatLon(10, 20).multiplyScalar(R);
const { east, north } = tangentFrame(FOCUS);
const LOOKS: [PropKind, number, boolean][] = [
  ['oak_tree', 500, false],
  ['berry_bush', 300, true],
  ['tree_stump', 300, false],
  ['fallen_log', 500, true],
];

/** A node `ahead` m north and `right` m east of the focus. */
function node(
  id: string,
  kind: PropKind,
  nodeKind: string,
  ahead: number,
  right: number,
  bearing = 0,
): NodeInstance {
  const position = FOCUS.clone()
    .addScaledVector(north, ahead)
    .addScaledVector(east, right)
    .normalize()
    .multiplyScalar(R);
  return {
    id,
    kind,
    node: nodeKind,
    flora: 0,
    position,
    yaw: 0,
    scale: 1,
    bearing,
    footprint: 0.5,
  };
}

function field(nodes: NodeInstance[]) {
  const meshes = (capacity: number) => [
    new InstancedMesh(new BoxGeometry(), new MeshBasicMaterial(), capacity),
  ];
  const looks: NodeLook[] = LOOKS.map(([kind, reach, staged]) => ({
    kind,
    reach,
    pieces: kind === 'berry_bush' ? 9 : 0,
    near: meshes(10),
    far: meshes(10),
    stages: staged
      ? { near: new StageTexture(10), far: new StageTexture(10) }
      : null,
  }));
  const scatter = {
    cellsAround: () => [0],
    nodes: () => nodes,
  } as unknown as Scatter;
  const stages = new NodeStages();
  stages.apply(
    { type: 'snapshot', run_id: 'r', tick: 1 } as unknown as LiveMessage,
    0,
  );
  return {
    field: new NodeField(looks, scatter, stages),
    stages,
    looks: new Map(looks.map((l) => [l.kind, l])),
  };
}

let tick = 0;
const event = (type: string, payload: Record<string, unknown>, actor = 'tek') =>
  ({
    type: 'event',
    run_id: 'r',
    tick: ++tick,
    event: {
      id: `e${tick}`,
      type,
      actor_id: actor,
      payload,
      line: '',
      importance: 0,
      position: null,
    },
  }) as unknown as LiveMessage;

const drawnOf = (f: NodeField, id: string) =>
  f.drawn()!.nodes.filter((n) => n.id === id);

test('each node is drawn once in its tier, out to its look reach', () => {
  const { field: f, looks } = field([
    node('near-oak', 'oak_tree', 'tree', 30, 0),
    node('far-oak', 'oak_tree', 'tree', 450, 0),
    node('gone-oak', 'oak_tree', 'tree', 520, 0),
    node('far-bush', 'berry_bush', 'berry_bush', 0, 280),
    node('gone-bush', 'berry_bush', 'berry_bush', 0, 320),
  ]);
  f.frame(FOCUS, false, 0);
  const ids = f
    .drawn()!
    .nodes.map((n) => n.id)
    .sort();
  expect(ids).toEqual(['far-bush', 'far-oak', 'near-oak']);
  expect(looks.get('oak_tree')!.near[0].count).toBe(1);
  expect(looks.get('oak_tree')!.far[0].count).toBe(1);
  expect(looks.get('berry_bush')!.near[0].visible).toBe(false);
  expect(looks.get('berry_bush')!.far[0].count).toBe(1);
  // too high: nothing
  f.frame(FOCUS, true, 0);
  expect(f.drawn()).toBeNull();
  expect(looks.get('oak_tree')!.near[0].visible).toBe(false);
});

test("a picked bush is drawn with fewer fruit in its tier's stage row", () => {
  const {
    field: f,
    stages,
    looks,
  } = field([
    node('flora:1', 'berry_bush', 'berry_bush', 10, 0),
    node('flora:2', 'berry_bush', 'berry_bush', 12, 0),
  ]);
  f.frame(FOCUS, false, 0);
  expect(drawnOf(f, 'flora:1')[0].stage!.pieces).toBe(9);
  stages.apply(
    event('node_changed', {
      node: 'flora:1',
      kind: 'berry_bush',
      item: 'berries',
      before: 12,
      after: 3,
      stage: 'x',
    }),
    1,
  );
  f.frame(FOCUS, false, 1);
  expect(drawnOf(f, 'flora:1')[0].stage!.pieces).toBe(2);
  const rows = looks.get('berry_bush')!.stages!.near;
  const shown = f
    .drawn()!
    .nodes.filter((n) => n.look === 'berry_bush')
    .map((n) => n.id);
  expect(rows.get(shown.indexOf('flora:1')).pieces).toBe(2);
  expect(rows.get(shown.indexOf('flora:2')).pieces).toBe(9);
});

test('a stage change re-draws only when it is one of the gathered nodes', () => {
  const {
    field: f,
    stages,
    looks,
  } = field([node('flora:1', 'berry_bush', 'berry_bush', 10, 0)]);
  f.frame(FOCUS, false, 0);
  const matrices = looks.get('berry_bush')!.near[0].instanceMatrix;
  const drawnAt = matrices.version;
  const change = (id: string) =>
    stages.apply(
      event('node_changed', {
        node: id,
        kind: 'berry_bush',
        item: 'berries',
        before: 12,
        after: 3,
        stage: 'x',
      }),
      1,
    );
  change('flora:far-away');
  f.frame(FOCUS, false, 1);
  expect(matrices.version).toBe(drawnAt);
  change('flora:1');
  f.frame(FOCUS, false, 2);
  expect(matrices.version).toBeGreaterThan(drawnAt);
  expect(drawnOf(f, 'flora:1')[0].stage!.pieces).toBe(2);
  // a new run makes every node full: drawn again whatever was changed
  stages.apply(
    { type: 'snapshot', run_id: 'r2', tick: 1 } as unknown as LiveMessage,
    3,
  );
  f.frame(FOCUS, false, 3);
  expect(drawnOf(f, 'flora:1')[0].stage!.pieces).toBe(9);
});

/** Where the instance's local point (0, 10, 0) (up the trunk) is drawn, relative to the node's base. */
function topOf(mesh: InstancedMesh, slot: number, base: Vector3) {
  const matrix = mesh.getMatrixAt(slot, new Matrix4());
  return new Vector3(0, 10, 0).applyMatrix4(matrix).sub(base);
}

test('a chopped tree shakes, falls along its bearing for 2 s, then lies as logs by its stump', () => {
  const oak = node('flora:9', 'oak_tree', 'tree', 20, 0, 0);
  const { field: f, stages, looks } = field([oak]);
  const meshes = looks.get('oak_tree')!.near;
  const up = oak.position.clone().normalize();
  f.frame(FOCUS, false, 0);
  const standing = topOf(meshes[0], 0, oak.position);
  expect(standing.clone().normalize().dot(up)).toBeCloseTo(1, 6);

  stages.apply(
    event('action_started', {
      number: 1,
      action: 'gather',
      args: { item: 'wood' },
      label: 'an oak',
      target: { kind: 'node', id: 'flora:9', name: 'an oak' },
    }),
    1,
  );
  // a third of a second apart: the two ends of a sway (3 a second)
  f.frame(FOCUS, false, 1 + 1 / 12);
  const a = topOf(meshes[0], 0, oak.position);
  f.frame(FOCUS, false, 1 + 3 / 12);
  const b = topOf(meshes[0], 0, oak.position);
  expect(drawnOf(f, 'flora:9')[0].motion).toBe('shake');
  expect(a.distanceTo(b)).toBeGreaterThan(0.5);
  expect(a.distanceTo(standing)).toBeLessThan(0.5);

  // felled heading 90 = falls east
  stages.apply(
    event('tree_felled', { node: 'flora:9', yaw_deg: 90, logs: 10 }),
    2,
  );
  const fall = tangentFrame(oak.position).east;
  f.frame(FOCUS, false, 2.5);
  expect(drawnOf(f, 'flora:9')[0].motion).toBe('fall');
  const early = topOf(meshes[0], 0, oak.position).dot(fall);
  f.frame(FOCUS, false, 3.5);
  const late = topOf(meshes[0], 0, oak.position);
  expect(late.dot(fall)).toBeGreaterThan(early);
  expect(early).toBeGreaterThan(0);
  // at 1.5 s of 2 the trunk is well over (angle π/2 × 0.75² ≈ 50°)
  expect(late.clone().normalize().dot(up)).toBeLessThan(
    Math.cos((45 * Math.PI) / 180),
  );
  expect(late.clone().normalize().dot(up)).toBeGreaterThan(
    Math.cos((55 * Math.PI) / 180),
  );

  f.frame(FOCUS, false, 2 + FALL_SECONDS);
  // landed: only its stump stands (its logs are the ground stack the feed sends)
  const after = drawnOf(f, 'flora:9');
  expect(after.map((n) => n.look)).toEqual(['tree_stump']);
  expect(looks.get('oak_tree')!.near[0].visible).toBe(false);
  expect(looks.get('fallen_log')!.near[0].visible).toBe(false);
  expect(
    new Vector3(...after[0].position).distanceTo(oak.position),
  ).toBeLessThan(1e-6);
});

test('a felled tree draws no logs of its own: a deadwood pile beside it keeps its slot and stage', () => {
  const oak = node('flora:1', 'oak_tree', 'tree', 20, 0);
  const pile = node('flora:2', 'fallen_log', 'deadwood', 25, 0);
  const { field: f, stages, looks } = field([oak, pile]);
  stages.apply(
    event('node_changed', {
      node: 'flora:2',
      kind: 'deadwood',
      item: 'wood',
      before: 6,
      after: 3,
      stage: 'x',
    }),
    0,
  );
  f.frame(FOCUS, false, 0);
  const rows = looks.get('fallen_log')!.stages!.near;
  expect(rows.get(0).level).toBe(0.5);
  stages.apply(
    event('tree_felled', { node: 'flora:1', yaw_deg: 90, logs: 10 }),
    1,
  );
  f.frame(FOCUS, false, 1 + FALL_SECONDS);
  const logs = f
    .drawn()!
    .nodes.filter((n) => n.look === 'fallen_log')
    .map((n) => n.id);
  expect(logs).toEqual(['flora:2']);
  expect(rows.get(0).level).toBe(0.5);
});

test('a felled tree with no heading falls along its table bearing; a sapling is a small tree', () => {
  const oak = node('flora:4', 'oak_tree', 'tree', 20, 0, Math.PI); // bearing south
  const { field: f, stages, looks } = field([oak]);
  stages.apply(event('tree_felled', { node: 'flora:4', logs: 10 }), 0);
  f.frame(FOCUS, false, 1);
  const top = topOf(looks.get('oak_tree')!.near[0], 0, oak.position);
  expect(top.dot(tangentFrame(oak.position).south)).toBeGreaterThan(0.5);
  stages.apply(
    event('node_changed', {
      node: 'flora:4',
      kind: 'tree',
      item: 'wood',
      before: 0,
      after: 1,
      stage: 'a sapling',
    }),
    5,
  );
  f.frame(FOCUS, false, 5);
  const sapling = drawnOf(f, 'flora:4');
  expect(sapling.map((n) => n.look)).toEqual(['oak_tree']);
  const matrix = looks.get('oak_tree')!.near[0].getMatrixAt(0, new Matrix4());
  expect(new Vector3().setFromMatrixScale(matrix).x).toBeCloseTo(
    SAPLING_SCALE,
    6,
  );
});
