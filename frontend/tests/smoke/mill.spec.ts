import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

import type { TownView } from '../../src/lib/client/types.gen';
import manifest from '../../src/lib/world/asset-manifest.json' with { type: 'json' };
import { assetBaseY, PROPS } from '../../src/lib/world/assets';
import { TOWN_WATER_Y } from '../../src/lib/world/ground-shape';
import { TOWN_URL } from './explore-helpers';

/* The mill (10 §5.3): its wheel turns in the mill stream, not on the bank beside it. */

const ROOT = path.resolve(import.meta.dirname, '../..');
/** The wheel's paddle width (the model's `width` default, metres). */
const PADDLE_WIDTH = 0.88;

interface GlbNode {
  name?: string;
  mesh?: number;
  translation?: number[];
  children?: number[];
}
interface Glb {
  nodes: GlbNode[];
  meshes: { primitives: { attributes: { POSITION: number } }[] }[];
  accessors: { min?: number[]; max?: number[] }[];
}

/** The wheel's hub (model metres) and its radius, from the GLB. */
function wheelOfModel() {
  const asset = manifest.assets.find(({ id }) => id === PROPS.water_wheel)!;
  const glb = readFileSync(path.join(ROOT, asset.files.glb.path));
  const json = JSON.parse(
    glb.subarray(20, 20 + glb.readUInt32LE(12)).toString('utf8'),
  ) as Glb;
  const wheel = json.nodes.find((node) => node.name === 'wheel')!;
  const mesh = json.nodes[wheel.children![0]].mesh!;
  const bounds =
    json.accessors[json.meshes[mesh].primitives[0].attributes.POSITION];
  return { hub: wheel.translation!, radius: bounds.max![1] };
}

function inside([x, z]: [number, number], polygon: [number, number][]) {
  let hit = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, zi] = polygon[i];
    const [xj, zj] = polygon[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi)
      hit = !hit;
  }
  return hit;
}

test('the mill wheel turns in the stream, dipping into its water', async ({
  playwright,
}) => {
  const api = await playwright.request.newContext();
  const town = (await (await api.get(TOWN_URL)).json()) as TownView;
  await api.dispose();
  const mill = town.placements.find(({ kind }) => kind === 'water_wheel')!;
  const stream = town.water.find(({ kind }) => kind === 'stream')!;
  const { hub, radius } = wheelOfModel();
  // the wheel turns in the model's x-y plane: its footprint is the disc's span along x by the paddles' width
  const yaw = (mill.rotation_deg * Math.PI) / 180;
  const corners = [-1, 1].flatMap((sx) =>
    [-1, 1].map((sz): [number, number] => {
      const [x, z] = [hub[0] + sx * radius, hub[2] + (sz * PADDLE_WIDTH) / 2];
      // a turn by yaw about up (three.js): x' = x cos + z sin, z' = -x sin + z cos
      return [
        mill.x + x * Math.cos(yaw) + z * Math.sin(yaw),
        mill.z - x * Math.sin(yaw) + z * Math.cos(yaw),
      ];
    }),
  );
  for (const corner of corners)
    expect(inside(corner, stream.polygon), `wheel corner ${corner}`).toBe(true);
  const bottom = assetBaseY(PROPS.water_wheel) + hub[1] - radius;
  expect(bottom).toBeLessThan(TOWN_WATER_Y);
});
