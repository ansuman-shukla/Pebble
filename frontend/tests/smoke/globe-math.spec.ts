import { expect, test } from '@playwright/test';
import { Matrix4, Vector3 } from 'three';

import {
  buildTerrain,
  decodeBase64,
  directionFromLatLon,
  encodeBase64,
  float32FromBase64,
  float32ToBase64,
  type Globe,
  latLonFromDirection,
  siteMapping,
  tangentFrame,
  uint32FromBase64,
  uint32ToBase64,
} from '../../src/lib/world/globe';
import { groundHides } from '../../src/lib/world/globe-pick';
import { icosphere } from '../../src/lib/world/icosphere';

/* Pure globe math (no browser): frames, the site mapping, the terrain lookup and the array encodings. */

const R = 2000;

const near = (a: Vector3, b: Vector3, tolerance: number) =>
  expect(a.distanceTo(b)).toBeLessThan(tolerance);

test('typed arrays round-trip through little-endian base64', () => {
  expect(float32ToBase64([1])).toBe('AACAPw==');
  expect(uint32ToBase64([1, 256])).toBe('AQAAAAABAAA=');
  const floats = [0, -1.5, 3.25, 1e-7, 123456.75];
  expect([...float32FromBase64(float32ToBase64(floats))]).toEqual([
    ...new Float32Array(floats),
  ]);
  const ints = [0, 1, 4294967295, 36001];
  expect([...uint32FromBase64(uint32ToBase64(ints))]).toEqual(ints);
  const bytes = new Uint8Array(70_000).map((_, i) => (i * 31) % 256);
  expect(decodeBase64(encodeBase64(bytes))).toEqual(bytes);
});

test('lat/lon follow the contract axes and invert', () => {
  near(directionFromLatLon(0, 0), new Vector3(0, 0, 1), 1e-12);
  near(directionFromLatLon(0, 90), new Vector3(1, 0, 0), 1e-12);
  near(directionFromLatLon(90, 0), new Vector3(0, 1, 0), 1e-12);
  for (const [lat, lon] of [
    [12, 34],
    [-56, -170],
    [80, 179],
  ]) {
    const back = latLonFromDirection(directionFromLatLon(lat, lon));
    expect(back.lat).toBeCloseTo(lat, 9);
    expect(back.lon).toBeCloseTo(lon, 9);
  }
});

test('the tangent frame is orthonormal and right-handed, with the pole fallback', () => {
  const equator = tangentFrame(new Vector3(0, 0, 1));
  near(equator.east, new Vector3(1, 0, 0), 1e-12);
  near(equator.north, new Vector3(0, 1, 0), 1e-12);
  near(equator.south, new Vector3(0, -1, 0), 1e-12);
  // at the pole cross(Y, u) vanishes: east comes from cross(Z, u)
  const pole = tangentFrame(new Vector3(0, 1, 0));
  near(pole.east, new Vector3(-1, 0, 0), 1e-12);

  const directions = [
    directionFromLatLon(0, 0),
    directionFromLatLon(45, 30),
    directionFromLatLon(-60, -120),
    directionFromLatLon(89.9999, 10),
    new Vector3(1e-9, 1, 0),
    new Vector3(0, -1, 0),
  ];
  for (const direction of directions) {
    const { up, east, north, south } = tangentFrame(direction);
    for (const axis of [up, east, north])
      expect(axis.length()).toBeCloseTo(1, 12);
    expect(up.dot(east)).toBeCloseTo(0, 12);
    expect(up.dot(north)).toBeCloseTo(0, 12);
    expect(east.dot(north)).toBeCloseTo(0, 12);
    near(new Vector3().crossVectors(east, up), south, 1e-12);
    near(south, north.clone().negate(), 1e-15);
  }
});

test('local metres map onto the globe and back exactly, also near a pole', () => {
  const h0 = 8;
  for (const [lat, lon] of [
    [0, 0],
    [32, 20],
    [-60, -120],
    [89.9, 45],
    [90, 0],
  ]) {
    const frame = tangentFrame(directionFromLatLon(lat, lon));
    const mapping = siteMapping(frame, R + h0);
    const world = new Vector3();
    const back = new Vector3();
    for (let x = -200; x <= 200; x += 25) {
      for (let z = -200; z <= 200; z += 25) {
        for (const y of [0, 3.5]) {
          mapping.toWorld(x, y, z, world);
          expect(world.length()).toBeCloseTo(R + h0 + y, 9);
          mapping.toLocal(world, back);
          near(back, new Vector3(x, y, z), 1e-6);
        }
      }
    }
    // the anchor is at the origin, x runs east and z south of it
    near(
      mapping.toWorld(0, 0, 0, world),
      frame.up.clone().multiplyScalar(R + h0),
      1e-9,
    );
    const anchor = frame.up.clone().multiplyScalar(R + h0);
    expect(
      mapping.toWorld(50, 0, 0, world).sub(anchor).dot(frame.east),
    ).toBeGreaterThan(49);
    expect(
      mapping.toWorld(0, 0, 50, world).sub(anchor).dot(frame.south),
    ).toBeGreaterThan(49);
  }
});

test('a placement matrix stands the model on the local normal, yawed about it', () => {
  const frame = tangentFrame(directionFromLatLon(40, -70));
  const mapping = siteMapping(frame, R + 8);
  const matrix = new Matrix4();
  const at = mapping.toWorld(120, 0, -80, new Vector3());
  mapping.matrix(120, 0, -80, 0, matrix);
  near(new Vector3(0, 0, 0).applyMatrix4(matrix), at, 1e-9);
  const upAt = at.clone().normalize();
  near(new Vector3(0, 1, 0).applyMatrix4(matrix).sub(at), upAt, 1e-9);
  // three.js rotation.y = +90° turns the model's +z towards east'
  mapping.matrix(120, 0, -80, Math.PI / 2, matrix);
  const modelZ = new Vector3(0, 0, 1).applyMatrix4(matrix).sub(at);
  const eastAt = frame.east
    .clone()
    .addScaledVector(upAt, -frame.east.dot(upAt))
    .normalize();
  near(modelZ, eastAt, 1e-9);
  expect(modelZ.dot(upAt)).toBeCloseTo(0, 9);
});

function testGlobe(frequency: number): Globe {
  const { positions, triangles } = icosphere(frequency);
  const cellCount = positions.length / 3;
  const heights = new Float32Array(cellCount).map(
    (_, i) => Math.sin(i * 12.9898) * 80,
  );
  return {
    radius: R,
    cellCount,
    positions,
    heights,
    biomes: new Uint8Array(cellCount).map((_, i) => i % 15),
    triangles,
  };
}

test('the icosphere has 10·f²+2 cells and 20·f² outward triangles', () => {
  const { positions, triangles } = icosphere(6);
  expect(positions.length / 3).toBe(362);
  expect(triangles.length / 3).toBe(720);
  const [a, b, c] = [new Vector3(), new Vector3(), new Vector3()];
  for (let t = 0; t < triangles.length; t += 3) {
    a.fromArray(positions, triangles[t] * 3);
    b.fromArray(positions, triangles[t + 1] * 3);
    c.fromArray(positions, triangles[t + 2] * 3);
    const normal = new Vector3()
      .subVectors(b, a)
      .cross(new Vector3().subVectors(c, a));
    expect(normal.dot(a)).toBeGreaterThan(0);
  }
});

test('the nearest cell walk finds the true nearest cell', () => {
  const globe = testGlobe(12);
  const terrain = buildTerrain(globe);
  const cell = new Vector3();
  for (let k = 0; k < 200; k++) {
    const direction = directionFromLatLon(
      Math.asin(Math.sin(k * 7.1)) * (180 / Math.PI),
      ((k * 47.3) % 360) - 180,
    );
    let best = -1;
    let bestDot = -Infinity;
    for (let i = 0; i < globe.cellCount; i++) {
      const score = cell.fromArray(globe.positions, i * 3).dot(direction);
      if (score > bestDot) [best, bestDot] = [i, score];
    }
    expect(terrain.nearestCell(direction, k % globe.cellCount)).toBe(best);
    expect(terrain.biomeAt(direction)).toBe(globe.biomes[best]);
  }
});

test('terrain height equals cell heights at cells and the rendered faces between them', () => {
  const globe = testGlobe(20);
  const terrain = buildTerrain(globe);
  const direction = new Vector3();
  for (let i = 0; i < globe.cellCount; i += 7) {
    direction.fromArray(globe.positions, i * 3);
    expect(terrain.heightAt(direction)).toBeCloseTo(globe.heights[i], 3);
  }
  const n = terrain.surface.divisions;
  const face = new Float64Array(9);
  const corner = [new Vector3(), new Vector3(), new Vector3()];
  const point = new Vector3();
  for (let t = 0; t < globe.triangles.length / 3; t += 5) {
    // a face of the triangle's refined lattice: the lower one at (i, j) or the upper one next to it
    const i = t % (n - 1);
    const j = (t >> 2) % (n - 1 - i);
    const lattice =
      t % 2
        ? [
            [i, j],
            [i + 1, j],
            [i, j + 1],
          ]
        : [
            [i + 1, j],
            [i + 1, j + 1],
            [i, j + 1],
          ];
    lattice.forEach(([li, lj], k) => {
      terrain.surface.vertex(t, li, lj, face, k * 3);
      corner[k].fromArray(face, k * 3);
    });
    const w1 = ((t * 0.37) % 0.8) + 0.05;
    const w2 = (1 - w1) * (((t * 0.61) % 0.9) + 0.05);
    point
      .copy(corner[0])
      .multiplyScalar(1 - w1 - w2)
      .addScaledVector(corner[1], w1)
      .addScaledVector(corner[2], w2);
    const hit = terrain.locate(point);
    expect(hit.height).toBeCloseTo(point.length() - R, 6);
    expect(hit.triangle).toBe(t);
    const cells = [0, 1, 2].map(
      (k) => globe.heights[globe.triangles[t * 3 + k]],
    );
    // the patch stays near the span of its cells (an edge middle bends by at most a quarter of its rise)
    expect(hit.height).toBeGreaterThan(
      Math.min(...cells) -
        0.5 * (Math.max(...cells) - Math.min(...cells)) -
        0.1,
    );
    expect(hit.height).toBeLessThan(
      Math.max(...cells) +
        0.5 * (Math.max(...cells) - Math.min(...cells)) +
        0.1,
    );
  }
});

test('the refined surface keeps flats flat and meets its neighbour patches without cracks', () => {
  const globe = testGlobe(30);
  globe.heights.fill(30);
  const flat = buildTerrain(globe);
  const direction = new Vector3();
  for (let k = 0; k < 200; k++) {
    directionFromLatLon(
      Math.asin(Math.sin(k * 3.7)) * (180 / Math.PI),
      ((k * 31.3) % 360) - 180,
      direction,
    );
    // faces are chords between lattice points on the sphere (up to ~25 m apart here): they sag by a few cm only
    const sag = 30 - flat.heightAt(direction);
    expect(sag).toBeGreaterThanOrEqual(-1e-6);
    expect(sag).toBeLessThan(0.05);
  }
  const rough = buildTerrain(testGlobe(30));
  const { surface } = rough;
  const n = surface.divisions;
  const [a, b] = [new Float64Array(3), new Float64Array(3)];
  // every grid edge's points are the same seen from both of its triangles
  const seen = new Map<number, [number, number]>();
  let gap = 0;
  let shared = 0;
  for (let t = 0; t < globe.triangles.length / 3; t++) {
    for (let side = 0; side < 3; side++) {
      const edge = surface.triangleEdges[t * 3 + side];
      const other = seen.get(edge);
      if (!other) {
        seen.set(edge, [t, side]);
        continue;
      }
      const [u, otherSide] = other;
      // lattice point s steps from the side's first corner (A on AB, B on BC, C on CA)
      const along = (edgeSide: number, s: number) =>
        [
          [s, 0],
          [n - s, s],
          [0, n - s],
        ][edgeSide];
      for (let step = 1; step < n; step++) {
        const [i, j] = along(side, step);
        const [oi, oj] = along(otherSide, n - step);
        surface.vertex(t, i, j, a, 0);
        surface.vertex(u, oi, oj, b, 0);
        gap = Math.max(gap, Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]));
        shared += 1;
      }
    }
  }
  expect(shared).toBe((globe.triangles.length / 2) * (n - 1));
  expect(gap).toBeLessThan(1e-6);
});

test('the ground hides a point behind a hill or past the horizon, not one in plain sight', () => {
  const R = 2000;
  /** A point `metres` along the planet's surface from the north pole, `height` above sea level. */
  const at = (metres: number, height: number) =>
    new Vector3(Math.sin(metres / R), Math.cos(metres / R), 0).multiplyScalar(
      R + height,
    );
  const sea = () => 0;
  expect(groundHides(at(0, 3), at(100, 2), R, sea)).toBe(false);
  // 300 m off, the planet's bulge (5.6 m) stands between two heads
  expect(groundHides(at(0, 3), at(300, 2), R, sea)).toBe(true);
  const hill = (direction: Vector3) => {
    const metres = Math.atan2(direction.x, direction.y) * R;
    return metres > 30 && metres < 70 ? 30 : 0;
  };
  expect(groundHides(at(0, 3), at(100, 2), R, hill)).toBe(true);
  // a target on a rise that stands a little over the line near it (its own ground) still shows
  const rise = (direction: Vector3) =>
    Math.atan2(direction.x, direction.y) * R > 85 ? 3.5 : 0;
  expect(groundHides(at(0, 3), at(100, 2), R, rise)).toBe(false);
  expect(groundHides(at(0, 3), at(15, 2), R, hill)).toBe(false);
});
