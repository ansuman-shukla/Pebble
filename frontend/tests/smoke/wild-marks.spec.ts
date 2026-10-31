import { expect, test } from '@playwright/test';
import { type Matrix4, Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import { buildTerrain, decodeWorld } from '../../src/lib/world/globe';
import {
  BANNER_SIDE_M,
  BONES_OUT_M,
  BONES_SCALE,
  CAVE_BACK_M,
  STONE_SCALE,
  wildMarks,
} from '../../src/lib/world/wild-marks';
import { WORLD_URL } from './globe-helpers';

/*
 * Dens and claim markers (10 §1.5, §1.6): a cave mouth behind each den's spot opening toward its hotspot with bones
 * before it, the town's boundary stone with its banner and the bands' cairns facing out of their hotspots, every
 * piece on the drawn ground.
 */

const position = (matrix: Matrix4) =>
  new Vector3().setFromMatrixPosition(matrix);
const front = (matrix: Matrix4) =>
  new Vector3().setFromMatrixColumn(matrix, 2).normalize();
const metres = (a: Vector3, b: Vector3, radius: number) =>
  a.angleTo(b) * radius;

test.describe('dens and markers of the real world', () => {
  let view: WorldView;
  let terrain: ReturnType<typeof buildTerrain>;

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext();
    view = (await (await api.get(WORLD_URL)).json()) as WorldView;
    await api.dispose();
    terrain = buildTerrain(decodeWorld(view));
  });

  const marks = () =>
    wildMarks(
      view.places,
      (direction) => terrain.heightAt(direction),
      view.radius_m,
    );
  const toward = (from: Vector3, to: Vector3) => {
    const along = to.clone().sub(from);
    return along.addScaledVector(from, -along.dot(from)).normalize();
  };

  test('each den is a cave opening toward its hotspot with bones before it, on the ground', () => {
    const radius = view.radius_m;
    const dens = view.places.features.filter((f) => f.kind === 'den');
    const { caves, bones } = marks();
    expect(dens.length).toBe(5);
    expect([caves.length, bones.length]).toEqual([5, 5]);
    dens.forEach((den, i) => {
      const at = new Vector3(...den.position);
      const centre = new Vector3(
        ...view.places.hotspots.find((h) => h.id === den.hotspot)!.centre,
      );
      const cave = position(caves[i]);
      const bone = position(bones[i]);
      const up = cave.clone().normalize();
      expect(metres(at, up, radius)).toBeCloseTo(CAVE_BACK_M, 2);
      expect(metres(at, bone.clone().normalize(), radius)).toBeCloseTo(
        BONES_OUT_M,
        2,
      );
      expect(front(caves[i]).dot(toward(up, centre))).toBeGreaterThan(0.99);
      // the den's spot lies between the cave and its bones: the mouth
      expect(
        toward(up, at).dot(toward(up, bone.clone().normalize())),
      ).toBeGreaterThan(0.99);
      expect(cave.length() - radius).toBeCloseTo(terrain.heightAt(up), 3);
      const boneUp = bone.clone().normalize();
      expect(
        new Vector3().setFromMatrixColumn(bones[i], 2).length(),
      ).toBeCloseTo(BONES_SCALE, 5);
      expect(bone.length() - radius).toBeCloseTo(terrain.heightAt(boneUp), 3);
    });
  });

  test('a claimed hotspot shows its owner: the town a boundary stone and banner, a band a cairn, facing out', () => {
    const radius = view.radius_m;
    const markers = view.places.features.filter((f) => f.kind === 'marker');
    const { stones, banners, cairns } = marks();
    const town = markers.filter((m) => m.owner === 'town');
    const bands = markers.filter((m) => m.owner !== 'town');
    expect([town.length, bands.length]).toEqual([1, 2]);
    expect([stones.length, banners.length, cairns.length]).toEqual([1, 1, 2]);
    const outOf = (marker: (typeof markers)[number]) => {
      const at = new Vector3(...marker.position);
      const centre = new Vector3(
        ...view.places.hotspots.find((h) => h.id === marker.hotspot)!.centre,
      );
      return toward(at, centre).negate();
    };
    const at = new Vector3(...town[0].position);
    expect(metres(position(stones[0]).normalize(), at, radius)).toBeLessThan(
      1e-3,
    );
    expect(front(stones[0]).dot(outOf(town[0]))).toBeGreaterThan(0.99);
    const scale = new Vector3().setFromMatrixColumn(stones[0], 0).length();
    expect(scale).toBeCloseTo(STONE_SCALE, 5);
    expect(metres(position(banners[0]).normalize(), at, radius)).toBeCloseTo(
      BANNER_SIDE_M,
      2,
    );
    bands.forEach((band, i) => {
      const spot = new Vector3(...band.position);
      expect(
        metres(position(cairns[i]).normalize(), spot, radius),
      ).toBeLessThan(1e-3);
      expect(front(cairns[i]).dot(outOf(band))).toBeGreaterThan(0.99);
      const up = spot.clone().normalize();
      expect(position(cairns[i]).length() - radius).toBeCloseTo(
        terrain.heightAt(up),
        3,
      );
    });
  });
});
