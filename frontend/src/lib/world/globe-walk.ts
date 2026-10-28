/*
 * Walking on the planet. A step is a displacement in the tangent plane, re-projected onto the sphere. Outside
 * the town, the ground is the terrain and water biomes block (sliding along the shore). Inside the town's chart
 * the step is resolved in the town's local metres with the flat town collisions (walls, gates, moat), through
 * the site mapping and back; on the town's ground disc the ground is the plateau plus walkable surfaces.
 */
import { Vector3 } from 'three';

import { type Point, resolveMove, type WalkWorld } from './collision';
import {
  type GlobeTerrain,
  type SiteMapping,
  tangentFrame,
  WATER_BIOMES,
  WATER_SURFACE,
} from './globe';

export interface TownWalk {
  mapping: SiteMapping;
  world: WalkWorld;
  /** Plateau height h0. */
  height: number;
  /** Radius of the town's own ground disc (local metres). */
  groundRadius: number;
  /** Within this radius steps are resolved with the town's collisions. */
  chartRadius: number;
  /** Height above the plateau of the walkable ground at a local point, probing down from fromY. */
  groundAt: (point: Point, fromY: number) => number;
  /** Highest step up onto a surface. */
  maxStepUp: number;
  probeHeight: number;
}

export interface GlobeWalk {
  /** Town local (x, z) when the point is inside the town's chart, else null. */
  townPoint(point: Vector3): Point | null;
  /** Height above sea level of the ground under a direction (`ground` = the current one, for probes). */
  groundAt(direction: Vector3, ground: number): number;
  walkable(direction: Vector3): boolean;
  /** Biome id of the cell nearest to a direction. */
  biomeAt(direction: Vector3): number;
  /** Where a player at `position` standing on `ground` ends up trying to move by `step`: a unit direction. */
  move(position: Vector3, step: Vector3, ground: number): Vector3;
}

export function createGlobeWalk(
  terrain: GlobeTerrain,
  town: TownWalk | null,
): GlobeWalk {
  const local = new Vector3();
  const target = new Vector3();

  function townPoint(point: Vector3): Point | null {
    if (!town) return null;
    town.mapping.toLocal(point, local);
    return Math.hypot(local.x, local.z) < town.chartRadius
      ? [local.x, local.z]
      : null;
  }

  const onTownGround = (point: Point) =>
    town !== null && Math.hypot(point[0], point[1]) < town.groundRadius;

  function walkable(direction: Vector3) {
    const cell = terrain.nearestCell(direction);
    return (
      !WATER_BIOMES.has(terrain.globe.biomes[cell]) &&
      // ground under the water surface is wet whatever its cell says
      terrain.heightAt(direction, cell) > WATER_SURFACE
    );
  }

  function groundAt(direction: Vector3, ground: number) {
    const point = townPoint(direction);
    if (town && point && onTownGround(point))
      return (
        town.height +
        town.groundAt(point, ground - town.height + town.probeHeight)
      );
    return terrain.heightAt(direction);
  }

  function townMove(
    walk: TownWalk,
    from: Point,
    position: Vector3,
    step: Vector3,
    ground: number,
  ) {
    walk.mapping.toLocal(target.copy(position).add(step), local);
    const groundY = ground - walk.height;
    const probe = (point: Point) =>
      walk.groundAt(point, groundY + walk.probeHeight);
    const to = resolveMove(
      walk.world,
      from,
      [local.x, local.z],
      groundY,
      (point) =>
        onTownGround(point)
          ? probe(point) - groundY <= walk.maxStepUp
          : walkable(walk.mapping.toWorld(point[0], 0, point[1], target)),
    );
    return walk.mapping.toWorld(to[0], 0, to[1], new Vector3()).normalize();
  }

  function move(position: Vector3, step: Vector3, ground: number) {
    const from = townPoint(position);
    if (town && from) return townMove(town, from, position, step, ground);
    const { east, north } = tangentFrame(position);
    // the whole step first, then each axis alone so the player slides along the shore
    for (const candidate of [
      step,
      east.multiplyScalar(step.dot(east)),
      north.multiplyScalar(step.dot(north)),
    ]) {
      const direction = target.copy(position).add(candidate).normalize();
      if (walkable(direction)) return direction.clone();
    }
    return position.clone().normalize();
  }

  return {
    townPoint,
    groundAt,
    walkable,
    biomeAt: (direction) => terrain.biomeAt(direction),
    move,
  };
}
