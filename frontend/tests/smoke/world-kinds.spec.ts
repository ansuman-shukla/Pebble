import { expect, test } from '@playwright/test';

import type { WorldView } from '../../src/lib/client/types.gen';
import { assetSize, kindScale, PROPS } from '../../src/lib/world/assets';

/*
 * The real generated world (GET /api/v1/world on the backend) only names kinds the frontend can draw, and the
 * backend footprints of its camps and landmarks match the drawn size (asset size x kindScale).
 */

const WORLD_URL = 'http://localhost:8100/api/v1/world';
/** Footprints are authored to 0.1 m. */
const FOOTPRINT_TOLERANCE = 0.1;

async function fetchWorld(
  request: import('@playwright/test').APIRequestContext,
) {
  const response = await request.get(WORLD_URL);
  expect(response.ok()).toBe(true);
  return (await response.json()) as WorldView;
}

test('every kind placed at a site of the real world is in the registry', async ({
  request,
}) => {
  const world = await fetchWorld(request);
  const kinds = new Set(
    world.sites.flatMap((site) => (site.placements ?? []).map((p) => p.kind)),
  );
  expect(kinds.size).toBeGreaterThan(10);
  expect([...kinds].filter((kind) => !(kind in PROPS))).toEqual([]);
});

test('site footprints match the drawn size of their kind', async ({
  request,
}) => {
  const world = await fetchWorld(request);
  const placements = world.sites
    .filter((site) => site.kind !== 'town')
    .flatMap((site) => site.placements ?? []);
  expect(placements.some((p) => p.kind === 'giant_tree')).toBe(true);
  for (const placement of placements) {
    const size = assetSize(PROPS[placement.kind as keyof typeof PROPS]);
    const scale = kindScale(placement.kind);
    const turned = placement.rotation_deg % 180 !== 0;
    const [x, z] = turned
      ? [size.z * scale, size.x * scale]
      : [size.x * scale, size.z * scale];
    const { x: fx, z: fz } = placement.footprint; // already turned by rotation_deg
    expect(Math.abs(fx - x), `${placement.kind} x`).toBeLessThanOrEqual(
      FOOTPRINT_TOLERANCE,
    );
    expect(Math.abs(fz - z), `${placement.kind} z`).toBeLessThanOrEqual(
      FOOTPRINT_TOLERANCE,
    );
  }
});
