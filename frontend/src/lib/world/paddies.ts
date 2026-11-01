/*
 * The rice paddies as drawn (10 §1.4): each paddy is one node (`paddy-1` ... `paddy-6`) laid as a rect of 2 m
 * tiles (town placements `paddy-3-0`, `paddy-3-1`, ...). A paddy is drawn as ONE field: a bund runs round its rim
 * only (no seams between its tiles) and every tile shows the paddy's live stage from the feed (`node_stages.yaml`
 * via `NodeStages`): young seedlings in flooded basins, the green stand, gold ears, then stubble on the drained mud.
 */
import type { Point } from './collision';

export const PADDY_KIND = 'rice_paddy';
export const PADDY_STAGES = ['seedlings', 'green', 'gold', 'stubble'] as const;
export type PaddyStage = (typeof PADDY_STAGES)[number];

/** Which of a tile's edges carry the paddy's rim bund: none, one side, or two (a corner). */
export const TILE_SHAPES = ['open', 'side', 'corner'] as const;
export type TileShape = (typeof TILE_SHAPES)[number];

/** Half a tile's side (the rice_paddy kind's footprint is 2 × 2 m). */
const HALF_TILE = 1;
const EDGE_TOLERANCE = 0.01;

interface PaddyTile {
  x: number;
  z: number;
  shape: TileShape;
  /** Radians about up (local yaw) turning the shape's bund (north for a side, north and west for a corner) onto
   * the paddy's rim. */
  yaw: number;
}

export interface PaddyField {
  /** The paddy's node id. */
  id: string;
  /** Local metres x0, z0, x1, z1 (x east, z south). */
  rect: [number, number, number, number];
  tiles: PaddyTile[];
}

/**
 * The drawn stage of a paddy from its node state's stage: a paddy the feed never mentioned is full, and a full
 * paddy is ripe (the backend's `entry_stage`).
 */
export function paddyStage(stage: string | null | undefined): PaddyStage {
  if (stage === null || stage === undefined) return 'gold';
  const known = PADDY_STAGES.find((name) => name === stage);
  if (!known) throw new Error(`unknown rice paddy stage ${stage}`);
  return known;
}

/** Yaw (radians) turning the shape's bund onto the rim: a side bund lies north at 0, a corner's north and west. */
const SIDE_YAW = { n: 0, w: Math.PI / 2, s: Math.PI, e: -Math.PI / 2 };
const CORNER_YAW = {
  nw: 0,
  ne: -Math.PI / 2,
  se: Math.PI,
  sw: Math.PI / 2,
};

function tileShape(
  x: number,
  z: number,
  [x0, z0, x1, z1]: PaddyField['rect'],
): Pick<PaddyTile, 'shape' | 'yaw'> {
  const at = (a: number, b: number) => Math.abs(a - b) < EDGE_TOLERANCE;
  const ns = at(z - HALF_TILE, z0) ? 'n' : at(z + HALF_TILE, z1) ? 's' : '';
  const we = at(x - HALF_TILE, x0) ? 'w' : at(x + HALF_TILE, x1) ? 'e' : '';
  if (ns && we)
    return { shape: 'corner', yaw: CORNER_YAW[`${ns}${we}` as 'nw'] };
  if (ns || we) return { shape: 'side', yaw: SIDE_YAW[(ns || we) as 'n'] };
  return { shape: 'open', yaw: 0 };
}

/** The paddies laid by the town's rice_paddy tile placements (`<paddy id>-<n>`), each tile shaped for its rim. */
export function paddyFields(
  placements: readonly { id: string; kind: string; x: number; z: number }[],
): PaddyField[] {
  const byPaddy = new Map<string, { x: number; z: number }[]>();
  for (const placement of placements) {
    if (placement.kind !== PADDY_KIND) continue;
    const id = placement.id.replace(/-\d+$/, '');
    const tiles = byPaddy.get(id) ?? [];
    tiles.push(placement);
    byPaddy.set(id, tiles);
  }
  return [...byPaddy].map(([id, tiles]) => {
    const rect: PaddyField['rect'] = [
      Math.min(...tiles.map(({ x }) => x)) - HALF_TILE,
      Math.min(...tiles.map(({ z }) => z)) - HALF_TILE,
      Math.max(...tiles.map(({ x }) => x)) + HALF_TILE,
      Math.max(...tiles.map(({ z }) => z)) + HALF_TILE,
    ];
    return {
      id,
      rect,
      tiles: tiles.map(({ x, z }) => ({ x, z, ...tileShape(x, z, rect) })),
    };
  });
}

/** A paddy's outline (local metres) pulled `inset` metres in, e.g. to cut it out of the ground marks under it. */
export function paddyOutline(
  { rect: [x0, z0, x1, z1] }: PaddyField,
  inset: number,
): Point[] {
  return [
    [x0 + inset, z0 + inset],
    [x1 - inset, z0 + inset],
    [x1 - inset, z1 - inset],
    [x0 + inset, z1 - inset],
  ];
}
