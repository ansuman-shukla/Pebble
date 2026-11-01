import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import { BIOME_PROPS } from '../../src/lib/world/biome-props';
import type { FloraTable } from '../../src/lib/world/flora';
import { buildTerrain, decodeWorld } from '../../src/lib/world/globe';
import { createScatter, type Scatter } from '../../src/lib/world/scatter';
import backend from './fixtures/flora-points.json' with { type: 'json' };
import {
  DRAW_CALL_BUDGET,
  FLORA_URL,
  floraOf,
  openGlobe,
  WORLD_URL,
} from './globe-helpers';

/*
 * The node renderer on the real world (10 §5.2, plan L3): every node near the camera's focus is drawn exactly once,
 * at its position, as its look: low things out to 300 m, trees, deadwood and seams out to 500 m.
 */

const SMALL_REACH = 300;
const FAR_REACH = 500;
const SMALL = new Set(['berry_bush', 'root_patch', 'reed_bed', 'tree_stump']);
/** South of the Elder grove's centre, facing it: 25 berry bushes and 10 oaks, broadleaf forest around. */
const ELDER_GROVE = '?at=11.9,6,0';

let view: WorldView;
let flora: FloraTable;
let scatter: Scatter;

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  view = (await (await api.get(WORLD_URL)).json()) as WorldView;
  flora = floraOf(view, await (await api.get(FLORA_URL)).body());
  await api.dispose();
  scatter = createScatter({
    terrain: buildTerrain(decodeWorld(view)),
    seed: view.seed,
    frequency: view.frequency,
    biomeNames: view.biome_names,
    table: BIOME_PROPS,
    clearings: [],
    rivers: [],
    flora,
    places: view.places,
  });
});

interface DrawnNode {
  id: string;
  look: string;
  position: [number, number, number];
}
type Drawn = { focus: [number, number, number]; nodes: DrawnNode[] } | null;
/** The page's node hook (nodes.tsx). */
type NodesWindow = { __pebbleNodes?: { drawn: () => Drawn } };

test('every node within reach of the focus is drawn once, at its place, as its look', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors, ELDER_GROVE);
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            (globalThis as NodesWindow).__pebbleNodes?.drawn()?.nodes.length ??
            0,
        ),
      {
        timeout: 30_000,
      },
    )
    .toBeGreaterThan(100);
  const drawn = (await page.evaluate(() =>
    (globalThis as NodesWindow).__pebbleNodes!.drawn(),
  )) as NonNullable<Drawn>;
  const focus = new Vector3(...drawn.focus);
  const byId = new Map<string, DrawnNode[]>();
  for (const node of drawn.nodes)
    byId.set(node.id, [...(byId.get(node.id) ?? []), node]);

  const expected = scatter
    .cellsAround(focus, FAR_REACH + 60)
    .flatMap((cell) => scatter.nodes(cell))
    .filter((node) => {
      const distance = node.position.distanceTo(focus);
      return distance < (SMALL.has(node.kind) ? SMALL_REACH : FAR_REACH);
    });
  expect(
    expected.filter((node) => node.node === 'berry_bush').length,
  ).toBeGreaterThanOrEqual(25);
  const faults: string[] = [];
  for (const node of expected) {
    const shown = byId.get(node.id) ?? [];
    if (shown.length !== 1) {
      faults.push(`${node.id} drawn ${shown.length} times`);
      continue;
    }
    const [one] = shown;
    if (one.look !== node.kind) faults.push(`${node.id} drawn as ${one.look}`);
    const off =
      new Vector3(...one.position)
        .normalize()
        .angleTo(node.position.clone().normalize()) * view.radius_m;
    if (off > 0.05) faults.push(`${node.id} drawn ${off.toFixed(3)} m off`);
  }
  // and where the backend's own flora puts them (fixtures/flora-points.json, written by the backend)
  expect(view.generator_version).toBe(backend.generator_version);
  const points = new Map(Object.entries(backend.points));
  let matched = 0;
  for (const shown of drawn.nodes) {
    const unit = points.get(shown.id.replace('flora:', ''));
    if (!shown.id.startsWith('flora:') || !unit) continue;
    matched += 1;
    const off =
      new Vector3(...shown.position).normalize().angleTo(new Vector3(...unit)) *
      view.radius_m;
    if (off > 0.05)
      faults.push(
        `${shown.id} drawn ${off.toFixed(3)} m off the backend's point`,
      );
  }
  expect(matched).toBeGreaterThan(200);
  expect(faults).toEqual([]);
  // nothing else is drawn
  expect(drawn.nodes.length).toBe(expected.length);
  await expect(world).toHaveAttribute('data-draw-calls', /\d/);
  expect(Number(await world.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );
  expect(errors).toEqual([]);
});

/** JavaScript's own rounding (halves up), as the stage rule uses it. */
const round = (value: number) => Math.floor(value + 0.5);

/** Berry-red pixels on the scene canvas (browser code as a string: the test TypeScript has no DOM types). */
const BERRY_PIXELS = `(() => {
  const scene = document.querySelector('canvas[data-engine]');
  const copy = document.createElement('canvas');
  copy.width = scene.width;
  copy.height = scene.height;
  const context = copy.getContext('2d');
  context.drawImage(scene, 0, 0);
  const { data } = context.getImageData(0, 0, copy.width, copy.height);
  let red = 0;
  for (let i = 0; i < data.length; i += 4)
    if (data[i] > 70 && data[i] > 2.1 * data[i + 1] && data[i] > 2.5 * data[i + 2]) red += 1;
  return red;
})()`;

/** Beside one of the Elder grove's bushes (flora:3941), an oak (flora:3935) 3 m east, on the mock feed. */
const BY_THE_BUSH = '?mockLive=1&at=11.53,6.215,0';

type Sender = {
  __pebbleMockLive: {
    sendNow: (
      type: string,
      actor: string,
      payload: Record<string, unknown>,
    ) => void;
  };
};

test('a picked bush loses its fruit on screen, a felled tree is a stump within 3 s', async ({
  page,
}) => {
  const errors: string[] = [];
  await openGlobe(page, errors, BY_THE_BUSH);
  const drawnOf = (id: string) =>
    page.evaluate(
      (node) =>
        (globalThis as NodesWindow).__pebbleNodes
          ?.drawn()
          ?.nodes.filter((n) => n.id === node) ?? [],
      id,
    );
  const send = (type: string, payload: Record<string, unknown>) =>
    page.evaluate(
      ([t, p]) =>
        (globalThis as unknown as Sender).__pebbleMockLive.sendNow(
          t as string,
          'kenji',
          p as Record<string, unknown>,
        ),
      [type, payload] as const,
    );
  await expect
    .poll(async () => (await drawnOf('flora:3941')).length, { timeout: 30_000 })
    .toBe(1);
  await page.waitForTimeout(1000);
  const full = await page.evaluate<number>(BERRY_PIXELS);
  expect(full).toBeGreaterThan(30);

  /** The bush at `after` of 12 berries, once drawn: its fruit pieces and the berry-red pixels on screen. */
  const picked = async (after: number) => {
    await send('node_changed', {
      node: 'flora:3941',
      kind: 'berry_bush',
      item: 'berries',
      before: 12,
      after,
      stage: 'picked',
    });
    const pieces = round((9 * Math.round((8 * after) / 12)) / 8);
    await expect
      .poll(
        async () =>
          (
            (await drawnOf('flora:3941'))[0] as unknown as {
              stage: { pieces: number };
            }
          ).stage.pieces,
      )
      .toBe(pieces);
    await page.waitForTimeout(300);
    return page.evaluate<number>(BERRY_PIXELS);
  };
  // half the berries: 5 of the 9 fruit pieces show (measured 0.47 of the red), 7 berries 6 pieces (0.63); one
  // piece more or less falls outside these bands
  const half = await picked(6);
  const more = await picked(7);
  expect(half / full).toBeGreaterThan(0.4);
  expect(half / full).toBeLessThan(0.55);
  expect(more / full).toBeGreaterThan(0.56);
  expect(more / full).toBeLessThan(0.72);
  expect(await picked(0)).toBeLessThan(full / 3);

  await send('tree_felled', { node: 'flora:3935', yaw_deg: 90, logs: 10 });
  const felled = Date.now();
  await expect
    .poll(async () => (await drawnOf('flora:3935')).map((n) => n.look).sort(), {
      intervals: [100],
      timeout: 5000,
    })
    .toEqual(['tree_stump']); // its logs are the ground stack the feed sends (ground-stacks.spec.ts)
  expect(Date.now() - felled).toBeLessThanOrEqual(3000);
  expect(errors).toEqual([]);
});
