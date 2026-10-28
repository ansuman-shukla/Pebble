/*
 * GET /api/v1/world, mirrored by hand from the globe contract until the backend ships it; swap these for the
 * generated client types (`@/lib/client/types.gen`) once `pnpm update-openapi` has them.
 */
import type { TownPlacement } from '@/lib/client/types.gen';

type Vec3Tuple = [number, number, number];

export interface Anchor {
  /** Unit vector of the anchor cell. */
  position: Vec3Tuple;
  east: Vec3Tuple;
  north: Vec3Tuple;
  /** Plateau height above sea level (h0). */
  height_m: number;
}

export interface Site {
  id: string;
  kind: 'town' | 'camp' | 'landmark';
  name: string;
  cell: number;
  anchor: Anchor;
  /** In the site's local metres (x east, z south), like the town's placements. */
  placements: TownPlacement[];
}

export interface River {
  id: string;
  name?: string | null;
  cells: number[];
}

export interface WorldView {
  seed: number;
  generator_version: string;
  radius_m: number;
  frequency: number;
  cell_count: number;
  /** Index = biome id. */
  biome_names: string[];
  /** base64, little-endian float32, cell_count * 3 unit vectors. */
  positions: string;
  /** base64 float32, cell_count, metres above sea level. */
  heights: string;
  /** base64 uint8, cell_count. */
  biomes: string;
  /** base64 uint32, triangle_count * 3 cell indices, counter-clockwise seen from outside. */
  triangles: string;
  rivers: River[];
  land_loop: number[];
  sites: Site[];
}
