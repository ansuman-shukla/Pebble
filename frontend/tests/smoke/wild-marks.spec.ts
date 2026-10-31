import { expect, test } from '@playwright/test';
import { type Matrix4, Vector3 } from 'three';

import type { TownView, WorldView } from '../../src/lib/client/types.gen';
import {
  anchorMapping,
  buildTerrain,
  decodeWorld,
} from '../../src/lib/world/globe';
import { planetMarks, ROUTE_WIDTH } from '../../src/lib/world/ground-marks';
import { clipWater, TOWN_WATER_Y } from '../../src/lib/world/ground-shape';
import { riverLayout, streamChannels } from '../../src/lib/world/river-courses';
import {
  BANNER_SIDE_M,
  BONES_APART_M,
  BONES_OUT_M,
  BONES_SCALE,
  CAVE_BACK_M,
  ROADSIDE_M,
  STONE_SCALE,
  STREAMER_SIDE_M,
  wildMarks,
} from '../../src/lib/world/wild-marks';
import { TOWN_URL, WORLD_URL } from './explore-helpers';
import { openGlobe } from './globe-helpers';

/*
 * Dens and claim markers (10 §1.5, §1.6): a cave mouth behind each den's spot opening toward its hotspot with two
 * scatters of bones before it; the town's boundary stone with its banner and the bands' cairns with their hide
 * streamers on the roadside, facing the road, never on it; every piece on the drawn ground; and the globe draws
 * them, the banner and the streamers waving.
 */

/** The town's ground disc (globe-page.tsx TOWN_GROUND_RADIUS). */
const TOWN_GROUND_RADIUS = 225;

const position = (matrix: Matrix4) =>
  new Vector3().setFromMatrixPosition(matrix);
const column = (matrix: Matrix4, index: number) =>
  new Vector3().setFromMatrixColumn(matrix, index);
const front = (matrix: Matrix4) => column(matrix, 2).normalize();
const metres = (a: Vector3, b: Vector3, radius: number) =>
  a.clone().normalize().angleTo(b.clone().normalize()) * radius;
/** The tangent at `from` toward `to` (unit directions). */
const toward = (from: Vector3, to: Vector3) => {
  const along = to.clone().sub(from);
  return along.addScaledVector(from, -along.dot(from)).normalize();
};

test.describe('dens and markers of the real world', () => {
  let view: WorldView;
  let town: TownView;
  let terrain: ReturnType<typeof buildTerrain>;
  let drawn: ReturnType<typeof ribbons>;

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext();
    view = (await (await api.get(WORLD_URL)).json()) as WorldView;
    town = (await (await api.get(TOWN_URL)).json()) as TownView;
    await api.dispose();
    terrain = buildTerrain(decodeWorld(view));
    drawn = ribbons();
  });

  const marks = () =>
    wildMarks(
      view.places,
      drawn,
      (direction) => terrain.heightAt(direction),
      view.radius_m,
    );
  const onGround = (matrix: Matrix4) => {
    const at = position(matrix);
    expect(at.length() - view.radius_m).toBeCloseTo(
      terrain.heightAt(at.clone().normalize()),
      3,
    );
  };
  /** The drawn roads and paths (ground-marks.ts ribbons), as the globe lays them. */
  const ribbons = () => {
    const site = view.sites.find((candidate) => candidate.kind === 'town')!;
    const height = site.anchor.height_m;
    const mapping = anchorMapping(site.anchor, view.radius_m);
    const rivers = riverLayout(
      terrain,
      view.rivers.map((river) => river.cells),
      {
        hole: {
          up: new Vector3(...site.anchor.position),
          angle: Math.atan(TOWN_GROUND_RADIUS / (view.radius_m + height)),
        },
        channels: streamChannels(town.water, mapping, height, TOWN_WATER_Y),
      },
    );
    return planetMarks({
      globe: terrain.globe,
      places: view.places,
      sites: view.sites,
      rivers,
      town: {
        placements: town.placements,
        water: clipWater(town.water, TOWN_GROUND_RADIUS),
      },
    }).ribbons;
  };

  test('each den is a cave opening toward its hotspot with two scatters of bones before it, on the ground', () => {
    const radius = view.radius_m;
    const dens = view.places.features.filter((f) => f.kind === 'den');
    const { caves, bones } = marks();
    expect(dens.length).toBe(5);
    expect([caves.length, bones.length]).toEqual([5, 10]);
    dens.forEach((den, i) => {
      const at = new Vector3(...den.position);
      const centre = new Vector3(
        ...view.places.hotspots.find((h) => h.id === den.hotspot)!.centre,
      );
      const cave = position(caves[i]).normalize();
      expect(metres(at, cave, radius)).toBeCloseTo(CAVE_BACK_M, 2);
      expect(front(caves[i]).dot(toward(cave, centre))).toBeGreaterThan(0.99);
      onGround(caves[i]);
      const pair = [bones[2 * i], bones[2 * i + 1]];
      const [a, b] = pair.map((matrix) => position(matrix).normalize());
      expect(metres(a, b, radius)).toBeCloseTo(BONES_APART_M, 2);
      const middle = a.clone().add(b).normalize();
      expect(metres(at, middle, radius)).toBeCloseTo(BONES_OUT_M, 1);
      // the den's spot is the mouth: between the cave and its bones
      expect(toward(at, cave).dot(toward(at, middle))).toBeLessThan(-0.99);
      for (const matrix of pair) {
        expect(column(matrix, 2).length()).toBeCloseTo(BONES_SCALE, 5);
        onGround(matrix);
      }
    });
  });

  test('a claimed hotspot shows its owner on the roadside, facing the road: stone and banner, cairn and streamer', () => {
    const radius = view.radius_m;
    const markers = view.places.features.filter((f) => f.kind === 'marker');
    const { stones, banners, cairns, streamers } = marks();
    const town = markers.filter((m) => m.owner === 'town');
    const bands = markers.filter((m) => m.owner !== 'town');
    expect([town.length, bands.length]).toEqual([1, 2]);
    expect([stones.length, banners.length]).toEqual([1, 1]);
    expect([cairns.length, streamers.length]).toEqual([2, 2]);
    /** The nearest drawn route to a spot: how far its middle line is, its width and the way to it. */
    const nearestRoute = (spot: Vector3) => {
      let best = { gap: Infinity, width: 0, point: spot };
      for (const ribbon of drawn)
        for (const point of ribbon.points) {
          const gap = metres(point, spot, radius);
          if (gap < best.gap) best = { gap, width: ribbon.width, point };
        }
      return best;
    };
    const pieces = [
      { piece: stones[0], partner: banners[0], side: BANNER_SIDE_M, x: 1 },
      ...cairns.map((cairn, i) => ({
        piece: cairn,
        partner: streamers[i],
        side: STREAMER_SIDE_M,
        x: -1,
      })),
    ];
    for (const { piece, partner, side, x } of pieces) {
      const at = position(piece).normalize();
      const route = nearestRoute(at);
      // off the drawn route: past its edge by about a metre, nowhere on it
      expect(route.gap).toBeGreaterThan(route.width / 2 + ROADSIDE_M * 0.5);
      expect(route.gap).toBeLessThan(route.width / 2 + ROADSIDE_M + 1.5);
      expect(front(piece).dot(toward(at, route.point))).toBeGreaterThan(0.95);
      onGround(piece);
      const by = position(partner).normalize();
      expect(metres(at, by, radius)).toBeCloseTo(side, 2);
      expect(toward(at, by).dot(column(piece, 0).normalize())).toBeCloseTo(
        x,
        2,
      );
      expect(nearestRoute(by).gap).toBeGreaterThan(nearestRoute(by).width / 2);
      onGround(partner);
    }
    const stone = stones[0];
    expect(column(stone, 1).length()).toBeCloseTo(STONE_SCALE.y, 5);
    expect(column(stone, 0).length()).toBeCloseTo(STONE_SCALE.x, 5);
    // the town's marker is its boundary stone: by the Lord's woods route it marks
    expect(
      metres(position(stone), new Vector3(...town[0].position), radius),
    ).toBeLessThan(ROUTE_WIDTH.road / 2 + ROADSIDE_M + 1.5);
  });
});

test('the globe draws every den and marker, the banner and the streamers waving', async ({
  page,
}) => {
  const errors: string[] = [];
  await openGlobe(page, errors);
  type Drawn = { counts: Record<string, number>; waving: string[] };
  const drawn = () =>
    page.evaluate(
      () =>
        (globalThis as { __pebbleWildMarks?: Drawn }).__pebbleWildMarks ?? null,
    );
  await expect.poll(drawn, { timeout: 30_000 }).not.toBeNull();
  const { counts, waving } = (await drawn())!;
  expect(counts).toEqual({
    caves: 5,
    bones: 10,
    stones: 1,
    banners: 1,
    cairns: 2,
    streamers: 2,
  });
  expect(waving).toEqual(['banners', 'streamers']); // the banner's cloth and the streamers' hide (wind.ts)
});
