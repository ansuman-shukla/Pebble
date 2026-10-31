/*
 * What grows and lies around in each biome of the globe, and the kinds landmarks are built from.
 * The globe scatters BIOME_PROPS deterministically per cell (hash of seed + cell), instanced, near the camera:
 * decor only (10 §5.2: grass, flowers, ferns, rocks, plain bushes), never a kind anyone can use. Every usable wild
 * thing is a node drawn where the simulation has it: flora from the backend's table (FLORA_LOOKS) and the fixed
 * mineral features (FEATURE_LOOKS).
 */
import { assetSize, PROPS, type PropKind } from './assets';

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
    { kind: 'coastal_boulder', perCell: 0.8, scale: [0.6, 1.4] },
    { kind: 'small_rock', perCell: 1, scale: [0.8, 1.6] },
  ],
  grassland: [
    { kind: 'grass_tuft', perCell: 10, scale: [0.8, 1.6] },
    { kind: 'wildflower', perCell: 5, scale: [0.8, 1.3] },
    { kind: 'bush', perCell: 0.6, scale: [0.8, 1.3] },
    { kind: 'rock', perCell: 0.3, scale: [0.7, 1.3] },
  ],
  broadleaf_forest: [
    { kind: 'bush', perCell: 3, scale: [0.8, 1.4] },
    { kind: 'fern', perCell: 4, scale: [0.8, 1.4] },
    { kind: 'grass_tuft', perCell: 4, scale: [0.8, 1.4] },
    { kind: 'rock', perCell: 0.3, scale: [0.7, 1.3] },
  ],
  taiga: [
    { kind: 'fern', perCell: 1.5, scale: [0.8, 1.2] },
    { kind: 'small_rock', perCell: 1, scale: [0.8, 1.6] },
  ],
  wetland: [
    { kind: 'cattail', perCell: 8, scale: [0.8, 1.3] },
    { kind: 'grass_tuft', perCell: 4, scale: [0.8, 1.4] },
  ],
  hills: [
    { kind: 'grass_tuft', perCell: 6, scale: [0.8, 1.4] },
    { kind: 'small_rock', perCell: 1.5, scale: [0.8, 1.8] },
    { kind: 'rock', perCell: 1, scale: [0.7, 1.5] },
    { kind: 'boulder', perCell: 0.8, scale: [0.6, 1.6] },
    { kind: 'bush', perCell: 0.8, scale: [0.8, 1.3] },
    { kind: 'rock_spire', perCell: 0.1, scale: [0.6, 1] },
  ],
  mountain: [
    { kind: 'small_rock', perCell: 2, scale: [0.8, 1.8] },
    { kind: 'rock_outcrop', perCell: 1.2, scale: [0.7, 1.6] },
    { kind: 'scree', perCell: 1, scale: [0.8, 1.5] },
    { kind: 'boulder_field', perCell: 0.8, scale: [0.8, 1.4] },
  ],
  savanna: [
    { kind: 'dry_grass', perCell: 10, scale: [0.8, 1.6] },
    { kind: 'dry_bush', perCell: 2, scale: [0.8, 1.4] },
    { kind: 'small_rock', perCell: 0.5, scale: [0.8, 1.4] },
    { kind: 'termite_mound', perCell: 0.3, scale: [0.7, 1.2] },
  ],
  tundra: [
    { kind: 'dry_grass', perCell: 4, scale: [0.6, 1] },
    { kind: 'small_rock', perCell: 3, scale: [0.8, 1.8] },
    { kind: 'rock', perCell: 0.6, scale: [0.7, 1.4] },
    { kind: 'boulder_field', perCell: 0.2, scale: [0.7, 1.1] },
  ],
  snow: [
    { kind: 'boulder_field', perCell: 0.4, scale: [0.8, 1.3] },
    { kind: 'rock_outcrop', perCell: 0.3, scale: [0.7, 1.3] },
    { kind: 'ice_block', perCell: 0.3, scale: [0.4, 0.85] },
  ],
  ice: [{ kind: 'ice_block', perCell: 1.2, scale: [0.5, 1.15] }],
  volcanic: [
    { kind: 'small_rock', perCell: 2, scale: [0.8, 1.6] },
    { kind: 'boulder', perCell: 0.6, scale: [0.6, 1.3] },
    { kind: 'basalt_column', perCell: 0.6, scale: [0.7, 1.4] },
    { kind: 'fumarole', perCell: 0.12, scale: [0.8, 1.2] },
  ],
};

/**
 * Small kinds (grass, flowers, ferns, pebbles, cattails) are only scattered within the near reach of the camera
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
]);

/** Rocks and stones: no decor rock lies in a mineral hotspot, where it would pass for the seam (10 §5.2). */
export const ROCK_DECOR: ReadonlySet<PropKind> = new Set<PropKind>([
  'small_rock',
  'rock',
  'boulder',
  'coastal_boulder',
  'rock_outcrop',
  'boulder_field',
  'scree',
  'basalt_column',
  'rock_spire',
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

/** What each usable flora kind (`flora_kinds`) is drawn as: node kinds draw as themselves, trees as their species. */
export const FLORA_LOOKS: Readonly<Record<string, PropKind>> = {
  oak_tree: 'oak_tree',
  birch_tree: 'birch_tree',
  pine_tree: 'pine_tree',
  young_pine: 'young_pine',
  snowy_spruce: 'snowy_spruce',
  acacia_tree: 'acacia_tree',
  dwarf_pine: 'dwarf_pine',
  tree_fern: 'tree_fern',
  nut_oak: 'nut_tree',
  berry_bush: 'berry_bush',
  root_patch: 'root_patch',
  reed_bed: 'reed_bed',
  fallen_log: 'fallen_log',
  driftwood: 'driftwood',
  dead_tree: 'dead_tree',
};

/** Flora drawn as a biome species (trees, logs, driftwood, dead trees): the wild kinds of old; the other looks are
 * World v1 kinds named by their node. */
export const SPECIES_LOOKS: readonly PropKind[] = [
  ...new Set(Object.values(FLORA_LOOKS)),
].filter(
  (kind) =>
    !['nut_tree', 'berry_bush', 'root_patch', 'reed_bed'].includes(kind),
);

/** The fixed node features drawn as a model (fishing spots, iron sand and gold pools are drawn otherwise). */
export const FEATURE_LOOKS: Readonly<Partial<Record<string, PropKind>>> = {
  flint_seam: 'flint_seam',
  obsidian_field: 'obsidian_field',
};

/** What a felled tree leaves: its stump (and its logs, drawn as a fallen log along the fall). */
export const STUMP_LOOK: PropKind = 'tree_stump';
export const LOGS_LOOK: PropKind = 'fallen_log';

/** Looks drawn by stage through the staged material (pieces, level, growth, tint; staged-material.ts). */
export const STAGED_LOOKS: ReadonlySet<PropKind> = new Set<PropKind>([
  'berry_bush',
  'root_patch',
  'reed_bed',
  'fallen_log',
  'driftwood',
  'dead_tree',
  'flint_seam',
  'obsidian_field',
]);

/** Every kind a node is drawn as, in any stage. */
export const NODE_LOOK_KINDS: readonly PropKind[] = [
  ...new Set<PropKind>([
    ...Object.values(FLORA_LOOKS),
    ...(Object.values(FEATURE_LOOKS) as PropKind[]),
    STUMP_LOOK,
    LOGS_LOOK,
  ]),
];

/** A standing tree's trunk: what decor keeps clear of under a crown. */
const TRUNK_RADIUS_M = 0.5;
/** Node kinds that stand as a tree (`flora_nodes`). */
export const TREE_NODES: ReadonlySet<string> = new Set(['tree', 'nut_tree']);

/**
 * Radius (metres) of the ground a node stands on at its drawn scale: a standing tree's trunk, else the model's
 * footprint.
 */
export function nodeFootprint(node: string, look: PropKind, scale: number) {
  if (TREE_NODES.has(node)) return TRUNK_RADIUS_M * scale;
  const size = assetSize(PROPS[look]);
  return 0.5 * Math.max(size.x, size.z) * scale;
}

/** Plants a walker passes through like ground cover. */
const SOFT_NODE_LOOKS = new Set<PropKind>(['root_patch', 'reed_bed']);

/** Wild kinds that block walking: decor but ground cover, and the nodes but the soft plants. */
export const BLOCKING_KINDS: readonly PropKind[] = [
  ...new Set<PropKind>([
    ...Object.values(BIOME_PROPS).flatMap((props) =>
      props.map((prop) => prop.kind),
    ),
    ...NODE_LOOK_KINDS,
  ]),
].filter((kind) => !GROUND_COVER.has(kind) && !SOFT_NODE_LOOKS.has(kind));
