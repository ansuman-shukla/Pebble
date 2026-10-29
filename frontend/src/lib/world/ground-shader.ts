/*
 * One ground material for the planet's terrain and the sites' own ground (zero textures). Every vertex carries 8
 * layer weights (`ground0` = grass, forest floor, dirt, gravel; `ground1` = sand, rock, snow, mud; RGBA8, summing
 * to 1) and its grass tint (the vertex colour). Per fragment, in planet-space metres (no UVs, no seams, no tiling):
 * - two noise fields break layers into patches (grass into dirt and gravel, rock into scree, ...: the style's
 *   breakup rules), then a height blend of the weights and the fields picks the top two layers with crisp, ragged
 *   1-3 m edges;
 * - only those two layers draw their pattern (ground-style.ts), and the pattern's relief bumps the normal;
 * - level of detail by view distance: full < 40 m, no bump 40-300 m, layer colours and a tone > 300 m, and the
 *   per-vertex layer colours alone > 1.5 km.
 * A mesh without the weight attributes (the town's grass) passes constant weights; its tint is the material colour.
 * Pages pick the quality with `?ground=`: `flat` (layer colours only, the A/B baseline) or `low` (one pattern, no
 * bump).
 */
import { Color, MeshStandardMaterial, type Vector3 } from 'three';

import {
  type GroundBreakup,
  GROUND_STYLE,
  type GroundStyle,
} from './ground-style';

export const GROUND_LAYERS = [
  'grass',
  'forest_floor',
  'dirt',
  'gravel',
  'sand',
  'rock',
  'snow',
  'mud',
] as const;
export type GroundLayer = (typeof GROUND_LAYERS)[number];
export type GroundWeights = Partial<Record<GroundLayer, number>>;

export type GroundQuality = 'full' | 'low' | 'flat';

/** The quality a page's query (`location.search`) asks for with `?ground=` (anything else: full). */
export function groundQuality(search: string): GroundQuality {
  const asked = new URLSearchParams(search).get('ground');
  return asked === 'flat' || asked === 'low' ? asked : 'full';
}

/** A cone of directions where the ground draws nothing (a site lays its own ground there). */
interface GroundHole {
  up: Vector3;
  /** cos of the cone's angular radius. */
  cos: number;
}

export interface GroundMaterialOptions {
  quality?: GroundQuality;
  hole?: GroundHole | null;
  /** Constant layer weights for a mesh without `ground0`/`ground1` (missing layers are 0; the rest is grass). */
  weights?: GroundWeights;
  /** The grass tint where the mesh has no vertex colours. */
  tint?: string;
  style?: GroundStyle;
}

/** How much of each face's own flat normal shows through the smooth normals: a hint of the low-poly facets. */
const FACETS = 0.35;
/** The facets fade out between these view distances (metres), where faces shrink to a few pixels. */
const FACETS_FADE: [number, number] = [250, 1200];

const glslFloat = (value: number) => value.toFixed(4);
const glslColor = (hex: string) => {
  const { r, g, b } = new Color(hex);
  return `vec3(${[r, g, b].map(glslFloat).join(', ')})`;
};

/** Layer weights in attribute order, the unnamed rest on grass. */
export function weightsArray(weights: GroundWeights) {
  const values = GROUND_LAYERS.map((layer) => weights[layer] ?? 0);
  const named = values.slice(1).reduce((sum, value) => sum + value, 0);
  if (weights.grass === undefined) values[0] = Math.max(0, 1 - named);
  return values;
}

const layerIndex = (layer: GroundLayer) => GROUND_LAYERS.indexOf(layer);

/*
 * The breakup rules as GLSL: each moves a share of its layer's weight (w, for the colours) to another layer. The
 * heights the pick reads (h) swap the two at full strength instead, so no third layer shows through as a ring
 * where a patch's edge splits its layer half and half.
 */
function breakupGlsl(rules: GroundBreakup[]) {
  const moves = rules.map(({ from, to, field, cut, amount }) => {
    const [a, b] = [layerIndex(from), layerIndex(to)];
    return `{ float s = smoothstep(${glslFloat(cut)}, ${glslFloat(cut)} + edge, f${field}); float m = w[${a}] * s * ${glslFloat(amount)}; w[${a}] -= m; w[${b}] += m; float hm = h[${a}] * ${glslFloat(amount)}; h[${a}] -= hm * max(0.0, 2.0 * s - 1.0); h[${b}] += hm * min(1.0, 2.0 * s); }`;
  });
  return `void groundBreakup(inout float w[8], inout float h[8], float f0, float f1, float edge) {\n${moves.join('\n')}\n}`;
}

/*
 * The two layers that draw their pattern: the top two by height (the weights h after the breakup, the fields and
 * a grain), and the first one's share t (0.5..1). Each layer's height rises from -1 with its weight, so a layer
 * fades in rather than pops; the top two share a 0.16 wide band and the second fades out as the third catches up,
 * so the blend never jumps where the pick changes.
 */
const GROUND_PICK = /* glsl */ `
float groundPick(float hw[8], float f0, float f1, float grain, out int first, out int second) {
  first = 0;
  second = 0;
  float h1 = -9.0;
  float h2 = -9.0;
  float h3 = -9.0;
  for (int i = 0; i < 8; i++) {
    float mixer = fract(float(i) * 0.618);
    float h = mix(-1.0, hw[i] + 0.9 * (mix(f0, f1, mixer) - 0.5) + 0.25 * (grain - 0.5), smoothstep(0.0, 0.03, hw[i]));
    if (h > h1) {
      h3 = h2;
      h2 = h1;
      second = first;
      h1 = h;
      first = i;
    } else if (h > h2) {
      h3 = h2;
      h2 = h;
      second = i;
    } else if (h > h3) h3 = h;
  }
  float a1 = min(h1 - h2 + 0.08, h1 - h3);
  float a2 = min(max(h2 - h1 + 0.08, 0.0), h2 - h3);
  return a1 + a2 > 0.0 ? a1 / (a1 + a2) : 1.0;
}
`;

/*
 * The breakup, then the pick: `float groundBlend(inout float w[8], float f0, float f1, float grain, float edge,
 * out int first, out int second)` returns the first layer's share and leaves the broken-up weights in w.
 */
export const groundBlendGlsl = (rules: GroundBreakup[]) => /* glsl */ `
${breakupGlsl(rules)}
${GROUND_PICK}
float groundBlend(inout float w[8], float f0, float f1, float grain, float edge, out int first, out int second) {
  float hw[8] = w;
  groundBreakup(w, hw, f0, f1, edge);
  return groundPick(hw, f0, f1, grain, first, second);
}
`;

/** The style as GLSL: colour constants, base colours, roughness, bump and breakup per layer, and the patterns. */
function styleChunk(style: GroundStyle) {
  const layers = GROUND_LAYERS.map((layer) => style.layers[layer]);
  const colors = GROUND_LAYERS.flatMap((layer) =>
    Object.entries(style.layers[layer].colors).map(
      ([name, hex]) => `const vec3 ${layer}_${name} = ${glslColor(hex)};`,
    ),
  );
  const list = (values: string[], type: string) =>
    `${type}[8](${values.join(', ')})`;
  return {
    constants: [
      `const vec3 grass_reference = ${glslColor(style.grassReference)};`,
      ...colors,
      `const vec3 GROUND_BASE[8] = ${list(
        layers.map(({ base }) => glslColor(base)),
        'vec3',
      )};`,
      `const float GROUND_ROUGHNESS[8] = ${list(
        layers.map(({ roughness }) => glslFloat(roughness)),
        'float',
      )};`,
      `const float GROUND_DEPTH[8] = ${list(
        layers.map(({ bump }) => glslFloat(bump)),
        'float',
      )};`,
    ].join('\n'),
    functions: [groundBlendGlsl(style.breakup), style.patterns].join('\n'),
  };
}

const VERTEX_COMMON = /* glsl */ `
varying vec3 vGroundPlanet;
varying vec4 vGround0;
varying vec4 vGround1;
#ifdef GROUND_CONST
uniform vec4 groundConst0;
uniform vec4 groundConst1;
#else
attribute vec4 ground0;
attribute vec4 ground1;
#endif
`;

const VERTEX_MAIN = /* glsl */ `
vGroundPlanet = position;
#ifdef GROUND_CONST
vGround0 = groundConst0;
vGround1 = groundConst1;
#else
vGround0 = ground0;
vGround1 = ground1;
#endif
`;

/** Width of a breakup patch's soft edge in field units: crisp, a few decimetres (widened by the pixel size). */
const BREAKUP_EDGE = 0.04;

const FRAGMENT_COMMON = /* glsl */ `
varying vec3 vGroundPlanet;
varying vec4 vGround0;
varying vec4 vGround1;
uniform float groundFacets;
uniform vec2 groundFacetsFade;
#ifdef GROUND_HOLE
uniform vec3 groundHoleUp;
uniform float groundHoleCos;
#endif

uint groundPcg(uint v) {
  uint state = v * 747796405u + 2891336453u;
  uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
  return (word >> 22u) ^ word;
}
float groundHash(ivec3 c) {
  uint h = (uint(c.x) * 0x8da6b343u) ^ (uint(c.y) * 0xd8163841u) ^ (uint(c.z) * 0xcb1ab31fu);
  return float(groundPcg(h)) * (1.0 / 4294967295.0);
}
float gNoise(vec3 p) {
  vec3 i = floor(p);
  vec3 f = p - i;
  vec3 u = f * f * (3.0 - 2.0 * f);
  ivec3 c = ivec3(i);
  float a = mix(groundHash(c), groundHash(c + ivec3(1, 0, 0)), u.x);
  float b = mix(groundHash(c + ivec3(0, 1, 0)), groundHash(c + ivec3(1, 1, 0)), u.x);
  float d = mix(groundHash(c + ivec3(0, 0, 1)), groundHash(c + ivec3(1, 0, 1)), u.x);
  float e = mix(groundHash(c + ivec3(0, 1, 1)), groundHash(c + ivec3(1, 1, 1)), u.x);
  return mix(mix(a, b, u.y), mix(d, e, u.y), u.z);
}
/*
 * Cells (Worley noise over the 8 nearest lattice points): x = distance to the nearest feature point, y = to the
 * second nearest, z = the nearest cell's id in 0..1. y − x is small along the cells' borders.
 */
vec3 gCells(vec3 p) {
  vec3 base = floor(p - 0.5);
  float f1 = 9.0;
  float f2 = 9.0;
  float id = 0.0;
  for (int k = 0; k < 8; k++) {
    ivec3 c = ivec3(base) + ivec3(k & 1, (k >> 1) & 1, k >> 2);
    uint h = groundPcg((uint(c.x) * 0x8da6b343u) ^ (uint(c.y) * 0xd8163841u) ^ (uint(c.z) * 0xcb1ab31fu));
    vec3 jitter = vec3(uvec3(h, h >> 10u, h >> 20u) & 1023u) * (1.0 / 1023.0);
    float d = length(vec3(c) + 0.15 + 0.7 * jitter - p);
    if (d < f1) {
      f2 = f1;
      f1 = d;
      id = float(h >> 8u) * (1.0 / 16777215.0);
    } else if (d < f2) f2 = d;
  }
  return vec3(f1, f2, id);
}
float gFine(vec3 p, float freq, float fw) {
  return mix(gNoise(p * freq), 0.5, smoothstep(0.35, 0.8, fw * freq));
}
/* The shared noises: 15 m drifts, 3 m patches, 1 m grain, 11 m drifts (and a 4 m one only the fields use). */
vec4 groundNoises(vec3 p, out float extra) {
  extra = gNoise(p * 0.43 + 53.0);
  return vec4(gNoise(p * 0.065), gNoise(p * 0.31 + 17.0), gNoise(p * 1.13 + 31.0), gNoise(p * 0.09 + 41.0));
}
/* A grass tint shifts the grass colours by its ratio to the style's reference tint, kept within bounds. */
vec3 groundTintShift(vec3 tint) {
  return mix(vec3(1.0), clamp(tint / grass_reference, vec3(0.6), vec3(1.5)), 0.75);
}
vec3 groundMacro(float w[8], vec3 grassTint) {
  vec3 c = vec3(0.0);
  for (int i = 0; i < 8; i++) c += w[i] * GROUND_BASE[i];
  return c + w[0] * GROUND_BASE[0] * (groundTintShift(grassTint) - 1.0);
}
/*
 * Bumps a view-space normal by a height field h (metres) over the fragment's view position. The slope is capped
 * so a layer's edge (where the relief steps) shades as a soft rim, not as jagged pixel blocks.
 */
vec3 groundBump(vec3 position, vec3 normal, float h) {
  vec3 dx = dFdx(position);
  vec3 dy = dFdy(position);
  vec3 r1 = cross(dy, normal);
  vec3 r2 = cross(normal, dx);
  float det = dot(dx, r1);
  float hx = clamp(dFdx(h), -0.5 * length(dx), 0.5 * length(dx));
  float hy = clamp(dFdy(h), -0.5 * length(dy), 0.5 * length(dy));
  vec3 grad = sign(det) * (hx * r1 + hy * r2);
  return normalize(abs(det) * normal - grad);
}
`;

/* Sets diffuseColor (from the grass tint already in it), groundRoughness and groundRelief (metres). */
const FRAGMENT_COLOR = /* glsl */ `
float groundRoughness;
float groundRelief = 0.0;
{
  vec3 tint = diffuseColor.rgb;
  float w[8] = float[8](vGround0.x, vGround0.y, vGround0.z, vGround0.w, vGround1.x, vGround1.y, vGround1.z, vGround1.w);
  vec3 macro = groundMacro(w, tint);
  vec3 color = macro;
  groundRoughness = 0.0;
  for (int i = 0; i < 8; i++) groundRoughness += w[i] * GROUND_ROUGHNESS[i];
#ifndef GROUND_FLAT
  float dist = length(vViewPosition);
  vec3 p = vGroundPlanet;
  float fw = length(fwidth(p));
  if (dist < GROUND_MACRO_END) {
    float extra;
    vec4 g = groundNoises(p, extra);
    // the breakup fields: drifts, patches and ragged 1 m edges
    float f0 = g.x * 0.42 + g.y * 0.38 + g.z * 0.2;
    float f1 = g.w * 0.5 + extra * 0.32 + (1.0 - g.z) * 0.18;
    int first;
    int second;
    float t = groundBlend(w, f0, f1, g.z, ${BREAKUP_EDGE} + fw * 0.5, first, second);
    vec3 near = groundMacro(w, tint);
    if (dist < GROUND_PATTERN_END) {
#ifdef GROUND_LOW
      t = 1.0;
#endif
      vec4 look = groundLook(first, p, tint, fw, g);
      vec4 other = t < 0.999 ? groundLook(second, p, tint, fw, g) : look;
      vec3 pattern = mix(other.rgb, look.rgb, t);
      groundRelief = mix(other.a * GROUND_DEPTH[second], look.a * GROUND_DEPTH[first], t);
      groundRoughness = mix(GROUND_ROUGHNESS[second], GROUND_ROUGHNESS[first], t);
      near = mix(pattern, near, smoothstep(GROUND_PATTERN_END * 0.8, GROUND_PATTERN_END, dist));
    }
    float tone = 0.92 + 0.16 * g.x;
    color = mix(near * tone, macro, smoothstep(GROUND_MACRO_END * 0.8, GROUND_MACRO_END, dist));
  }
#endif
  diffuseColor.rgb = color;
}
`;

const FRAGMENT_NORMAL = /* glsl */ `
{
  vec3 facet = normalize(cross(dFdx(vViewPosition), dFdy(vViewPosition)));
  float fade = 1.0 - smoothstep(groundFacetsFade.x, groundFacetsFade.y, length(vViewPosition));
  normal = normalize(mix(normal, facet, groundFacets * fade));
}
`;

const FRAGMENT_BUMP = /* glsl */ `
#ifdef GROUND_BUMP
normal = groundBump(-vViewPosition, normal, groundRelief * (1.0 - smoothstep(30.0, 40.0, length(vViewPosition))));
#endif
`;

/** View distances (metres) where the patterns end and where only the per-vertex colours remain. */
const PATTERN_END = { full: 300, low: 150 };
const MACRO_END = 1500;

/** The ground material (MeshStandardMaterial: lit, shadowed and fogged like everything else). */
export function groundMaterial({
  quality = 'full',
  hole = null,
  weights,
  tint,
  style = GROUND_STYLE,
}: GroundMaterialOptions = {}) {
  const material = new MeshStandardMaterial({
    color: tint ?? '#ffffff',
    vertexColors: tint === undefined,
    roughness: 1,
  });
  const defines: Record<string, string> = {
    GROUND_PATTERN_END: glslFloat(
      PATTERN_END[quality === 'low' ? 'low' : 'full'],
    ),
    GROUND_MACRO_END: glslFloat(MACRO_END),
  };
  if (quality === 'flat') defines.GROUND_FLAT = '';
  if (quality === 'low') defines.GROUND_LOW = '';
  if (quality === 'full') defines.GROUND_BUMP = '';
  if (weights) defines.GROUND_CONST = '';
  if (hole) defines.GROUND_HOLE = '';
  material.defines = defines;
  const constant = weightsArray(weights ?? {});
  const chunk = styleChunk(style);
  material.onBeforeCompile = (shader) => {
    shader.uniforms.groundFacets = { value: FACETS };
    shader.uniforms.groundFacetsFade = { value: FACETS_FADE };
    shader.uniforms.groundConst0 = { value: constant.slice(0, 4) };
    shader.uniforms.groundConst1 = { value: constant.slice(4, 8) };
    if (hole) {
      shader.uniforms.groundHoleUp = { value: hole.up };
      shader.uniforms.groundHoleCos = { value: hole.cos };
    }
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\n${VERTEX_COMMON}`)
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>\n${VERTEX_MAIN}`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>\n${chunk.constants}\n${FRAGMENT_COMMON}\n${chunk.functions}`,
      )
      .replace(
        'void main() {',
        'void main() {\n#ifdef GROUND_HOLE\nif (dot(normalize(vGroundPlanet), groundHoleUp) > groundHoleCos) discard;\n#endif',
      )
      .replace(
        '#include <color_fragment>',
        `#include <color_fragment>\n${FRAGMENT_COLOR}`,
      )
      .replace(
        '#include <roughnessmap_fragment>',
        '#include <roughnessmap_fragment>\nroughnessFactor = groundRoughness;',
      )
      .replace(
        '#include <normal_fragment_begin>',
        `#include <normal_fragment_begin>\n${FRAGMENT_NORMAL}`,
      )
      .replace(
        '#include <normal_fragment_maps>',
        `#include <normal_fragment_maps>\n${FRAGMENT_BUMP}`,
      );
  };
  material.customProgramCacheKey = () =>
    `ground-${quality}-${weights ? 'const' : 'vertex'}-${hole ? 'hole' : 'whole'}-${tint === undefined}`;
  return material;
}
