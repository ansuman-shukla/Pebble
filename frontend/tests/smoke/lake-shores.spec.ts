import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  buildTerrain,
  decodeWorld,
  type GlobeTerrain,
} from '../../src/lib/world/globe';
import {
  isLakeCell,
  lakeSurface,
  stillWaterGeometry,
} from '../../src/lib/world/water-mesh';
import { WORLD_URL } from './globe-helpers';

/*
 * A lake's water lies level over its grid triangles, but off its own cells, over ground at or below its level (the
 * falls pool's outlet floor is carved at the lake's height for 130 m), it thins out and settles onto the ground
 * by the triangle's dry edge: no straight edge of water across the valley, no sheet of shore foam over the dry
 * floor, nothing in mid-air (critic round 1: the falls pool's flat slabs with hard straight edges).
 */

let view: WorldView;
let terrain: GlobeTerrain;

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  view = (await (await api.get(WORLD_URL)).json()) as WorldView;
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
});

test("a lake's water fades out onto the ground at its triangles' dry edges", () => {
  const { globe } = terrain;
  const geometry = stillWaterGeometry(terrain);
  const position = geometry.getAttribute('position');
  const water = geometry.getAttribute('water');
  // the water's vertices (height, depth) by direction, in 1 m buckets
  const key = (v: Vector3) =>
    [v.x, v.y, v.z].map((c) => Math.round(c * globe.radius)).join(',');
  const drawn = new Map<string, [number, number][]>();
  const at = new Vector3();
  for (let i = 0; i < position.count; i++) {
    at.fromBufferAttribute(position, i);
    const height = at.length() - globe.radius;
    const bucket = key(at.normalize());
    drawn.set(bucket, [...(drawn.get(bucket) ?? []), [height, water.getX(i)]]);
  }
  const divisions = terrain.surface.divisions;
  const faults: string[] = [];
  let checked = 0;
  for (let t = 0; t < globe.triangles.length / 3; t++) {
    const surface = lakeSurface(globe, t);
    if (surface === -Infinity) continue;
    const cells = [0, 1, 2].map((k) => globe.triangles[t * 3 + k]);
    for (let k = 0; k < 3; k++) {
      const ends = [cells[k], cells[(k + 1) % 3]];
      // an edge between two dry cells: the lake's water ends there
      if (ends.some((cell) => isLakeCell(globe, cell))) continue;
      const [a, b] = ends.map((cell) =>
        new Vector3().fromArray(globe.positions, cell * 3),
      );
      for (let i = 1; i < divisions; i++) {
        const point = a
          .clone()
          .lerp(b, i / divisions)
          .normalize();
        const ground = terrain.heightAt(point);
        if (ground >= surface) continue; // the bank rises over the water there: it hides it
        for (const [height, depth] of drawn.get(key(point)) ?? []) {
          checked += 1;
          if (depth > 0 || height - ground > 0.1)
            faults.push(
              `triangle ${t}: water ${(height - ground).toFixed(2)} m over the ground, ${depth.toFixed(2)} deep`,
            );
        }
      }
    }
  }
  expect(checked).toBeGreaterThan(20);
  expect(faults).toEqual([]);
});
