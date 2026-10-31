import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  decodeFlora,
  type FloraTable,
  floraBearing,
  floraDirection,
  floraIndex,
  floraNodeId,
  floraRows,
  floraScale,
  OFFSET_STEP_M,
  packFlora,
} from '../../src/lib/world/flora';
import {
  cellDirection,
  decodeWorld,
  type Globe,
  tangentFrame,
} from '../../src/lib/world/globe';
import { FLORA_URL, floraOf, WORLD_URL } from './globe-helpers';

/*
 * The flora table (10 §1.1, D120): decoded from the backend's packed bytes, every item where the simulation has
 * it. The backend counts hotspots and home rings exactly by position, so the decoded positions must reproduce its
 * counts: the Elder grove's 25 berry bushes and 10 nut trees, each camp's home ring of 8 bushes, 8 root patches and
 * 6 deadwood piles.
 */

const KINDS = ['oak_tree', 'berry_bush', 'fallen_log'];
const NODES = ['tree', 'berry_bush', 'deadwood'];

function small(): Omit<FloraTable, 'kinds' | 'nodes'> {
  return {
    count: 4,
    cell: Uint32Array.from([3, 3, 7, 70_000]),
    east: Int8Array.from([-127, 0, 5, 127]),
    north: Int8Array.from([12, -3, 0, -128]),
    kind: Uint8Array.from([0, 1, 2, 1]),
    scale: Uint8Array.from([85, 100, 120, 255]),
    yaw: Uint8Array.from([0, 64, 128, 255]),
  };
}

test('a packed table decodes to the same columns, little-endian', () => {
  const table = small();
  const bytes = packFlora(table);
  expect(bytes.byteLength).toBe(36);
  // cell u32 little-endian first: 70 000 = 0x00011170
  expect([...new Uint8Array(bytes, 12, 4)]).toEqual([0x70, 0x11, 0x01, 0x00]);
  // then east i8 × n: -127 as a byte
  expect(new Uint8Array(bytes)[16]).toBe(0x81);
  const decoded = decodeFlora(bytes, KINDS, NODES);
  expect(decoded.count).toBe(4);
  // yaw is 256ths of a turn from north, scale hundredths
  expect(floraBearing(decoded, 1)).toBeCloseTo(Math.PI / 2, 9);
  expect(floraBearing(decoded, 2)).toBeCloseTo(Math.PI, 9);
  expect(floraScale(decoded, 0)).toBeCloseTo(0.85, 9);
  expect(floraScale(decoded, 3)).toBeCloseTo(2.55, 9);
  for (const column of [
    'cell',
    'east',
    'north',
    'kind',
    'scale',
    'yaw',
  ] as const)
    expect([...decoded[column]], column).toEqual([...table[column]]);
});

test('a table that is not whole items or names an unknown kind is refused', () => {
  expect(() => decodeFlora(new ArrayBuffer(10), KINDS, NODES)).toThrow(
    /multiple of 9/,
  );
  const table = small();
  table.kind[2] = 3;
  expect(() => decodeFlora(packFlora(table), KINDS, NODES)).toThrow(
    /kind code 3/,
  );
  expect(() => decodeFlora(packFlora(small()), KINDS, ['tree'])).toThrow(
    /length/,
  );
});

test('rows give each cell its items and node ids name table indexes', () => {
  const decoded = decodeFlora(packFlora(small()), KINDS, NODES);
  const rows = floraRows(decoded, 70_001);
  expect(rows(3)).toEqual([0, 2]);
  expect(rows(4)).toEqual([2, 2]);
  expect(rows(7)).toEqual([2, 3]);
  expect(rows(70_000)).toEqual([3, 4]);
  const unsorted = small();
  unsorted.cell[1] = 1;
  expect(() =>
    floraRows(decodeFlora(packFlora(unsorted), KINDS, NODES), 70_001),
  ).toThrow(/sorted/);
  expect(floraNodeId(41_036)).toBe('flora:41036');
  expect(floraIndex('flora:41036')).toBe(41_036);
  expect(floraIndex('elder_grove:den')).toBeNull();
  expect(floraIndex('flora:')).toBeNull();
});

test('an item lies its offset steps east and north of its cell centre', () => {
  const globe: Globe = {
    radius: 2000,
    cellCount: 1,
    positions: Float32Array.from([0.6, 0.48, 0.64]),
    heights: Float32Array.from([0]),
    biomes: Uint8Array.from([3]),
    triangles: new Uint32Array(0),
  };
  const table = decodeFlora(
    packFlora({
      count: 1,
      cell: Uint32Array.from([0]),
      east: Int8Array.from([50]),
      north: Int8Array.from([-25]),
      kind: Uint8Array.from([0]),
      scale: Uint8Array.from([100]),
      yaw: Uint8Array.from([0]),
    }),
    KINDS,
    NODES,
  );
  const centre = cellDirection(globe, 0, new Vector3());
  const { east, north } = tangentFrame(centre);
  const offset = floraDirection(globe, table, 0)
    .multiplyScalar(2000 / floraDirection(globe, table, 0).dot(centre))
    .sub(centre.clone().multiplyScalar(2000));
  expect(offset.dot(east)).toBeCloseTo(50 * OFFSET_STEP_M, 6);
  expect(offset.dot(north)).toBeCloseTo(-25 * OFFSET_STEP_M, 6);
});

test.describe('on the real world', () => {
  let view: WorldView;
  let globe: Globe;
  let flora: FloraTable;

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext();
    view = (await (await api.get(WORLD_URL)).json()) as WorldView;
    flora = floraOf(view, await (await api.get(FLORA_URL)).body());
    await api.dispose();
    globe = decodeWorld(view);
  });

  /** Items of a node kind within `radius` metres of a unit vector. */
  function countWithin(centre: Vector3, radius: number, node: string) {
    const at = new Vector3();
    let count = 0;
    for (let i = 0; i < flora.count; i++) {
      if (flora.nodes[flora.kind[i]] !== node) continue;
      if (
        floraDirection(globe, flora, i, at).angleTo(centre) * globe.radius <=
        radius
      )
        count += 1;
    }
    return count;
  }

  test('the Elder grove holds exactly its 25 berry bushes and 10 nut trees', () => {
    const grove = view.places.hotspots.find((h) => h.id === 'elder_grove')!;
    const centre = new Vector3(...grove.centre);
    expect(countWithin(centre, grove.radius_m, 'berry_bush')).toBe(25);
    expect(countWithin(centre, grove.radius_m, 'nut_tree')).toBe(10);
  });

  test("each camp's home ring holds exactly 8 berry bushes, 8 root patches and 6 deadwood piles", () => {
    const camps = view.sites.filter((site) => site.kind === 'camp');
    expect(camps.length).toBe(2);
    for (const camp of camps) {
      const centre = new Vector3(...camp.anchor.position);
      expect(countWithin(centre, 400, 'berry_bush'), camp.id).toBe(8);
      expect(countWithin(centre, 400, 'root_patch'), camp.id).toBe(8);
      expect(countWithin(centre, 400, 'deadwood'), camp.id).toBe(6);
    }
  });
});
