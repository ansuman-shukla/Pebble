import { expect, test } from '@playwright/test';
import { Box3 } from 'three';

import type { Furniture } from '../../src/lib/client/types.gen';
import { assetSize, PROPS } from '../../src/lib/world/assets';
import {
  furniturePlacements,
  LOG_PAST_SEATS_M,
  MAT_SIZE,
} from '../../src/lib/world/furniture';
import { proceduralScene } from '../../src/lib/world/procedural-props';

/*
 * The furniture under slots (D198, issue #80): drawn at each slot's height, a log as long as the seats on it, a mat
 * long under a lying body.
 */

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
