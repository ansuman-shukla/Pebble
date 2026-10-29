/*
 * The ground's look, in one place: the biome tints of the terrain. A later reskin (a blocky look) swaps this
 * module.
 */

/** Terrain colour per biome (by name, so the client never depends on the id order). */
const BIOME_COLORS: Record<string, string> = {
  deep_ocean: '#24405e',
  shallow_ocean: '#5f9c9e',
  beach: '#e6d6a2',
  grassland: '#93b55c',
  broadleaf_forest: '#4f8a3c',
  taiga: '#3e6a4c',
  wetland: '#6f8c5c',
  hills: '#9c9a62',
  mountain: '#8b847a',
  savanna: '#c6b264',
  tundra: '#a9a892',
  snow: '#f1f4f6',
  ice: '#d9ebf4',
  lake: '#5f9c9e',
  volcanic: '#5e5450',
};
const FALLBACK_COLOR = '#ff00ff';

/** The terrain colour of a biome. */
export const biomeColor = (name: string) =>
  BIOME_COLORS[name] ?? FALLBACK_COLOR;
