import { expect, test } from '@playwright/test';

import type { WorldView } from '../../src/lib/client/types.gen';
import { decodeWorld } from '../../src/lib/world/globe';
import { terrainGeometry } from '../../src/lib/world/globe-mesh';

/* The terrain mesh of the real world (GET /api/v1/world): lakes, which lie above the sea, are drawn as water. */

const WORLD_URL = 'http://localhost:8100/api/v1/world';

test('lakes above the sea are drawn as water, not sand', async ({
  request,
}) => {
  const response = await request.get(WORLD_URL);
  expect(response.ok()).toBe(true);
  const view = (await response.json()) as WorldView;
  const globe = decodeWorld(view);
  const colors = terrainGeometry(globe, view.biome_names).getAttribute('color');
  const lake = view.biome_names.indexOf('lake');
  let lakeFaces = 0;
  for (let t = 0; t < globe.triangles.length / 3; t++) {
    const cells = globe.triangles.subarray(t * 3, t * 3 + 3);
    if (![...cells].every((cell) => globe.biomes[cell] === lake)) continue;
    const height = [...cells].reduce((sum, c) => sum + globe.heights[c], 0) / 3;
    if (height <= 0.2) continue;
    lakeFaces += 1;
    const [r, g, b] = [0, 1, 2].map((k) => colors.getComponent(t * 3, k));
    expect(b, `face ${t}`).toBeGreaterThan(r + 0.2);
    expect(b, `face ${t}`).toBeGreaterThan(g);
  }
  expect(lakeFaces).toBeGreaterThan(50);
});
