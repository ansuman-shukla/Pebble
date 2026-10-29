import { expect, test } from '@playwright/test';
import { Group, Mesh, BoxGeometry, Vector3 } from 'three';

import {
  DOOR_SWING_S,
  doorwayOf,
  holdsDoor,
  Passers,
  swingToward,
} from '../../src/lib/world/doors';

/* Doors that open for passers-by (no browser): who holds a doorway, how a door swings, who counts as passing. */

/** A house front like the machiya's: leaves hung at x ±0.65, z 1.15, meeting in the middle. */
function house() {
  const model = new Group();
  for (const [name, hingeX, leafX] of [
    ['door-r', 0.65, -0.32],
    ['door-l', -0.65, 0.32],
  ] as const) {
    const node = new Group();
    node.name = name;
    node.position.set(hingeX, 0, 1.15);
    const leaf = new Mesh(new BoxGeometry(0.62, 2, 0.1));
    leaf.position.set(leafX, 1.1, 0.05);
    node.add(leaf);
    model.add(node);
  }
  model.updateMatrixWorld(true);
  return model;
}

test('a doorway lies between its leaves, each opening inwards towards its free edge', () => {
  const doorway = doorwayOf(house(), 'machiya-townhouse-8ef64e')!;
  expect(doorway.centre.toArray()).toEqual([0, 0, 1.15]);
  const right = doorway.leaves.find(({ node }) => node === 'door-r')!;
  const left = doorway.leaves.find(({ node }) => node === 'door-l')!;
  expect(right.openYaw).toBeCloseTo(-0.45 * Math.PI, 6);
  expect(left.openYaw).toBeCloseTo(0.45 * Math.PI, 6);
  // no leaves, or the gatehouse's (open for good): no doorway
  expect(doorwayOf(new Group(), 'kura-storehouse-5c9631')).toBeNull();
  expect(doorwayOf(house(), 'castle-gatehouse-4ed5c6')).toBeNull();
});

test('feet going in or out in the doorway or just in front hold it open, not inside or off to the side', () => {
  const doorway = doorwayOf(house(), 'machiya-townhouse-8ef64e')!;
  const inwards = new Vector3(0.1, 0, -0.3);
  const holds = (x: number, z: number, heading = inwards) =>
    holdsDoor(new Vector3(x, 0, z), heading, doorway);
  expect(holds(0, 1.15)).toBe(true);
  expect(holds(1.4, 3.6)).toBe(true);
  expect(holds(-1.4, 0.6)).toBe(true);
  expect(holds(0, 3.7)).toBe(false);
  expect(holds(1.6, 2)).toBe(false);
  expect(holds(-1.6, 2)).toBe(false);
  // inside the house: asleep by the door doesn't hold it open
  expect(holds(0, 0.5)).toBe(false);
  // coming out holds it; walking along the front, even right across the doorway, doesn't
  expect(holds(0, 2, new Vector3(-0.2, 0, 0.3))).toBe(true);
  expect(holds(0, 2, new Vector3(0.3, 0, 0.3))).toBe(true);
  expect(holds(0, 1.5, new Vector3(0.35, 0, 0.1))).toBe(false);
  expect(holds(0.2, 2, new Vector3(-0.35, 0, -0.2))).toBe(false);
});

test('a door swings fully open or shut in its swing time, and no further', () => {
  expect(DOOR_SWING_S).toBe(0.8);
  expect(swingToward(0, true, 0.4)).toBeCloseTo(0.5, 6);
  expect(swingToward(0.5, true, 0.4)).toBeCloseTo(1, 6);
  expect(swingToward(0.9, true, 0.4)).toBe(1);
  expect(swingToward(1, false, 0.2)).toBeCloseTo(0.75, 6);
  expect(swingToward(0.1, false, 0.4)).toBe(0);
  // a paused clock (0 s of motion) holds it where it is
  expect(swingToward(0.3, true, 0)).toBe(0.3);
});

test('people on the move pass; standing ones stop passing a moment after they stop', () => {
  const passers = new Passers();
  const walker = new Vector3(0, 0, 0);
  const worker = new Vector3(5, 0, 5);
  const people = new Map([
    ['walker', walker],
    ['worker', worker],
  ]);
  passers.update(people, 0);
  expect([...passers.passing.keys()]).toEqual([]);
  // the worker shuffles a few centimetres, again and again: still standing
  worker.set(5.05, 0, 5);
  passers.update(people, 0.02);
  worker.set(5, 0, 5.05);
  passers.update(people, 0.04);
  expect([...passers.passing.keys()]).toEqual([]);
  // one frame later the walker is 0.15 m on: passing at once
  walker.set(0.15, 0, 0);
  passers.update(people, 0.06);
  expect([...passers.passing.keys()]).toEqual(['walker']);
  walker.set(0.4, 0, 0);
  passers.update(people, 0.3);
  expect([...passers.passing.keys()]).toEqual(['walker']);
  expect(passers.passing.get('walker')).toBe(walker);
  // which way they went: their last step, kept after they stop
  expect(passers.steps.get('walker')!.toArray()).toEqual([0.25, 0, 0]);
  expect(passers.steps.has('worker')).toBe(false);
  walker.set(0.4, 0, -0.5);
  passers.update(people, 0.6);
  expect(passers.steps.get('walker')!.toArray()).toEqual([0, 0, -0.5]);
  // the walker stops: still passing for 1.5 s, then not
  passers.update(people, 2);
  expect([...passers.passing.keys()]).toEqual(['walker']);
  expect(passers.steps.get('walker')!.toArray()).toEqual([0, 0, -0.5]);
  passers.update(people, 2.3);
  expect([...passers.passing.keys()]).toEqual([]);
  // someone who leaves the page is forgotten; back again, they start standing
  people.delete('walker');
  passers.update(people, 2.6);
  expect(passers.steps.has('walker')).toBe(false);
  walker.set(9, 0, 9);
  people.set('walker', walker);
  passers.update(people, 2.9);
  expect([...passers.passing.keys()]).toEqual([]);
});
