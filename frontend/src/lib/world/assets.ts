/*
 * The asset registry: world kinds -> vendored Polyfork files.
 * The backend only ever names kinds; file ids, palettes and clip names live here.
 */
import manifest from './asset-manifest.json' with { type: 'json' };

export type PropKind =
  // town buildings
  | 'castle_keep'
  | 'castle_gatehouse'
  | 'corner_turret'
  | 'stone_wall'
  | 'plaster_wall'
  | 'moat_bridge'
  | 'townhouse'
  | 'farmhouse'
  | 'storehouse'
  | 'temple_hall'
  | 'pagoda'
  | 'bell_tower'
  | 'teahouse'
  | 'lookout_tower'
  | 'stone_stair'
  // town props
  | 'well'
  | 'water_wheel'
  | 'rice_paddy'
  | 'drying_rack'
  | 'bamboo_fence'
  | 'palisade'
  | 'paving_tile'
  | 'lantern'
  | 'fire_basket'
  | 'banner'
  | 'notice_board'
  | 'sake_barrel'
  | 'bucket'
  | 'bench'
  | 'stone_basin'
  | 'war_drum'
  | 'tether_rail'
  | 'hand_cart'
  | 'ox_cart'
  | 'river_boat'
  // town plants
  | 'cherry_tree'
  | 'maple_tree'
  | 'sculpted_pine'
  | 'bamboo'
  | 'azalea'
  | 'reeds'
  // stone age camps
  | 'fire_pit'
  | 'firewood'
  | 'lean_to'
  | 'cook_tripod'
  | 'reed_basket'
  | 'reed_torch'
  | 'petroglyph_boulder'
  | 'fallen_log'
  | 'rock'
  // biome trees and plants
  | 'oak_tree'
  | 'birch_tree'
  | 'pine_tree'
  | 'young_pine'
  | 'snowy_spruce'
  | 'acacia_tree'
  | 'tree_fern'
  | 'dead_tree'
  | 'dwarf_pine'
  | 'bush'
  | 'dry_bush'
  | 'fern'
  | 'grass_tuft'
  | 'dry_grass'
  | 'dune_grass'
  | 'wildflower'
  | 'cattail'
  | 'driftwood'
  | 'termite_mound'
  // biome rocks
  | 'small_rock'
  | 'boulder'
  | 'coastal_boulder'
  | 'rock_outcrop'
  | 'boulder_field'
  | 'scree'
  | 'ice_block'
  // landmarks
  | 'rock_spire'
  | 'basalt_column'
  | 'lava_rock'
  | 'obsidian'
  | 'fumarole'
  | 'geyser'
  | 'hot_spring_pool'
  | 'giant_tree'
  // world v1 nodes (named by their node kind) and their stages
  | 'berry_bush'
  | 'root_patch'
  | 'reed_bed'
  | 'nut_tree'
  | 'tree_stump'
  | 'flint_seam'
  | 'obsidian_field'
  // world v1 dens, remains, roads and markers
  | 'cave_mouth'
  | 'bone_scatter'
  | 'signpost'
  | 'log_bridge'
  | 'boundary_stone'
  | 'cairn'
  // world v1 stores, stations and furniture
  | 'market_stall'
  | 'forge'
  | 'anvil'
  | 'chest'
  | 'grain_sack'
  | 'coin_pouch'
  | 'camp_drying_rack'
  | 'sleeping_mat'
  | 'field_barricade';

export const PROPS: Record<PropKind, string> = {
  castle_keep: 'tenshu-keep-2ff636',
  castle_gatehouse: 'castle-gatehouse-4ed5c6',
  corner_turret: 'corner-yagura-turret-950468',
  stone_wall: 'ishigaki-stone-wall-255b7e',
  plaster_wall: 'dobei-plaster-wall-b75823',
  moat_bridge: 'moat-bridge-4fbcd9',
  townhouse: 'machiya-townhouse-8ef64e',
  farmhouse: 'minka-farmhouse-680475',
  storehouse: 'kura-storehouse-5c9631',
  temple_hall: 'buddhist-temple-hall-f0aa09',
  pagoda: 'tiered-pagoda-f4ade0',
  bell_tower: 'temple-bell-tower-745387',
  teahouse: 'open-front-teahouse-c7dd18',
  lookout_tower: 'fire-lookout-tower-714fa1',
  stone_stair: 'terrace-stone-stair-494ef8',
  well: 'roofed-well-43a2fc',
  water_wheel: 'stream-water-wheel-ea2d68',
  rice_paddy: 'rice-paddy-tile-dc727e',
  drying_rack: 'hasa-rice-drying-rack-d545bc',
  bamboo_fence: 'takegaki-bamboo-fence-c6718b',
  palisade: 'wooden-palisade-d4f4db',
  paving_tile: 'stone-paving-tile-5af0d1',
  lantern: 'andon-floor-lantern-b1b7ea',
  fire_basket: 'kagaribi-fire-basket-d28c11',
  banner: 'nobori-banner-ae4d88',
  notice_board: 'kosatsu-notice-board-c9d276',
  sake_barrel: 'komodaru-sake-barrel-c5199a',
  bucket: 'wooden-teoke-bucket-e65f35',
  bench: 'teahouse-bench-6b34e1',
  stone_basin: 'tsukubai-stone-basin-677586',
  war_drum: 'war-drum-on-stand-cbb91a',
  tether_rail: 'horse-tether-rail-b26462',
  hand_cart: 'daihachiguruma-hand-cart-c026f3',
  ox_cart: 'ox-cart-9c857f',
  river_boat: 'flat-river-boat-6bac37',
  cherry_tree: 'cherry-tree-a710a9',
  maple_tree: 'japanese-maple-d2fb29',
  sculpted_pine: 'sculpted-pine-e45d4f',
  bamboo: 'bamboo-stalk-e4d362',
  azalea: 'azalea-bush-7bb14d',
  reeds: 'moat-reed-clump-dd6b60',
  fire_pit: 'stone-fire-pit-4136b0',
  firewood: 'firewood-stack-8a2899',
  lean_to: 'lean-to-shelter-f0709f',
  cook_tripod: 'campfire-cook-tripod-d95a1e',
  reed_basket: 'kete-reed-basket-6ca36c',
  reed_torch: 'reed-fire-torch-f7453e',
  petroglyph_boulder: 'petroglyph-boulder-7203c3',
  fallen_log: 'fallen-log-1685fb',
  rock: 'medium-rock-e08405',
  oak_tree: 'broadleaf-oak-997c22',
  birch_tree: 'birch-tree-181b33',
  pine_tree: 'tall-pine-tree-ab4108',
  young_pine: 'young-pine-0d7695',
  snowy_spruce: 'snow-laden-spruce-36716e',
  acacia_tree: 'espino-cd3edd',
  tree_fern: 'tree-fern-78320e',
  dead_tree: 'dead-tree-6795fa',
  dwarf_pine: 'dwarf-pine-mat-faee77',
  bush: 'round-bush-cd2ac0',
  dry_bush: 'sagebrush-700b03',
  fern: 'fern-plant-1559b8',
  grass_tuft: 'grass-tuft-a40a08',
  dry_grass: 'grass-tuft-62e90c',
  dune_grass: 'marram-grass-tuft-8c7a99',
  wildflower: 'wildflower-68d3a1',
  cattail: 'cattail-reed-6abbb3',
  driftwood: 'driftwood-log-90340b',
  termite_mound: 'termite-mound-9bc94b',
  small_rock: 'small-rock-db33a7',
  boulder: 'large-boulder-a29b99',
  coastal_boulder: 'large-coastal-boulder-a2cab1',
  rock_outcrop: 'rock-outcrop-158ac3',
  boulder_field: 'boulder-field-cluster-08e364',
  scree: 'scree-heap-42cce5',
  ice_block: 'ice-chunk-b23ad7',
  rock_spire: 'rock-spire-13819c',
  basalt_column: 'basalt-column-outcrop-f1339d',
  lava_rock: 'lava-rock-pile-d56d19',
  obsidian: 'obsidian-shard-cluster-c8f5d3',
  fumarole: 'fumarole-vent-8280ba',
  geyser: 'geyser-cone-2b5033',
  hot_spring_pool: 'hot-spring-pool-26312c',
  giant_tree: 'oak-tree-50ee7c',
  berry_bush: 'berry-bush-ee4812',
  root_patch: 'taro-plant-8c0493',
  reed_bed: 'totora-reed-bed-36d78f',
  nut_tree: 'broadleaf-oak-997c22',
  tree_stump: 'tree-stump-ec3f48',
  flint_seam: 'ballast-heap-2fb138',
  obsidian_field: 'lava-rock-pile-d56d19',
  cave_mouth: 'smuggler-cave-mouth-69a07e',
  bone_scatter: 'bone-scatter-90313d',
  signpost: 'trail-signpost-bd29a7',
  log_bridge: 'log-plank-bridge-a5f74f',
  boundary_stone: 'garden-rock-2d3b51',
  cairn: 'pipi-horeko-cairn-f5db4b',
  market_stall: 'market-stall-94937d',
  forge: 'blacksmith-forge-09fa85',
  anvil: 'anvil-1286cb',
  chest: 'timber-crate-ba0739',
  grain_sack: 'grain-sack-401d96',
  coin_pouch: 'coin-pouch-be4dd8',
  camp_drying_rack: 'drying-net-rack-93ec3b',
  sleeping_mat: 'straw-pile-ebd54d',
  field_barricade: 'field-barricade-a646b9',
};

export type HandPropKind =
  | 'axe'
  | 'hoe'
  | 'hammer'
  | 'torch'
  | 'spear'
  | 'basket'
  | 'coin_pouch'
  | 'sack'
  | 'pick'
  | 'fishing_rod';

/**
 * What a citizen holds or carries: a vendored model attached to a hand bone, or an item of the humanoid engine's
 * own wardrobe (`righthand` slot) where the catalogue has no separate model.
 */
export type HandProp = { asset: string } | { wardrobe: string };

export const HAND_PROPS: Record<HandPropKind, HandProp> = {
  axe: { asset: 'hand-axe-cee9e7' },
  hoe: { asset: 'garden-hoe-3974ad' },
  hammer: { asset: 'hammer-fa3e51' },
  torch: { asset: 'torch-stake-d82a2c' },
  spear: { asset: 'yari-spear-e72c1f' },
  basket: { asset: 'kete-reed-basket-6ca36c' },
  coin_pouch: { asset: 'coin-pouch-be4dd8' },
  sack: { asset: 'grain-sack-401d96' },
  pick: { wardrobe: 'pick' },
  fishing_rod: { wardrobe: 'fishing-rod' },
};

/**
 * Kinds drawn larger than the asset's real-world size (the backend footprints in data/world/kinds.yaml match).
 * The elder tree is a gnarled oak enlarged to read as ancient (D39); the ice chunk (0.9 m) is drawn as a block
 * that can mark the ice gate.
 */
const KIND_SCALE: Partial<Record<string, number>> = {
  giant_tree: 3.5,
  ice_block: 3,
};

/** Uniform render scale of a kind (1 for everything at real size). */
export const kindScale = (kind: string) => KIND_SCALE[kind] ?? 1;

export type AnimalKind =
  | 'deer'
  | 'elk'
  | 'antelope'
  | 'rabbit'
  | 'hare'
  | 'boar'
  | 'goat'
  | 'fox'
  | 'wolf'
  | 'bear'
  | 'polar_bear'
  | 'lion'
  | 'shark'
  | 'fish'
  | 'duck';

export interface AnimalAsset {
  asset: string;
  idle: string;
  move: string;
  /** The fast gait: running, or swimming fast. */
  run: string;
  /** Recolours baked vertex colours (source palette hex -> new hex) to make a related species. */
  recolor?: Record<string, string>;
  /** v0 stand-ins only: a related species at a different size. */
  scale?: number;
}

const LAND = { idle: 'Idle', move: 'Walk', run: 'Run' };
const WATER = { idle: 'Idle', move: 'Swim', run: 'Swim fast' };

export const ANIMALS: Record<AnimalKind, AnimalAsset> = {
  deer: { asset: 'forest-deer-fe648d', ...LAND },
  elk: {
    asset: 'forest-deer-fe648d',
    ...LAND,
    recolor: { '#b88a53': '#6b4a2e', '#e3c79c': '#c9b48a' },
    scale: 1.3,
  },
  antelope: {
    asset: 'forest-deer-fe648d',
    ...LAND,
    recolor: { '#b88a53': '#c8955a', '#e3c79c': '#f2e6d0' },
    scale: 0.8,
  },
  rabbit: { asset: 'forest-rabbit-ea2da0', ...LAND },
  hare: { asset: 'mountain-hare-base', ...LAND },
  boar: {
    asset: 'pig-base',
    ...LAND,
    recolor: {
      '#EFB1AA': '#4a3426',
      '#E4A399': '#5c4232',
      '#9C6860': '#3a281d',
      '#765139': '#2e2018',
    },
  },
  goat: { asset: 'alpine-ibex-base', ...LAND },
  fox: { asset: 'red-fox-5c3bc0', ...LAND },
  wolf: { asset: 'wolf-base', ...LAND },
  bear: { asset: 'black-bear-adbdc7', ...LAND },
  polar_bear: {
    asset: 'black-bear-adbdc7',
    ...LAND,
    recolor: {
      '#503A2B': '#efece4',
      '#342820': '#dcd8ce',
      '#191816': '#d6d1c6',
      '#B99A70': '#e8e2d4',
      '#2B211B': '#cfc9bc',
    },
    scale: 1.15,
  },
  lion: { asset: 'lion-base', ...LAND },
  shark: { asset: 'reef-shark-base', ...WATER },
  fish: { asset: 'reef-fish-base', ...WATER },
  duck: { asset: 'duck-base', ...LAND },
};

export const assetUrl = (id: string) => `/assets/polyfork/${id}/${id}.glb`;
export const collidersUrl = (id: string) =>
  `/assets/polyfork/${id}/${id}-colliders.json`;

/*
 * Assets built to stand below the town ground. The moat bridge stands on the moat floor and its walked lips sit
 * pierHeight (1.6 m) + the apron (0.1 m) above it, so it is lowered until the lips (1.68-1.70 m) meet the ground at y = 0.
 */
const BASE_Y: Record<string, number> = { 'moat-bridge-4fbcd9': -1.68 };

/** Height at which to place an asset in a flat town (0 for everything that rests on the ground). */
export const assetBaseY = (id: string) => BASE_Y[id] ?? 0;

const SIZES = new Map(manifest.assets.map((asset) => [asset.id, asset.size_m]));

/** Real-world size in metres (Polyfork measures every asset; models rest on y = 0). */
export function assetSize(id: string) {
  const size = SIZES.get(id);
  if (!size) throw new Error(`asset ${id} is not in the manifest`);
  return size;
}
