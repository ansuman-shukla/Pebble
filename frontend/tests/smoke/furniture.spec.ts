import { expect, test } from '@playwright/test';
import { Box3, Vector3 } from 'three';

import type { Furniture, WorldView } from '../../src/lib/client/types.gen';
import { MockLiveServer } from '../../src/lib/live/mock-live';
import { assetSize, PROPS } from '../../src/lib/world/assets';
import {
  furniturePlacements,
  LOG_PAST_SEATS_M,
  MAT_SIZE,
} from '../../src/lib/world/furniture';
import { anchorMapping } from '../../src/lib/world/globe';
import { proceduralScene } from '../../src/lib/world/procedural-props';
import { WORLD_URL } from './globe-helpers';

/*
 * The furniture under slots (D198, issue #80): drawn at each slot's height, a log as long as the seats on it, a mat
 * long under a lying body; and the mock feed's seated and lying people are on such a piece, never in the air.
 */

/** A seat on a piece lies this close to where the feed puts its sitter. */
const ON_M = 0.05;

const piece = (overrides: Partial<Furniture>): Furniture => ({
  id: 'camp:fire-pit#seat-1',
  site: 'camp',
  kind: 'log_seat',
  x: 0.74,
  z: -2.03,
  heading_deg: 340,
  seat_m: 0.4,
  span_m: 0.84,
  ...overrides,
});

/** The top of a drawn piece (its seat) and its extent along its own x and z, as placed. */
function drawn(furniture: Furniture) {
  const [placed] = furniturePlacements([furniture], furniture.site);
  const id = PROPS[furniture.kind];
  const size = assetSize(id);
  const [sx, sy, sz] = placed.scale;
  const top = id.startsWith('procedural-')
    ? new Box3().setFromObject(proceduralScene(id)).max.y
    : size.y;
  return {
    placed,
    top: top * sy,
    across: size.x * sx,
    along: size.z * sz,
  };
}

test('each piece is drawn at its slot, turned its way, its seat at the slot height', () => {
  const log = drawn(piece({}));
  expect(log.placed).toMatchObject({ x: 0.74, z: -2.03, rotation_deg: 340 });
  expect(log.top).toBeCloseTo(0.4, 2);
  expect(log.across).toBeCloseTo(0.84 + LOG_PAST_SEATS_M, 2); // both sitters on it, with room at its ends
  expect(log.along).toBeCloseTo(0.4, 2); // round: as thick as it is high
  expect(drawn(piece({ span_m: 0, seat_m: 0.5 })).across).toBeCloseTo(0.9, 2);
  expect(drawn(piece({ span_m: 0, seat_m: 0.5 })).top).toBeCloseTo(0.5, 2);
  const stool = drawn(piece({ kind: 'stool', seat_m: 0.3, span_m: 0 }));
  expect(stool.top).toBeCloseTo(0.3, 2);
  expect(
    drawn(piece({ kind: 'stool', seat_m: 0.36, span_m: 0 })).top,
  ).toBeCloseTo(0.36, 2);
  const lord = drawn(piece({ kind: 'lord_seat', seat_m: 0.45, span_m: 0 }));
  expect(lord.top).toBeCloseTo(0.45, 2);
  const mat = drawn(piece({ kind: 'sleeping_mat', seat_m: 0, span_m: 0 }));
  expect([mat.across, mat.top, mat.along].map((m) => m.toFixed(2))).toEqual(
    [MAT_SIZE.x, MAT_SIZE.y, MAT_SIZE.z].map((m) => m.toFixed(2)),
  ); // flat and long the way a lying body faces
  expect(
    furniturePlacements([piece({}), piece({ site: 'town' })], 'town'),
  ).toHaveLength(1);
});

test('the mock feed seats and beds people on drawn furniture, never in the air', async ({
  request,
}) => {
  const world = (await (await request.get(WORLD_URL)).json()) as WorldView;
  const pieces = (await (
    await request.get(`${WORLD_URL}/furniture`)
  ).json()) as Furniture[];
  const sites = new Map(world.sites.map((site) => [site.id, site]));
  const seats = pieces.flatMap((one) => {
    const site = sites.get(one.site);
    if (!site) throw new Error(`no site ${one.site}`);
    const mapping = anchorMapping(site.anchor, world.radius_m);
    const turn = (one.heading_deg * Math.PI) / 180;
    const half = (one.span_m ?? 0) / 2;
    return [-half, half].map((along) => ({
      piece: one,
      unit: mapping
        .toWorld(
          one.x + Math.cos(turn) * along,
          0,
          one.z - Math.sin(turn) * along,
          new Vector3(),
        )
        .normalize(),
    }));
  });
  const server = new MockLiveServer(world);
  const used = new Set<string>();
  for (let tick = 0; tick < 60; tick += 1) {
    for (const citizen of server.entities().citizens) {
      if (citizen.posture !== 'sitting' && citizen.slot_heading === null)
        continue;
      const at = new Vector3(...citizen.position.unit);
      const [nearest] = seats
        .map((seat) => ({
          ...seat,
          metres: seat.unit.angleTo(at) * world.radius_m,
        }))
        .sort((a, b) => a.metres - b.metres);
      const where = `${citizen.id} at tick ${tick}`;
      expect(nearest.metres, where).toBeLessThan(ON_M);
      expect(citizen.slot_heading, where).toBeCloseTo(
        nearest.piece.heading_deg,
        -1.5,
      );
      expect(citizen.slot_height_m ?? 0, where).toBeCloseTo(
        nearest.piece.seat_m,
        2,
      );
      used.add(nearest.piece.kind);
    }
    server.skip(1);
  }
  expect([...used].sort()).toEqual([
    'log_seat',
    'lord_seat',
    'sleeping_mat',
    'stool',
  ]);
});
