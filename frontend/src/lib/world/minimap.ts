/*
 * The minimap's geometry (10-world-v1 §5.4): a square around where the camera is (the site or hotspot it is in, else
 * the wilds around it), local metres (x east, z south) at METRES_PER_PX, north up. Whoever is off the map is drawn on
 * its edge, toward where they are.
 */
import { Vector3 } from 'three';

import type { LiveAnimal, LiveCitizen } from '@/lib/live/live-contract';
import { type SiteMapping, siteMapping, tangentFrame } from '@/lib/world/globe';

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

/** A named place the minimap centres on while the camera is within `reach` metres of its anchor: a site, a hotspot. */
export interface MapArea {
  id: string;
  name: string;
  mapping: SiteMapping;
  reach: number;
}

/** What the minimap shows: an area, or the wilds (`WILDS`) around the camera. */
export type MapView = Omit<MapArea, 'reach'>;

export const WILDS = 'wilds';
/** In the wilds the map stays put until the camera is this far (m) from its centre. */
const WILDS_RECENTRE_M = 100;

const anchorOf = (mapping: SiteMapping) =>
  mapping.toWorld(0, 0, 0, new Vector3()).normalize();

/**
 * Where the camera's `focus` is on the map: the first area (sites before hotspots) it is in, else the wilds named by
 * the `biome` under it, centred on it and moved once it walks off (`current` is kept while it still fits).
 */
export function mapViewAt(
  focus: Vector3,
  areas: readonly MapArea[],
  radius: number,
  biome: string,
  current: MapView | null,
): MapView {
  const here = focus.clone().normalize();
  const area = areas.find(
    (candidate) =>
      anchorOf(candidate.mapping).angleTo(here) * radius < candidate.reach,
  );
  if (area)
    return current?.id === area.id
      ? current
      : { id: area.id, name: area.name, mapping: area.mapping };
  const name = `the wilds · ${biome.replaceAll('_', ' ')}`;
  if (
    current?.id === WILDS &&
    anchorOf(current.mapping).angleTo(here) * radius < WILDS_RECENTRE_M
  )
    return current.name === name ? current : { ...current, name };
  return { id: WILDS, name, mapping: siteMapping(tangentFrame(here), radius) };
}

/** A node on the map: its simulation id and where it is (unit direction). */
export interface MapNode {
  id: string;
  direction: Vector3;
}

/** A node's dot by how full it is (stock / cap): the scarcity view. */
export function nodeColor(fill: number) {
  if (fill >= 0.66) return '#15803d';
  if (fill >= 0.33) return '#ca8a04';
  if (fill > 0) return '#ea580c';
  return '#78716c';
}
