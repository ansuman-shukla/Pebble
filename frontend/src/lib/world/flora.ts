/*
 * The usable flora table (10 §1.1, D120): every tree, nut tree, berry bush, root patch, reed bed and deadwood pile
 * on the planet, from `GET /api/v1/world/flora`. An item's id is its index in the table (the simulation's node id
 * is `flora:<index>`, `floraNodeId`). Layout (backend `app/world/flora.py`), little-endian, struct of arrays over
 * n items sorted by cell:
 *
 *   cell u32 × n | east i8 × n | north i8 × n | kind u8 × n | scale u8 × n | yaw u8 × n
 *
 * An item lies `east`, `north` × OFFSET_STEP_M metres off its cell's centre in the cell's tangent frame, mapped
 * gnomonically at the planet radius; `kind` indexes `WorldPlaces.flora_kinds`; `scale` is hundredths of the drawn
 * size; `yaw` is 256ths of a turn, a compass bearing (0 north, 90° east) along which a felled tree falls.
 */
import { Vector3 } from 'three';

import { cellDirection, type Globe, tangentFrame } from './globe';

const FLORA_BYTES_PER_ITEM = 9;
export const OFFSET_STEP_M = 0.2;
const SCALE_STEP = 0.01;
const YAW_STEP = (Math.PI * 2) / 256;

export interface FloraTable {
  count: number;
  cell: Uint32Array;
  east: Int8Array;
  north: Int8Array;
  kind: Uint8Array;
  scale: Uint8Array;
  yaw: Uint8Array;
  /** Flora kind of each kind code (`flora_kinds`) and its node kind (`flora_nodes`). */
  kinds: readonly string[];
  nodes: readonly string[];
}

/** The table from the packed bytes and the kind lists of `/world/places`. */
export function decodeFlora(
  bytes: ArrayBuffer,
  kinds: readonly string[],
  nodes: readonly string[],
): FloraTable {
  if (bytes.byteLength % FLORA_BYTES_PER_ITEM)
    throw new Error(
      `a flora table is a multiple of ${FLORA_BYTES_PER_ITEM} bytes, got ${bytes.byteLength}`,
    );
  if (kinds.length !== nodes.length)
    throw new Error('flora_kinds and flora_nodes differ in length');
  const count = bytes.byteLength / FLORA_BYTES_PER_ITEM;
  const view = new DataView(bytes);
  const cell = new Uint32Array(count);
  for (let i = 0; i < count; i++) cell[i] = view.getUint32(i * 4, true);
  const column = <T>(index: number, make: (start: number) => T) =>
    make(count * (4 + index));
  const table: FloraTable = {
    count,
    cell,
    east: column(0, (start) => new Int8Array(bytes, start, count)),
    north: column(1, (start) => new Int8Array(bytes, start, count)),
    kind: column(2, (start) => new Uint8Array(bytes, start, count)),
    scale: column(3, (start) => new Uint8Array(bytes, start, count)),
    yaw: column(4, (start) => new Uint8Array(bytes, start, count)),
    kinds,
    nodes,
  };
  const unknown = table.kind.find((code) => code >= kinds.length);
  if (unknown !== undefined)
    throw new Error(`flora kind code ${unknown} is not in flora_kinds`);
  return table;
}

/** The packed bytes of a table (the backend's layout): mock worlds and tests build tables with it. */
export function packFlora(table: Omit<FloraTable, 'kinds' | 'nodes'>) {
  const { count } = table;
  const bytes = new ArrayBuffer(count * FLORA_BYTES_PER_ITEM);
  const view = new DataView(bytes);
  for (let i = 0; i < count; i++) view.setUint32(i * 4, table.cell[i], true);
  const out = new Uint8Array(bytes);
  [table.east, table.north, table.kind, table.scale, table.yaw].forEach(
    (column, index) =>
      out.set(
        new Uint8Array(column.buffer, column.byteOffset, count),
        count * (4 + index),
      ),
  );
  return bytes;
}

export const floraNodeId = (index: number) => `flora:${index}`;

/** The table index a node id names, or null for a node that isn't flora (a fixed feature). */
export function floraIndex(id: string) {
  const match = /^flora:(\d+)$/.exec(id);
  return match ? Number(match[1]) : null;
}

/** First index of each cell's items: items of cell c are [start(c), start(c + 1)) (the table is sorted by cell). */
export function floraRows(table: FloraTable, cellCount: number) {
  const starts = new Uint32Array(cellCount + 1);
  for (let i = 0; i < table.count; i++) starts[table.cell[i] + 1] += 1;
  for (let c = 0; c < cellCount; c++) starts[c + 1] += starts[c];
  for (let i = 1; i < table.count; i++)
    if (table.cell[i] < table.cell[i - 1])
      throw new Error('the flora table is not sorted by cell');
  return (cell: number): [number, number] => [starts[cell], starts[cell + 1]];
}

const centre = new Vector3();

/** Unit vector of item `index` (the simulation's node position). */
export function floraDirection(
  globe: Globe,
  table: FloraTable,
  index: number,
  target = new Vector3(),
) {
  cellDirection(globe, table.cell[index], centre);
  const { east, north } = tangentFrame(centre);
  return target
    .copy(centre)
    .multiplyScalar(globe.radius)
    .addScaledVector(east, table.east[index] * OFFSET_STEP_M)
    .addScaledVector(north, table.north[index] * OFFSET_STEP_M)
    .normalize();
}

/** The compass bearing of item `index` in radians (0 north, π/2 east). */
export const floraBearing = (table: FloraTable, index: number) =>
  table.yaw[index] * YAW_STEP;

/** The drawn-size factor of item `index`. */
export const floraScale = (table: FloraTable, index: number) =>
  table.scale[index] * SCALE_STEP;
