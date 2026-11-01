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
 * and `fuel`, and dressing a stream turned off (`dressPart`, prop-motion.ts). A hearth (the forge's) burns while
 * someone crafts at it and cools EMBERS game minutes after: its fire glows in it, dying down as it cools, and its
 * chimney smokes (`propWorld.chimneys`, for the smoke); cold, its fire is gone.
 */

/** Kinds lying flat on the ground: their shadows would be invisible, so they skip the shadow pass. */
const FLAT_KINDS = new Set(['rice_paddy', 'paving_tile', 'sleeping_mat']);
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

/** A hearth's fire part, the middle of its base, and its chimney's top (model space). */
interface Hearth {
  part: string;
  base: [number, number, number];
  chimney: [number, number, number];
}
/** Kinds with a hearth: the forge's fire glows in the hearth at its back and smokes out of the chimney above. */
const HEARTHS: Partial<Record<string, Hearth>> = {
  forge: {
    part: 'fire',
    base: [-1.45, 0.55, -0.45],
    chimney: [-1.5, 3.96, -1],
  },
};
/** Someone crafting within this many metres of a hearth's placement works it (the forge's anvil slot is 2.9 m out). */
const HEARTH_REACH = 5;
/** Game minutes a hearth's embers glow after the work stops. */
export const EMBERS = 30;
/** A cooling hearth's fire shrinks to this much of its size before it goes out. */
const EMBER_SIZE = 0.35;

/**
 * How hot a hearth is at town time `minutes` (game minutes) when it was last worked at `workedAt`: 1 while worked,
 * its embers cooling to 0 over EMBERS minutes after (cold if never worked, or the clock went back before it).
 */
export function hearthHeat(workedAt: number, minutes: number) {
  const since = minutes - workedAt;
  return since >= 0 && since < EMBERS ? 1 - since / EMBERS : 0;
}
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
const shrink = new Matrix4();
const fromBase = new Matrix4();

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
  /** The kind's hearth, and per instance its chimney's top (world), when last worked and the heat drawn. */
  private readonly hearth: Hearth | null;
  private readonly chimneys: Vector3[] = [];
  private readonly workedAt: Float64Array;
  private readonly heat: Float32Array;
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
    this.hearth = HEARTHS[kind] ?? null;
    this.workedAt = new Float64Array(this.hearth ? count : 0).fill(-Infinity);
    this.heat = new Float32Array(this.hearth ? count : 0).fill(Number.NaN);
    if (this.hearth)
      this.chimneys = placed.map((matrix) =>
        new Vector3(...this.hearth!.chimney).applyMatrix4(matrix),
      );
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
      propViews.hearths.delete(placement.id);
      propWorld.chimneys.delete(`${placement.id}:chimney`);
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

  /**
   * Hides a cold fire's flame and fuel and the dressing turned off, shows them again when they come back; heats and
   * cools the hearths.
   */
  private showParts(now: number) {
    if (now - this.lookedAtParts < PART_LOOK && now >= this.lookedAtParts)
      return;
    this.lookedAtParts = now;
    if (this.hearth) this.tendHearths(this.hearth);
    this.at.forEach((at, index) => {
      const cold = this.hasFire && coldFireAt(at);
      this.slots.forEach((slot, slotIndex) => {
        if (slot.node === this.hearth?.part) return;
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

  /**
   * Each hearth someone crafts at is worked now; its heat (by when it was last worked) sizes its fire about the
   * fire's base (gone when cold) and its chimney smokes while it burns.
   */
  private tendHearths(hearth: Hearth) {
    const slot = this.slots.find(({ node }) => node === hearth.part);
    this.at.forEach((at, index) => {
      for (const id of propWorld.crafters) {
        const feet = propWorld.people.get(id);
        if (feet && feet.distanceTo(at) < HEARTH_REACH)
          this.workedAt[index] = propWorld.minutes;
      }
      const heat = hearthHeat(this.workedAt[index], propWorld.minutes);
      const { id } = this.placements[index];
      propViews.hearths.set(id, heat);
      propWorld.chimneys.set(`${id}:chimney`, {
        lit: heat > 0,
        strength: heat,
        position: this.chimneys[index],
      });
      const drawn = this.heat[index];
      // a hearth going out or coming alight changes at once, a cooling one by visible steps
      const out = heat === 0;
      if (!slot || (out === (drawn === 0) && Math.abs(heat - drawn) < 0.02))
        return;
      this.heat[index] = heat;
      slot.moves.set(index, slot.part, out ? HIDDEN : fireAt(hearth, heat));
    });
  }
}

/** A hearth's fire at `heat` (above 0): its own size worked, shrunk about its base as its embers cool. */
function fireAt(hearth: Hearth, heat: number) {
  const size = EMBER_SIZE + (1 - EMBER_SIZE) * heat;
  const [x, y, z] = hearth.base;
  return move
    .makeTranslation(x, y, z)
    .multiply(shrink.makeScale(size, size, size))
    .multiply(fromBase.makeTranslation(-x, -y, -z));
}
