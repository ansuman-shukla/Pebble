import {
  InstancedMesh,
  type Material,
  Matrix4,
  Quaternion,
  Vector3,
} from 'three';

import {
  type KindModel,
  type MovingPart,
  movingLooks,
} from '@/components/world/kind-parts';
import type { TownPlacement } from '@/lib/client/types.gen';
import {
  type DoorSwing,
  holdsDoor,
  leafMove,
  Passers,
  swingToward,
} from '@/lib/world/doors';
import {
  ClipBudget,
  clipPhase,
  PartMoves,
  propViews,
  propWorld,
  sampleClip,
} from '@/lib/world/prop-motion';
import { visualRate } from '@/lib/world/visual-rate';

/*
 * The instances of one kind of placement and what moves their parts (10 §5.3), through a PartMoves texture per
 * part: the model's loop plays for the nearest instances (the mill wheel always turns; plants, cloth and ropes
 * sway on wind time, at most ×3, mechanisms, flames and water on clip time), door leaves swing open while
 * someone goes in or out through the doorway, and parts hide while they shouldn't show: a cold fire's `flame`
 * and `fuel`, and dressing a stream turned off (`dressPart`, prop-motion.ts).
 */

/** Kinds lying flat on the ground: their shadows would be invisible, so they skip the shadow pass. */
const FLAT_KINDS = new Set(['rice_paddy', 'paving_tile']);
/** Kinds whose loop plays wherever the camera is, outside the clip budget. */
const ALWAYS_MOVING = new Set(['water_wheel']);
/** Kinds whose loop is a mechanism, a flame or water: it plays on clip time. Every other loop is wind sway. */
const CLIP_LOOPS = new Set([
  'water_wheel',
  'well',
  'bell_tower',
  'reed_torch',
  'fumarole',
  'geyser',
  'hot_spring_pool',
  'stone_basin',
]);
/** Sub-meshes hidden while the fire they stand at is out. */
const FIRE_PARTS = new Set(['flame', 'fuel']);
/** A live fire belongs to the instance within this many metres of its flame. */
const FIRE_MATCH = 2.5;
/** Doors look for people within this many metres before testing the doorway. */
const DOOR_NEAR = 6;
/** Seconds between looks for people at the doors and at what parts should show. */
const DOOR_LOOK = 0.1;
const PART_LOOK = 0.25;
/** Bounding spheres of parts that move grow by this much (metres), so a swung leaf isn't culled. */
const MOVE_MARGIN = 1;

/** One budget for every kind on the page, and one look at who passes the doors. */
const budget = new ClipBudget();
const passers = new Passers();
const HIDDEN = new Matrix4().makeScale(0, 0, 0);
const REST = new Matrix4();
const move = new Matrix4();
const feet = new Vector3();
const heading = new Vector3();
const turn = new Quaternion();
const unused = new Vector3();

const coldFireAt = (at: Vector3) => {
  for (const fire of propWorld.fires.values())
    if (fire.position.distanceTo(at) < FIRE_MATCH) return !fire.lit;
  return false;
};

/** A moving sub-mesh of the kind: where its moves go and what moves it. */
interface Slot extends MovingPart {
  moves: PartMoves;
  part: number;
  fire: boolean;
}

/** The instances of one kind and what moves them; `frame` runs every frame. */
export class LivingKind {
  readonly meshes: InstancedMesh[];
  /** One per part that has moving sub-meshes, in part order. */
  readonly moves: PartMoves[] = [];
  private readonly ownMaterials: Material[] = [];
  private readonly slots: Slot[] = [];
  private readonly at: Vector3[];
  private readonly distances: Float32Array;
  private readonly phases: number[];
  private readonly doorAmounts: Float32Array;
  private readonly doorOpen: Uint8Array;
  /** Per instance and slot: 1 while the part is hidden. */
  private readonly hidden: Uint8Array;
  private readonly hasFire: boolean;
  private readonly toLocal: Matrix4[] = [];
  /** The slots of the swinging door leaves and how each swings. */
  private readonly leaves: { slot: Slot; leaf: DoorSwing }[] = [];
  private played: readonly number[] = [];
  private lookedAtDoors = -Infinity;
  private lookedAtParts = -Infinity;

  constructor(
    private readonly key: string,
    private readonly kind: string,
    private readonly model: KindModel,
    private readonly placements: readonly Pick<TownPlacement, 'id'>[],
    placed: Matrix4[],
  ) {
    const count = placed.length;
    this.at = placed.map((matrix) =>
      new Vector3().setFromMatrixPosition(matrix),
    );
    this.distances = new Float32Array(count);
    this.phases = model.clip
      ? placements.map((placement) =>
          clipPhase(placement.id, model.clip!.duration),
        )
      : [];
    this.doorAmounts = new Float32Array(count);
    this.doorOpen = new Uint8Array(count);
    if (model.doorway)
      this.toLocal = placed.map((matrix) => matrix.clone().invert());
    this.meshes = model.parts.map((part) => {
      let { material, depthMaterial } = part;
      if (part.moving.length > 0) {
        const moves = new PartMoves(part.moving.length, count);
        ({ material, depthMaterial } = movingLooks(part, moves));
        this.moves.push(moves);
        this.ownMaterials.push(material, depthMaterial!);
        part.moving.forEach((moving, index) =>
          this.slots.push({
            ...moving,
            moves,
            part: index,
            fire: FIRE_PARTS.has(moving.node),
          }),
        );
      }
      const instances = new InstancedMesh(part.geometry, material, count);
      instances.name = `${kind}:${part.moving.map(({ node }) => node).join(',') || 'still'}`;
      placed.forEach((matrix, index) => instances.setMatrixAt(index, matrix));
      if (depthMaterial) instances.customDepthMaterial = depthMaterial;
      instances.computeBoundingSphere();
      if (part.moving.length > 0 && instances.boundingSphere)
        instances.boundingSphere.radius += MOVE_MARGIN;
      instances.castShadow = !FLAT_KINDS.has(kind);
      instances.receiveShadow = true;
      return instances;
    });
    this.hidden = new Uint8Array(count * this.slots.length);
    for (const slot of this.slots) {
      const leaf = model.doorway?.leaves.find(({ node }) => node === slot.node);
      if (leaf) this.leaves.push({ slot, leaf });
    }
    this.hasFire = this.slots.some((slot) => slot.fire);
  }

  frame(camera: Vector3, now: number, delta: number) {
    if (this.slots.length === 0) return;
    this.showParts(now);
    this.playLoop(camera, now);
    if (this.model.doorway)
      this.swingDoors(now, delta * visualRate(propWorld.rate));
    for (const moves of this.moves) moves.flush();
  }

  dispose() {
    budget.forget(this.key);
    propViews.playing.delete(this.key);
    for (const placement of this.placements) {
      propViews.turns.delete(placement.id);
      propViews.openDoors.delete(placement.id);
    }
    for (const instances of this.meshes) instances.dispose();
    for (const moves of this.moves) moves.dispose();
    for (const material of this.ownMaterials) material.dispose();
  }

  private playLoop(camera: Vector3, now: number) {
    const { clip } = this.model;
    if (!clip) return;
    let playing: readonly number[];
    if (ALWAYS_MOVING.has(this.kind))
      playing = this.at.map((_, index) => index);
    else {
      this.at.forEach(
        (at, index) => (this.distances[index] = camera.distanceTo(at)),
      );
      budget.offer(this.key, this.distances);
      playing = budget.picked(this.key, now);
    }
    propViews.playing.set(this.key, {
      kind: this.kind,
      count: playing.length,
    });
    for (const index of this.played)
      if (!playing.includes(index))
        propViews.turns.delete(this.placements[index].id);
    this.played = playing;
    const time = CLIP_LOOPS.has(this.kind)
      ? propWorld.clipTime
      : propWorld.windTime;
    let first = true;
    for (const [index, slot] of this.slots.entries()) {
      if (slot.clip === null) continue;
      for (const at of playing) {
        if (this.hidden[at * this.slots.length + index]) continue;
        sampleClip(clip, slot.clip, time + this.phases[at], move);
        slot.moves.set(at, slot.part, move);
        if (!first) continue;
        move.decompose(unused, turn, unused);
        propViews.turns.set(
          this.placements[at].id,
          2 * Math.acos(Math.min(1, Math.abs(turn.w))),
        );
      }
      first = false;
    }
  }

  private swingDoors(now: number, seconds: number) {
    const doorway = this.model.doorway!;
    passers.update(propWorld.people, now);
    if (now - this.lookedAtDoors >= DOOR_LOOK || now < this.lookedAtDoors) {
      this.lookedAtDoors = now;
      this.at.forEach((at, index) => {
        let open = false;
        for (const [id, person] of passers.passing) {
          if (person.distanceTo(at) > DOOR_NEAR) continue;
          feet.copy(person).applyMatrix4(this.toLocal[index]);
          heading.copy(passers.steps.get(id)!);
          heading.transformDirection(this.toLocal[index]);
          if (holdsDoor(feet, heading, doorway)) {
            open = true;
            break;
          }
        }
        this.doorOpen[index] = open ? 1 : 0;
      });
    }
    this.doorAmounts.forEach((amount, index) => {
      const next = swingToward(amount, this.doorOpen[index] === 1, seconds);
      if (next === amount) return;
      this.doorAmounts[index] = next;
      for (const { slot, leaf } of this.leaves)
        slot.moves.set(index, slot.part, leafMove(leaf, next, move));
      const id = this.placements[index].id;
      if (next > 0) propViews.openDoors.add(id);
      else propViews.openDoors.delete(id);
    });
  }

  /** Hides a cold fire's flame and fuel and the dressing turned off, shows them again when they come back. */
  private showParts(now: number) {
    if (now - this.lookedAtParts < PART_LOOK && now >= this.lookedAtParts)
      return;
    this.lookedAtParts = now;
    this.at.forEach((at, index) => {
      const cold = this.hasFire && coldFireAt(at);
      this.slots.forEach((slot, slotIndex) => {
        const name = `${this.placements[index].id}:${slot.node}`;
        const hidden =
          (slot.fire && cold) || propWorld.dressing.get(name) === false ? 1 : 0;
        const key = index * this.slots.length + slotIndex;
        if (hidden === this.hidden[key]) return;
        this.hidden[key] = hidden;
        slot.moves.set(index, slot.part, hidden ? HIDDEN : REST);
        if (hidden) propViews.hidden.add(name);
        else propViews.hidden.delete(name);
      });
    });
  }
}
