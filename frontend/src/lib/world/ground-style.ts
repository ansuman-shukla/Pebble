/*
 * The ground's look, in one place: the biome tints of the terrain (the grass colour per biome, and what the planet
 * shows from orbit), each ground layer's colours and pattern, and how plain grass breaks into bare patches. The
 * ground shader (ground-shader.ts) owns the layer weights, the noise, the blending and the level of detail; a later
 * reskin (a blocky look) swaps this module, not the weights.
 *
 * Patterns are GLSL. They may read the shader's helpers:
 * - `float gNoise(vec3 p)`: smooth 3D value noise in 0..1 (planet-space metres, no tiling, no seams);
 * - `float gFine(vec3 p, float freq, float fw)`: gNoise(p * freq) fading to 0.5 where a pixel (fw metres) can't
 *   resolve it, so fine patterns never shimmer;
 * - `vec3 gCells(vec3 p)`: cells (stones, slabs): distances to the nearest and second nearest cell centre and the
 *   nearest cell's id 0..1;
 * - `vec3 groundTintShift(vec3 tint)`: how a grass tint shifts the grass colours (1 for the reference tint);
 * - every colour below as `<layer>_<name>` (linear `vec3`).
 * `groundLook(layer, p, tint, fw, g)` returns the layer's colour at planet point p (rgb) and its relief 0..1 (a),
 * which drives the bump: 0.5 is the ground's mean level (where the detail fades out too), so the layers meet
 * without a step. `tint` is the terrain's grass tint there (the vertex colour); `g` holds the noises the
 * breakup already paid for (15 m drifts, 3 m patches, 1 m grain, 11 m drifts), free to reuse.
 */
import type { GroundLayer } from './ground-shader';

interface GroundLayerStyle {
  /** The layer's average colour: what it shows from afar, where the pattern fades out. */
  base: string;
  /** Colours its pattern reads as `<layer>_<name>`. */
  colors: Record<string, string>;
  roughness: number;
  /** Bump depth (metres) of the pattern's relief. */
  bump: number;
}

/** Where a layer gives way to another in noise patches (field 0 or 1 above `cut`, up to `amount` of it). */
export interface GroundBreakup {
  from: GroundLayer;
  to: GroundLayer;
  field: 0 | 1;
  cut: number;
  amount: number;
}

export interface GroundStyle {
  layers: Record<GroundLayer, GroundLayerStyle>;
  /** The grass tint the grass colours are drawn for; another tint shifts them by tint / grassReference. */
  grassReference: string;
  breakup: GroundBreakup[];
  patterns: string;
}

/**
 * Terrain tint per biome (by name, so the client never depends on the id order): the vertex colour, which tints
 * the grass (dune grass on beaches, alpine grass on mountains). Water biomes never show it.
 */
const BIOME_COLORS: Record<string, string> = {
  deep_ocean: '#24405e',
  shallow_ocean: '#5f9c9e',
  beach: '#b5b878',
  grassland: '#93b55c',
  broadleaf_forest: '#4f8a3c',
  taiga: '#3e6a4c',
  wetland: '#6f8c5c',
  hills: '#9aa45e',
  mountain: '#8f9a6c',
  savanna: '#c6b264',
  tundra: '#9fa07c',
  snow: '#f1f4f6',
  ice: '#d9ebf4',
  lake: '#5f9c9e',
  volcanic: '#77755a',
};
const FALLBACK_COLOR = '#ff00ff';

/** The terrain tint of a biome. */
export const biomeColor = (name: string) =>
  BIOME_COLORS[name] ?? FALLBACK_COLOR;

const PATTERNS = /* glsl */ `
vec4 groundLook(int layer, vec3 p, vec3 tint, float fw, vec4 g) {
  vec3 c;
  float relief;
  if (layer == 0) {
    // grass: lush, dry and cool meadow drifts, tufts and blades near by
    c = mix(grass_lush, grass_dry, smoothstep(0.38, 0.68, g.x * 0.6 + g.y * 0.4));
    c = mix(c, grass_cool, smoothstep(0.55, 0.75, g.w) * 0.7);
    c *= groundTintShift(tint);
    float tufts = gFine(p + 11.0, 1.7, fw);
    float blades = smoothstep(0.25, 0.75, gFine(p, 23.0, fw));
    c *= 0.72 + 0.36 * tufts + 0.24 * blades;
    relief = tufts * 0.5 + blades * 0.5;
  } else if (layer == 1) {
    // forest floor: leaf litter over dark soil, moss in patches, twigs and needles near by
    c = mix(forest_floor_litter, forest_floor_moss, smoothstep(0.55, 0.7, g.y * 0.7 + g.z * 0.3));
    float leaves = gFine(p + 4.0, 4.7, fw);
    float twigs = gFine(p + 9.0, 11.0, fw);
    c = mix(c, forest_floor_leaf, smoothstep(0.58, 0.72, leaves) * 0.75);
    c = mix(c, forest_floor_soil, smoothstep(0.62, 0.78, twigs) * 0.6);
    c *= 0.85 + 0.3 * twigs;
    relief = leaves * 0.6 + twigs * 0.4;
  } else if (layer == 2) {
    // dirt: trodden earth, mottled, with pebbles
    float mottle = g.y * 0.6 + g.z * 0.4;
    c = mix(dirt_dark, dirt_light, smoothstep(0.3, 0.7, mottle));
    float pebble = smoothstep(0.76, 0.86, gFine(p + 3.0, 9.0, fw));
    c = mix(c, dirt_pebble, pebble * 0.7);
    c *= 0.86 + 0.28 * gFine(p + 8.0, 12.0, fw);
    relief = 0.35 + mottle * 0.2 + pebble * 0.6;
  } else if (layer == 3) {
    // gravel: small stones of mixed tones (cells) packed in darker grit
    vec3 cells = gCells(p * 13.0);
    float keep = 1.0 - smoothstep(0.25, 0.6, fw * 13.0);
    float stone = mix(0.5, smoothstep(0.0, 0.18, cells.y - cells.x), keep);
    float tone = mix(0.5, cells.z, keep);
    c = mix(gravel_light, gravel_warm, smoothstep(0.45, 0.8, tone)) * (0.85 + 0.25 * tone);
    c = mix(gravel_dark, c, 0.35 + 0.65 * stone);
    c *= 0.88 + 0.24 * g.z;
    relief = stone;
  } else if (layer == 4) {
    // sand: pale drifts with wind ripples
    float keep = 1.0 - smoothstep(0.15, 0.4, fw * 1.2);
    float ripple = sin(dot(p, vec3(0.83, 0.12, 0.55)) * 7.0 + g.y * 9.0) * 0.5 + 0.5;
    c = mix(sand_light, sand_dark, g.x * 0.7);
    c *= 1.0 + (ripple - 0.5) * 0.14 * keep;
    c *= 0.93 + 0.14 * gFine(p, 11.0, fw);
    relief = mix(0.5, ripple, keep);
  } else if (layer == 5) {
    // rock: weathered stone, broken by a few cracks along warped slab borders, lichen in places
    vec3 slabs = gCells(p * 0.55 + vec3(g.x, g.y, g.w) * 4.0);
    float keep = 1.0 - smoothstep(0.25, 0.6, fw * 0.55);
    float crack = (1.0 - smoothstep(0.01, 0.05, slabs.y - slabs.x)) * smoothstep(0.5, 0.62, g.z) * keep;
    float grain = gFine(p + 3.0, 3.1, fw);
    c = mix(rock_dark, rock_light, mix(0.5, slabs.z, keep) * 0.3 + g.x * 0.3 + g.y * 0.15 + grain * 0.25);
    c = mix(c, rock_lichen, smoothstep(0.62, 0.72, g.w) * smoothstep(0.5, 0.8, grain) * 0.6);
    c *= 1.0 - 0.4 * crack;
    relief = grain * 0.6 + g.y * 0.4 - crack * 0.5;
  } else if (layer == 6) {
    // snow: soft drifts, blue in their hollows, wind-carved ripples near by
    float drift = g.x * 0.6 + g.y * 0.4;
    float keep = 1.0 - smoothstep(0.2, 0.5, fw * 2.0);
    float ripple = sin(dot(p, vec3(0.31, 0.62, 0.72)) * 3.0 + g.y * 7.0) * 0.5 + 0.5;
    c = mix(snow_shade, snow_bright, smoothstep(0.3, 0.7, drift - (ripple - 0.5) * 0.2 * keep));
    c *= 0.97 + 0.06 * gFine(p, 6.0, fw);
    relief = mix(drift, ripple, 0.5 * keep);
  } else {
    // mud: dark wet hollows in lighter drying mud
    float wet = smoothstep(0.52, 0.62, g.y * 0.7 + g.z * 0.3);
    c = mix(mud_light, mud_dark, wet);
    c *= 0.88 + 0.24 * gFine(p + 7.0, 3.7, fw);
    relief = 0.65 - 0.5 * wet;
  }
  return vec4(c, relief);
}
`;

export const GROUND_STYLE: GroundStyle = {
  grassReference: BIOME_COLORS.grassland,
  layers: {
    grass: {
      base: '#86a653',
      colors: {
        lush: '#6a9045',
        dry: '#a8a85a',
        cool: '#5f9a5a',
        flower: '#d9d9a0',
      },
      roughness: 0.95,
      bump: 0.02,
    },
    forest_floor: {
      base: '#5d5a35',
      colors: {
        litter: '#6b5a36',
        moss: '#4f6e34',
        leaf: '#8a6a34',
        soil: '#3e3424',
      },
      roughness: 0.95,
      bump: 0.05,
    },
    dirt: {
      base: '#8c7250',
      colors: {
        dark: '#755d40',
        light: '#a38660',
        pebble: '#a59783',
      },
      roughness: 0.97,
      bump: 0.05,
    },
    gravel: {
      base: '#978d7c',
      colors: {
        dark: '#7a7062',
        light: '#b3a994',
        warm: '#a08868',
      },
      roughness: 0.92,
      bump: 0.07,
    },
    sand: {
      base: '#e0cf9c',
      colors: {
        light: '#ead9a8',
        dark: '#cdb886',
      },
      roughness: 0.96,
      bump: 0.03,
    },
    rock: {
      base: '#837d74',
      colors: {
        dark: '#625d57',
        light: '#9d978c',
        lichen: '#8e9466',
      },
      roughness: 0.85,
      bump: 0.12,
    },
    snow: {
      base: '#eef2f5',
      colors: {
        bright: '#f6f9fb',
        shade: '#cfdbe6',
      },
      roughness: 0.8,
      bump: 0.04,
    },
    mud: {
      base: '#5a4b36',
      colors: {
        light: '#6e5b40',
        dark: '#3b3124',
      },
      roughness: 0.7,
      bump: 0.03,
    },
  },
  // the fields are smooth noise around 0.5 (sd ~0.1): a cut of 0.6 bares ~15 %, 0.64 ~7 %, 0.69 ~2 %
  breakup: [
    { from: 'grass', to: 'dirt', field: 0, cut: 0.61, amount: 1 },
    { from: 'grass', to: 'gravel', field: 1, cut: 0.665, amount: 1 },
    { from: 'forest_floor', to: 'dirt', field: 1, cut: 0.62, amount: 0.9 },
    { from: 'forest_floor', to: 'grass', field: 0, cut: 0.6, amount: 0.8 },
    { from: 'rock', to: 'gravel', field: 0, cut: 0.6, amount: 0.9 },
    { from: 'snow', to: 'rock', field: 1, cut: 0.67, amount: 0.9 },
    { from: 'sand', to: 'gravel', field: 1, cut: 0.69, amount: 0.6 },
    { from: 'dirt', to: 'gravel', field: 1, cut: 0.6, amount: 0.8 },
  ],
  patterns: PATTERNS,
};
