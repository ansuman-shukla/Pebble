import type { Group } from 'three';

/** Options of Polyfork's parametric rice paddy tile (rice-paddy-tile-dc727e); every one is optional. */
export interface RicePaddyOptions {
  colorway?: 'lowland' | 'dark-loam' | 'dry-bund' | 'grey-silt';
  /** Any zone's colour (a hex): `turf`, `earth`, `mud`, `water`, `rice`, `ripe`, `grain`, `straw`, `snow`. */
  water?: string;
  /** The crop's growth: spring seedlings, the green summer stand, the gold autumn ears; winter lies bare. */
  season?: 'spring' | 'summer' | 'autumn' | 'winter';
  /** Which tile edges carry the raised outer bund (`one-side`: −z, `corner`: −x and −z, `two-sides`: ±z). */
  bund?: 'all' | 'three-sides' | 'two-sides' | 'corner' | 'one-side' | 'none';
  /** How the tile's own bunds divide it (`one`: a single basin edge to edge). */
  basins?: 'four' | 'two' | 'one';
  /** Autumn only: the crop cut, the field drained, cut straw standing on the mud. */
  harvested?: boolean;
}

/** A 2 × 2 m tile (y up from 0) as a group holding one vertex-coloured mesh. */
export function createAsset(options?: RicePaddyOptions): Group;
