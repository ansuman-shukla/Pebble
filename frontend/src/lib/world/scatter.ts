/*
 * What stands on the wild ground, per cell. Nodes (10 §1.1): every usable thing exactly where the simulation has
 * it, from the flora table and the fixed mineral features, never cleared around sites. Decor (10 §5.2): biome
 * props nobody can use, deterministic per cell (a random stream seeded from the world seed and the cell index, so
 * a cell always grows the same instances whenever and from wherever it is scattered); decor keeps off sites,
 * rivers, roads and paths (their drawn middle lines), lake water (as drawn), nodes and their work spots, fixed
 * features (a waterhole's pool and bank), rock ground, and mineral hotspots (rocks).
 */
import { Matrix4, Quaternion, Vector3 } from 'three';

import { kindScale, type PropKind } from './assets';
import {
  type BIOME_PROPS,
  FEATURE_LOOKS,
  FLORA_LOOKS,
  nodeFootprint,
  ROCK_DECOR,
} from './biome-props';
import {
  type FloraTable,
  floraBearing,
  floraDirection,
  floraNodeId,
  floraRows,
  floraScale,
} from './flora';
import {
  cellDirection,
  type GlobeTerrain,
  tangentFrame,
  WATER_BIOMES,
} from './globe';
import { biomeGroundClaims, groundWeights } from './globe-mesh';
import { routeLines } from './ground-marks';
import { GROUND_LAYERS } from './ground-shader';
import { lakeSurface } from './water-mesh';
import { WATERHOLE_BANK_M } from './waterholes';
import type { WorldPlaces } from '@/lib/client/types.gen';

export interface ScatterInstance {
  kind: PropKind;
  /** World position of the model's base (sunk a little into slopes). */
  position: Vector3;
  /** Radians about the local up. */
  yaw: number;
  scale: number;
}

/** A usable thing: a flora item or a fixed feature (a mineral seam). */
export interface NodeInstance extends ScatterInstance {
  /** The simulation's node id: `flora:<index>` or the feature's id. */
  id: string;
  /** Its flora table index (null for a feature). */
  flora: number | null;
  /** Node kind (`tree`, `berry_bush`, `flint_seam`, ...). */
  node: string;
  /** Compass bearing (radians, 0 north, π/2 east) a felled tree falls along. */
  bearing: number;
  /** Radius (metres) of the ground it stands on. */
  footprint: number;
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

/** A disc of the surface kept free of decor (a site), as a direction and a radius in metres. */
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
  /** The usable flora (none: no flora nodes). */
  flora?: FloraTable;
  /** Roads and paths, fixed features and hotspots (none: decor keeps off none of them). */
  places?: Pick<WorldPlaces, 'roads' | 'features' | 'hotspots'>;
}

/** How far decor keeps from a river's centre line, metres. */
const RIVER_CLEARANCE = 6;
/** ... from a road's or path's drawn middle line: half its width + 1 m (the backend's flora keeps the same). */
export const ROAD_CLEARANCE: Record<string, number> = { road: 2.5, path: 1.75 };
/** ... above a lake's drawn water (metres; the backend's flora keeps the same). */
const LAKE_CLEARANCE = 0.3;
/** ... from a node's footprint: its work spots lie within SPOT_REACH of it, and decor keeps 1.2 m off a spot. */
const SPOT_REACH = 1;
export const NODE_CLEARANCE = SPOT_REACH + 1.2;
/** ... from a fixed feature that isn't drawn as a node (fishing spot, waterhole, den, signpost, marker). */
const FEATURE_CLEARANCE = 3;
/** ... from a waterhole's drawn pool (the backend's flora keeps the same). */
const POOL_CLEARANCE = WATERHOLE_BANK_M + 1;
/** No decor where the ground is mostly rock (10 §5.2). */
const MAX_DECOR_ROCK = 0.5;
/** Hotspots with these features are mineral hotspots: no decor rocks inside. */
const MINERALS = new Set(['flint_seam', 'obsidian_field', 'gold_pool']);
/** Nothing grows on terrain steeper than this (cliffs): props would float on their downhill side. */
export const MAX_PROP_SLOPE_DEG = 40;
const MAX_TILT = 1 - Math.cos((MAX_PROP_SLOPE_DEG * Math.PI) / 180);
const REFERENCE_FREQUENCY = 60;
const ROCK = GROUND_LAYERS.indexOf('rock');

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

/** A stable angle from an id (features have no yaw of their own). */
function idYaw(id: string) {
  let hash = 2166136261;
  for (let i = 0; i < id.length; i++)
    hash = Math.imul(hash ^ id.charCodeAt(i), 16777619);
  return ((hash >>> 0) / 4294967296) * Math.PI * 2;
}

function distanceToSegment(p: Vector3, a: Vector3, b: Vector3) {
  const ab = b.clone().sub(a);
  const t = Math.max(
    0,
    Math.min(1, p.clone().sub(a).dot(ab) / Math.max(ab.lengthSq(), 1e-12)),
  );
  return p.distanceTo(a.clone().addScaledVector(ab, t));
}

/** Polylines through cell centres (rivers), indexed by cell, each link with its clearance. */
function cellLinks(lines: { cells: number[]; clearance: number }[]) {
  const links = new Map<number, [number, number][]>();
  for (const { cells, clearance } of lines)
    cells.forEach((cell, i) => {
      const own = links.get(cell) ?? [];
      if (i > 0) own.push([cells[i - 1], clearance]);
      if (i + 1 < cells.length) own.push([cells[i + 1], clearance]);
      links.set(cell, own);
    });
  return links;
}

export function createScatter({
  terrain,
  seed,
  frequency,
  biomeNames,
  table,
  clearings,
  rivers,
  flora,
  places,
}: ScatterOptions) {
  const { globe } = terrain;
  const { radius } = globe;
  /** Mean distance between neighbouring cells. */
  const spacing = (radius * 1.11) / frequency;
  const density = (REFERENCE_FREQUENCY / frequency) ** 2;
  const lines = cellLinks(
    rivers.map((cells) => ({ cells, clearance: RIVER_CLEARANCE })),
  );
  // the roads' and paths' drawn middle lines in steps, by the cell nearest each step's end
  const routeSteps = new Map<number, [Vector3, Vector3, number][]>();
  let hint: number | undefined;
  for (const { kind, points } of routeLines(globe, places?.roads ?? []).lines)
    for (let i = 1; i < points.length; i++) {
      hint = terrain.nearestCell(points[i], hint);
      const steps = routeSteps.get(hint) ?? [];
      steps.push([
        points[i - 1].clone().multiplyScalar(radius),
        points[i].clone().multiplyScalar(radius),
        ROAD_CLEARANCE[kind],
      ]);
      routeSteps.set(hint, steps);
    }
  const claims = biomeNames.map(biomeGroundClaims);
  const weights = new Float64Array(GROUND_LAYERS.length);
  const rows = flora ? floraRows(flora, globe.cellCount) : null;
  const featureNodes = new Map<number, NodeInstance[]>();
  const featureMarks = new Map<
    number,
    { direction: Vector3; clear: number }[]
  >();
  for (const feature of places?.features ?? []) {
    const direction = new Vector3(...feature.position).normalize();
    const look = FEATURE_LOOKS[feature.kind];
    if (look) {
      const node = placed(feature.cell, direction, {
        kind: look,
        yaw: idYaw(feature.id),
        scale: 1,
        id: feature.id,
        flora: null,
        node: feature.kind,
        bearing: 0,
        footprint: nodeFootprint(feature.kind, look, 1),
      });
      featureNodes.set(feature.cell, [
        ...(featureNodes.get(feature.cell) ?? []),
        node,
      ]);
    } else
      featureMarks.set(feature.cell, [
        ...(featureMarks.get(feature.cell) ?? []),
        { direction, clear: feature.pool ? POOL_CLEARANCE : FEATURE_CLEARANCE },
      ]);
  }
  const mineralHotspots = (places?.hotspots ?? [])
    .filter((hotspot) =>
      places!.features.some(
        (feature) =>
          feature.hotspot === hotspot.id && MINERALS.has(feature.kind),
      ),
    )
    .map((hotspot) => ({
      direction: new Vector3(...hotspot.centre),
      radius: hotspot.radius_m,
    }));
  const nodeCache = new Map<number, NodeInstance[]>();

  /** A node standing on the terrain at `direction` (sunk a little into slopes, like decor). */
  function placed(
    cell: number,
    direction: Vector3,
    node: Omit<NodeInstance, 'position'>,
  ): NodeInstance {
    const hit = terrain.locate(direction, cell);
    return {
      ...node,
      position: direction
        .clone()
        .multiplyScalar(radius + hit.height - 0.1 - hit.tilt * 2),
    };
  }

  /** The usable things in one cell: its flora items and fixed mineral features (cached). */
  function nodes(index: number): NodeInstance[] {
    let found = nodeCache.get(index);
    if (found) return found;
    found = [...(featureNodes.get(index) ?? [])];
    if (flora && rows) {
      const [start, end] = rows(index);
      for (let i = start; i < end; i++) {
        const node = flora.nodes[flora.kind[i]];
        const kind = FLORA_LOOKS[flora.kinds[flora.kind[i]]];
        if (!kind)
          throw new Error(
            `no look for flora kind ${flora.kinds[flora.kind[i]]}`,
          );
        const scale = floraScale(flora, i);
        const bearing = floraBearing(flora, i);
        found.push(
          placed(index, floraDirection(globe, flora, i), {
            kind,
            yaw: bearing,
            scale,
            id: floraNodeId(i),
            flora: i,
            node,
            bearing,
            footprint: nodeFootprint(node, kind, scale),
          }),
        );
      }
    }
    nodeCache.set(index, found);
    return found;
  }

  function nearLine(point: Vector3, cell: number) {
    const unit = point.clone().normalize().multiplyScalar(radius);
    const a = new Vector3();
    const b = new Vector3();
    for (const owner of [cell, ...terrain.neighbours(cell)]) {
      for (const [other, clearance] of lines.get(owner) ?? []) {
        cellDirection(globe, owner, a).multiplyScalar(radius);
        cellDirection(globe, other, b).multiplyScalar(radius);
        if (distanceToSegment(unit, a, b) < clearance) return true;
      }
      for (const [from, to, clearance] of routeSteps.get(owner) ?? [])
        if (distanceToSegment(unit, from, to) < clearance) return true;
    }
    return false;
  }

  /** Within reach of a node (its footprint + NODE_CLEARANCE) or of a fixed feature. */
  function nearNode(direction: Vector3, cell: number) {
    for (const owner of [cell, ...terrain.neighbours(cell)]) {
      for (const node of nodes(owner)) {
        const clear = node.footprint + NODE_CLEARANCE;
        if (direction.angleTo(node.position) * radius < clear) return true;
      }
      for (const mark of featureMarks.get(owner) ?? [])
        if (direction.angleTo(mark.direction) * radius < mark.clear)
          return true;
    }
    return false;
  }

  /** The decor growing in one cell (always the same for the same seed, cell and world). */
  function decor(index: number): ScatterInstance[] {
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
        if (hit.height < lakeSurface(globe, hit.triangle) + LAKE_CLEARANCE)
          continue;
        groundWeights(
          {
            claims: claims[globe.biomes[hit.cell]],
            slope: (Math.acos(1 - hit.tilt) * 180) / Math.PI,
            height: hit.height,
            lakeLevel: Infinity,
          },
          weights,
        );
        if (weights[ROCK] > MAX_DECOR_ROCK) continue;
        if (
          ROCK_DECOR.has(kind) &&
          mineralHotspots.some(
            (hotspot) =>
              direction.angleTo(hotspot.direction) * radius < hotspot.radius,
          )
        )
          continue;
        if (nearNode(direction, index)) continue;
        const position = direction.multiplyScalar(
          radius + hit.height - 0.1 - hit.tilt * 2,
        );
        if (nearLine(position, hit.cell)) continue;
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

  /** Everything standing in one cell, decor and nodes (what the walker collides with). */
  const cell = (index: number): ScatterInstance[] => [
    ...decor(index),
    ...nodes(index),
  ];

  return { spacing, cell, decor, nodes, cellsAround };
}

export type Scatter = ReturnType<typeof createScatter>;
