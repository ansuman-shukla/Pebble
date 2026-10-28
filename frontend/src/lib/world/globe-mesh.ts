/*
 * Geometry for the planet: the terrain (one flat-shaded triangle per grid triangle, coloured by its corners'
 * biomes) and the rivers (ribbons that follow the terrain along their cell paths).
 */
import { BufferGeometry, Color, Float32BufferAttribute, Vector3 } from 'three';

import {
  cellDirection,
  type Globe,
  type GlobeTerrain,
  WATER_BIOMES,
  WATER_SURFACE,
} from './globe';

const BIOME_COLORS: Record<string, string> = {
  deep_ocean: '#24405e',
  shallow_ocean: '#5f9c9e',
  beach: '#e6d6a2',
  grassland: '#93b55c',
  broadleaf_forest: '#4f8a3c',
  taiga: '#3e6a4c',
  wetland: '#6f8c5c',
  hills: '#9c9a62',
  mountain: '#8b847a',
  savanna: '#c6b264',
  tundra: '#a9a892',
  snow: '#f1f4f6',
  ice: '#d9ebf4',
  lake: '#5f9c9e',
  volcanic: '#5e5450',
};
const FALLBACK_COLOR = '#ff00ff';
/** Lakes are terrain faces flat at their surface height, drawn the colour the sea shows near its shores. */
const LAKE_WATER = '#4284b0';
/** How far a dry face touching water turns to sand: a sea beach, a lake shore. */
const BEACH_SAND = 0.6;
const LAKE_SHORE_SAND = 0.25;

/** The terrain colour of a biome (by name, so the client never depends on the id order). */
export const biomeColor = (name: string) =>
  BIOME_COLORS[name] ?? FALLBACK_COLOR;

/** Small deterministic per-triangle brightness jitter for the low-poly look. */
function jitter(index: number) {
  let h = Math.imul(index + 1, 0x27d4eb2d);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  return (((h ^ (h >>> 13)) >>> 0) / 4294967296) * 2 - 1;
}

/**
 * Non-indexed terrain: every triangle gets its own vertices and one colour (flat, faceted shading). A face
 * above the sea takes the colours of its land corners (a shore face turns to sand), a face under it those
 * of its water corners, so no sea colour shows on dry land. Lakes lie above the sea at their surface height:
 * a face whose corners are all lake is the lake's water.
 */
export function terrainGeometry(globe: Globe, biomeNames: readonly string[]) {
  const { positions, heights, biomes, triangles, radius } = globe;
  const palette = biomeNames.map((name) => new Color(biomeColor(name)));
  const sand = new Color(biomeColor('beach'));
  const shallows = new Color(biomeColor('shallow_ocean'));
  const lake = biomeNames.indexOf('lake');
  const lakeWater = new Color(LAKE_WATER);
  const count = triangles.length;
  const vertices = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const color = new Color();
  for (let t = 0; t < count / 3; t++) {
    const cells = triangles.subarray(t * 3, t * 3 + 3);
    let height = 0;
    cells.forEach((cell, k) => {
      const scale = radius + heights[cell];
      for (let axis = 0; axis < 3; axis++)
        vertices[(t * 3 + k) * 3 + axis] = positions[cell * 3 + axis] * scale;
      height += heights[cell] / 3;
    });
    const dry = height > WATER_SURFACE;
    const lakeCorners = [...cells].filter((cell) => biomes[cell] === lake);
    if (dry && lakeCorners.length === 3) {
      color.copy(lakeWater).multiplyScalar(1 + jitter(t) * 0.02);
      for (let k = 0; k < 3; k++) color.toArray(colors, (t * 3 + k) * 3);
      continue;
    }
    const matching = [...cells].filter(
      (cell) => WATER_BIOMES.has(biomes[cell]) !== dry,
    );
    color.setRGB(0, 0, 0);
    for (const cell of matching) color.add(palette[biomes[cell]]);
    if (matching.length > 0) color.multiplyScalar(1 / matching.length);
    else color.copy(dry ? sand : shallows);
    if (dry && matching.length < 3)
      color.lerp(
        sand,
        matching.length + lakeCorners.length === 3
          ? LAKE_SHORE_SAND
          : BEACH_SAND,
      );
    // higher land a touch lighter, plus a little noise per face
    const shade = 1 + jitter(t) * 0.05 + Math.max(0, height) / 1500;
    color.multiplyScalar(shade);
    for (let k = 0; k < 3; k++) color.toArray(colors, (t * 3 + k) * 3);
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3));
  geometry.setAttribute('color', new Float32BufferAttribute(colors, 3));
  geometry.computeVertexNormals();
  return geometry;
}

const RIVER_WIDTH = 6;
const RIVER_LIFT = 0.35;
const RIVER_STEPS = 4;

/** Ribbons along each river's cell path, sampled several times per cell and lifted just above the ground. */
export function riverGeometry(terrain: GlobeTerrain, rivers: number[][]) {
  const { globe } = terrain;
  const { radius } = globe;
  const vertices: number[] = [];
  const surface = (direction: Vector3, hint: number) =>
    direction
      .clone()
      .multiplyScalar(
        radius + Math.max(terrain.heightAt(direction, hint), 0) + RIVER_LIFT,
      );
  for (const cells of rivers) {
    if (cells.length < 2) continue;
    const path: { direction: Vector3; cell: number }[] = [];
    for (let i = 0; i + 1 < cells.length; i++) {
      const a = cellDirection(globe, cells[i], new Vector3());
      const b = cellDirection(globe, cells[i + 1], new Vector3());
      for (let s = 0; s < RIVER_STEPS; s++)
        path.push({
          direction: a
            .clone()
            .lerp(b, s / RIVER_STEPS)
            .normalize(),
          cell: cells[i],
        });
    }
    const last = cells[cells.length - 1];
    path.push({
      direction: cellDirection(globe, last, new Vector3()),
      cell: last,
    });
    const edges = path.map(({ direction, cell }, i) => {
      const ahead = path[Math.min(i + 1, path.length - 1)].direction;
      const behind = path[Math.max(i - 1, 0)].direction;
      const side = new Vector3()
        .subVectors(ahead, behind)
        .cross(direction)
        .normalize()
        .multiplyScalar(RIVER_WIDTH / 2 / radius);
      return [
        surface(direction.clone().add(side).normalize(), cell),
        surface(direction.clone().sub(side).normalize(), cell),
      ];
    });
    for (let i = 0; i + 1 < edges.length; i++) {
      const [a, b] = edges[i];
      const [c, d] = edges[i + 1];
      // a and c are on the right bank: counter-clockwise seen from above
      vertices.push(...a.toArray(), ...c.toArray(), ...b.toArray());
      vertices.push(...c.toArray(), ...d.toArray(), ...b.toArray());
    }
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(vertices, 3));
  geometry.computeVertexNormals();
  return geometry;
}
