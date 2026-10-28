/*
 * What grows and lies around in each biome of the globe, and the kinds landmarks are built from.
 * The globe scatters BIOME_PROPS deterministically per cell (hash of seed + cell), instanced, near the camera.
 */
import type { PropKind } from './assets';

/** Index = biome id in the world arrays (fixed order, see the globe contract). */
export const BIOME_NAMES = [
  'deep_ocean',
  'shallow_ocean',
  'beach',
  'grassland',
  'broadleaf_forest',
  'taiga',
  'wetland',
  'hills',
  'mountain',
  'savanna',
  'tundra',
  'snow',
  'ice',
  'lake',
  'volcanic',
] as const;

export type BiomeName = (typeof BIOME_NAMES)[number];

export interface ScatterEntry {
  kind: PropKind;
  /** Expected instances per ~40 m cell. */
  perCell: number;
  /** Uniform scale range [min, max] applied to the model's drawn size (real-world size x kindScale). */
  scale: [number, number];
}

export const BIOME_PROPS: Record<BiomeName, ScatterEntry[]> = {
  deep_ocean: [],
  shallow_ocean: [],
  lake: [],
  beach: [
    { kind: 'dune_grass', perCell: 3, scale: [0.8, 1.3] },
    { kind: 'driftwood', perCell: 0.6, scale: [0.8, 1.2] },
    { kind: 'coastal_boulder', perCell: 0.8, scale: [0.6, 1.4] },
    { kind: 'small_rock', perCell: 1, scale: [0.8, 1.6] },
  ],
  grassland: [
    { kind: 'grass_tuft', perCell: 10, scale: [0.8, 1.6] },
    { kind: 'wildflower', perCell: 5, scale: [0.8, 1.3] },
    { kind: 'bush', perCell: 0.6, scale: [0.8, 1.3] },
    { kind: 'oak_tree', perCell: 0.4, scale: [0.9, 1.3] },
    { kind: 'rock', perCell: 0.3, scale: [0.7, 1.3] },
  ],
  broadleaf_forest: [
    { kind: 'oak_tree', perCell: 5, scale: [0.85, 1.35] },
    { kind: 'birch_tree', perCell: 3, scale: [0.85, 1.25] },
    { kind: 'bush', perCell: 3, scale: [0.8, 1.4] },
    { kind: 'fern', perCell: 4, scale: [0.8, 1.4] },
    { kind: 'grass_tuft', perCell: 4, scale: [0.8, 1.4] },
    { kind: 'fallen_log', perCell: 0.3, scale: [0.9, 1.2] },
    { kind: 'rock', perCell: 0.3, scale: [0.7, 1.3] },
  ],
  taiga: [
    { kind: 'pine_tree', perCell: 7, scale: [0.8, 1.3] },
    { kind: 'young_pine', perCell: 3, scale: [0.7, 1.2] },
    { kind: 'snowy_spruce', perCell: 0.5, scale: [0.85, 1.2] },
    { kind: 'fern', perCell: 1.5, scale: [0.8, 1.2] },
    { kind: 'small_rock', perCell: 1, scale: [0.8, 1.6] },
    { kind: 'fallen_log', perCell: 0.3, scale: [0.9, 1.2] },
  ],
  wetland: [
    { kind: 'cattail', perCell: 8, scale: [0.8, 1.3] },
    { kind: 'reeds', perCell: 4, scale: [0.8, 1.2] },
    { kind: 'grass_tuft', perCell: 4, scale: [0.8, 1.4] },
    { kind: 'birch_tree', perCell: 1, scale: [0.8, 1.1] },
    { kind: 'tree_fern', perCell: 0.6, scale: [0.8, 1.2] },
    { kind: 'dead_tree', perCell: 0.4, scale: [0.8, 1.2] },
  ],
  hills: [
    { kind: 'grass_tuft', perCell: 6, scale: [0.8, 1.4] },
    { kind: 'small_rock', perCell: 1.5, scale: [0.8, 1.8] },
    { kind: 'rock', perCell: 1, scale: [0.7, 1.5] },
    { kind: 'boulder', perCell: 0.8, scale: [0.6, 1.6] },
    { kind: 'bush', perCell: 0.8, scale: [0.8, 1.3] },
    { kind: 'oak_tree', perCell: 0.3, scale: [0.8, 1.2] },
    { kind: 'rock_spire', perCell: 0.1, scale: [0.6, 1] },
  ],
  mountain: [
    { kind: 'small_rock', perCell: 2, scale: [0.8, 1.8] },
    { kind: 'rock_outcrop', perCell: 1.2, scale: [0.7, 1.6] },
    { kind: 'scree', perCell: 1, scale: [0.8, 1.5] },
    { kind: 'boulder_field', perCell: 0.8, scale: [0.8, 1.4] },
    { kind: 'dwarf_pine', perCell: 0.6, scale: [0.6, 1] },
    { kind: 'snowy_spruce', perCell: 0.3, scale: [0.8, 1.1] },
  ],
  savanna: [
    { kind: 'dry_grass', perCell: 10, scale: [0.8, 1.6] },
    { kind: 'dry_bush', perCell: 2, scale: [0.8, 1.4] },
    { kind: 'acacia_tree', perCell: 0.8, scale: [0.8, 1.3] },
    { kind: 'small_rock', perCell: 0.5, scale: [0.8, 1.4] },
    { kind: 'termite_mound', perCell: 0.3, scale: [0.7, 1.2] },
    { kind: 'dead_tree', perCell: 0.15, scale: [0.8, 1.1] },
  ],
  tundra: [
    { kind: 'dry_grass', perCell: 4, scale: [0.6, 1] },
    { kind: 'small_rock', perCell: 3, scale: [0.8, 1.8] },
    { kind: 'dwarf_pine', perCell: 1.5, scale: [0.5, 0.9] },
    { kind: 'rock', perCell: 0.6, scale: [0.7, 1.4] },
    { kind: 'boulder_field', perCell: 0.2, scale: [0.7, 1.1] },
  ],
  snow: [
    { kind: 'snowy_spruce', perCell: 1.5, scale: [0.8, 1.2] },
    { kind: 'boulder_field', perCell: 0.4, scale: [0.8, 1.3] },
    { kind: 'rock_outcrop', perCell: 0.3, scale: [0.7, 1.3] },
    { kind: 'ice_block', perCell: 0.3, scale: [0.4, 0.85] },
  ],
  ice: [{ kind: 'ice_block', perCell: 1.2, scale: [0.5, 1.15] }],
  volcanic: [
    { kind: 'lava_rock', perCell: 2, scale: [0.7, 1.5] },
    { kind: 'small_rock', perCell: 1, scale: [0.8, 1.6] },
    { kind: 'basalt_column', perCell: 0.6, scale: [0.7, 1.4] },
    { kind: 'obsidian', perCell: 0.4, scale: [0.6, 1.2] },
    { kind: 'dead_tree', perCell: 0.3, scale: [0.8, 1.1] },
    { kind: 'fumarole', perCell: 0.12, scale: [0.8, 1.2] },
  ],
};

/**
 * Small kinds (grass, flowers, ferns, pebbles, reeds) are only scattered within the near reach of the camera
 * target; trees, bushes and rocks reach much further (see BiomeScatter).
 */
export const GROUND_COVER: ReadonlySet<PropKind> = new Set<PropKind>([
  'grass_tuft',
  'dry_grass',
  'dune_grass',
  'wildflower',
  'fern',
  'small_rock',
  'cattail',
  'reeds',
]);

/** Kinds the backend world spec places at landmark sites (giant_tree is the elder tree, drawn scaled up). */
export const LANDMARK_KINDS = [
  'rock_spire',
  'boulder',
  'basalt_column',
  'lava_rock',
  'fumarole',
  'geyser',
  'hot_spring_pool',
  'obsidian',
  'giant_tree',
  'snowy_spruce',
  'ice_block',
] as const satisfies readonly PropKind[];
