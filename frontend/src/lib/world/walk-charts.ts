/*
 * What the globe walker collides with outside the town: camp and landmark placements (Polyfork colliders,
 * each standing on the terrain under it like the rendered model) and the scattered decor and nodes near the
 * player (trees, rocks, bushes; ground cover never blocks), all in a chart's local metres.
 */
import { Matrix4, Vector3 } from 'three';

import { PROPS } from './assets';
import { BLOCKING_KINDS } from './biome-props';
import {
  buildWalkWorld,
  type ColliderFile,
  type PlacementLift,
  type Point,
  type Shape,
  shapesOf,
  type WalkPlacement,
  type WalkWater,
  type WalkWorld,
} from './collision';
import { anchorMapping, type GlobeTerrain, type SiteMapping } from './globe';
import type { WalkChart, WildBlockers } from './globe-walk';
import { type Scatter, type ScatterInstance, scatterMatrix } from './scatter';
import type { Site } from '@/lib/client/types.gen';

const BLOCKING = new Set(BLOCKING_KINDS);

/** Asset ids of the blocking scattered kinds (their colliders must be loaded). */
export const BLOCKING_SCATTER_ASSETS = BLOCKING_KINDS.map(
  (kind) => PROPS[kind],
);

/** Local height of a placement's base when it stands on the terrain under it (camps and landmarks). */
export function terrainLift(
  terrain: GlobeTerrain,
  mapping: SiteMapping,
  height: number,
): PlacementLift {
  const at = new Vector3();
  return (placement) =>
    terrain.heightAt(mapping.toWorld(placement.x, 0, placement.z, at)) - height;
}

/** Collider shapes of the blocking scattered props within `reach` metres of `center`, in `mapping`'s metres. */
export function createWildBlockers(
  scatter: Scatter,
  colliders: ReadonlyMap<string, ColliderFile>,
  radius: number,
): WildBlockers {
  const cells = new Map<number, ScatterInstance[]>();
  const model = new Matrix4();
  const vertex = new Vector3();
  const local = new Vector3();
  return (mapping, center, reach) => {
    const shapes: Shape[] = [];
    for (const cell of scatter.cellsAround(center, reach + scatter.spacing)) {
      let grown = cells.get(cell);
      if (!grown) {
        grown = scatter
          .cell(cell)
          .filter((instance) => BLOCKING.has(instance.kind));
        cells.set(cell, grown);
      }
      grown.forEach((instance, index) => {
        if (instance.position.angleTo(center) * radius > reach) return;
        const file = colliders.get(PROPS[instance.kind]);
        if (!file)
          throw new Error(`colliders for ${instance.kind} are not loaded`);
        scatterMatrix(instance, model);
        shapes.push(
          ...shapesOf(`scatter-${cell}-${index}`, file.parts, ([x, y, z]) => {
            mapping.toLocal(vertex.set(x, y, z).applyMatrix4(model), local);
            return [local.x, local.y, local.z];
          }),
        );
      });
    }
    return shapes;
  };
}

/** The town on the globe as the walker needs it. */
export interface WalkTown {
  mapping: SiteMapping;
  /** Plateau height h0. */
  height: number;
  placements: WalkPlacement[];
  water: WalkWater[];
  /** Radius of the town's own ground disc (local metres). */
  groundRadius: number;
}

/** How far past its ground disc the town's collisions still apply. */
const TOWN_CHART_MARGIN = 15;
/** A camp's or landmark's chart reaches this far past its outermost placement. */
const SITE_CHART_MARGIN = 20;

/** How the player gets onto the town's walkable surfaces (bridge, paving). */
export interface TownSurfaces {
  /** Height of the walkable ground at a local point of the town's world, probing down from fromY. */
  heightAt: (world: WalkWorld, point: Point, fromY: number) => number;
  maxStepUp: number;
  probeHeight: number;
}

/** The town's chart: walls, gates and moat, and its plateau with walkable surfaces. */
export function townChart(
  town: WalkTown,
  colliders: ReadonlyMap<string, ColliderFile>,
  surfaces: TownSurfaces,
): WalkChart {
  const world = buildWalkWorld(town.placements, town.water, colliders);
  return {
    id: 'town',
    mapping: town.mapping,
    world,
    height: town.height,
    radius: town.groundRadius + TOWN_CHART_MARGIN,
    ground: {
      radius: town.groundRadius,
      groundAt: (point, fromY) => surfaces.heightAt(world, point, fromY),
      maxStepUp: surfaces.maxStepUp,
      probeHeight: surfaces.probeHeight,
    },
  };
}

/** A chart per camp and landmark with placements: its placements on the terrain and the trees around it. */
export function siteCharts(
  terrain: GlobeTerrain,
  sites: Site[],
  colliders: ReadonlyMap<string, ColliderFile>,
  wild: WildBlockers,
): WalkChart[] {
  const radius = terrain.globe.radius;
  return sites
    .filter((site) => site.kind !== 'town' && (site.placements ?? []).length)
    .map((site): WalkChart => {
      const placements = site.placements ?? [];
      const mapping = anchorMapping(site.anchor, radius);
      const height = site.anchor.height_m;
      const reach =
        Math.max(...placements.map(({ x, z }) => Math.hypot(x, z))) +
        SITE_CHART_MARGIN;
      const trees = wild(mapping, new Vector3(...site.anchor.position), reach);
      return {
        id: site.id,
        mapping,
        height,
        radius: reach,
        world: buildWalkWorld(
          placements,
          [],
          colliders,
          terrainLift(terrain, mapping, height),
          trees,
        ),
      };
    });
}

/** Ground height under a direction as it is drawn: the town's own disc, else the terrain. */
export function groundUnder(
  terrain: GlobeTerrain,
  town: WalkTown,
  direction: Vector3,
  scratch: Vector3,
) {
  town.mapping.toLocal(scratch.copy(direction), scratch);
  return Math.hypot(scratch.x, scratch.z) < town.groundRadius
    ? town.height
    : terrain.heightAt(direction);
}
