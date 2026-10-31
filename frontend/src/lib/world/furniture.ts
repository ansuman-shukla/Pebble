/*
 * The furniture people sit and lie on (GET /api/v1/world/furniture, D198) as placements to draw: each piece at its
 * slot, turned the way whoever uses it faces, stretched so its seat is at the slot's height. A log seat is as long
 * as the seats on it need (`span_m` between the outer two, plus a body's width); a sleeping mat (the straw pile) is
 * spread flat and long under a lying body, its length along the way the body faces (head behind, feet ahead).
 */
import type { Furniture } from '@/lib/client/types.gen';
import { assetSize, PROPS } from '@/lib/world/assets';
import { FURNITURE_SEAT } from '@/lib/world/procedural-props';

/** A log seat reaches this far past its outer seats, together (a sitter's width). */
export const LOG_PAST_SEATS_M = 0.9;
/** A sleeping mat as drawn: across the body, its height, along the body (metres). */
export const MAT_SIZE = { x: 0.9, y: 0.07, z: 2 };

export interface FurniturePlacement {
  id: string;
  kind: Furniture['kind'];
  x: number;
  z: number;
  rotation_deg: number;
  /** The model's stretch along its own x (across), y (up) and z (the way it faces). */
  scale: [number, number, number];
}

function stretch(piece: Furniture): [number, number, number] {
  const id = PROPS[piece.kind];
  const size = assetSize(id);
  if (piece.kind === 'sleeping_mat')
    return [MAT_SIZE.x / size.x, MAT_SIZE.y / size.y, MAT_SIZE.z / size.z];
  const up = piece.seat_m / FURNITURE_SEAT[id];
  const across =
    piece.kind === 'log_seat'
      ? ((piece.span_m ?? 0) + LOG_PAST_SEATS_M) / size.x
      : 1;
  return [across, up, piece.kind === 'log_seat' ? up : 1];
}

/** The pieces of one site, as placements in its chart. */
export function furniturePlacements(
  pieces: readonly Furniture[],
  site: string,
): FurniturePlacement[] {
  return pieces
    .filter((piece) => piece.site === site)
    .map((piece) => ({
      id: piece.id,
      kind: piece.kind,
      x: piece.x,
      z: piece.z,
      rotation_deg: piece.heading_deg,
      scale: stretch(piece),
    }));
}
