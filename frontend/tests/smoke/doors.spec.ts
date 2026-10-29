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

test('feet in the doorway or just in front hold it open, not inside or off to the side', () => {
  const doorway = doorwayOf(house(), 'machiya-townhouse-8ef64e')!;
  const holds = (x: number, z: number) =>
    holdsDoor(new Vector3(x, 0, z), doorway);
  expect(holds(0, 1.15)).toBe(true);
  expect(holds(1.4, 3.6)).toBe(true);
  expect(holds(-1.4, 0.6)).toBe(true);
  expect(holds(0, 3.7)).toBe(false);
  expect(holds(1.6, 2)).toBe(false);
  expect(holds(-1.6, 2)).toBe(false);
  // inside the house: asleep by the door doesn't hold it open
  expect(holds(0, 0.5)).toBe(false);
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
  walker.set(0.4, 0, 0);
  worker.set(5.05, 0, 5);
  // looks within 0.25 s change nothing
  passers.update(people, 0.1);
  expect([...passers.passing.keys()]).toEqual([]);
  passers.update(people, 0.3);
  expect([...passers.passing.keys()]).toEqual(['walker']);
  expect(passers.passing.get('walker')).toBe(walker);
  // the walker stops: still passing for 1.5 s, then not
  passers.update(people, 1.7);
  expect([...passers.passing.keys()]).toEqual(['walker']);
  passers.update(people, 2);
  expect([...passers.passing.keys()]).toEqual([]);
  // someone who leaves the page is forgotten; back again, they start standing
  people.delete('walker');
  passers.update(people, 2.3);
  walker.set(9, 0, 9);
  people.set('walker', walker);
  passers.update(people, 2.6);
  expect([...passers.passing.keys()]).toEqual([]);
});
