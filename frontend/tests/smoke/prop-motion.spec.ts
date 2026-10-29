import { expect, test } from '@playwright/test';
import {
  AnimationClip,
  Group,
  Matrix4,
  Mesh,
  Quaternion,
  QuaternionKeyframeTrack,
  Vector3,
} from 'three';

import {
  advanceProps,
  bakeClip,
  CLIP_BUDGET,
  CLIP_REACH,
  ClipBudget,
  clipPhase,
  nearestWithin,
  PartMoves,
  propWorld,
  sampleClip,
} from '../../src/lib/world/prop-motion';
import { windUniforms } from '../../src/lib/world/wind';

/* Baked loops, the clip budget and the prop clock (no browser): what makes the Polyfork props move (10 §5.3). */

const Y = new Vector3(0, 1, 0);

/** A model with a wheel (hub 2 m up, 1 m out on x) turning once about z in 4 s, and a still frame. */
function wheelModel() {
  const root = new Group();
  const frame = new Mesh();
  frame.name = 'frame';
  const wheel = new Group();
  wheel.name = 'wheel';
  wheel.position.set(1, 2, 0);
  const rim = new Mesh();
  rim.name = 'rim';
  rim.position.set(0, 1, 0);
  wheel.add(rim);
  root.add(frame, wheel);
  const turns = [0, 1, 2, 3, 4].map((step) =>
    new Quaternion()
      .setFromAxisAngle(new Vector3(0, 0, 1), (step * Math.PI) / 2)
      .toArray(),
  );
  const clip = new AnimationClip('tick', 4, [
    new QuaternionKeyframeTrack(
      'wheel.quaternion',
      [0, 1, 2, 3, 4],
      turns.flat(),
    ),
  ]);
  return { root, rim, frame, clip };
}

/** Where the rim's centre (at rest: (1, 3, 0)) is drawn after `move`. */
const rimAt = (move: Matrix4) => new Vector3(1, 3, 0).applyMatrix4(move);

test('a baked loop moves a part from its rest pose as the clip does', () => {
  const { root, rim, clip } = wheelModel();
  const track = bakeClip(root, clip, [rim]);
  expect(track.duration).toBe(4);
  expect(track.samples).toBe(96);
  const move = new Matrix4();
  // at rest, a quarter turn (about the hub at (1, 2)), half a turn
  expect(
    rimAt(sampleClip(track, 0, 0, move)).distanceTo(new Vector3(1, 3, 0)),
  ).toBeLessThan(1e-5);
  expect(
    rimAt(sampleClip(track, 0, 1, move)).distanceTo(new Vector3(0, 2, 0)),
  ).toBeLessThan(1e-5);
  expect(
    rimAt(sampleClip(track, 0, 2, move)).distanceTo(new Vector3(1, 1, 0)),
  ).toBeLessThan(1e-5);
  // between samples it blends along the arc (radius kept), and the loop wraps both ways
  const between = rimAt(sampleClip(track, 0, 0.51, move));
  expect(between.distanceTo(new Vector3(1, 2, 0))).toBeCloseTo(1, 2);
  expect(between.x).toBeCloseTo(1 - Math.sin(0.51 * (Math.PI / 2)), 2);
  expect(between.y).toBeCloseTo(2 + Math.cos(0.51 * (Math.PI / 2)), 2);
  expect(
    rimAt(sampleClip(track, 0, 5, move)).distanceTo(new Vector3(0, 2, 0)),
  ).toBeLessThan(1e-5);
  expect(
    rimAt(sampleClip(track, 0, -3, move)).distanceTo(new Vector3(0, 2, 0)),
  ).toBeLessThan(1e-5);
});

test('a still part baked with a loop never moves', () => {
  const { root, rim, frame, clip } = wheelModel();
  const track = bakeClip(root, clip, [rim, frame]);
  const move = new Matrix4();
  for (const time of [0, 0.7, 1.9, 3.3])
    expect(sampleClip(track, 1, time, move).equals(new Matrix4())).toBe(true);
});

test('each instance starts its loop somewhere of its own, the same every time', () => {
  const phases = ['pine-1', 'pine-2', 'pine-3', 'water-wheel'].map((id) =>
    clipPhase(id, 13.6),
  );
  for (const phase of phases) {
    expect(phase).toBeGreaterThanOrEqual(0);
    expect(phase).toBeLessThan(13.6);
  }
  expect(new Set(phases).size).toBe(4);
  expect(clipPhase('pine-1', 13.6)).toBe(phases[0]);
});

test('the nearest instances within reach play, nearest first', () => {
  expect(nearestWithin([50, 130, 10, 119, 30], 120, 3)).toEqual([2, 4, 0]);
  expect(nearestWithin([50, 130, 10, 119.9], 120, 9)).toEqual([2, 0, 3]);
  expect(nearestWithin([120, 121], 120, 9)).toEqual([]);
});

test('kinds share one clip budget: the nearest 64 within 120 m across them', () => {
  expect([CLIP_REACH, CLIP_BUDGET]).toEqual([120, 64]);
  const budget = new ClipBudget();
  const fence = Float32Array.from({ length: 100 }, (_, i) => 20 + i);
  const trees = Float32Array.from([5, 150, 60.5, 119]);
  budget.offer('fence', fence);
  budget.offer('trees', trees);
  const fencePicks = budget.picked('fence', 0);
  const treePicks = budget.picked('trees', 0);
  expect(fencePicks.length + treePicks.length).toBe(64);
  // the 64th nearest is the fence post at 82 m: the tree at 60.5 m plays, the ones at 119 and 150 m don't
  expect(treePicks).toEqual([0, 2]);
  expect(Math.max(...fencePicks.map((i) => fence[i]))).toBe(81);
  // picks hold until REPICK has passed, then follow the new offers
  budget.offer('trees', Float32Array.from([200, 200, 200, 1]));
  expect(budget.picked('trees', 0.1)).toEqual([0, 2]);
  expect(budget.picked('trees', 0.3)).toEqual([3]);
  budget.forget('trees');
  expect(budget.picked('trees', 1)).toEqual([]);
  expect(budget.picked('fence', 1)).toHaveLength(64);
});

test('the prop clock plays clips up to ×10 and wind up to ×3, once a frame, nothing while paused', () => {
  const start = { clip: propWorld.clipTime, wind: propWorld.windTime };
  propWorld.rate = 1;
  advanceProps(100);
  advanceProps(100.05);
  advanceProps(100.05);
  expect(propWorld.clipTime - start.clip).toBeCloseTo(0.05, 6);
  propWorld.rate = 60;
  const minutes = propWorld.minutes;
  advanceProps(100.1);
  expect(propWorld.clipTime - start.clip).toBeCloseTo(0.55, 6);
  expect(propWorld.windTime - start.wind).toBeCloseTo(0.2, 6);
  expect(propWorld.minutes - minutes).toBeCloseTo(0.05, 6);
  expect(windUniforms.windTime.value).toBe(propWorld.windTime);
  // a hidden tab's long frame counts as 0.1 s, a clock going back as nothing, a paused clock stills everything
  advanceProps(130);
  expect(propWorld.clipTime - start.clip).toBeCloseTo(1.55, 6);
  advanceProps(120);
  expect(propWorld.clipTime - start.clip).toBeCloseTo(1.55, 6);
  propWorld.rate = 0;
  advanceProps(120.05);
  expect(propWorld.clipTime - start.clip).toBeCloseTo(1.55, 6);
  expect(propWorld.windTime - start.wind).toBeCloseTo(0.5, 6);
  propWorld.rate = 1;
});

test('part moves keep a matrix per instance and moving part, the identity until set', () => {
  const moves = new PartMoves(3, 5);
  expect([moves.texture.image.width, moves.texture.image.height]).toEqual([
    12, 5,
  ]);
  const move = new Matrix4().compose(
    new Vector3(1, 2, 3),
    new Quaternion().setFromAxisAngle(Y, 0.4),
    new Vector3(1, 1, 1),
  );
  const version = moves.texture.version;
  moves.flush();
  expect(moves.texture.version).toBe(version);
  moves.set(4, 2, move);
  const stored = moves.get(4, 2, new Matrix4()).elements;
  move.elements.forEach((value, i) => expect(stored[i]).toBeCloseTo(value, 6));
  for (const [instance, part] of [
    [4, 1],
    [3, 2],
    [0, 0],
  ])
    expect(moves.get(instance, part, new Matrix4()).equals(new Matrix4())).toBe(
      true,
    );
  // texel (part × 4 + column, instance) holds the matrix's column, as the shader reads it
  const texels = moves.texture.image.data as Float32Array;
  const texel = (x: number, y: number) => [
    ...texels.slice((y * 12 + x) * 4, (y * 12 + x) * 4 + 4),
  ];
  expect(texel(11, 4)).toEqual([1, 2, 3, 1]);
  moves.flush();
  expect(moves.texture.version).toBe(version + 1);
  expect(moves.chunk().uniforms.partMoves.value).toBe(moves.texture);
});
