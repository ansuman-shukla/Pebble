/*
 * Geometry for the planet's water, each carrying the `water` attribute the water shader reads
 * (water-material.ts): the sea and the lakes (one surface, with the depth under it per vertex), the river
 * ribbons (across / downstream / speed / fade), falling sheets at waterfalls and the ring of foam at their foot.
 */
import {
  BufferAttribute,
  BufferGeometry,
  Float32BufferAttribute,
  Vector3,
} from 'three';

import {
  type Globe,
  type GlobeTerrain,
  WATER_BIOMES,
  WATER_SURFACE,
} from './globe';
import type { RiverLayout, Waterfall } from './river-courses';
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
/**
 * Lake water lies this far above the lake's flat bed (its surface height in the terrain), so its shore is a
 * contour across the rising bank instead of the bed's polygon of grid edges.
 */
export const LAKE_LIFT = 0.25;
/** Lakes are flat in the terrain: their depth for the shader grows by LAKE_STEP per cell from the shore. */
const LAKE_STEP = 2.5;
const LAKE_DEPTH_MAX = 9;

/** A water cell above the sea's surface: a lake. */
const isLakeCell = ({ biomes, heights }: Globe, cell: number) =>
  WATER_BIOMES.has(biomes[cell]) && heights[cell] > WATER_SURFACE;

/**
 * The height (above sea level) of the lake water drawn over a grid triangle: its lowest lake corner's bed +
 * LAKE_LIFT, over the whole triangle (the ground above it hides it); -Infinity without a lake corner. Nothing may
 * stand where the ground lies under it (the backend's flora keeps the same rule).
 */
export function lakeSurface(globe: Globe, triangle: number) {
  let level = Infinity;
  for (let k = 0; k < 3; k++) {
    const cell = globe.triangles[triangle * 3 + k];
    if (isLakeCell(globe, cell)) level = Math.min(level, globe.heights[cell]);
  }
  return level === Infinity ? -Infinity : level + LAKE_LIFT;
}

/** How deep each lake cell's water is taken to be: LAKE_STEP per cell from the nearest dry cell. */
function lakeDepths(terrain: GlobeTerrain) {
  const { globe } = terrain;
  const { cellCount } = globe;
  const isLake = (cell: number) => isLakeCell(globe, cell);
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
    const surfaceHeight = lakeSurface(globe, t);
    if (surfaceHeight > -Infinity) {
      const level = surfaceHeight - LAKE_LIFT;
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
        // on the flat bed the depth grows away from the shore; up the bank it thins to nothing where the
        // ground meets the surface
        const bed = b0 * bedDepths[0] + b1 * bedDepths[1] + b2 * bedDepths[2];
        const rise = surface.height(t, b0, b1, b2) - level;
        return (LAKE_LIFT + bed) * (1 - rise / LAKE_LIFT);
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

// --- waterfalls ---

/** Rows down a falling sheet and columns across it. */
const SHEET_ROWS = 18;
const SHEET_COLUMNS = 6;
/** The sheet keeps this far (metres) off the cliff, and lands this far out from the foot of the slope. */
const SHEET_CLEARANCE = 1.2;
const SHEET_REACH = 3;
/** The sheet widens by this much of its width on the way down, and bows out by SHEET_BOW metres in the middle. */
const SHEET_SPREAD = 0.4;
/** A falling sheet is this much wider than the river at its lip (the water spreads as it leaves the edge). */
const SHEET_WIDEN = 1.5;
const SHEET_BOW = 0.8;
const GRAVITY = 9.81;

/** The tangent frame of a fall: up at the lip, out over the drop, and across. */
export function fallFrame(fall: Waterfall) {
  const up = fall.lip.clone();
  const out = fall.foot.clone().sub(fall.lip);
  out.addScaledVector(up, -out.dot(up)).normalize();
  const across = new Vector3().crossVectors(out, up);
  return { up, out, across };
}

/**
 * Where the falling water passes at fraction s ∈ [0, 1] of the drop: it leaves the lip level and curves down
 * (x grows with √s, a thrown jet), pushed further out wherever it would touch the cliff.
 */
export function fallPath(terrain: GlobeTerrain, fall: Waterfall) {
  const { radius } = terrain.globe;
  const { up, out } = fallFrame(fall);
  const drop = fall.lipHeight - fall.footHeight;
  const reach = fall.lip.angleTo(fall.foot) * radius + SHEET_REACH;
  const direction = new Vector3();
  const path: { x: number; height: number }[] = [];
  let pushed = 0;
  for (let k = 0; k <= SHEET_ROWS; k++) {
    const s = k / SHEET_ROWS;
    const height = fall.lipHeight - drop * s;
    let x = Math.max(reach * Math.sqrt(s), pushed);
    for (let tries = 0; tries < 40 && k > 0 && k < SHEET_ROWS; tries++) {
      direction
        .copy(up)
        .addScaledVector(out, x / radius)
        .normalize();
      if (height >= terrain.heightAt(direction) + SHEET_CLEARANCE) break;
      x += 1;
    }
    pushed = x;
    path.push({ x, height });
  }
  return path;
}

/** The falling sheet of a waterfall: curved down from the lip, widening, a little bowed. */
export function fallSheetGeometry(terrain: GlobeTerrain, fall: Waterfall) {
  const { radius } = terrain.globe;
  const { up, out: outward, across } = fallFrame(fall);
  const path = fallPath(terrain, fall);
  const out = builder();
  const spot = new Vector3();
  let length = 0;
  let previous: number[] | null = null;
  path.forEach(({ x, height }, k) => {
    const s = k / SHEET_ROWS;
    if (k > 0)
      length += Math.hypot(x - path[k - 1].x, height - path[k - 1].height);
    const half = ((fall.width * SHEET_WIDEN) / 2) * (1 + SHEET_SPREAD * s);
    const fallen = fall.lipHeight - height;
    const speed = 1.5 + Math.sqrt(2 * GRAVITY * fallen);
    const row: number[] = [];
    for (let c = 0; c <= SHEET_COLUMNS; c++) {
      const a = (c / SHEET_COLUMNS) * 2 - 1;
      const bow =
        SHEET_BOW * (1 - a * a) * Math.sin(Math.PI * Math.min(s * 1.5, 1));
      spot
        .copy(up)
        .addScaledVector(outward, (x + bow) / radius)
        .addScaledVector(across, (a * half) / radius)
        .normalize()
        .multiplyScalar(radius + height + RIVER_LIFT);
      row.push(out.vertex(spot, [a, length, speed, s]));
    }
    if (previous)
      for (let c = 0; c < SHEET_COLUMNS; c++) {
        out.triangle(previous[c], row[c], previous[c + 1]);
        out.triangle(previous[c + 1], row[c], row[c + 1]);
      }
    previous = row;
  });
  const geometry = out.build();
  // a sheet faces out over the drop, not up
  geometry.computeVertexNormals();
  return geometry;
}

/** Where the falling water lands: the foot of the sheet's path, on the pool's surface. */
export function fallLanding(terrain: GlobeTerrain, fall: Waterfall) {
  const { radius } = terrain.globe;
  const { up, out } = fallFrame(fall);
  const path = fallPath(terrain, fall);
  const { x } = path[path.length - 1];
  return up
    .clone()
    .addScaledVector(out, x / radius)
    .normalize();
}

/** Rings of foam radii (metres) around the landing point, and segments around. */
const FOAM_RADII = [0, 2, 5, 9, 14, 18];
const FOAM_SEGMENTS = 36;
const FOAM_LIFT = 0.12;

/** A disc of churned foam on the pool where a fall lands (water: distance, local east/north metres). */
export function fallFoamGeometry(terrain: GlobeTerrain, fall: Waterfall) {
  const { radius } = terrain.globe;
  const { out: outward, across } = fallFrame(fall);
  const centre = fallLanding(terrain, fall);
  const out = builder();
  const spot = new Vector3();
  const rings = FOAM_RADII.map((r, ring) => {
    const count = ring === 0 ? 1 : FOAM_SEGMENTS;
    return Array.from({ length: count }, (_, k) => {
      const angle = (k / FOAM_SEGMENTS) * Math.PI * 2;
      const [x, y] = [Math.cos(angle) * r, Math.sin(angle) * r];
      spot
        .copy(centre)
        .addScaledVector(outward, x / radius)
        .addScaledVector(across, y / radius)
        .normalize()
        .multiplyScalar(radius + fall.footHeight + LAKE_LIFT + FOAM_LIFT);
      return out.vertex(spot, [r, x, y, 0]);
    });
  });
  for (let ring = 1; ring < rings.length; ring++)
    for (let k = 0; k < FOAM_SEGMENTS; k++) {
      const next = (k + 1) % FOAM_SEGMENTS;
      const inner = rings[ring - 1];
      const outer = rings[ring];
      // angles run clockwise seen from above (from `out` towards `across`)
      if (ring === 1) out.triangle(inner[0], outer[next], outer[k]);
      else {
        out.triangle(inner[k], outer[next], outer[k]);
        out.triangle(inner[k], inner[next], outer[next]);
      }
    }
  return out.build();
}
