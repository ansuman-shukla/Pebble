/*
 * Waterholes drawn as pools (10 §4.6): a waterhole with no river or lake at hand (`Feature.pool`) is a level pool
 * dug into the ground where the simulation has it. Its water lies WATERHOLE_POOL_M round the waterhole, a little
 * below the ground at its middle, over a bowl-shaped bed; a muddy bank rises from the water to meet the ground
 * WATERHOLE_BANK_M out, where the terrain stops drawing (a hole in the ground shader) and the bank's outer ring
 * lies on the terrain's own height. On a slope the bank is cut into the hill above the water and raised as a low
 * dam below it, so the water stays level and contained. Herds drink standing round the water's edge (the
 * backend's `POOL_RADIUS_M` / `POOL_BANK_M` are the same numbers).
 */
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  Vector3,
} from 'three';

import type { Feature } from '../client/types.gen';
import { type GlobeTerrain, tangentFrame } from './globe';
import {
  biomeGroundClaims,
  groundWeights,
  quantizeWeights,
} from './globe-mesh';
import { GROUND_LAYERS } from './ground-shader';
import { biomeColor } from './ground-style';

/** The pool's water reaches this far (metres) from the waterhole (the backend's POOL_RADIUS_M). */
export const WATERHOLE_POOL_M = 3;
/** Its bank meets the ground this far out (the backend's POOL_BANK_M). */
export const WATERHOLE_BANK_M = 7;
/** The terrain stops drawing this far inside the bank's outer ring, so no sliver of sky shows between them. */
const HOLE_MARGIN = 0.2;
/** The water lies this far below the ground at the waterhole. */
const DIG = 0.3;
/** The bed is this deep at the middle (deep enough for the water shader's colour; steep near the edge). */
const DEPTH = 1.8;
/** Below the water the bank rises at least this far above it (out to the crest), then falls to the ground. */
const CREST_RISE = 0.25;
const CREST_M = 4;
/** Rings of the bowl (metres from the middle): the bed, the water's edge, the bank out to the ground. */
const RINGS = [
  0,
  1.2,
  2.2,
  WATERHOLE_POOL_M,
  3.5,
  CREST_M,
  5,
  6,
  WATERHOLE_BANK_M,
];
const SEGMENTS = 48;
const MUD = GROUND_LAYERS.indexOf('mud');
const DIRT = GROUND_LAYERS.indexOf('dirt');

export interface WaterholePool {
  id: string;
  /** Unit direction of the waterhole. */
  up: Vector3;
  /** The water's height above sea level. */
  level: number;
}

/** The waterholes the simulation has away from rivers and lakes, each a pool at its own level. */
export function waterholePools(
  features: readonly Pick<Feature, 'id' | 'kind' | 'pool' | 'position'>[],
  terrain: GlobeTerrain,
): WaterholePool[] {
  return features
    .filter((feature) => feature.kind === 'waterhole' && feature.pool)
    .map((feature) => {
      const up = new Vector3(...feature.position).normalize();
      return { id: feature.id, up, level: terrain.heightAt(up) - DIG };
    });
}

/** The cones of ground the terrain leaves to the pools (up, cos of the angular radius). */
export const poolHoles = (pools: readonly WaterholePool[], radius: number) =>
  pools.map(({ up }) => ({
    up,
    cos: Math.cos((WATERHOLE_BANK_M - HOLE_MARGIN) / radius),
  }));

/** The bed's height under the water at `r` metres from the middle (the water's edge at WATERHOLE_POOL_M). */
const bed = (level: number, r: number) =>
  level - DEPTH * (1 - (r / WATERHOLE_POOL_M) ** 3);

/**
 * The pools' bowls and their water, in planet metres: `bank` (bed and bank, with the ground shader's layer weights:
 * wet mud by the water turning into the ground's own layers at the outer ring) and `water` (with the depth the
 * water shader reads).
 */
export function poolGeometry(
  pools: readonly WaterholePool[],
  terrain: GlobeTerrain,
  biomeNames: readonly string[],
) {
  const { globe } = terrain;
  const { radius } = globe;
  const positions: number[] = [];
  const colors: number[] = [];
  const layers: number[] = [];
  const index: number[] = [];
  const waterPositions: number[] = [];
  const waterData: number[] = [];
  const waterIndex: number[] = [];
  const direction = new Vector3();
  const tint = new Color();
  const weights = new Float64Array(GROUND_LAYERS.length);
  const bytes = new Uint8Array(GROUND_LAYERS.length);

  for (const pool of pools) {
    const { east, north } = tangentFrame(pool.up);
    const start = positions.length / 3;
    const waterStart = waterPositions.length / 3;
    const at = (r: number, angle: number) =>
      direction
        .copy(pool.up)
        .multiplyScalar(radius)
        .addScaledVector(east, Math.cos(angle) * r)
        .addScaledVector(north, Math.sin(angle) * r)
        .normalize();
    const hit = terrain.locate(pool.up);
    const cell = hit.cell;
    tint.set(biomeColor(biomeNames[globe.biomes[cell]]));
    for (let k = 0; k < SEGMENTS; k++) {
      const angle = (k / SEGMENTS) * Math.PI * 2;
      const lip = pool.level + 0.04;
      const outer = terrain.heightAt(at(WATERHOLE_BANK_M, angle), cell);
      for (const r of RINGS) {
        let height: number;
        if (r < WATERHOLE_POOL_M) height = bed(pool.level, r);
        else {
          // from the water's edge up (or down) to the ground, never lower than the crest out to CREST_M
          const s =
            (r - WATERHOLE_POOL_M) / (WATERHOLE_BANK_M - WATERHOLE_POOL_M);
          const base = lip + (outer - lip) * s * s * (3 - 2 * s);
          const hold =
            r <= CREST_M
              ? 1
              : (WATERHOLE_BANK_M - r) / (WATERHOLE_BANK_M - CREST_M);
          height = base + Math.max(0, pool.level + CREST_RISE - base) * hold;
        }
        if (r === WATERHOLE_BANK_M) height = outer;
        at(r, angle).multiplyScalar(radius + height);
        positions.push(direction.x, direction.y, direction.z);
        colors.push(tint.r, tint.g, tint.b);
        // wet mud by the water, trodden dirt up the bank, the ground's own layers where it meets the terrain
        if (r === WATERHOLE_BANK_M) {
          const ground = terrain.locate(at(r, angle), cell);
          groundWeights(
            {
              claims: biomeGroundClaims(biomeNames[globe.biomes[ground.cell]]),
              slope: (Math.acos(1 - ground.tilt) * 180) / Math.PI,
              height: ground.height,
              lakeLevel: Infinity,
            },
            weights,
          );
        } else {
          weights.fill(0);
          const dry = Math.max(0, (r - 3.5) / (WATERHOLE_BANK_M - 3.5));
          weights[MUD] = 1 - dry;
          weights[DIRT] = dry;
        }
        quantizeWeights(weights, bytes, 0);
        layers.push(...bytes);
      }
      for (const r of RINGS.filter((ring) => ring <= WATERHOLE_POOL_M)) {
        at(r, angle).multiplyScalar(radius + pool.level);
        waterPositions.push(direction.x, direction.y, direction.z);
        waterData.push(pool.level - bed(pool.level, r), 0, 0, 0);
      }
    }
    const quads = (out: number[], first: number, rings: number) => {
      for (let k = 0; k < SEGMENTS; k++) {
        const a = first + k * rings;
        const b = first + ((k + 1) % SEGMENTS) * rings;
        for (let i = 0; i + 1 < rings; i++)
          out.push(a + i, a + i + 1, b + i, b + i, a + i + 1, b + i + 1);
      }
    };
    quads(index, start, RINGS.length);
    quads(
      waterIndex,
      waterStart,
      RINGS.filter((ring) => ring <= WATERHOLE_POOL_M).length,
    );
  }

  const bank = new BufferGeometry();
  bank.setAttribute('position', new Float32BufferAttribute(positions, 3));
  bank.setAttribute('color', new Float32BufferAttribute(colors, 3));
  const packed = Uint8Array.from(layers);
  const ground0 = new Uint8Array(packed.length / 2);
  const ground1 = new Uint8Array(packed.length / 2);
  for (let v = 0; v < packed.length / 8; v++) {
    ground0.set(packed.subarray(v * 8, v * 8 + 4), v * 4);
    ground1.set(packed.subarray(v * 8 + 4, v * 8 + 8), v * 4);
  }
  bank.setAttribute('ground0', new BufferAttribute(ground0, 4, true));
  bank.setAttribute('ground1', new BufferAttribute(ground1, 4, true));
  bank.setIndex(index);
  bank.computeVertexNormals();

  const water = new BufferGeometry();
  water.setAttribute('position', new Float32BufferAttribute(waterPositions, 3));
  water.setAttribute('water', new Float32BufferAttribute(waterData, 4));
  water.setIndex(waterIndex);
  water.computeVertexNormals();
  return { bank, water };
}
