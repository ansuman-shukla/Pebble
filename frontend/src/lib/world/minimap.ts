/*
 * The minimap's geometry (10-world-v1 §5.4): a square around the site nearest the camera, local metres (x east,
 * z south) at METRES_PER_PX, north up. Whoever is off the map is drawn on its edge, toward where they are.
 */
import { Vector3 } from 'three';

import type { LiveAnimal, LiveCitizen } from '@/lib/live/live-contract';
import type { SiteMapping } from '@/lib/world/globe';

export const MAP_PX = 200;
export const METRES_PER_PX = 2;
/** Markers of people off the map sit this far inside its edge (px). */
const EDGE_PX = 4;

export interface MapPoint {
  x: number;
  y: number;
  /** Off the map: drawn on the edge. */
  edge: boolean;
}

/** The pixel of a site-local point; points off the map are pulled onto its edge along the line from the centre. */
export function mapPixel(x: number, z: number): MapPoint {
  const half = MAP_PX / 2;
  const px = x / METRES_PER_PX;
  const py = z / METRES_PER_PX;
  const reach = half - EDGE_PX;
  const over = Math.max(Math.abs(px), Math.abs(py)) / reach;
  if (over <= 1) return { x: half + px, y: half + py, edge: false };
  return { x: half + px / over, y: half + py / over, edge: true };
}

const scratch = {
  up: new Vector3(),
  east: new Vector3(),
  south: new Vector3(),
  along: new Vector3(),
  local: new Vector3(),
};
/** Far enough along a direction that mapPixel puts it on the edge. */
const OFF_MAP_M = 1e9;

/** The site's tangent axis through local (x, z) at its anchor `up` (both unit), into `target`. */
function axis(
  mapping: SiteMapping,
  up: Vector3,
  x: number,
  z: number,
  target: Vector3,
) {
  mapping.toWorld(x, 0, z, target).normalize();
  return target.addScaledVector(up, -target.dot(up)).normalize();
}

/**
 * The pixel of a world point on a site's map: by the site's local metres while it is less than 90° from the anchor,
 * else on the edge toward it along the site's tangent plane (its east and south parts). The site mapping is
 * gnomonic: past 90° its local x/z point the opposite way, and near the antipode they land back inside the map.
 */
export function mapPixelOf(mapping: SiteMapping, point: Vector3): MapPoint {
  const { up, east, south, along, local } = scratch;
  mapping.toWorld(0, 0, 0, up).normalize();
  along.copy(point).normalize();
  if (along.dot(up) > 0) {
    mapping.toLocal(point, local);
    return mapPixel(local.x, local.z);
  }
  const x = along.dot(axis(mapping, up, 1, 0, east));
  const z = along.dot(axis(mapping, up, 0, 1, south));
  // straight through the planet every way is as near: drawn at north
  if (x * x + z * z < 1e-12) return mapPixel(0, -OFF_MAP_M);
  return mapPixel(x * OFF_MAP_M, z * OFF_MAP_M);
}

/** The site-local point (metres) under a pixel of the map. */
export const mapPoint = (x: number, y: number) => ({
  x: (x - MAP_PX / 2) * METRES_PER_PX,
  z: (y - MAP_PX / 2) * METRES_PER_PX,
});

export const REGION_COLORS: Record<LiveCitizen['region'], string> = {
  town: '#2563eb',
  band_a: '#16a34a',
  band_b: '#9333ea',
};

const PREDATORS: ReadonlySet<LiveAnimal['kind']> = new Set([
  'wolf',
  'bear',
  'lion',
  'polar_bear',
  'shark',
]);

export const animalColor = (kind: LiveAnimal['kind']) =>
  PREDATORS.has(kind) ? '#dc2626' : '#a16207';

export const FIRE_COLOR = '#f97316';
