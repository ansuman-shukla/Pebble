/*
 * DEV/TEST ONLY: a flora table for the mock world (`?mock=1`), which has no backend to serve one. Same kinds and
 * per-cell densities as the backend's `data/world/flora.yaml` (natural flora only: no hotspots or home rings),
 * placed per cell by a seeded stream like the backend, so mock pages keep their forests.
 */
import { Vector3 } from 'three';

import { type FloraTable, OFFSET_STEP_M } from './flora';
import { cellDirection, type Globe, tangentFrame, WATER_BIOMES } from './globe';

const KINDS: [string, string, [number, number]][] = [
  ['oak_tree', 'tree', [0.85, 1.35]],
  ['birch_tree', 'tree', [0.85, 1.25]],
  ['pine_tree', 'tree', [0.8, 1.3]],
  ['young_pine', 'tree', [0.7, 1.2]],
  ['snowy_spruce', 'tree', [0.8, 1.2]],
  ['acacia_tree', 'tree', [0.8, 1.3]],
  ['dwarf_pine', 'tree', [0.5, 1.0]],
  ['tree_fern', 'tree', [0.8, 1.2]],
  ['nut_oak', 'nut_tree', [0.95, 1.35]],
  ['berry_bush', 'berry_bush', [0.8, 1.2]],
  ['root_patch', 'root_patch', [0.8, 1.2]],
  ['reed_bed', 'reed_bed', [0.8, 1.2]],
  ['fallen_log', 'deadwood', [0.9, 1.2]],
  ['driftwood', 'deadwood', [0.8, 1.2]],
  ['dead_tree', 'deadwood', [0.8, 1.2]],
];

const PER_CELL: Record<string, Record<string, number>> = {
  beach: { driftwood: 0.6 },
  grassland: {
    oak_tree: 0.4,
    nut_oak: 0.03,
    berry_bush: 0.05,
    root_patch: 0.05,
    fallen_log: 0.05,
  },
  broadleaf_forest: {
    oak_tree: 4.5,
    birch_tree: 2.7,
    nut_oak: 0.15,
    berry_bush: 0.25,
    root_patch: 0.05,
    fallen_log: 0.3,
  },
  taiga: {
    pine_tree: 7,
    young_pine: 3,
    snowy_spruce: 0.5,
    berry_bush: 0.2,
    fallen_log: 0.3,
  },
  wetland: {
    birch_tree: 1,
    tree_fern: 0.6,
    reed_bed: 1.5,
    root_patch: 0.5,
    berry_bush: 0.3,
    dead_tree: 0.4,
  },
  hills: { oak_tree: 0.3, berry_bush: 0.05, root_patch: 0.03 },
  mountain: { dwarf_pine: 0.6, snowy_spruce: 0.3 },
  savanna: { acacia_tree: 0.8, root_patch: 0.1, dead_tree: 0.15 },
  tundra: { dwarf_pine: 1.5, berry_bush: 0.1 },
  snow: { snowy_spruce: 1.5 },
  volcanic: { dead_tree: 0.3 },
};

/** Densities are for frequency 60 cells, like the backend's. */
const REFERENCE_FREQUENCY = 60;

/** mulberry32. */
function random(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Natural flora on every land cell outside `clearings` (direction + radius in metres). */
export function mockFlora(
  globe: Globe,
  biomeNames: readonly string[],
  frequency: number,
  seed: number,
  clearings: { direction: Vector3; radius: number }[],
): FloraTable {
  const spacing = (globe.radius * 1.11) / frequency;
  const density = (REFERENCE_FREQUENCY / frequency) ** 2;
  const codes = new Map(KINDS.map(([kind], code) => [kind, code]));
  const next = random(seed ^ 0x5eed);
  const items: number[][] = [];
  const centre = new Vector3();
  const at = new Vector3();
  for (let cell = 0; cell < globe.cellCount; cell++) {
    if (WATER_BIOMES.has(globe.biomes[cell])) continue;
    const table = PER_CELL[biomeNames[globe.biomes[cell]]] ?? {};
    cellDirection(globe, cell, centre);
    const { east, north } = tangentFrame(centre);
    for (const [kind, perCell] of Object.entries(table)) {
      const count = Math.floor(perCell * density + next());
      for (let k = 0; k < count; k++) {
        const angle = next() * Math.PI * 2;
        const distance = Math.sqrt(next()) * spacing * 0.55;
        const e = Math.round((Math.cos(angle) * distance) / OFFSET_STEP_M);
        const n = Math.round((Math.sin(angle) * distance) / OFFSET_STEP_M);
        at.copy(centre)
          .multiplyScalar(globe.radius)
          .addScaledVector(east, e * OFFSET_STEP_M)
          .addScaledVector(north, n * OFFSET_STEP_M)
          .normalize();
        const scale = next();
        const yaw = Math.floor(next() * 256);
        if (
          clearings.some(
            (c) => at.angleTo(c.direction) * globe.radius < c.radius,
          )
        )
          continue;
        const code = codes.get(kind)!;
        const [low, high] = KINDS[code][2];
        items.push([
          cell,
          e,
          n,
          code,
          Math.round((low + (high - low) * scale) * 100),
          yaw,
        ]);
      }
    }
  }
  const column = <T extends Uint32Array | Int8Array | Uint8Array>(
    make: new (length: number) => T,
    field: number,
  ) => {
    const out = new make(items.length);
    items.forEach((item, i) => (out[i] = item[field]));
    return out;
  };
  return {
    count: items.length,
    cell: column(Uint32Array, 0),
    east: column(Int8Array, 1),
    north: column(Int8Array, 2),
    kind: column(Uint8Array, 3),
    scale: column(Uint8Array, 4),
    yaw: column(Uint8Array, 5),
    kinds: KINDS.map(([kind]) => kind),
    nodes: KINDS.map(([, node]) => node),
  };
}
