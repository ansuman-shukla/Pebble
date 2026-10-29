/*
 * Doors. Polyfork rigs door leaves as named nodes pivoting on their hinge. The castle gatehouse's stand open in
 * the walkable world: the colliders JSON is built with the doors shut, so the same swing is applied to the leaf
 * parts. Every other pair of leaves (`door-l`, `door-r`, 10 §5.5) is drawn shut and swings open while someone
 * on the move is in its doorway or just in front of it (passing, going in, coming home); they stay solid for the
 * walker.
 */
import { Box3, Matrix4, type Object3D, Vector3 } from 'three';

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

/** Leaves that swing open for passers-by. */
const SWING_LEAVES = ['door-l', 'door-r'];
/** How far a swinging leaf opens (radians): inwards, short of the wall. */
const SWING = 0.45 * Math.PI;
/** A doorway holds its doors open for feet within this half width of its centre ... */
const DOORWAY_HALF_WIDTH = 1.5;
/** ... from just inside the threshold (people inside don't hold it) to this far in front of it (metres). */
const DOORWAY_INSIDE = 0.6;
const DOORWAY_FRONT = 2.5;
/** Seconds a door takes to swing fully open or shut at natural speed. */
export const DOOR_SWING_S = 0.8;

/** One leaf that swings: its hinge (the node's rest matrix in model space) and which way it opens. */
export interface DoorSwing {
  node: string;
  hinge: Matrix4;
  /** Turn about the hinge's up that opens the leaf inwards (radians). */
  openYaw: number;
}

/** The model's doorway: between its swinging leaves' hinges, in model space (models face +z). */
export interface Doorway {
  leaves: DoorSwing[];
  centre: Vector3;
}

const box = new Box3();
const leafCentre = new Vector3();

/**
 * The swinging leaves of a model (a posed copy, matrices up to date) and their doorway, or null when it has none
 * (the gatehouse's leaves stand open for good). A leaf opens inwards (-z): towards its free edge's side of the hinge.
 */
export function doorwayOf(model: Object3D, id: string): Doorway | null {
  if (OPEN_DOORS[id]) return null;
  const toModel = model.matrixWorld.clone().invert();
  const leaves: DoorSwing[] = [];
  for (const name of SWING_LEAVES) {
    const node = model.getObjectByName(name);
    if (!node) continue;
    const hinge = toModel.clone().multiply(node.matrixWorld);
    box.setFromObject(node).getCenter(leafCentre).applyMatrix4(toModel);
    leafCentre.applyMatrix4(hinge.clone().invert());
    leaves.push({
      node: name,
      hinge,
      openYaw: Math.sign(leafCentre.x) * SWING,
    });
  }
  if (leaves.length === 0) return null;
  const centre = new Vector3();
  for (const leaf of leaves)
    centre.add(new Vector3().setFromMatrixPosition(leaf.hinge));
  return { leaves, centre: centre.divideScalar(leaves.length) };
}

const turn = new Matrix4();
const unhinge = new Matrix4();

/** The move of a leaf baked at rest when it is open by `amount` (0 shut, 1 open): a turn about its hinge. */
export function leafMove(leaf: DoorSwing, amount: number, target: Matrix4) {
  turn.makeRotationY(amount * leaf.openYaw);
  unhinge.copy(leaf.hinge).invert();
  return target.multiplyMatrices(leaf.hinge, turn).multiply(unhinge);
}

/** Whether feet at `local` (model space of the building) hold its doors open. */
export function holdsDoor(local: Vector3, doorway: Doorway) {
  const ahead = local.z - doorway.centre.z;
  return (
    Math.abs(local.x - doorway.centre.x) <= DOORWAY_HALF_WIDTH &&
    ahead >= -DOORWAY_INSIDE &&
    ahead <= DOORWAY_FRONT
  );
}

/** A door's opening after `seconds` of motion (already × visualRate) towards open or shut. */
export function swingToward(amount: number, open: boolean, seconds: number) {
  const step = seconds / DOOR_SWING_S;
  return open ? Math.min(1, amount + step) : Math.max(0, amount - step);
}

/** Feet that moved this far (metres) ... */
const PASSING_STEP = 0.1;
/** ... since the last look, this many seconds ago or more, are passing; they count this long after they stop. */
const PASSING_LOOK = 0.25;
const PASSING_LINGER = 1.5;

/**
 * Who is passing by: doors open for people on the move (walking past, going in or coming out), not for someone
 * standing or working in front of them. `update` with every drawn person's feet; repeated calls within
 * PASSING_LOOK seconds change nothing.
 */
export class Passers {
  private readonly last = new Map<string, Vector3>();
  private readonly movedAt = new Map<string, number>();
  private lookedAt = -Infinity;
  readonly passing = new Map<string, Vector3>();

  update(people: ReadonlyMap<string, Vector3>, now: number) {
    if (now - this.lookedAt < PASSING_LOOK && now >= this.lookedAt) return;
    this.lookedAt = now;
    this.passing.clear();
    for (const [id, feet] of people) {
      const last = this.last.get(id);
      if (!last) this.last.set(id, feet.clone());
      else if (last.distanceTo(feet) > PASSING_STEP) {
        last.copy(feet);
        this.movedAt.set(id, now);
      }
      if (now - (this.movedAt.get(id) ?? -Infinity) <= PASSING_LINGER)
        this.passing.set(id, feet);
    }
    for (const id of this.last.keys())
      if (!people.has(id)) {
        this.last.delete(id);
        this.movedAt.delete(id);
      }
  }
}
