/*
 * Geometry for the planet's water, each carrying the `water` attribute the water shader reads
 * (water-material.ts): the sea and the lakes (one surface, with the depth under it per vertex) and the river
 * ribbons (across / downstream / speed / fade).
 */
import {
  BufferAttribute,
  BufferGeometry,
  Float32BufferAttribute,
  Vector3,
} from 'three';

import { type GlobeTerrain, WATER_BIOMES, WATER_SURFACE } from './globe';
import type { RiverLayout } from './river-courses';
import { BANK_EDGE } from './water-material';

/** Collects vertices (position, up normal, water data) and triangles. */
function builder() {
  const positions: number[] = [];
  const normals: number[] = [];
  const water: number[] = [];
  const index: number[] = [];
  const up = new Vector3();
  return {
    /** Adds a vertex and returns its id. */
    vertex(position: Vector3, data: [number, number, number, number]) {
      positions.push(position.x, position.y, position.z);
      up.copy(position).normalize();
      normals.push(up.x, up.y, up.z);
      water.push(...data);
      return positions.length / 3 - 1;
    },
    triangle(a: number, b: number, c: number) {
      index.push(a, b, c);
    },
    build() {
      const geometry = new BufferGeometry();
      geometry.setAttribute(
        'position',
        new Float32BufferAttribute(positions, 3),
      );
      geometry.setAttribute('normal', new Float32BufferAttribute(normals, 3));
      geometry.setAttribute('water', new Float32BufferAttribute(water, 4));
      geometry.setIndex(
        new BufferAttribute(
          positions.length / 3 > 65535
            ? Uint32Array.from(index)
            : Uint16Array.from(index),
          1,
        ),
      );
      return geometry;
    },
  };
}

// --- the sea and the lakes ---

/** Sea triangles whose corners all lie deeper than this (metres) are drawn as one face, not the refined lattice. */
const SHALLOW_SEA = 2;
/** Lake water floats this far above the lake's flat bed (its surface height in the terrain). */
const LAKE_LIFT = 0.05;
/** Ground this close (metres) above a lake's surface height is still its flat bed. */
const LAKE_BED = 0.01;
/** Lakes are flat in the terrain: their depth for the shader grows by LAKE_STEP per cell from the shore. */
const LAKE_STEP = 2.5;
const LAKE_DEPTH_MAX = 9;

/** How deep each lake cell's water is taken to be: LAKE_STEP per cell from the nearest dry cell. */
function lakeDepths(terrain: GlobeTerrain) {
  const { biomes, heights, cellCount } = terrain.globe;
  const isLake = (cell: number) =>
    WATER_BIOMES.has(biomes[cell]) && heights[cell] > WATER_SURFACE;
  const depth = new Float32Array(cellCount);
  let frontier: number[] = [];
  for (let cell = 0; cell < cellCount; cell++) {
    if (!isLake(cell)) continue;
    depth[cell] = -1;
    if ([...terrain.neighbours(cell)].some((n) => !isLake(n))) {
      depth[cell] = LAKE_STEP / 2;
      frontier.push(cell);
    }
  }
  while (frontier.length > 0) {
    const next: number[] = [];
    for (const cell of frontier)
      for (const neighbour of terrain.neighbours(cell))
        if (depth[neighbour] === -1) {
          depth[neighbour] = Math.min(depth[cell] + LAKE_STEP, LAKE_DEPTH_MAX);
          next.push(neighbour);
        }
    frontier = next;
  }
  return { depth, isLake };
}

/**
 * The surface of the sea (at WATER_SURFACE) and of every lake (at its own height), with the depth of the water
 * under each vertex. Sea faces are flat per grid triangle so a refined shore triangle meets a plain deep one
 * without cracks; near the shore the triangle is refined like the terrain so the depth (and with it the
 * shader's soft edge and foam) follows the real shoreline. Lakes are refined everywhere and follow the sphere.
 */
export function stillWaterGeometry(terrain: GlobeTerrain) {
  const { globe, surface } = terrain;
  const { positions, heights, triangles, radius } = globe;
  const n = surface.divisions;
  const lakes = lakeDepths(terrain);
  const out = builder();
  const corner = [new Vector3(), new Vector3(), new Vector3()];
  const point = new Vector3();

  /** A triangle's lattice points, row by row; `place` positions a point and returns its water depth. */
  function lattice(
    place: (b0: number, b1: number, b2: number, target: Vector3) => number,
  ) {
    const ids: number[] = [];
    for (let j = 0; j <= n; j++)
      for (let i = 0; i + j <= n; i++) {
        const [b0, b1, b2] = [(n - i - j) / n, i / n, j / n];
        const depth = place(b0, b1, b2, point);
        ids.push(out.vertex(point, [depth, 0, 0, 0]));
      }
    let rowStart = 0;
    for (let j = 0; j < n; j++) {
      const next = rowStart + n - j + 1;
      for (let i = 0; i + j < n; i++) {
        out.triangle(ids[rowStart + i], ids[rowStart + i + 1], ids[next + i]);
        if (i + j < n - 1)
          out.triangle(ids[rowStart + i + 1], ids[next + i + 1], ids[next + i]);
      }
      rowStart = next;
    }
  }

  for (let t = 0; t < triangles.length / 3; t++) {
    const cells = [
      triangles[t * 3],
      triangles[t * 3 + 1],
      triangles[t * 3 + 2],
    ];
    cells.forEach((cell, k) => corner[k].fromArray(positions, cell * 3));
    const cornerHeights = cells.map((cell) => heights[cell]);

    // the sea: flat across the grid triangle at R + WATER_SURFACE
    if (Math.min(...cornerHeights) < WATER_SURFACE) {
      const level = radius + WATER_SURFACE;
      if (Math.max(...cornerHeights) < WATER_SURFACE - SHALLOW_SEA) {
        const ids = cells.map((_, k) =>
          out.vertex(point.copy(corner[k]).multiplyScalar(level), [
            WATER_SURFACE - cornerHeights[k],
            0,
            0,
            0,
          ]),
        );
        out.triangle(ids[0], ids[1], ids[2]);
      } else
        lattice((b0, b1, b2, target) => {
          target
            .copy(corner[0])
            .multiplyScalar(b0)
            .addScaledVector(corner[1], b1)
            .addScaledVector(corner[2], b2)
            .multiplyScalar(level);
          return target.length() - radius - surface.height(t, b0, b1, b2);
        });
    }

    // a lake: at its surface height, refined, on the sphere
    const lakeCorners = cells.filter((cell) => lakes.isLake(cell));
    if (lakeCorners.length > 0) {
      const level = Math.min(...lakeCorners.map((cell) => heights[cell]));
      const bedDepths = cells.map((cell) =>
        lakes.isLake(cell) ? lakes.depth[cell] : 0,
      );
      lattice((b0, b1, b2, target) => {
        target
          .copy(corner[0])
          .multiplyScalar(b0)
          .addScaledVector(corner[1], b1)
          .addScaledVector(corner[2], b2)
          .normalize()
          .multiplyScalar(radius + level + LAKE_LIFT);
        const ground = surface.height(t, b0, b1, b2);
        // on the lake's flat bed the depth grows away from the shore; where the bank rises the water is gone
        return ground <= level + LAKE_BED
          ? b0 * bedDepths[0] + b1 * bedDepths[1] + b2 * bedDepths[2]
          : level + LAKE_LIFT - ground;
      });
    }
  }
  return out.build();
}

// --- rivers ---

/** Ribbons float this far above the ground under them. */
const RIVER_LIFT = 0.15;
/** Vertices across a ribbon, in half widths of the water (beyond ±1 is the wet bank). */
const ACROSS = [-BANK_EDGE, -0.6, 0, 0.6, BANK_EDGE];

/** A ribbon along every river run, draped over the terrain, its banks reaching a little past the water. */
export function riverGeometry(terrain: GlobeTerrain, layout: RiverLayout) {
  const { radius } = terrain.globe;
  const out = builder();
  const side = new Vector3();
  const spot = new Vector3();
  for (const { points } of layout.runs) {
    let previous: number[] | null = null;
    points.forEach((point, i) => {
      const ahead = points[Math.min(i + 1, points.length - 1)].direction;
      const behind = points[Math.max(i - 1, 0)].direction;
      side.subVectors(ahead, behind).cross(point.direction).normalize();
      const row = ACROSS.map((across) => {
        spot
          .copy(point.direction)
          .addScaledVector(side, (across * point.width) / 2 / radius)
          .normalize();
        // in a site's channel the water lies flat; elsewhere it follows the ground
        const ground = point.flat
          ? point.height
          : Math.max(terrain.heightAt(spot), WATER_SURFACE);
        spot.multiplyScalar(radius + ground + RIVER_LIFT);
        return out.vertex(spot, [across, point.along, point.speed, point.fade]);
      });
      if (previous)
        for (let k = 0; k + 1 < row.length; k++) {
          // `side` points to the right bank: counter-clockwise seen from above
          out.triangle(previous[k], previous[k + 1], row[k]);
          out.triangle(previous[k + 1], row[k + 1], row[k]);
        }
      previous = row;
    });
  }
  return out.build();
}
