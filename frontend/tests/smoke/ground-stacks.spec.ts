import { expect, test } from '@playwright/test';
import {
  BoxGeometry,
  InstancedMesh,
  Matrix4,
  MeshBasicMaterial,
  Vector3,
} from 'three';

import type { LiveMessage, LiveStack } from '../../src/lib/live/live-contract';
import { assetSize, PROPS } from '../../src/lib/world/assets';
import { directionFromLatLon, tangentFrame } from '../../src/lib/world/globe';
import {
  EASE_SECONDS,
  REACH,
  StackField,
  type StackLook,
  type StackLookMeshes,
} from '../../src/lib/world/ground-stacks';
import { FALL_SECONDS } from '../../src/lib/world/node-field';
import { NodeStages } from '../../src/lib/world/node-stages';
import type { NodeInstance, Scatter } from '../../src/lib/world/scatter';
import type { PlaceOnGround } from '../../src/lib/world/walk-charts';
import { DRAW_CALL_BUDGET, openGlobe } from './globe-helpers';

/*
 * The ground stacks without a browser: what each stack of the feed draws as (a felled tree's logs beside its stump,
 * a woodpile, meat beside the remains, a sack for anything unknown), how big for its count, where, and that a pile
 * grows in, shrinks as some is carried off and goes with the last of it; then on the globe, from the mock feed.
 */

const R = 2000;
const FOCUS = directionFromLatLon(10, 20).multiplyScalar(R);
const { east, north } = tangentFrame(FOCUS);
const LOOKS: StackLook[] = [
  'fallen_log',
  'firewood',
  'grain_sack',
  'meat',
  'hide',
  'small_rock',
];

/** A point `ahead` m north and `right` m east of the focus, on the ground (radius R). */
function at(ahead: number, right: number) {
  return FOCUS.clone()
    .addScaledVector(north, ahead)
    .addScaledVector(east, right)
    .normalize()
    .multiplyScalar(R);
}

function tree(id: string, ahead: number, right: number): NodeInstance {
  return {
    id,
    kind: 'oak_tree',
    node: 'tree',
    flora: 0,
    position: at(ahead, right),
    yaw: 0,
    scale: 1,
    bearing: 0,
    footprint: 0.5,
  };
}

function stack(
  id: string,
  item: string,
  count: number,
  point: Vector3,
): LiveStack {
  const unit = point.clone().normalize();
  return { id, item, count, unit: [unit.x, unit.y, unit.z], cell: 0 };
}

/** The drawn ground: a sphere of radius R, or rising `rise` metres a metre eastward of the focus. */
function ground(rise = 0): PlaceOnGround {
  return (unit, target) => {
    const point = target.copy(unit).normalize().multiplyScalar(R);
    const eastward = point.clone().sub(FOCUS).dot(east);
    return target
      .copy(unit)
      .normalize()
      .multiplyScalar(R + rise * eastward);
  };
}

function field(trees: NodeInstance[] = [], place = ground()) {
  const looks: StackLookMeshes[] = LOOKS.map((look) => ({
    look,
    meshes: [new InstancedMesh(new BoxGeometry(), new MeshBasicMaterial(), 16)],
  }));
  /** What the field asked of the world: ground samples and tree searches. */
  const asked = { ground: 0, trees: 0 };
  const scatter = {
    cellsAround: () => {
      asked.trees += 1;
      return [0];
    },
    nodes: () => trees,
  } as unknown as Scatter;
  const stages = new NodeStages();
  const counted: PlaceOnGround = (unit, target) => {
    asked.ground += 1;
    return place(unit, target);
  };
  return {
    field: new StackField(looks, scatter, stages, counted),
    stages,
    asked,
    meshes: new Map(looks.map((look) => [look.look, look.meshes[0]])),
  };
}

const felled = (node: string, yaw: number) =>
  ({
    type: 'event',
    run_id: 'r',
    tick: 1,
    event: {
      id: `felled-${node}`,
      type: 'tree_felled',
      actor_id: 'bo',
      payload: { node, yaw_deg: yaw, logs: 10, stack: 'stack-38' },
      line: '',
      importance: 2,
      position: null,
    },
  }) as unknown as LiveMessage;

test("a felled tree's logs lie beside its stump along the fall once it lands, shorten as they are carried off and go", () => {
  const oak = tree('flora:40978', 20, 0);
  const { field: f, stages, meshes } = field([oak]);
  const logs = meshes.get('fallen_log')!;
  stages.apply(felled(oak.id, 90), 10); // heading 90: falls east
  f.set([stack('stack-38', 'wood', 10, oak.position)], 10);
  f.frame(FOCUS, false, 10 + FALL_SECONDS * 0.75);
  expect(f.drawn()).toEqual([]); // the tree is still falling
  expect(logs.visible).toBe(false);

  f.frame(FOCUS, false, 10 + FALL_SECONDS);
  const [pile] = f.drawn();
  expect([pile.ids, pile.look, pile.tree, pile.count]).toEqual([
    ['stack-38'],
    'fallen_log',
    oak.id,
    10,
  ]);
  expect(meshes.get('firewood')!.visible).toBe(false); // not as a woodpile too
  const fall = tangentFrame(oak.position).east;
  const offset = new Vector3(...pile.position).sub(oak.position);
  expect(offset.dot(fall)).toBeCloseTo(2, 3);
  expect(offset.length()).toBeCloseTo(2, 3);
  f.frame(FOCUS, false, 11 + FALL_SECONDS); // grown in
  expect(f.drawn()[0].scale).toBeCloseTo(1, 6);
  const whole = logs.getMatrixAt(0, new Matrix4());
  const along = new Vector3().setFromMatrixColumn(whole, 0);
  expect(along.clone().normalize().dot(fall)).toBeCloseTo(1, 4);
  expect(along.length()).toBeCloseTo(1, 6);

  // four of the ten carried off: the logs shorten (along the fall only) to six tenths
  f.set([stack('stack-38', 'wood', 6, oak.position)], 20);
  f.frame(FOCUS, false, 20 + EASE_SECONDS / 4);
  const easing = f.drawn()[0].scale;
  expect(easing).toBeLessThan(1);
  expect(easing).toBeGreaterThan(0.6);
  f.frame(FOCUS, false, 20 + EASE_SECONDS);
  expect(f.drawn()[0].count).toBe(6);
  expect(f.drawn()[0].scale).toBeCloseTo(0.6, 6);
  const shorter = logs.getMatrixAt(0, new Matrix4());
  expect(new Vector3().setFromMatrixColumn(shorter, 0).length()).toBeCloseTo(
    0.6,
    6,
  );
  expect(new Vector3().setFromMatrixColumn(shorter, 1).length()).toBeCloseTo(
    1,
    6,
  );

  // the rest carried off: the logs shrink away and are gone
  f.set([], 30);
  f.frame(FOCUS, false, 30 + EASE_SECONDS / 2);
  expect(f.drawn()).toEqual([]);
  expect(logs.visible).toBe(true); // shrinking away
  expect(
    new Vector3()
      .setFromMatrixColumn(logs.getMatrixAt(0, new Matrix4()), 0)
      .length(),
  ).toBeLessThan(0.6);
  f.frame(FOCUS, false, 30 + EASE_SECONDS);
  expect(f.drawn()).toEqual([]);
  expect(logs.visible).toBe(false);
});

test("a page opened after the felling draws the logs at once, along the tree's table bearing", () => {
  const oak = { ...tree('flora:7', 15, 5), bearing: Math.PI }; // falls south
  const { field: f, meshes } = field([oak]);
  f.set([stack('stack-9', 'wood', 10, oak.position)], 0);
  f.frame(FOCUS, false, EASE_SECONDS);
  const [pile] = f.drawn();
  expect([pile.look, pile.tree, pile.scale]).toEqual(['fallen_log', oak.id, 1]);
  const offset = new Vector3(...pile.position).sub(oak.position);
  expect(offset.dot(tangentFrame(oak.position).south)).toBeCloseTo(2, 3);
  expect(meshes.get('fallen_log')!.count).toBe(1);
});

test('stacks lie as their item looks, one pile per item and spot, sized by count, within reach', () => {
  const oak = tree('flora:1', 40, 0);
  const { field: f, meshes } = field([oak]);
  const camp = at(5, 5);
  const remains = at(-10, 3);
  f.set(
    [
      // three loads of wood put down on one spot by the fire, and wood a metre off the oak's trunk
      stack('stack-5', 'wood', 2, camp),
      stack('stack-6', 'wood', 3, camp),
      stack('stack-17', 'wood', 1, camp),
      stack('stack-40', 'wood', 12, at(41, 0)),
      stack('stack-37', 'meat', 6, remains),
      stack('stack-50', 'flint', 5, at(0, -8)),
      stack('stack-51', 'mystery', 1, at(0, 8)),
      stack('stack-52', 'meat', 4, at(REACH + 30, 0)),
      // only wood on a trunk is a tree's logs
      stack('stack-53', 'hide', 1, oak.position),
    ],
    0,
  );
  f.frame(FOCUS, false, EASE_SECONDS);
  const drawn = new Map(f.drawn().map((pile) => [pile.ids.join(','), pile]));
  expect([...drawn.keys()].sort()).toEqual([
    'stack-37',
    'stack-40',
    'stack-5,stack-6,stack-17',
    'stack-50',
    'stack-51',
    'stack-53',
  ]); // the far meat is out of reach
  const woodpile = drawn.get('stack-5,stack-6,stack-17')!;
  expect([woodpile.look, woodpile.count, woodpile.tree]).toEqual([
    'firewood',
    6,
    null,
  ]);
  expect(woodpile.scale).toBeCloseTo(Math.cbrt(6 / 12), 6);
  expect(new Vector3(...woodpile.position).distanceTo(camp)).toBeLessThan(1e-6);
  const full = drawn.get('stack-40')!;
  expect([full.look, full.scale, full.tree]).toEqual(['firewood', 1, null]);
  const meat = drawn.get('stack-37')!;
  expect([meat.look, meat.scale]).toEqual(['meat', 1]);
  // beside the remains it was cut from, not under them
  expect(new Vector3(...meat.position).distanceTo(remains)).toBeCloseTo(0.8, 2);
  expect(drawn.get('stack-50')!.look).toBe('small_rock');
  expect(drawn.get('stack-51')!.look).toBe('grain_sack');
  expect([drawn.get('stack-53')!.look, drawn.get('stack-53')!.tree]).toEqual([
    'hide',
    null,
  ]);
  expect(meshes.get('firewood')!.count).toBe(2);
  expect(meshes.get('meat')!.count).toBe(1);
  expect(meshes.get('fallen_log')!.visible).toBe(false);
  // a pile's matrix scales every way with its count
  const scales = [0, 1]
    .map((slot) => meshes.get('firewood')!.getMatrixAt(slot, new Matrix4()))
    .map((m) => new Vector3().setFromMatrixColumn(m, 1).length())
    .sort();
  expect(scales[0]).toBeCloseTo(Math.cbrt(6 / 12), 6);
  expect(scales[1]).toBeCloseTo(1, 6);
});

test('nothing is drawn while the camera is too high', () => {
  const { field: f, meshes } = field();
  f.set([stack('stack-1', 'wood', 12, at(3, 0))], 0);
  f.frame(FOCUS, false, EASE_SECONDS);
  expect(meshes.get('firewood')!.visible).toBe(true);
  f.frame(FOCUS, true, 2 * EASE_SECONDS);
  expect(meshes.get('firewood')!.visible).toBe(false);
  expect(f.drawn()).toEqual([]);
  f.frame(FOCUS, false, 3 * EASE_SECONDS);
  expect(meshes.get('firewood')!.visible).toBe(true);
});

test("on a slope a felled tree's logs lie with both ends on the ground", () => {
  const half = assetSize(PROPS.fallen_log).x / 2;
  for (const rise of [-0.5, 0.35]) {
    const place = ground(rise);
    const oak = { ...tree('flora:40427', 20, 0), bearing: Math.PI / 2 }; // falls east
    const { field: f, meshes } = field([oak], place);
    f.set([stack('stack-26', 'wood', 10, oak.position)], 0);
    f.frame(FOCUS, false, EASE_SECONDS);
    const matrix = meshes.get('fallen_log')!.getMatrixAt(0, new Matrix4());
    for (const x of [-half, half]) {
      const end = new Vector3(x, 0, 0).applyMatrix4(matrix);
      const under = place(end.clone().normalize(), new Vector3());
      expect(end.distanceTo(under)).toBeLessThan(0.1);
    }
    // the log tilts with the ground: its far end that much higher (lower) over its length along the slope
    const near = new Vector3(-half, 0, 0).applyMatrix4(matrix);
    const far = new Vector3(half, 0, 0).applyMatrix4(matrix);
    expect(far.length() - near.length()).toBeCloseTo(
      (rise * 2 * half) / Math.hypot(1, rise),
      2,
    );
  }
});

test('flat looks lie along the slope, models stand up off the planet', () => {
  const rise = 0.5;
  const { field: f, meshes } = field([], ground(rise));
  f.set(
    [
      stack('stack-1', 'hide', 1, at(4, 2)),
      stack('stack-2', 'wood', 12, at(-4, 2)),
    ],
    0,
  );
  f.frame(FOCUS, false, EASE_SECONDS);
  const upOf = (look: StackLook) =>
    new Vector3()
      .setFromMatrixColumn(meshes.get(look)!.getMatrixAt(0, new Matrix4()), 1)
      .normalize();
  const up = tangentFrame(at(4, 2)).up;
  const slope = up
    .clone()
    .addScaledVector(tangentFrame(at(4, 2)).east, -rise)
    .normalize();
  expect(upOf('hide').dot(slope)).toBeGreaterThan(0.999);
  expect(upOf('firewood').dot(tangentFrame(at(-4, 2)).up)).toBeGreaterThan(
    0.9999,
  );
});

type StacksWindow = {
  __pebbleStacks?: {
    drawn: () => {
      ids: string[];
      look: string;
      tree: string | null;
      count: number;
      scale: number;
    }[];
    instances: () => Record<string, number>;
  };
  __pebbleNodes?: {
    drawn: () => {
      nodes: { id: string; look: string; position: number[] }[];
    } | null;
  };
  __pebbleMockLive: {
    sendNow: (
      type: string,
      actor: string,
      payload: Record<string, unknown>,
    ) => void;
    setStacks: (stacks: LiveStack[]) => void;
  };
};

/** Beside the berry bush south of the Elder grove; the oak flora:3935 stands just ahead (nodes.spec.ts). */
const BY_THE_OAK = '?mockLive=1&at=11.53,6.215,0';
const OAK = 'flora:3935';

test("on the globe, a felled tree's logs appear beside its stump and go when carried off", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  const world = await openGlobe(page, errors, BY_THE_OAK);
  const oakAt = async () =>
    page.evaluate(
      (id) =>
        (globalThis as unknown as StacksWindow).__pebbleNodes
          ?.drawn()
          ?.nodes.filter((node) => node.id === id) ?? [],
      OAK,
    );
  await expect
    .poll(async () => (await oakAt()).length, { timeout: 30_000 })
    .toBe(1);
  const [oak] = await oakAt();
  const trunk = new Vector3(...oak.position).normalize();
  const piles = () =>
    page.evaluate(() =>
      (globalThis as unknown as StacksWindow).__pebbleStacks!.drawn(),
    );
  const instances = () =>
    page.evaluate(() =>
      (globalThis as unknown as StacksWindow).__pebbleStacks!.instances(),
    );
  const lay = (count: number) =>
    page.evaluate(
      ([unit, n]) =>
        (globalThis as unknown as StacksWindow).__pebbleMockLive.setStacks(
          n > 0
            ? [
                {
                  id: 'stack-38',
                  item: 'wood',
                  count: n,
                  unit: unit as [number, number, number],
                  cell: 0,
                },
              ]
            : [],
        ),
      [trunk.toArray(), count] as const,
    );
  expect(await piles()).toEqual([]);

  // Bo fells the oak: it falls, and its ten logs land as a stack at the trunk
  await page.evaluate(
    (id) =>
      (globalThis as unknown as StacksWindow).__pebbleMockLive.sendNow(
        'tree_felled',
        'kenji',
        { node: id, yaw_deg: 90, logs: 10, stack: 'stack-38' },
      ),
    OAK,
  );
  await lay(10);
  await expect
    .poll(async () => (await piles()).map((p) => [p.look, p.tree, p.count]), {
      timeout: 5_000,
    })
    .toEqual([['fallen_log', OAK, 10]]);
  await expect.poll(async () => (await piles())[0].scale).toBeCloseTo(1, 3);
  expect((await instances()).fallen_log).toBe(1);
  expect((await oakAt()).map((node) => node.look)).toEqual(['tree_stump']);
  expect(Number(await world.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );

  // six carried off: the logs shorten; the rest carried off: they go
  await lay(4);
  await expect.poll(async () => (await piles())[0]?.scale).toBeCloseTo(0.4, 3);
  expect((await instances()).fallen_log).toBe(1);
  await lay(0);
  await expect.poll(async () => (await instances()).fallen_log).toBe(0);
  expect(await piles()).toEqual([]);
  expect((await oakAt()).map((node) => node.look)).toEqual(['tree_stump']);
  expect(errors).toEqual([]);
});
