/*
 * The minimap's geometry (10-world-v1 §5.4): a square around the site nearest the camera, local metres (x east,
 * z south) at METRES_PER_PX, north up. Whoever is off the map is drawn on its edge, toward where they are.
 */
import type { LiveAnimal, LiveCitizen } from '@/lib/live/live-contract';

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
