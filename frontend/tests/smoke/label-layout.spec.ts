import { expect, test } from '@playwright/test';

import { type LabelBox, stackLabels } from '../../src/lib/world/label-layout';

/* Label stacking (no browser): nearer labels keep their spot, farther ones move up, speech bubbles end on top. */

const box = (change: Partial<LabelBox>): LabelBox => ({
  x: 100,
  bottom: 200,
  width: 80,
  height: 20,
  distance: 10,
  kind: 'name',
  ...change,
});

test('labels that do not overlap stay where they are', () => {
  const apart = [
    box({ x: 100 }),
    box({ x: 181, distance: 20 }),
    box({ x: 140, bottom: 179, distance: 30 }),
  ];
  expect(stackLabels(apart)).toEqual([200, 200, 179]);
});

test('the farther of two overlapping labels moves up above the nearer one', () => {
  expect(
    stackLabels([box({ distance: 30 }), box({ x: 130, bottom: 205 })]),
  ).toEqual([183, 205]);
});

test('labels pile up nearest first', () => {
  expect(
    stackLabels([
      box({ x: 120, distance: 25 }),
      box({ x: 90, bottom: 210, distance: 5 }),
      box({ x: 105, bottom: 195, distance: 15 }),
    ]),
  ).toEqual([166, 210, 188]);
});

test('a speech bubble clears the name tags even when it is nearer', () => {
  expect(
    stackLabels([
      box({ kind: 'speech', height: 40, distance: 2 }),
      box({ x: 110, distance: 20 }),
    ]),
  ).toEqual([178, 200]);
});
