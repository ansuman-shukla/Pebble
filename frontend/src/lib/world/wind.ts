/*
 * The wind (10 §5.3): one direction and strength for the sky, from a noise of game time that turns over the day,
 * sways vegetation (tree 0.15 m, bamboo 0.25, crops 0.08, grass 0.05 at the top) and waves cloth (banners) in the
 * vertex shader, at natural speed × windRate (D83). Kinds sway by their name (`KIND_SWAY`); cloth is a part named
 * `banner-cloth` (10 §5.5). `windOffset` is the shader's formula in TypeScript, for tests and probes.
 */
import { Vector3 } from 'three';

import { type PropKind, PROPS } from './assets';
import type { VertexChunk } from './vertex-chunks';

export type SwayClass = 'tree' | 'bamboo' | 'crop' | 'grass';

/** Metres the top of a plant leans in a full wind. */
export const SWAY_M: Record<SwayClass, number> = {
  tree: 0.15,
  bamboo: 0.25,
  crop: 0.08,
  grass: 0.05,
};

/** Metres the free edge of a banner waves in a full wind. */
export const CLOTH_WAVE_M = 0.12;

/** Parts that wave like cloth: fixed along the edge nearest the model's axis (the pole), free at the other. */
export const CLOTH_PARTS = new Set(['banner-cloth']);

const KIND_SWAY: Partial<Record<PropKind, SwayClass>> = {
  cherry_tree: 'tree',
  maple_tree: 'tree',
  sculpted_pine: 'tree',
  oak_tree: 'tree',
  nut_tree: 'tree',
  birch_tree: 'tree',
  pine_tree: 'tree',
  young_pine: 'tree',
  snowy_spruce: 'tree',
  acacia_tree: 'tree',
  tree_fern: 'tree',
  dead_tree: 'tree',
  giant_tree: 'tree',
  bamboo: 'bamboo',
  // crops and the low plants of fields and shores (shrubs lean like crops)
  rice_paddy: 'crop',
  reeds: 'crop',
  reed_bed: 'crop',
  cattail: 'crop',
  root_patch: 'crop',
  azalea: 'crop',
  bush: 'crop',
  dry_bush: 'crop',
  berry_bush: 'crop',
  dwarf_pine: 'crop',
  grass_tuft: 'grass',
  dry_grass: 'grass',
  dune_grass: 'grass',
  wildflower: 'grass',
  fern: 'grass',
};

const SWAY_BY_ASSET = new Map(
  Object.entries(KIND_SWAY).map(([kind, sway]) => [
    PROPS[kind as PropKind],
    sway,
  ]),
);

/** How a model's asset sways in the wind, or undefined when it stands still. */
export const swayOf = (id: string) => SWAY_BY_ASSET.get(id);

/** What a material's wind chunk needs to know about its model. */
export interface WindProfile {
  /** Metres the model's top leans in a full wind (0: no sway). */
  sway: number;
  /** Height of the model (its top leans `sway`, its foot stays put). */
  height: number;
  /** Model-space normal of its cloth parts, when some vertices carry a `windCloth` weight. */
  clothNormal?: Vector3;
}

/** One sky: shared by every wind material. */
export const windUniforms = {
  windTime: { value: 0 },
  windDirection: { value: new Vector3(1, 0, 0) },
  windStrength: { value: 0.5 },
};

const DAY_TURN = 12 * 60;
const STRENGTH_CHANGE = 3 * 60;

function hash(n: number) {
  const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
}

/** Smooth 1D value noise in [0, 1). */
function noise(x: number) {
  const i = Math.floor(x);
  const f = x - i;
  const t = f * f * (3 - 2 * f);
  return hash(i) * (1 - t) + hash(i + 1) * t;
}

/** The wind at town time `minutes`: its compass angle (radians, from east towards north) and strength 0.25-1. */
export function windAt(minutes: number) {
  return {
    angle: noise(minutes / DAY_TURN) * 2 * Math.PI,
    strength: 0.25 + 0.75 * noise(minutes / STRENGTH_CHANGE + 17.3),
  };
}

const Y = new Vector3(0, 1, 0);
const east = new Vector3();
const north = new Vector3();

/** Sets the sky's wind for town time `minutes`, `time` seconds of wind played, blowing across `up` (flat: +y). */
export function setWind(minutes: number, time: number, up?: Vector3) {
  const { angle, strength } = windAt(minutes);
  if (up && Math.abs(up.y) < 0.999) {
    east.crossVectors(Y, up).normalize();
    north.crossVectors(up, east);
  } else {
    east.set(1, 0, 0);
    north.set(0, 0, -1);
  }
  windUniforms.windDirection.value
    .copy(east)
    .multiplyScalar(Math.cos(angle))
    .addScaledVector(north, Math.sin(angle));
  windUniforms.windStrength.value = strength;
  windUniforms.windTime.value = time;
}

const VERTEX_COMMON = /* glsl */ `
uniform float windTime;
uniform vec3 windDirection;
uniform float windStrength;
uniform float windSway;
uniform float windHeight;
#ifdef WIND_CLOTH
attribute float windCloth;
uniform vec3 windClothNormal;
uniform float windClothWave;
#endif
`;

/* `transformed` is in model space (parts are baked at rest), so its height is the height above the model's foot. */
const VERTEX_MAIN = /* glsl */ `
{
#ifdef USE_INSTANCING
  mat4 windPlace = modelMatrix * instanceMatrix;
#else
  mat4 windPlace = modelMatrix;
#endif
  vec3 windLocal = transpose(mat3(windPlace)) * windDirection;
  windLocal.y = 0.0;
  float windAcross = length(windLocal);
  windLocal = windAcross > 1e-4 ? windLocal / windAcross : vec3(0.0);
  float windPhase = dot(windPlace[3].xyz, vec3(0.37, 0.21, 0.29));
  float windRise = clamp(transformed.y / windHeight, 0.0, 1.0);
  float windLean = 0.5 + 0.5 * sin(windTime * 1.3 + windPhase + 0.25 * (transformed.x + transformed.z));
  transformed += windLocal * (windSway * windStrength * windRise * windRise * windLean);
#ifdef WIND_CLOTH
  float windWave = sin(windTime * 3.0 - windCloth * 5.0 + windPhase + transformed.y * 1.2);
  transformed += windClothNormal * (windClothWave * windCloth * (0.35 + 0.65 * windStrength) * windWave);
#endif
}
`;

/**
 * The shader's offset of a model-space `point` in TypeScript: `across` is the wind's direction in model space
 * (horizontal, unit or zero), `phase` the instance's phase, `cloth` the vertex's cloth weight.
 */
export function windOffset(
  point: Vector3,
  profile: WindProfile,
  wind: { time: number; strength: number; across: Vector3; phase: number },
  cloth = 0,
  target = new Vector3(),
) {
  const rise = Math.min(Math.max(point.y / profile.height, 0), 1);
  const lean =
    0.5 +
    0.5 * Math.sin(wind.time * 1.3 + wind.phase + 0.25 * (point.x + point.z));
  target
    .copy(wind.across)
    .multiplyScalar(profile.sway * wind.strength * rise * rise * lean);
  if (profile.clothNormal) {
    const wave = Math.sin(
      wind.time * 3 - cloth * 5 + wind.phase + point.y * 1.2,
    );
    target.addScaledVector(
      profile.clothNormal,
      CLOTH_WAVE_M * cloth * (0.35 + 0.65 * wind.strength) * wave,
    );
  }
  return target;
}

/** The wind as a vertex chunk (vertex-chunks.ts) for a model with `profile`, on its colour and shadow materials. */
export function windChunk(profile: WindProfile): VertexChunk {
  const cloth = profile.clothNormal !== undefined;
  return {
    key: cloth ? 'wind-cloth' : 'wind',
    defines: cloth ? { WIND_CLOTH: '' } : {},
    uniforms: {
      ...windUniforms,
      windSway: { value: profile.sway },
      windHeight: { value: Math.max(profile.height, 0.01) },
      ...(cloth && {
        windClothNormal: { value: profile.clothNormal },
        windClothWave: { value: CLOTH_WAVE_M },
      }),
    },
    common: VERTEX_COMMON,
    position: VERTEX_MAIN,
  };
}

/** The per-vertex cloth weight of a cloth part's model-space positions: 0 at the fixed edge, 1 at the free edge. */
export function clothWeights(positions: ArrayLike<number>) {
  const count = positions.length / 3;
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < count; i++)
    for (let axis = 0; axis < 3; axis++) {
      min[axis] = Math.min(min[axis], positions[i * 3 + axis]);
      max[axis] = Math.max(max[axis], positions[i * 3 + axis]);
    }
  // the cloth hangs in a vertical plane: it is thin across one horizontal axis and spans the other from the pole
  const along = max[0] - min[0] >= max[2] - min[2] ? 0 : 2;
  const fixed =
    Math.abs(min[along]) <= Math.abs(max[along]) ? min[along] : max[along];
  const span = Math.max(max[along] - min[along], 1e-6);
  const weights = new Float32Array(count);
  for (let i = 0; i < count; i++)
    weights[i] = Math.abs(positions[i * 3 + along] - fixed) / span;
  const normal = along === 0 ? new Vector3(0, 0, 1) : new Vector3(1, 0, 0);
  return { weights, normal };
}
