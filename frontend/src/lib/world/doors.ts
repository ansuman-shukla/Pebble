/*
 * Doors that stand open in the walkable world. Polyfork rigs door leaves as named nodes pivoting on their
 * hinge; the colliders JSON is built with the doors shut, so the same swing is applied to the leaf parts.
 */
import type { Object3D } from 'three';

export interface DoorLeaf {
  /** Node name in the GLB; its origin is the hinge. */
  node: string;
  /** Hinge position in model space (x, z). */
  hinge: [number, number];
  /** x-range the shut leaf covers in model space. */
  span: [number, number];
  /** Swing around y (radians, three.js convention) that opens the leaf. */
  openYaw: number;
}

const OPEN_DOORS: Record<string, DoorLeaf[]> = {
  // both leaves swing inward (towards -z, the town face) back against the passage walls
  'castle-gatehouse-4ed5c6': [
    {
      node: 'door-r',
      hinge: [1.05, 0.6],
      span: [0, 1.05],
      openYaw: -Math.PI / 2,
    },
    {
      node: 'door-l',
      hinge: [-1.05, 0.6],
      span: [-1.05, 0],
      openYaw: Math.PI / 2,
    },
  ],
};

const LEAF_TOLERANCE = 0.1;

function isLeafPart(part: number[][], leaf: DoorLeaf) {
  const [minX, maxX] = leaf.span;
  return part.every(
    ([x, , z]) =>
      x >= minX - LEAF_TOLERANCE &&
      x <= maxX + LEAF_TOLERANCE &&
      Math.abs(z - leaf.hinge[1]) <= LEAF_TOLERANCE,
  );
}

/** Collider parts with the door leaves swung open (parts are [x, y, z] point lists in model space). */
export function openDoorParts<T extends number[][]>(id: string, parts: T[]) {
  const leaves = OPEN_DOORS[id];
  if (!leaves) return parts;
  return parts.map((part) => {
    const leaf = leaves.find((candidate) => isLeafPart(part, candidate));
    if (!leaf) return part;
    const [hingeX, hingeZ] = leaf.hinge;
    const cos = Math.cos(leaf.openYaw);
    const sin = Math.sin(leaf.openYaw);
    return part.map(([x, y, z]) => {
      const dx = x - hingeX;
      const dz = z - hingeZ;
      return [hingeX + dx * cos + dz * sin, y, hingeZ - dx * sin + dz * cos];
    }) as T;
  });
}

/** Swings the door leaves of a loaded model open (mutates the given copy). */
export function openDoors(model: Object3D, id: string) {
  for (const leaf of OPEN_DOORS[id] ?? []) {
    const node = model.getObjectByName(leaf.node);
    if (!node) throw new Error(`${id} has no door node ${leaf.node}`);
    node.rotation.y = leaf.openYaw;
  }
}
