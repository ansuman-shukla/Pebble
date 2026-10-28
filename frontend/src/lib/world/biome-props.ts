/*
 * Biome vegetation and rocks scattered on the globe: per cell of the frequency-60 grid, on average `perCell`
 * instances of each kind, scaled uniformly within `scale`. Placeholder table built from the town's kinds until the
 * biome asset set lands.
 */
import type { PropKind } from './assets';

export type BiomeName =
  | 'deep_ocean'
  | 'shallow_ocean'
  | 'beach'
  | 'grassland'
  | 'broadleaf_forest'
  | 'taiga'
  | 'wetland'
  | 'hills'
  | 'mountain'
  | 'savanna'
  | 'tundra'
  | 'snow'
  | 'ice'
  | 'lake'
  | 'volcanic';

export const BIOME_PROPS: Record<
  BiomeName,
  { kind: PropKind; perCell: number; scale: [number, number] }[]
> = {
  deep_ocean: [],
  shallow_ocean: [],
  beach: [
    { kind: 'rock', perCell: 0.3, scale: [0.5, 1] },
    { kind: 'reeds', perCell: 0.3, scale: [0.8, 1.2] },
  ],
  grassland: [
    { kind: 'azalea', perCell: 0.8, scale: [0.8, 1.3] },
    { kind: 'cherry_tree', perCell: 0.25, scale: [0.8, 1.2] },
    { kind: 'rock', perCell: 0.3, scale: [0.6, 1.2] },
  ],
  broadleaf_forest: [
    { kind: 'maple_tree', perCell: 2, scale: [0.9, 1.5] },
    { kind: 'cherry_tree', perCell: 0.8, scale: [0.9, 1.3] },
    { kind: 'azalea', perCell: 0.6, scale: [0.8, 1.2] },
    { kind: 'fallen_log', perCell: 0.3, scale: [0.8, 1.2] },
  ],
  taiga: [
    { kind: 'sculpted_pine', perCell: 2.5, scale: [1, 1.8] },
    { kind: 'rock', perCell: 0.4, scale: [0.6, 1.3] },
    { kind: 'fallen_log', perCell: 0.3, scale: [0.8, 1.2] },
  ],
  wetland: [
    { kind: 'reeds', perCell: 3, scale: [0.8, 1.4] },
    { kind: 'bamboo', perCell: 0.6, scale: [0.8, 1.2] },
  ],
  hills: [
    { kind: 'rock', perCell: 1, scale: [0.8, 1.8] },
    { kind: 'sculpted_pine', perCell: 0.5, scale: [0.9, 1.4] },
    { kind: 'azalea', perCell: 0.3, scale: [0.8, 1.2] },
  ],
  mountain: [{ kind: 'rock', perCell: 1.5, scale: [1, 2.5] }],
  savanna: [
    { kind: 'bamboo', perCell: 0.5, scale: [0.8, 1.2] },
    { kind: 'maple_tree', perCell: 0.2, scale: [0.8, 1.1] },
    { kind: 'rock', perCell: 0.2, scale: [0.6, 1.2] },
  ],
  tundra: [{ kind: 'rock', perCell: 0.5, scale: [0.6, 1.4] }],
  snow: [{ kind: 'rock', perCell: 0.2, scale: [0.8, 1.6] }],
  ice: [],
  lake: [],
  volcanic: [{ kind: 'rock', perCell: 1, scale: [0.8, 2] }],
};
