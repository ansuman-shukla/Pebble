/*
 * One water shader for every kind of water: the sea and lakes (`still`), rivers (`flowing`), falling sheets
 * (`falling`), foam around a fall's foot (`foam`) and the town's moat and stream (`pool`). It is a
 * MeshStandardMaterial (so the sun, the sky light, shadows and fog light it like everything else) with a few
 * chunks added: an animated height field bumps the normal, colour and opacity follow the water's depth, the
 * banks fade out softly with a band of foam, and the sky's colour shows at grazing angles (dusk tints the water,
 * night darkens it). All materials share one clock and one sky colour, refreshed from the scene's fog (the sky
 * colour, see globe-sky.tsx) whenever a water mesh renders.
 *
 * Per-vertex data comes in the `water` attribute (vec4):
 * - still / pool: x = depth under the surface in metres (negative on dry land), yzw unused
 * - flowing: x = across (−1 … 1 at the water's edges, out to ±BANK_EDGE over the wet bank), y = metres downstream,
 *   z = flow speed (m/s), w = fade (0 where the river begins, ends or joins other water)
 * - falling: x = across (−1 … 1), y = metres down the sheet, z = fall speed (m/s), w = 0 at the lip … 1 at the foot
 * - foam: x = metres from where the fall lands, yz = that offset in metres (along the fall, across), w unused
 */
import { Color, MeshStandardMaterial, type Scene } from 'three';

export type WaterKind = 'still' | 'flowing' | 'falling' | 'foam' | 'pool';

/** How far past the water's edge (in half widths) a river ribbon's wet bank reaches. */
export const BANK_EDGE = 1.3;

const DAY_SKY = '#a9cfea';
/** Water over a shallow bed, over deep water, and the damp ground along a river. */
const SHALLOW = '#3f9c9c';
const DEEP = '#123a5e';
const BANK = '#5b4a33';

/** Shared by every water material: seconds since load and the sky colour. */
const shared = {
  waterTime: { value: 0 },
  waterSky: { value: new Color(DAY_SKY) },
  waterShallow: { value: new Color(SHALLOW) },
  waterDeep: { value: new Color(DEEP) },
  waterBank: { value: new Color(BANK) },
};

/** The clock every water material animates with (exposed for the render stats). */
export const waterClock = () => shared.waterTime.value;

const LOADED_AT = performance.now();

function refresh(scene: Scene) {
  shared.waterTime.value = (performance.now() - LOADED_AT) / 1000;
  const fog = scene.fog;
  if (fog) shared.waterSky.value.copy(fog.color);
}

const COMMON = /* glsl */ `
uniform float waterTime;
uniform vec3 waterSky;
uniform vec3 waterShallow;
uniform vec3 waterDeep;
uniform vec3 waterBank;
varying vec3 vWaterWorld;
varying vec4 vWater;
`;

const FRAGMENT_HELPERS = /* glsl */ `
float waterHash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
float waterNoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(waterHash(i), waterHash(i + vec2(1.0, 0.0)), u.x),
    mix(waterHash(i + vec2(0.0, 1.0)), waterHash(i + vec2(1.0, 1.0)), u.x),
    u.y
  );
}
/* Gentle waves on still water: a few sines over the world position (seamless on the sphere). */
float waterWaves(vec3 p, float t) {
  return 0.50 * sin(dot(p, vec3(0.31, 0.11, 0.23)) + t * 0.9)
    + 0.35 * sin(dot(p, vec3(-0.17, 0.29, 0.19)) + t * 1.3)
    + 0.25 * sin(dot(p, vec3(0.43, -0.37, 0.09)) + t * 1.7)
    + 0.18 * sin(dot(p, vec3(-0.21, -0.48, 0.52)) + t * 2.3)
    + 0.12 * sin(dot(p, vec3(0.83, 0.61, -0.47)) + t * 2.9)
    + 0.08 * sin(dot(p, vec3(-0.97, 0.53, 0.88)) + t * 3.7);
}
/* Bumps a view-space normal by a height field h over the fragment's view position (screen derivatives). */
vec3 waterBump(vec3 position, vec3 normal, float h) {
  vec3 dx = dFdx(position);
  vec3 dy = dFdy(position);
  vec3 r1 = cross(dy, normal);
  vec3 r2 = cross(normal, dx);
  float det = dot(dx, r1);
  vec3 grad = sign(det) * (dFdx(h) * r1 + dFdy(h) * r2);
  return normalize(abs(det) * normal - grad);
}
`;

/* The water's look per kind: sets diffuseColor (rgb + alpha), bumps \`normal\` and adds sky light. */
const SURFACE = /* glsl */ `
{
  float t = waterTime;
  float viewDistance = length(vViewPosition);
  float detail = 1.0 - smoothstep(120.0, 700.0, viewDistance);
  vec3 shallowColor = waterShallow;
  vec3 deepColor = waterDeep;
  vec3 foamColor = vec3(0.9, 0.95, 1.0);
  vec3 color;
  float alpha;
  float height;
  float foam = 0.0;
  float reflection = 0.35;

#if defined(WATER_STILL) || defined(WATER_POOL)
  float depth = vWater.x;
  float deepMix = smoothstep(0.0, 14.0, depth);
  color = mix(shallowColor, deepColor, sqrt(deepMix));
  height = waterWaves(vWaterWorld, t) * 0.08;
  #ifdef WATER_STILL
    alpha = smoothstep(0.0, 1.6, depth) * mix(0.62, 0.93, deepMix);
    // lapping foam at the shore: bands that run up the beach, broken up by the waves
    float lap = sin(depth * 5.0 - t * 1.6 + height * 30.0);
    float shore = (1.0 - smoothstep(0.05, 0.9, depth)) * smoothstep(-0.05, 0.08, depth);
    foam = shore * smoothstep(0.1, 0.9, lap * 0.5 + 0.5);
  #else
    alpha = 0.9;
  #endif
#endif

#ifdef WATER_FLOWING
  float across = vWater.x;
  float along = vWater.y;
  float speed = vWater.z;
  float edge = abs(across);
  vec2 flow = vec2(across * 3.0, along * 0.12 - t * speed * 0.12);
  float streak = waterNoise(flow) * 0.6 + waterNoise(flow * vec2(2.1, 2.6) + 7.1) * 0.4;
  height = streak * 0.3 * (0.6 + speed * 0.25);
  float centre = 1.0 - edge * edge;
  color = mix(shallowColor, deepColor, clamp(centre * 0.8, 0.0, 1.0));
  float water = 1.0 - smoothstep(0.82, 1.0, edge);
  // rapids: steeper water froths along its streaks; every river foams a little along its banks
  float rapids = smoothstep(1.4, 3.5, speed);
  foam = smoothstep(0.72 - rapids * 0.22, 0.95, streak) * (0.15 + rapids * 0.7) * water;
  vec2 ripple = vec2(across * 7.0, along * 0.45 - t * speed * 0.45);
  foam += smoothstep(0.7, 0.97, edge) * water * smoothstep(0.45, 0.8, waterNoise(ripple)) * 0.6;
  // the wet bank: dark damp ground fading out into the terrain
  float bank = (1.0 - smoothstep(1.0, ${BANK_EDGE.toFixed(2)}, edge)) * (1.0 - water);
  color = mix(color, waterBank, 1.0 - water);
  alpha = max(water * 0.9, bank * 0.45) * vWater.w;
  reflection *= water;
#endif

#ifdef WATER_FALLING
  float across = vWater.x;
  float down = vWater.y;
  float speed = vWater.z;
  float foot = vWater.w;
  vec2 fall = vec2(across * 7.0, down * 0.22 - t * speed * 0.22);
  float streak = waterNoise(fall * vec2(1.0, 0.35)) * 0.55 + waterNoise(fall * vec2(2.7, 0.9) + 4.2) * 0.45;
  height = streak * 0.6;
  color = mix(vec3(0.55, 0.78, 0.86), foamColor, 0.35 + foot * 0.4);
  foam = smoothstep(0.45, 0.85, streak) * (0.5 + foot * 0.5);
  float sides = 1.0 - smoothstep(0.7, 1.0, abs(across));
  alpha = sides * (0.7 + streak * 0.3);
  reflection = 0.25;
#endif

#ifdef WATER_FOAM
  float distance = vWater.x;
  vec2 local = vWater.yz;
  vec2 churn = local * 0.45 - local / max(distance, 0.001) * t * 1.3;
  float froth = waterNoise(churn) * 0.6 + waterNoise(churn * 2.7 + 1.9) * 0.4;
  color = foamColor;
  height = froth * 0.3;
  alpha = smoothstep(0.35, 0.8, froth) * (1.0 - smoothstep(4.0, 16.0, distance)) * 0.85;
  reflection = 0.1;
#endif

  normal = waterBump(-vViewPosition, normal, height * detail);
  float facing = clamp(dot(normal, normalize(vViewPosition)), 0.0, 1.0);
  float fresnel = 0.04 + 0.96 * pow(1.0 - facing, 5.0);
  color = mix(color, foamColor, clamp(foam, 0.0, 1.0));
  diffuseColor.rgb = color;
  diffuseColor.a = clamp(max(alpha, foam * 0.9 * step(0.001, alpha + foam)) + fresnel * 0.35 * alpha, 0.0, 1.0);
  totalEmissiveRadiance += waterSky * fresnel * reflection;
  // white water catches the sky's light from every side (none at night: the sky is dark then)
  totalEmissiveRadiance += waterSky * clamp(foam, 0.0, 1.0) * 0.25;
}
`;

const DEFINES: Record<WaterKind, string> = {
  still: 'WATER_STILL',
  flowing: 'WATER_FLOWING',
  falling: 'WATER_FALLING',
  foam: 'WATER_FOAM',
  pool: 'WATER_POOL',
};

/** A water material of one kind (its geometry carries the `water` attribute described above). */
export function waterMaterial(kind: WaterKind) {
  const material = new MeshStandardMaterial({
    color: '#ffffff',
    roughness: 0.28,
    metalness: 0,
    transparent: true,
    depthWrite: kind === 'still' || kind === 'pool',
    polygonOffset: true,
    polygonOffsetFactor: kind === 'flowing' ? -2 : -1,
    polygonOffsetUnits: kind === 'flowing' ? -4 : -2,
  });
  material.defines = { [DEFINES[kind]]: '' };
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, shared);
    shader.vertexShader = shader.vertexShader
      .replace(
        '#include <common>',
        `#include <common>\n${COMMON}\nattribute vec4 water;`,
      )
      .replace(
        '#include <project_vertex>',
        '#include <project_vertex>\nvWater = water;\nvWaterWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>\n${COMMON}\n${FRAGMENT_HELPERS}`,
      )
      .replace(
        '#include <normal_fragment_maps>',
        `#include <normal_fragment_maps>\n${SURFACE}`,
      );
  };
  material.customProgramCacheKey = () => `water-${kind}`;
  material.onBeforeRender = (_renderer, scene) => refresh(scene);
  return material;
}
