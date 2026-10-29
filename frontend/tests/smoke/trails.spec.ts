import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import {
  pruneTrails,
  SAMPLE_S,
  sampleTrail,
  TRAIL_S,
  trailVertices,
  type Trails,
  writeTrails,
} from '../../src/lib/live/trails';

/* Fast-forward trails (no browser): the last 20 real seconds of each walker's drawn path, one merged set of segments. */

const SAMPLES = TRAIL_S / SAMPLE_S;
const buffers = (movers = 2) => ({
  positions: new Float32Array(trailVertices(movers) * 3),
  alphas: new Float32Array(trailVertices(movers)),
});
const write = (trails: Trails, gap = 1000, room = buffers()) => {
  const vertices = writeTrails(trails, room.positions, room.alphas, gap);
  return { vertices, ...room };
};
const xs = (positions: Float32Array, vertices: number) =>
  Array.from({ length: vertices }, (_, v) => positions[v * 3]);

test('a walker trails the spots it was drawn at, oldest to newest, fading back from it', () => {
  const trails: Trails = new Map();
  for (const x of [0, 10, 20])
    sampleTrail(trails, 'kenji', new Vector3(x, 1, 2));
  const { vertices, positions, alphas } = write(trails);
  expect(vertices).toBe(4);
  expect(xs(positions, vertices)).toEqual([0, 10, 10, 20]);
  expect(positions[1]).toBe(1);
  expect(positions[2]).toBe(2);
  expect(alphas[3]).toBeCloseTo(1, 6); // at the walker
  expect(alphas[0]).toBeCloseTo(1 - 2 / (SAMPLES - 1), 6);
  expect(alphas[1]).toBeCloseTo(alphas[2], 6); // one line, no step in its fade
});

test('standing still adds nothing to a trail', () => {
  const trails: Trails = new Map();
  sampleTrail(trails, 'kenji', new Vector3(0, 0, 0));
  sampleTrail(trails, 'kenji', new Vector3(0.01, 0, 0));
  expect(write(trails).vertices).toBe(0);
  sampleTrail(trails, 'kenji', new Vector3(1, 0, 0));
  expect(write(trails).vertices).toBe(2);
});

test('a trail keeps only its last 20 seconds', () => {
  expect(TRAIL_S).toBe(20); // 10 §4.2.3
  const trails: Trails = new Map();
  const spots = SAMPLES + 15;
  for (let i = 0; i < spots; i++)
    sampleTrail(trails, 'kenji', new Vector3(i, 0, 0));
  const { vertices, positions, alphas } = write(trails);
  expect(vertices).toBe((SAMPLES - 1) * 2);
  expect(positions[0]).toBe(spots - SAMPLES); // the oldest kept
  expect(positions[(vertices - 1) * 3]).toBe(spots - 1);
  expect(alphas[0]).toBeCloseTo(0, 6);
  expect(alphas[vertices - 1]).toBeCloseTo(1, 6);
});

test('a resync across the map is not drawn as a leg', () => {
  const trails: Trails = new Map();
  for (const x of [0, 10, 500, 510])
    sampleTrail(trails, 'kenji', new Vector3(x, 0, 0));
  const { vertices, positions } = write(trails, 100);
  expect(xs(positions, vertices)).toEqual([0, 10, 500, 510]);
});

test('every walker has its own trail, forgotten once it is no longer drawn', () => {
  const trails: Trails = new Map();
  for (const x of [0, 10]) {
    sampleTrail(trails, 'kenji', new Vector3(x, 0, 0));
    sampleTrail(trails, 'aiko', new Vector3(0, x, 0));
  }
  expect(write(trails).vertices).toBe(4);
  pruneTrails(trails, new Set(['aiko']));
  expect([...trails.keys()]).toEqual(['aiko']);
  expect(write(trails).vertices).toBe(2);
});

test('trails stop where the buffers end', () => {
  const trails: Trails = new Map();
  for (const id of ['a', 'b', 'c'])
    for (let i = 0; i < SAMPLES; i++)
      sampleTrail(trails, id, new Vector3(i, 0, 0));
  const room = buffers(2);
  expect(write(trails, 1000, room).vertices).toBe(trailVertices(2));
});
