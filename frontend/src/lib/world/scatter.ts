/*
 * Deterministic biome props: every cell seeds its own random stream from (world seed, cell index), so a cell
 * always grows the same instances no matter when or from where it is scattered.
 */
import { Matrix4, Quaternion, Vector3 } from 'three';

import { kindScale, type PropKind } from './assets';
import type { BIOME_PROPS } from './biome-props';
import {
  cellDirection,
  type GlobeTerrain,
  tangentFrame,
  WATER_BIOMES,
} from './globe';

export interface ScatterInstance {
  kind: PropKind;
  /** World position of the model's base (sunk a little into slopes). */
  position: Vector3;
  /** Radians about the local up. */
  yaw: number;
  scale: number;
}

const Y_AXIS = new Vector3(0, 1, 0);
const upright = new Quaternion();
const yawTurn = new Quaternion();
const scaled = new Vector3();
const up = new Vector3();

/** The model matrix of an instance: standing on the local normal, yawed about it, at its drawn size. */
export function scatterMatrix(
  instance: ScatterInstance,
  target = new Matrix4(),
) {
  up.copy(instance.position).normalize();
  upright
    .setFromUnitVectors(Y_AXIS, up)
    .multiply(yawTurn.setFromAxisAngle(Y_AXIS, instance.yaw));
  return target.compose(
    instance.position,
    upright,
    scaled.setScalar(instance.scale * kindScale(instance.kind)),
  );
}

/** A disc of the surface kept free of props (a site), as a direction and a radius in metres. */
interface Clearing {
  direction: Vector3;
  radius: number;
}

export interface ScatterOptions {
  terrain: GlobeTerrain;
  seed: number;
  /** Grid frequency: perCell counts are for frequency 60 and scale with cell area. */
  frequency: number;
  biomeNames: readonly string[];
  table: typeof BIOME_PROPS;
  clearings: Clearing[];
  rivers: number[][];
}

/** How far props keep from a river's centre line, metres. */
const RIVER_CLEARANCE = 6;
/** Nothing grows on terrain steeper than this (cliffs): props would float on their downhill side. */
export const MAX_PROP_SLOPE_DEG = 40;
const MAX_TILT = 1 - Math.cos((MAX_PROP_SLOPE_DEG * Math.PI) / 180);
const REFERENCE_FREQUENCY = 60;

/** mulberry32: a small fast seeded generator, [0, 1). */
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

const cellSeed = (seed: number, cell: number) =>
  Math.imul(seed ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(cell + 1, 0xc2b2ae35);

function distanceToSegment(p: Vector3, a: Vector3, b: Vector3) {
  const ab = b.clone().sub(a);
  const t = Math.max(
    0,
    Math.min(1, p.clone().sub(a).dot(ab) / Math.max(ab.lengthSq(), 1e-12)),
  );
  return p.distanceTo(a.clone().addScaledVector(ab, t));
}

export function createScatter({
  terrain,
  seed,
  frequency,
  biomeNames,
  table,
  clearings,
  rivers,
}: ScatterOptions) {
  const { globe } = terrain;
  const { radius } = globe;
  /** Mean distance between neighbouring cells. */
  const spacing = (radius * 1.11) / frequency;
  const density = (REFERENCE_FREQUENCY / frequency) ** 2;
  const riverLinks = new Map<number, number[]>();
  for (const cells of rivers) {
    cells.forEach((cell, i) => {
      const links = riverLinks.get(cell) ?? [];
      if (i > 0) links.push(cells[i - 1]);
      if (i + 1 < cells.length) links.push(cells[i + 1]);
      riverLinks.set(cell, links);
    });
  }

  function nearRiver(point: Vector3, cell: number) {
    const unit = point.clone().normalize().multiplyScalar(radius);
    const a = new Vector3();
    const b = new Vector3();
    for (const owner of [cell, ...terrain.neighbours(cell)]) {
      for (const other of riverLinks.get(owner) ?? []) {
        cellDirection(globe, owner, a).multiplyScalar(radius);
        cellDirection(globe, other, b).multiplyScalar(radius);
        if (distanceToSegment(unit, a, b) < RIVER_CLEARANCE) return true;
      }
    }
    return false;
  }

  /** The instances growing in one cell (always the same for the same seed and cell). */
  function cell(index: number): ScatterInstance[] {
    const props =
      table[biomeNames[globe.biomes[index]] as keyof typeof BIOME_PROPS] ?? [];
    if (props.length === 0) return [];
    const centre = cellDirection(globe, index, new Vector3());
    if (
      clearings.some(
        (clearing) =>
          centre.angleTo(clearing.direction) * radius <
          clearing.radius + spacing,
      )
    )
      return [];
    const next = random(cellSeed(seed, index));
    const { east, north } = tangentFrame(centre);
    const instances: ScatterInstance[] = [];
    for (const { kind, perCell, scale } of props) {
      const expected = perCell * density;
      const count = Math.floor(expected + next());
      for (let k = 0; k < count; k++) {
        const angle = next() * Math.PI * 2;
        const distance = Math.sqrt(next()) * spacing * 0.55;
        const yaw = next() * Math.PI * 2;
        const size = scale[0] + (scale[1] - scale[0]) * next();
        const direction = centre
          .clone()
          .multiplyScalar(radius)
          .addScaledVector(east, Math.cos(angle) * distance)
          .addScaledVector(north, Math.sin(angle) * distance)
          .normalize();
        if (WATER_BIOMES.has(terrain.biomeAt(direction, index))) continue;
        if (
          clearings.some(
            (clearing) =>
              direction.angleTo(clearing.direction) * radius < clearing.radius,
          )
        )
          continue;
        const hit = terrain.locate(direction, index);
        if (hit.tilt > MAX_TILT) continue;
        const position = direction.multiplyScalar(
          radius + hit.height - 0.1 - hit.tilt * 2,
        );
        if (nearRiver(position, hit.cell)) continue;
        instances.push({ kind, position, yaw, scale: size });
      }
    }
    return instances;
  }

  /** Cells whose centre is within `distance` metres of a direction (breadth-first from the nearest cell). */
  function cellsAround(direction: Vector3, distance: number) {
    const unit = direction.clone().normalize();
    const start = terrain.nearestCell(unit);
    const found = [start];
    const seen = new Set(found);
    const at = new Vector3();
    for (let k = 0; k < found.length; k++) {
      for (const near of terrain.neighbours(found[k])) {
        if (seen.has(near)) continue;
        seen.add(near);
        if (cellDirection(globe, near, at).angleTo(unit) * radius <= distance)
          found.push(near);
      }
    }
    return found;
  }

  return { spacing, cell, cellsAround };
}

export type Scatter = ReturnType<typeof createScatter>;
