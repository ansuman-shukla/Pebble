import { expect, test } from '@playwright/test';
import { BufferAttribute, Vector3 } from 'three';

import {
  pruneTrails,
  sampleTrail,
  TRAIL_S,
  trailStep,
  trailVertices,
  type Trails,
  uploadTrails,
  writeTrails,
} from '../../src/lib/live/trails';

/* Fast-forward trails (no browser): the last 20 real seconds of each walker's drawn path, laid down by drawn distance
 * and ending at the walker, one merged set of segments. */

const buffers = (movers = 2) => ({
  positions: new Float32Array(trailVertices(movers) * 3),
  alphas: new Float32Array(trailVertices(movers)),
});
const write = (trails: Trails, now: number, gap = 1000, room = buffers()) => {
  const vertices = writeTrails(trails, room.positions, room.alphas, gap, now);
  return { vertices, ...room };
};
const xs = (positions: Float32Array, vertices: number) =>
  Array.from({ length: vertices }, (_, v) => positions[v * 3]);
/** Moves `id` to `x` (metres east) at real second `now`, laying spots `step` metres apart. */
const walk = (trails: Trails, id: string, x: number, now: number, step = 1) =>
  sampleTrail(trails, id, new Vector3(x, 1, 2), now, step);

test('a walker trails the spots it was drawn at, oldest to newest, fading with their age', () => {
  const trails: Trails = new Map();
  walk(trails, 'kenji', 0, 0);
  walk(trails, 'kenji', 10, 5);
  walk(trails, 'kenji', 20, 10);
  const { vertices, positions, alphas } = write(trails, 10);
  expect(vertices).toBe(4);
  expect(xs(positions, vertices)).toEqual([0, 10, 10, 20]);
  expect(positions[1]).toBe(1);
  expect(positions[2]).toBe(2);
  expect(alphas[3]).toBeCloseTo(1, 6); // at the walker
  expect(alphas[0]).toBeCloseTo(1 - 10 / TRAIL_S, 6);
  expect(alphas[1]).toBeCloseTo(1 - 5 / TRAIL_S, 6);
  expect(alphas[1]).toBeCloseTo(alphas[2], 6); // one line, no step in its fade
});

test('the trail always ends where the walker is drawn now, between its spots', () => {
  const trails: Trails = new Map();
  walk(trails, 'kenji', 0, 0, 10);
  walk(trails, 'kenji', 4, 0.1, 10); // short of the next spot: the tip moves on
  let drawn = write(trails, 0.1);
  expect(xs(drawn.positions, drawn.vertices)).toEqual([0, 4]);
  expect(drawn.alphas[1]).toBe(1);
  walk(trails, 'kenji', 7, 0.2, 10);
  drawn = write(trails, 0.2);
  expect(xs(drawn.positions, drawn.vertices)).toEqual([0, 7]);
  walk(trails, 'kenji', 12, 0.3, 10); // 10 m on: a spot is laid there
  walk(trails, 'kenji', 15, 0.4, 10);
  drawn = write(trails, 0.4);
  expect(xs(drawn.positions, drawn.vertices)).toEqual([0, 12, 12, 15]);
});

test('spots are laid by drawn distance, not time: standing adds nothing, a fast walker adds one per step', () => {
  const trails: Trails = new Map();
  walk(trails, 'kenji', 0, 0);
  for (let frame = 1; frame <= 60; frame++)
    walk(trails, 'kenji', 0.001 * frame, frame / 60); // standing a second
  expect(write(trails, 1).vertices).toBe(2); // only the leg to the tip
  for (let frame = 1; frame <= 10; frame++)
    walk(trails, 'kenji', 3 * frame, 1 + frame / 60); // 3 m a frame
  const { vertices, positions } = write(trails, 2);
  expect(xs(positions, vertices)).toEqual([
    0, 3, 3, 6, 6, 9, 9, 12, 12, 15, 15, 18, 18, 21, 21, 24, 24, 27, 27, 30,
  ]);
});

test('spots lie far enough apart that 20 seconds of walking fit, however fast the clock', () => {
  expect(TRAIL_S).toBe(20); // 10 §4.2.3
  expect(trailStep(11)).toBeCloseTo(0.77, 2);
  expect(trailStep(60)).toBeCloseTo(4.21, 2);
  expect(trailStep(600)).toBeCloseTo(42.1, 1);
  expect(trailStep(1)).toBe(0.5); // never closer than half a metre
  // walking at ×600 for 20 s lays a spot every step: every one of them is still kept
  const trails: Trails = new Map();
  const step = trailStep(600);
  const spots = Math.round(16_800 / step);
  for (let k = 0; k <= spots; k++)
    walk(trails, 'kenji', k * step * 1.001, (k * 20) / spots, step);
  const { vertices, positions } = write(trails, 20);
  expect(vertices).toBe(spots * 2);
  expect(positions[0]).toBe(0); // from where it was 20 s ago...
  expect(positions[(vertices - 1) * 3]).toBeCloseTo(16_800 * 1.001, -1); // ...to where it is now
});

test('a trail keeps only its last 20 seconds', () => {
  const trails: Trails = new Map();
  for (let second = 0; second <= 30; second++)
    walk(trails, 'kenji', second, second);
  const { vertices, positions, alphas } = write(trails, 30);
  expect(positions[0]).toBe(10); // the oldest kept
  expect(positions[(vertices - 1) * 3]).toBe(30);
  expect(alphas[0]).toBeCloseTo(0, 6);
  expect(alphas[vertices - 1]).toBeCloseTo(1, 6);
  // standing still past 20 s: nothing left behind it
  for (let second = 31; second <= 51; second++)
    walk(trails, 'kenji', 30, second);
  expect(write(trails, 51).vertices).toBe(0);
});

test('a resync across the map is not drawn as a leg, nor is one to the tip', () => {
  const trails: Trails = new Map();
  for (const [x, now] of [
    [0, 0],
    [10, 1],
    [500, 2],
    [510, 3],
  ])
    walk(trails, 'kenji', x, now);
  expect(xs(write(trails, 3, 100).positions, 4)).toEqual([0, 10, 500, 510]);
  walk(trails, 'kenji', 510.5, 3.1); // the tip
  walk(trails, 'kenji', 900, 3.2, 1000); // faded across, short of a spot
  expect(write(trails, 3.2, 100).vertices).toBe(4);
});

test('every walker has its own trail, forgotten once it is no longer drawn', () => {
  const trails: Trails = new Map();
  for (const x of [0, 10]) {
    walk(trails, 'kenji', x, x);
    sampleTrail(trails, 'aiko', new Vector3(0, x, 0), x, 1);
  }
  expect(write(trails, 10).vertices).toBe(4);
  pruneTrails(trails, new Set(['aiko']));
  expect([...trails.keys()]).toEqual(['aiko']);
  expect(write(trails, 10).vertices).toBe(2);
});

test('trails stop where the buffers end', () => {
  const trails: Trails = new Map();
  for (const id of ['a', 'b', 'c'])
    for (let i = 0; i < 1000; i++) walk(trails, id, i, i / 100);
  const room = buffers(2);
  expect(write(trails, 10, 1000, room).vertices).toBe(trailVertices(2));
});

test('only the written vertices are uploaded, and nothing at all when no trail is drawn', () => {
  const positions = new BufferAttribute(new Float32Array(30), 3);
  const colors = new BufferAttribute(new Float32Array(40), 4);
  uploadTrails([positions, colors], 0); // an empty range would upload the whole buffer
  for (const attribute of [positions, colors]) {
    expect(attribute.version).toBe(0);
    expect(attribute.updateRanges).toEqual([]);
  }
  uploadTrails([positions, colors], 4);
  expect(positions.version).toBe(1);
  expect(positions.updateRanges).toEqual([{ start: 0, count: 12 }]);
  expect(colors.updateRanges).toEqual([{ start: 0, count: 16 }]);
  uploadTrails([positions, colors], 2);
  expect(positions.version).toBe(2);
  expect(positions.updateRanges).toEqual([{ start: 0, count: 6 }]);
  uploadTrails([positions, colors], 0); // a pending upload keeps its range
  expect(positions.version).toBe(2);
  expect(positions.updateRanges).toEqual([{ start: 0, count: 6 }]);
});

test('a trail runs through the route corners walked between frames, not straight across them', () => {
  const trails: Trails = new Map();
  const at = (x: number, z: number) => new Vector3(x, 1, z);
  const step = trailStep(600); // 42 m: a frame at ×600 walks round a corner and on
  sampleTrail(trails, 'kenji', at(0, 0), 0, step);
  // round the moat's corner: east 30 m, then north 30 m, all in one frame
  sampleTrail(trails, 'kenji', at(30, 30), 0.1, step, [at(30, 0)]);
  const { vertices, positions } = write(trails, 0.1);
  const points = Array.from({ length: vertices }, (_, v) => [
    positions[v * 3],
    positions[v * 3 + 2],
  ]);
  expect(points).toEqual([
    [0, 0],
    [30, 0],
    [30, 0],
    [30, 30],
  ]);
  // the corner stays in the trail after the walker walks on, before the next spot
  sampleTrail(trails, 'kenji', at(30, 40), 0.2, step);
  expect(xs(write(trails, 0.2).positions, 4)).toEqual([0, 30, 30, 30]);
});

test('a walker that faded across (a resync) starts a new line where it came back, however short the hop', () => {
  const trails: Trails = new Map();
  walk(trails, 'kenji', 0, 0);
  walk(trails, 'kenji', 10, 1);
  sampleTrail(trails, 'kenji', new Vector3(20, 1, 2), 1.1, 1, [], true);
  walk(trails, 'kenji', 30, 2);
  // 0-10 walked, 10-20 faded across (not drawn), 20-30 walked
  expect(xs(write(trails, 2).positions, 4)).toEqual([0, 10, 20, 30]);
  expect(write(trails, 2).vertices).toBe(4);
  // a jump through a corner breaks before the corner, not after it
  sampleTrail(
    trails,
    'kenji',
    new Vector3(50, 1, 2),
    2.1,
    1,
    [new Vector3(40, 1, 2)],
    true,
  );
  const { vertices, positions } = write(trails, 2.1);
  expect(xs(positions, vertices)).toEqual([0, 10, 20, 30, 40, 50]);
});
