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
 * `groundLook(layer, p, tint, fw, g, roughness)` returns the layer's colour at planet point p (rgb) and its relief
 * 0..1 (a), which drives the bump: 0.5 is the ground's mean level (where the detail fades out too), so the layers
 * meet without a step. `tint` is the terrain's grass tint there (the vertex colour); `g` holds the noises the
 * breakup already paid for (15 m drifts, 3 m patches, 1 m grain, 11 m drifts), free to reuse. `roughness` comes in
 * as the layer's own and a pattern may change it (glossy puddles).
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
vec4 groundLook(int layer, vec3 p, vec3 tint, float fw, vec4 g, inout float roughness) {
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
    relief = tufts * 0.8 + blades * 0.2;
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
    float pebbles = gFine(p + 3.0, 9.0, fw);
    // edges at least a pixel and a half wide (the noise climbs ~13 a metre)
    float pebble = smoothstep(0.76, 0.86 + 20.0 * fw, pebbles);
    c = mix(c, dirt_pebble, pebble * 0.7);
    c *= 0.86 + 0.28 * gFine(p + 8.0, 12.0, fw);
    relief = 0.4 + mottle * 0.1 + smoothstep(0.6, 0.9, pebbles) * 0.6;
  } else if (layer == 3) {
    // gravel: loose rounded stones of uneven sizes and tones (cells, some left empty) in darker grit, mottled in
    // clumps that still show where the stones are too small to see
    float clump = gFine(p + 6.0, 4.3, fw);
    float mottle = g.y * 0.45 + g.z * 0.35 + clump * 0.2;
    float grit = gFine(p + 2.0, 31.0, fw);
    c = mix(gravel_grit, gravel_mid, smoothstep(0.2, 0.85, mottle)) * (0.9 + 0.2 * grit);
    float stones = 0.0;
    float domes = 0.0;
    float kb = 1.0 - smoothstep(0.2, 0.5, fw * 9.0);
    if (kb > 0.0) {
      vec3 big = gCells(p * 9.0);
      float r = 0.26 + 0.2 * fract(big.z * 7.0) + 0.06 * (grit - 0.5);
      float stone = (1.0 - smoothstep(r - 0.06 - 9.0 * fw, r + 0.03, big.x)) * step(0.15, big.z) * kb;
      // rounded: the relief rises over the whole stone, not in a step at its rim
      domes = (1.0 - smoothstep(0.0, r + 0.03, big.x)) * step(0.15, big.z) * kb;
      vec3 tone = mix(mix(gravel_light, gravel_warm, smoothstep(0.4, 0.8, fract(big.z * 13.0))), gravel_dark, step(0.85, fract(big.z * 29.0)));
      c = mix(c, tone * (0.8 + 0.3 * smoothstep(r, 0.0, big.x)), stone);
      stones = stone;
    }
    float ks = 1.0 - smoothstep(0.2, 0.5, fw * 23.0);
    if (ks > 0.0) {
      vec3 small = gCells(p * 23.0 + 5.0);
      float stone = (1.0 - smoothstep(0.24 - 23.0 * fw, 0.34, small.x)) * step(0.25, small.z) * ks * (1.0 - stones);
      c = mix(c, mix(gravel_mid, gravel_light, small.z) * 1.05, stone);
      stones += stone * 0.6;
      domes += (1.0 - smoothstep(0.0, 0.34, small.x)) * step(0.25, small.z) * ks * (1.0 - stones) * 0.6;
    }
    // far away the stones and grit average out into the mottle
    c = mix(c, mix(gravel_far_dark, gravel_far_light, smoothstep(0.2, 0.85, mottle)), 1.0 - max(kb, ks));
    // the stones cover ~15 % of the ground in domes on average
    relief = 0.5 + (domes - 0.15) * 1.2 * max(kb, ks);
  } else if (layer == 4) {
    // sand: pale drifts with wind ripples
    float keep = 1.0 - smoothstep(0.15, 0.4, fw * 1.2);
    float ripple = sin(dot(p, vec3(0.83, 0.12, 0.55)) * 7.0 + g.y * 9.0) * 0.5 + 0.5;
    c = mix(sand_light, sand_dark, g.x * 0.7);
    c *= 1.0 + (ripple - 0.5) * 0.14 * keep;
    c *= 0.93 + 0.14 * gFine(p, 11.0, fw);
    relief = mix(0.5, ripple, keep);
  } else if (layer == 5) {
    // rock: weathered slabs of uneven tone in strata, grooved along their borders, a few dark cracks, lichen
    vec3 slabs = gCells(p * 0.55 + vec3(g.x, g.y, g.w) * 4.0);
    float keep = 1.0 - smoothstep(0.25, 0.6, fw * 0.55);
    float border = slabs.y - slabs.x;
    // a crack at least a pixel and a half wide (fw * 0.55 cell units a pixel), fainter as it widens
    float crackWidth = 0.05 + fw * 0.8;
    float crack = (1.0 - smoothstep(0.01, crackWidth, border)) * smoothstep(0.45, 0.6, g.z) * keep * 0.05 / crackWidth;
    float groove = (1.0 - smoothstep(0.0, 0.12, border)) * keep;
    float strata = sin(length(p) * 2.1 + g.w * 9.0 + g.y * 3.0) * (1.0 - smoothstep(0.15, 0.5, fw));
    float grain = gFine(p + 3.0, 3.1, fw);
    c = mix(rock_dark, rock_light, mix(0.5, slabs.z, keep) * 0.45 + g.x * 0.25 + grain * 0.3);
    c = mix(c, rock_lichen, smoothstep(0.62, 0.72, g.w) * smoothstep(0.5, 0.8, grain) * 0.6);
    c *= (1.0 + 0.08 * strata) * (1.0 - 0.45 * crack - 0.15 * groove) * (0.9 + 0.2 * gFine(p + 13.0, 9.0, fw));
    // a groove is a few decimetres wide: its relief goes before it narrows to a few pixels
    relief = 0.55 + (grain - 0.5) * 0.5 + strata * 0.1 - groove * 0.4 * (1.0 - smoothstep(0.005, 0.015, fw));
  } else if (layer == 6) {
    // snow: soft drifts, blue in their hollows, wind-carved ripples near by
    float drift = g.x * 0.6 + g.y * 0.4;
    float keep = 1.0 - smoothstep(0.2, 0.5, fw * 2.0);
    float ripple = sin(dot(p, vec3(0.31, 0.62, 0.72)) * 3.0 + g.y * 7.0) * 0.5 + 0.5;
    c = mix(snow_shade, snow_bright, smoothstep(0.3, 0.7, drift - (ripple - 0.5) * 0.2 * keep));
    c *= 0.97 + 0.06 * gFine(p, 6.0, fw);
    relief = mix(drift, ripple, 0.5 * keep);
  } else {
    // mud: dark wet hollows in lighter drying mud, trodden silt, cracks where it dried, glossy puddles in the
    // wettest hollows and the odd tuft of grass or reed
    float damp = g.y * 0.7 + g.z * 0.3;
    float wet = smoothstep(0.52, 0.62, damp);
    float lumps = gFine(p + 7.0, 3.7, fw);
    float silt = gFine(p + 19.0, 13.0, fw);
    // the wet mud is churned finer
    c = mix(mud_light, mud_dark, wet) * (0.88 + 0.24 * lumps) * (0.9 - 0.06 * wet + (0.2 + 0.12 * wet) * silt);
    relief = 0.65 - 0.5 * wet + (lumps - 0.5) * 0.3 + (silt - 0.5) * (0.15 + 0.15 * wet);
    // the driest patches part into plates along cracks a few centimetres wide, at least a pixel and a half (fw * 2.4
    // cell units a pixel), fainter as they widen
    float keepCracks = (1.0 - smoothstep(0.2, 0.5, fw * 2.4)) * (1.0 - smoothstep(0.34, 0.42, damp - (g.w - 0.5) * 0.3));
    if (keepCracks > 0.0) {
      vec3 plates = gCells(p * 2.4 + vec3(g.z, g.w, g.x) * 0.8);
      float crackWidth = 0.03 + fw * 3.6;
      // some cracks die out, so the plates join up instead of paving the ground
      float crack = (1.0 - smoothstep(0.0, crackWidth, plates.y - plates.x)) * smoothstep(0.3, 0.55, lumps) * keepCracks * 0.03 / crackWidth;
      c *= (1.0 + 0.05 * (plates.z - 0.5) * keepCracks) * (1.0 - 0.45 * crack);
      relief -= crack * 0.35;
    }
    // ragged tufts of reed and grass a few centimetres across, and water standing in hoof pocks in the wet mud,
    // gone where a pixel can't hold them
    float keepTufts = 1.0 - smoothstep(0.2, 0.5, fw * 6.0);
    if (keepTufts > 0.0) {
      vec3 tufts = gCells(p * 6.0 + 3.0);
      float d = tufts.x + (silt - 0.5) * 0.15;
      float r = 0.2 + 0.12 * fract(tufts.z * 7.0);
      float tuft = (1.0 - smoothstep(r - 6.0 * fw, r + 0.04, d)) * step(0.84, tufts.z) * (1.0 - wet * 0.7) * keepTufts;
      c = mix(c, mix(mud_reed, mud_shoot, fract(tufts.z * 13.0)) * (0.8 + 0.4 * silt), tuft);
      float pock = (1.0 - smoothstep(r * 1.3 - 6.0 * fw, r * 1.3 + 0.04, d)) * step(tufts.z, 0.25) * wet * keepTufts;
      c = mix(c, mud_water * 0.75, pock * 0.8);
      roughness = mix(roughness, 0.25, pock);
      relief += tuft * 0.3 - pock * 0.2;
    }
    // standing water: dark, flat and glossy, with a wet rim
    float pond = damp * 0.7 + lumps * 0.15 + g.w * 0.15;
    float pool = smoothstep(0.67, 0.69 + fw * 0.5, pond);
    c *= 1.0 - 0.25 * smoothstep(0.63, 0.67, pond);
    c = mix(c, mud_water * (0.9 + 0.2 * g.z), pool);
    relief = mix(relief, 0.15, pool);
    roughness = mix(roughness, 0.2, pool);
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
      base: '#837767',
      colors: {
        grit: '#665b4d',
        mid: '#8a7f70',
        dark: '#6b655d',
        light: '#ada391',
        warm: '#a2866a',
        far_dark: '#6f6455',
        far_light: '#978a77',
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
      base: '#8b867d',
      colors: {
        dark: '#625e58',
        light: '#ada79b',
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
        water: '#4a5258',
        reed: '#6f7a3c',
        shoot: '#94924f',
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
