/*
 * Walking on the planet. A step is a displacement in the tangent plane, re-projected onto the sphere, and is
 * always resolved in the local metres of a chart (a gnomonic site mapping) with the flat 2D collisions of
 * collision.ts, then mapped back:
 *   - the town's chart: its walls, gates, moat and townspeople; on its ground disc the ground is the plateau
 *     plus walkable surfaces (bridges, paving);
 *   - a camp's or landmark's chart: its placements' colliders (standing on the terrain) and nearby trees;
 *   - elsewhere a "wild" chart re-anchored around the player: the colliders of scattered trees, rocks, bushes.
 * Outside the town's ground the ground is the terrain: water blocks and slopes steeper than MAX_GRADE can't be
 * climbed (the step slides along the slope's contour instead). Travel mode skips scattered props and slopes.
 */
import { Vector3 } from 'three';

import {
  blockerWorld,
  clearOfBlockers,
  isBlocked,
  isWater,
  type LocalPoint,
  type Point,
  raycastBlockers,
  resolveMove,
  type Shape,
  type WalkWorld,
} from './collision';
import {
  type Globe,
  type GlobeTerrain,
  type SiteMapping,
  siteMapping,
  tangentFrame,
  WATER_BIOMES,
  WATER_SURFACE,
} from './globe';

/** A site's own ground (the town's plateau disc) with walkable surfaces on it. */
interface ChartGround {
  /** Radius of the ground disc (local metres). */
  radius: number;
  /** Height above the anchor of the walkable ground at a local point, probing down from fromY. */
  groundAt: (point: Point, fromY: number) => number;
  /** Highest step up onto a surface. */
  maxStepUp: number;
  probeHeight: number;
}

/** A place whose collisions are resolved in its own local metres. */
export interface WalkChart {
  id: string;
  mapping: SiteMapping;
  world: WalkWorld;
  /** Anchor height h0 above sea level (local y = 0). */
  height: number;
  /** Steps within this radius of the anchor (local metres) resolve in this chart. */
  radius: number;
  /** The site's own ground; without it the ground is the terrain. */
  ground?: ChartGround;
  /** Moving blockers in local metres (townspeople), read at every step. */
  dynamic?: () => readonly Shape[];
}

/** Blockers of the scattered props around a direction, in a mapping's local metres. */
export type WildBlockers = (
  mapping: SiteMapping,
  center: Vector3,
  reach: number,
) => Shape[];

/** Steepest slope (rise per metre) the player can walk up: 45°. */
const MAX_GRADE = 1;
/** The wild chart covers this many metres around its anchor... */
const WILD_REACH = 70;
/** ...and is re-anchored once the player is this far from it. */
const WILD_RECENTER = 35;
/** Look-ahead and spacing of the terrain gradient samples, metres. */
const SLOPE_AHEAD = 0.3;
const SLOPE_SAMPLE = 0.5;
const CAMERA_GROUND_SAMPLES = 12;
/** Drop spots are searched on rings around the picked point out to this many metres. */
const DROP_SEARCH = 12;

export interface GlobeWalk {
  /** Town local (x, z) when the point is inside the town's chart, else null. */
  townPoint(point: Vector3): Point | null;
  /** Height above sea level of the ground under a direction (`ground` = the current one, for probes). */
  groundAt(direction: Vector3, ground: number): number;
  /** Ground height without surface probes (the town plateau or the terrain), for the camera. */
  floorAt(direction: Vector3): number;
  walkable(direction: Vector3): boolean;
  /** Biome id of the cell nearest to a direction. */
  biomeAt(direction: Vector3): number;
  /** Rise per metre of the ground just ahead of `position` along the unit tangent `heading`. */
  grade(position: Vector3, heading: Vector3): number;
  /**
   * Where a player at `position` standing on `ground` ends up trying to move by `step` (possibly zero, which
   * still pushes the player out of moving people): a unit direction. `travel` skips props and slopes.
   */
  move(
    position: Vector3,
    step: Vector3,
    ground: number,
    travel: boolean,
  ): Vector3;
  /** Whether a player can stand at the direction: dry land, not inside anything. */
  isFree(direction: Vector3): boolean;
  /** Whether the direction is land (not the sea, a lake, the moat or the stream). */
  isDry(direction: Vector3): boolean;
  /** A free spot at or near (within DROP_SEARCH m) a picked direction, or null if it is water. */
  dropSpot(direction: Vector3): Vector3 | null;
  /**
   * How much (0..1) of the segment from the player's eye to the camera is clear of blockers and stays
   * `clearance` above the ground (or water).
   */
  cameraReach(eye: Vector3, camera: Vector3, clearance: number): number;
  /** Whether the segment from the player's eye to the camera stays `clearance` above the ground (or water). */
  aboveGround(eye: Vector3, camera: Vector3, clearance: number): boolean;
  /** Moves a camera position out of blockers within `radius` of it (in place). */
  clearCamera(camera: Vector3, radius: number): Vector3;
}

const NO_SHAPES: readonly Shape[] = [];

/** What walking needs of the terrain: heights, biomes and the nearest cell. */
export type WalkTerrain = Pick<
  GlobeTerrain,
  'nearestCell' | 'heightAt' | 'biomeAt'
> & { globe: Pick<Globe, 'radius' | 'biomes'> };

export function createGlobeWalk(
  terrain: WalkTerrain,
  charts: WalkChart[],
  wildBlockers: WildBlockers | null,
): GlobeWalk {
  const radius = terrain.globe.radius;
  const local = new Vector3();
  const target = new Vector3();
  const sample = new Vector3();
  const wildAt = new Vector3();
  const town = charts.find((chart) => chart.ground) ?? null;
  let wild: (WalkChart & { anchor: Vector3; props: boolean }) | null = null;

  function wildChart(direction: Vector3, props: boolean): WalkChart {
    const unit = wildAt.copy(direction).normalize();
    if (
      wild &&
      wild.props === props &&
      wild.anchor.angleTo(unit) * radius < WILD_RECENTER
    )
      return wild;
    const anchor = unit.clone();
    const height = terrain.heightAt(anchor);
    const mapping = siteMapping(tangentFrame(anchor), radius + height);
    const shapes =
      props && wildBlockers
        ? wildBlockers(mapping, anchor, WILD_REACH + WILD_RECENTER)
        : [];
    wild = {
      id: 'wild',
      anchor,
      props,
      mapping,
      height,
      radius: Infinity,
      world: blockerWorld(shapes),
    };
    return wild;
  }

  /** The chart a point resolves in, with its local (x, z). */
  function chartAt(point: Vector3, props = true) {
    for (const chart of charts) {
      chart.mapping.toLocal(point, local);
      if (Math.hypot(local.x, local.z) < chart.radius)
        return { chart, at: [local.x, local.z] as Point };
    }
    const chart = wildChart(point, props);
    chart.mapping.toLocal(point, local);
    return { chart, at: [local.x, local.z] as Point };
  }

  function townPoint(point: Vector3): Point | null {
    if (!town) return null;
    town.mapping.toLocal(point, local);
    return Math.hypot(local.x, local.z) < town.radius
      ? [local.x, local.z]
      : null;
  }

  const onGround = (chart: WalkChart, point: Point) =>
    chart.ground !== undefined &&
    Math.hypot(point[0], point[1]) < chart.ground.radius;

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
    if (town?.ground && point && onGround(town, point))
      return (
        town.height +
        town.ground.groundAt(
          point,
          ground - town.height + town.ground.probeHeight,
        )
      );
    return terrain.heightAt(direction);
  }

  function floorAt(direction: Vector3) {
    const point = townPoint(direction);
    if (town && point && onGround(town, point)) return town.height;
    return Math.max(terrain.heightAt(direction), WATER_SURFACE);
  }

  /** Terrain gradient (rise per metre, a world tangent) at a direction; zero on a site's own ground. */
  function gradient(direction: Vector3, result: Vector3) {
    result.set(0, 0, 0);
    const point = townPoint(direction);
    if (town && point && onGround(town, point)) return result;
    const { east, north } = tangentFrame(direction);
    const base = sample.copy(direction).setLength(radius);
    const h = terrain.heightAt(base);
    const he = terrain.heightAt(
      target.copy(base).addScaledVector(east, SLOPE_SAMPLE),
    );
    const hn = terrain.heightAt(
      target.copy(base).addScaledVector(north, SLOPE_SAMPLE),
    );
    return result
      .addScaledVector(east, (he - h) / SLOPE_SAMPLE)
      .addScaledVector(north, (hn - h) / SLOPE_SAMPLE);
  }

  const slope = new Vector3();
  const ahead = new Vector3();
  const slid = new Vector3();

  function grade(position: Vector3, heading: Vector3) {
    ahead.copy(position).addScaledVector(heading, SLOPE_AHEAD);
    return gradient(ahead, slope).dot(heading);
  }

  /** Whether a step from `from` to `to` (local, in `chart`) may be taken on the terrain. */
  function terrainStep(
    chart: WalkChart,
    from: Point,
    to: Point,
    climb: boolean,
  ) {
    const there = chart.mapping.toWorld(to[0], 0, to[1], target);
    if (!walkable(there)) return false;
    if (!climb) return true;
    const run = Math.hypot(to[0] - from[0], to[1] - from[1]);
    if (run < 1e-9) return true;
    const rise =
      terrain.heightAt(there) -
      terrain.heightAt(chart.mapping.toWorld(from[0], 0, from[1], sample));
    return rise <= run * MAX_GRADE;
  }

  function move(
    position: Vector3,
    step: Vector3,
    ground: number,
    travel: boolean,
  ) {
    const { chart, at: from } = chartAt(position, !travel);
    const length = step.length();
    slid.copy(step);
    if (!travel && length > 0) {
      // too steep ahead: keep only the part of the step along the slope's contour
      ahead.copy(position).addScaledVector(step, SLOPE_AHEAD / length);
      gradient(ahead, slope);
      const steepness = slope.length();
      if (steepness > 1e-6 && step.dot(slope) / length > MAX_GRADE) {
        slope.divideScalar(steepness);
        slid.addScaledVector(slope, -step.dot(slope));
      }
    }
    chart.mapping.toLocal(target.copy(position).add(slid), local);
    const groundY = ground - chart.height;
    const ledge = chart.ground;
    const to = resolveMove(
      chart.world,
      from,
      [local.x, local.z],
      groundY,
      (point, previous) =>
        ledge && onGround(chart, point)
          ? ledge.groundAt(point, groundY + ledge.probeHeight) - groundY <=
            ledge.maxStepUp
          : terrainStep(chart, previous, point, !travel),
      chart.dynamic?.() ?? NO_SHAPES,
    );
    return chart.mapping.toWorld(to[0], 0, to[1], new Vector3()).normalize();
  }

  /** Whether the local point of a chart is dry and clear for a player standing on its ground. */
  function standable(chart: WalkChart, point: Point) {
    const direction = chart.mapping.toWorld(
      point[0],
      0,
      point[1],
      new Vector3(),
    );
    if (onGround(chart, point)) {
      if (isWater(chart.world, point)) return false;
    } else if (!walkable(direction)) return false;
    const ground = groundAt(direction, chart.height + 50);
    return !isBlocked(
      chart.world,
      point,
      ground - chart.height,
      chart.dynamic?.() ?? NO_SHAPES,
    );
  }

  function isFree(direction: Vector3) {
    const { chart, at } = chartAt(direction);
    return standable(chart, at);
  }

  function isDry(direction: Vector3) {
    const point = townPoint(direction);
    return town && point && onGround(town, point)
      ? !isWater(town.world, point)
      : walkable(direction);
  }

  function dropSpot(direction: Vector3) {
    if (!isDry(direction)) return null;
    const { chart, at } = chartAt(direction);
    for (let ring = 0; ring <= DROP_SEARCH; ring += 0.5) {
      const count = ring === 0 ? 1 : Math.ceil((ring * Math.PI * 2) / 0.5);
      for (let k = 0; k < count; k++) {
        const angle = (k / count) * Math.PI * 2;
        const point: Point = [
          at[0] + Math.sin(angle) * ring,
          at[1] + Math.cos(angle) * ring,
        ];
        if (standable(chart, point))
          return chart.mapping
            .toWorld(point[0], 0, point[1], new Vector3())
            .normalize();
      }
    }
    return direction.clone().normalize();
  }

  const toLocalPoint = (chart: WalkChart, point: Vector3): LocalPoint => {
    chart.mapping.toLocal(point, local);
    return [local.x, local.y, local.z];
  };

  /** How far (0..limit) along the segment the ground stays below it (hills behind the player, a ledge). */
  function groundReach(
    eye: Vector3,
    camera: Vector3,
    limit: number,
    clearance: number,
  ) {
    for (let k = 1; k <= CAMERA_GROUND_SAMPLES; k++) {
      const t = (k / CAMERA_GROUND_SAMPLES) * limit;
      sample.lerpVectors(eye, camera, t);
      if (sample.length() < radius + floorAt(sample) + clearance)
        return ((k - 1) / CAMERA_GROUND_SAMPLES) * limit;
    }
    return limit;
  }

  function cameraReach(eye: Vector3, camera: Vector3, clearance: number) {
    const { chart } = chartAt(eye);
    const reach = raycastBlockers(
      chart.world,
      toLocalPoint(chart, eye),
      toLocalPoint(chart, camera),
      chart.dynamic?.() ?? NO_SHAPES,
    );
    return groundReach(eye, camera, reach, clearance);
  }

  function clearCamera(camera: Vector3, clearance: number) {
    const { chart, at } = chartAt(camera);
    const height = camera.length() - radius - chart.height;
    const [x, z] = clearOfBlockers(
      chart.world,
      at,
      height,
      clearance,
      chart.dynamic?.() ?? NO_SHAPES,
    );
    if (x !== at[0] || z !== at[1]) chart.mapping.toWorld(x, height, z, camera);
    return camera;
  }

  return {
    townPoint,
    groundAt,
    floorAt,
    walkable,
    biomeAt: (direction) => terrain.biomeAt(direction),
    grade,
    move,
    isFree,
    isDry,
    dropSpot,
    cameraReach,
    aboveGround: (eye, camera, clearance) =>
      groundReach(eye, camera, 1, clearance) === 1,
    clearCamera,
  };
}
