import { readFileSync } from 'node:fs';
import path from 'node:path';

import { Vector3 } from 'three';

import manifest from '../../src/lib/world/asset-manifest.json' with { type: 'json' };
import type { Site, TownView, WorldView } from '../../src/lib/client/types.gen';
import { BIOME_PROPS } from '../../src/lib/world/biome-props';
import {
  colliderIdsOf,
  type ColliderFile,
  type Point,
} from '../../src/lib/world/collision';
import {
  anchorMapping,
  buildTerrain,
  decodeWorld,
  type GlobeTerrain,
  type SiteMapping,
  tangent,
} from '../../src/lib/world/globe';
import {
  createGlobeWalk,
  type GlobeWalk,
  type WildBlockers,
} from '../../src/lib/world/globe-walk';
import { clipWater } from '../../src/lib/world/ground-shape';
import { createScatter, type Scatter } from '../../src/lib/world/scatter';
import {
  BLOCKING_SCATTER_ASSETS,
  createWildBlockers,
  siteCharts,
  townChart,
} from '../../src/lib/world/walk-charts';

/*
 * The globe walker outside the browser, on the real world from the backend: the same charts, scattered props
 * and colliders files the page builds (town surfaces are flat here: no bridge raycasts).
 */

export { WORLD_URL } from './globe-helpers';
/** The town from the same backend as the world (PLAYWRIGHT_API_URL). */
export const TOWN_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1/town`;
/** The page's prop clearings around the town and the other sites. */
const TOWN_CLEARING = 300;
const SITE_CLEARING = 45;
/** The page's town ground disc. */
export const TOWN_GROUND_RADIUS = 225;

const ROOT = path.resolve(import.meta.dirname, '../..');
const byId = new Map(manifest.assets.map((asset) => [asset.id, asset]));

/** Colliders files from the vendored assets, by asset id. */
export function loadColliders(ids: Iterable<string>) {
  const files = new Map<string, ColliderFile>();
  for (const id of ids) {
    if (files.has(id)) continue;
    const file = path.join(ROOT, byId.get(id)!.files.colliders.path);
    files.set(id, JSON.parse(readFileSync(file, 'utf8')) as ColliderFile);
  }
  return files;
}

export interface Explore {
  view: WorldView;
  town: TownView;
  terrain: GlobeTerrain;
  R: number;
  scatter: Scatter;
  colliders: Map<string, ColliderFile>;
  wild: WildBlockers;
  townMapping: SiteMapping;
  citizens: Map<string, Point>;
  /** A walk with every collision; `props: false` leaves out scattered props. */
  walk: (options?: { props?: boolean }) => GlobeWalk;
  site: (id: string) => Site;
}

export function explore(view: WorldView, town: TownView): Explore {
  const terrain = buildTerrain(decodeWorld(view));
  const R = view.radius_m;
  const scatter = createScatter({
    terrain,
    seed: view.seed,
    frequency: view.frequency,
    biomeNames: view.biome_names,
    table: BIOME_PROPS,
    clearings: view.sites.map((site) => ({
      direction: new Vector3(...site.anchor.position),
      radius: site.kind === 'town' ? TOWN_CLEARING : SITE_CLEARING,
    })),
    rivers: view.rivers.map((river) => river.cells),
  });
  const colliders = loadColliders([
    ...colliderIdsOf(town.placements),
    ...view.sites.flatMap((site) => colliderIdsOf(site.placements ?? [])),
    ...BLOCKING_SCATTER_ASSETS,
  ]);
  const wild = createWildBlockers(scatter, colliders, R);
  const townSite = view.sites.find((site) => site.kind === 'town')!;
  const townMapping = anchorMapping(townSite.anchor, R);
  const citizens = new Map<string, Point>();
  const walk = ({ props = true } = {}) => {
    const blockers = props ? wild : () => [];
    return createGlobeWalk(
      terrain,
      [
        townChart(
          {
            mapping: townMapping,
            height: townSite.anchor.height_m,
            placements: town.placements,
            water: clipWater(town.water, TOWN_GROUND_RADIUS),
            groundRadius: TOWN_GROUND_RADIUS,
            citizenSpots: citizens,
          },
          colliders,
          { heightAt: () => 0, maxStepUp: 0.5, probeHeight: 1 },
        ),
        ...siteCharts(terrain, view.sites, colliders, blockers),
      ],
      blockers,
    );
  };
  return {
    view,
    town,
    terrain,
    R,
    scatter,
    colliders,
    wild,
    townMapping,
    citizens,
    walk,
    site: (id) => view.sites.find((site) => site.id === id)!,
  };
}

/**
 * Walks from `from` towards `to` (unit directions) in steps of `stride` metres, as the player does each frame;
 * returns every direction it stood at.
 */
export function walkTowards(
  world: Explore,
  walk: GlobeWalk,
  from: Vector3,
  to: Vector3,
  { stride = 0.05, steps = 200, travel = false } = {},
) {
  let direction = from.clone().normalize();
  let ground = walk.groundAt(direction, 1000);
  const path = [direction];
  const target = to.clone().normalize().multiplyScalar(world.R);
  for (let k = 0; k < steps; k++) {
    const position = direction.clone().multiplyScalar(world.R + ground);
    const heading = tangent(target.clone().sub(position), direction);
    if (direction.angleTo(to) * world.R < stride) break;
    direction = walk.move(
      position,
      heading.multiplyScalar(stride),
      ground,
      travel,
    );
    ground = walk.groundAt(direction, ground);
    path.push(direction);
  }
  return path;
}

/** Metres between two directions on the sea-level sphere. */
export const metres = (world: Explore, a: Vector3, b: Vector3) =>
  a.angleTo(b) * world.R;
