/*
 * What lies on the ground, as the live feed's `stacks` say (10 §5.2): a felled tree's logs, meat a predator left at
 * the remains, wood brought to a camp, goods put down. Stacks of one item on one spot draw as one pile of their total;
 * a pile's size follows its count (by volume), so taking some shrinks it and taking the last makes it go. Wood lying
 * on a felled tree's trunk is that tree's logs: a fallen log beside the stump along the fall, its ends on the ground
 * (felled-logs.ts; shorter as logs are carried off), shown once the tree has landed. A stack is placed once, when it
 * first appears (only its count ever changes), and a frame whose stacks and counts are unchanged costs nothing. Piles are drawn within REACH of the camera's focus, instanced per look
 * (one draw call per look part with anything in it); a pile grows in when it appears and shrinks away when it goes.
 */
import { InstancedMesh, Matrix4, Quaternion, Vector3 } from 'three';

import type { LiveStack } from '@/lib/live/live-contract';

import type { PropKind } from './assets';
import { LOGS_LOOK, TREE_NODES } from './biome-props';
import { lyingLogs } from './felled-logs';
import { tangentFrame } from './globe';
import { DRAWN_STACK_PROPS, type DrawnStackProp } from './ground-stack-props';
import { fillMeshes, hideMeshes } from './instanced-tiers';
import { FALL_SECONDS } from './node-field';
import type { NodeStages } from './node-stages';
import type { NodeInstance, Scatter } from './scatter';
import type { PlaceOnGround } from './walk-charts';

export type StackLook = PropKind | DrawnStackProp;

/** Piles are drawn within this many metres of the focus (like low nodes). */
export const REACH = 300;
/** Re-pick the piles in reach when the focus moved this far. */
const RESPLIT = 20;
/** Stacks of one item on one spot (rounded to this many metres) draw as one pile. */
const SPOT_M = 0.5;
/** A flat look tilts with the ground sampled this far either side of it. */
const SLOPE_M = 0.4;
/** Wood within this of a tree's trunk is that tree's logs. */
const ON_TRUNK_M = 0.5;
/** A felled tree's logs: the count drawn whole (10 §1.1: a tree gives 10). */
const TREE_LOGS = 10;
/** Partly carried off, the logs are drawn no shorter than this share. */
const SHORTEST_LOGS = 0.3;
/** A pile is drawn between these shares of its look's size. */
const SMALLEST = 0.45;
const LARGEST = 1.4;
/** A pile grows in, resizes and shrinks away over this long (seconds). */
export const EASE_SECONDS = 0.4;
/** Meat lies this far beside the point it was dropped (the remains it came from lie on that point). */
const MEAT_ASIDE_M = 0.8;
/** Most piles of one look in reach. */
export const CAPACITY = 256;

/** How an item lies on the ground: its look and the count its look shows at full size. */
interface ItemLook {
  look: StackLook;
  full: number;
}

const TOOL: ItemLook = { look: 'tool', full: 1 };
const ITEM_LOOKS: Record<string, ItemLook> = {
  wood: { look: 'firewood', full: 12 },
  meat: { look: 'meat', full: 6 },
  'dried meat': { look: 'meat', full: 6 },
  fish: { look: 'fish', full: 3 },
  hide: { look: 'hide', full: 1 },
  berries: { look: 'reed_basket', full: 10 },
  roots: { look: 'reed_basket', full: 8 },
  nuts: { look: 'reed_basket', full: 15 },
  rice: { look: 'grain_sack', full: 20 },
  pack: { look: 'grain_sack', full: 1 },
  reeds: { look: 'reeds', full: 10 },
  cloth: { look: 'cloth', full: 2 },
  coins: { look: 'coin_pouch', full: 50 },
  flint: { look: 'small_rock', full: 5 },
  obsidian: { look: 'small_rock', full: 5 },
  'iron sand': { look: 'small_rock', full: 10 },
  gold: { look: 'small_rock', full: 3 },
  'flint spear': TOOL,
  'obsidian spear': TOOL,
  'iron spear': TOOL,
  'stone axe': TOOL,
  'iron axe': TOOL,
  sickle: TOOL,
};
/** An item the table doesn't know still shows: as a sack. */
const UNKNOWN_ITEM = {
  look: 'grain_sack',
  full: 1,
} as const satisfies ItemLook;

const itemLook = (item: string) => ITEM_LOOKS[item] ?? UNKNOWN_ITEM;

const isDrawnProp = (look: StackLook): look is DrawnStackProp =>
  (DRAWN_STACK_PROPS as readonly string[]).includes(look);

/** Every look a pile can take: models from the catalogue (the rest are drawn from code, DRAWN_STACK_PROPS). */
export const STACK_MODEL_LOOKS: readonly PropKind[] = [
  ...new Set<PropKind>([
    LOGS_LOOK,
    UNKNOWN_ITEM.look,
    ...Object.values(ITEM_LOOKS)
      .map(({ look }) => look)
      .filter((look): look is PropKind => !isDrawnProp(look)),
  ]),
];

/** A share of a look's size from a count: volume grows with the count. */
const pileScale = (count: number, full: number) =>
  Math.min(Math.max(Math.cbrt(count / full), SMALLEST), LARGEST);

/** One look's instanced meshes (one per merged part of its model). */
export interface StackLookMeshes {
  look: StackLook;
  meshes: InstancedMesh[];
}

/** What the page's test hooks read of a drawn pile. */
export interface DrawnStack {
  /** The stacks it draws (one item on one spot). */
  ids: string[];
  item: string;
  count: number;
  look: StackLook;
  /** The felled tree whose logs it is, if it is. */
  tree: string | null;
  /** World metres of the instance's origin. */
  position: [number, number, number];
  /** Its size now, as a share of the look's (logs: their length). */
  scale: number;
}

/** A stack's spot as first seen (a stack's item and place never change): the pile it belongs to. */
interface StackSpot {
  item: string;
  /** Its pile's key: the item and the spot rounded to SPOT_M. */
  pile: string;
  unit: Vector3;
}

/** A pile as laid out: everything but its size, which eases. */
interface Pile {
  key: string;
  ids: string[];
  item: string;
  count: number;
  look: StackLook;
  tree: NodeInstance | null;
  /** Its matrix at full size. */
  base: Matrix4;
  /** The size it eases to, and from what at which time. */
  target: number;
  from: number;
  since: number;
}

const yAxis = new Vector3(0, 1, 0);
const stretch = new Matrix4();
const scratch = new Vector3();

/** A stable number in 0..1 from a key (a pile's turn on its spot). */
function hashOf(key: string) {
  let hash = 2166136261;
  for (const char of key) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return (hash >>> 0) / 4294967296;
}

export class StackField {
  private looks: Map<StackLook, StackLookMeshes>;
  private stacks: readonly LiveStack[] = [];
  /** Every stack's spot (sampled once) and count as last set, by id. */
  private spots = new Map<string, StackSpot>();
  private counts = new Map<string, number>();
  private piles = new Map<string, Pile>();
  private leaving: Pile[] = [];
  private shown: { pile: Pile; scale: number }[] = [];
  private splitAt: Vector3 | null = null;
  private seen = 0;
  private dirty = true;
  private easing = false;
  /** The client time the next tree in reach lands (its logs then show). */
  private nextLanding = Infinity;
  private hidden = true;

  constructor(
    looks: readonly StackLookMeshes[],
    private readonly scatter: Scatter,
    private readonly stages: NodeStages,
    private readonly place: PlaceOnGround,
  ) {
    this.looks = new Map(looks.map((look) => [look.look, look]));
    this.seen = stages.version;
  }

  /**
   * The feed's stacks now (`now`: client seconds, like the node stages' clock). Only counts can change for a stack
   * id, so a frame with the same ids and counts changes nothing, and a new stack is the only one placed.
   */
  set(stacks: readonly LiveStack[], now: number) {
    if (stacks === this.stacks) return;
    this.stacks = stacks;
    const same =
      stacks.length === this.counts.size &&
      stacks.every((stack) => this.counts.get(stack.id) === stack.count);
    if (!same) this.layout(now);
  }

  /** The tree standing (or felled) on this trunk, if any. */
  private treeAt(unit: Vector3): NodeInstance | null {
    for (const cell of this.scatter.cellsAround(unit, ON_TRUNK_M * 4))
      for (const node of this.scatter.nodes(cell)) {
        if (!TREE_NODES.has(node.node)) continue;
        const off =
          scratch.copy(node.position).normalize().angleTo(unit) *
          node.position.length();
        if (off < ON_TRUNK_M) return node;
      }
    return null;
  }

  private spotOf(stack: LiveStack): StackSpot {
    const known = this.spots.get(stack.id);
    if (known) return known;
    const unit = new Vector3(...stack.unit).normalize();
    const { x, y, z } = this.place(unit, scratch).divideScalar(SPOT_M);
    const spot = {
      item: stack.item,
      pile: `${stack.item}|${Math.round(x)},${Math.round(y)},${Math.round(z)}`,
      unit,
    };
    this.spots.set(stack.id, spot);
    return spot;
  }

  /** The piles from the stacks: new ones grow in, changed ones resize, gone ones shrink away. */
  private layout(now: number) {
    this.counts = new Map(this.stacks.map((stack) => [stack.id, stack.count]));
    for (const id of this.spots.keys())
      if (!this.counts.has(id)) this.spots.delete(id);
    const groups = new Map<
      string,
      { ids: string[]; count: number; spot: StackSpot }
    >();
    for (const stack of this.stacks) {
      const spot = this.spotOf(stack);
      const group = groups.get(spot.pile);
      if (group) {
        group.ids.push(stack.id);
        group.count += stack.count;
      } else
        groups.set(spot.pile, { ids: [stack.id], count: stack.count, spot });
    }
    const next = new Map<string, Pile>();
    for (const [key, { ids, count, spot }] of groups) {
      const known = this.piles.get(key);
      const pile = known ? { ...known, ids, count } : this.newPile(key, spot);
      const target = pile.tree
        ? Math.min(Math.max(count / TREE_LOGS, SHORTEST_LOGS), 1)
        : pileScale(count, itemLook(spot.item).full);
      if (!known || known.target !== target) {
        pile.from = known ? this.sizeOf(known, now) : 0;
        pile.since = now;
      }
      next.set(key, { ...pile, ids, count, target });
    }
    for (const [key, pile] of this.piles)
      if (!next.has(key))
        this.leaving.push({
          ...pile,
          from: this.sizeOf(pile, now),
          target: 0,
          since: now,
        });
    this.piles = next;
    this.dirty = true;
  }

  /** A pile first seen: its look, the tree whose logs it is (wood on a trunk) and where it is drawn. */
  private newPile(key: string, spot: StackSpot): Pile {
    const tree = spot.item === 'wood' ? this.treeAt(spot.unit) : null;
    const look = tree ? LOGS_LOOK : itemLook(spot.item).look;
    return {
      key,
      ids: [],
      item: spot.item,
      count: 0,
      look,
      tree,
      base: tree ? this.logsBase(tree) : this.pileBase(spot.unit, look, key),
      target: 0,
      from: 0,
      since: 0,
    };
  }

  /** A felled tree's logs on the ground beside its stump, along the way it fell (felled-logs.ts). */
  private logsBase(tree: NodeInstance) {
    const bearing = this.stages.fallBearing(tree.id) ?? tree.bearing;
    return lyingLogs(tree, bearing, this.place).model;
  }

  /**
   * A pile on the ground at its point (meat beside it), turned its own way about its up: the ground's slope for the
   * flat looks drawn from code (a hide, cloth), the planet's up for the rest.
   */
  private pileBase(unit: Vector3, look: StackLook, key: string) {
    const turn = hashOf(key) * 2 * Math.PI;
    const { up, east, north } = tangentFrame(unit);
    const point = unit.clone();
    if (look === 'meat') {
      const aside = east
        .clone()
        .multiplyScalar(Math.cos(turn))
        .addScaledVector(north, Math.sin(turn));
      const radius = this.place(unit, new Vector3()).length();
      point.addScaledVector(aside, MEAT_ASIDE_M / radius).normalize();
    }
    const position = this.place(point, new Vector3());
    const standing = isDrawnProp(look) ? this.slopeUp(point, position) : up;
    const rotation = new Quaternion()
      .setFromUnitVectors(yAxis, standing)
      .multiply(new Quaternion().setFromAxisAngle(yAxis, turn));
    return new Matrix4().compose(position, rotation, new Vector3(1, 1, 1));
  }

  /** The drawn ground's up at a point: across the ground SLOPE_M east-west and north-south of it. */
  private slopeUp(unit: Vector3, at: Vector3) {
    const { east, north } = tangentFrame(unit);
    const radius = at.length();
    const ground = (dx: number, dz: number) =>
      this.place(
        unit
          .clone()
          .addScaledVector(east, dx / radius)
          .addScaledVector(north, dz / radius)
          .normalize(),
        new Vector3(),
      );
    const eastward = ground(SLOPE_M, 0).sub(ground(-SLOPE_M, 0));
    const northward = ground(0, SLOPE_M).sub(ground(0, -SLOPE_M));
    const normal = new Vector3().crossVectors(eastward, northward).normalize();
    return normal.dot(at) < 0 ? normal.negate() : normal;
  }

  /** A pile's size at client time `now`: easing from where it was to its target. */
  private sizeOf(pile: Pile, now: number) {
    const t = Math.min(Math.max((now - pile.since) / EASE_SECONDS, 0), 1);
    return pile.from + (pile.target - pile.from) * t * (2 - t);
  }

  /** The pile's tree is still falling (its logs show once it lands). */
  private falling(pile: Pile, now: number) {
    if (!pile.tree) return false;
    const fell = this.stages.fellAt(pile.tree.id);
    if (fell === undefined || now - fell >= FALL_SECONDS) return false;
    this.nextLanding = Math.min(this.nextLanding, fell + FALL_SECONDS);
    return true;
  }

  private matrixOf(pile: Pile, scale: number, target: Matrix4) {
    // logs shorten along their length (model x); a pile shrinks every way
    const [x, y] = pile.tree ? [scale, 1] : [scale, scale];
    return target.multiplyMatrices(pile.base, stretch.makeScale(x, y, y));
  }

  /** A tree felled or grown back: its logs lie along the way the feed says it fell. */
  private refell() {
    const changed = this.stages.changedSince(this.seen);
    this.seen = this.stages.version;
    if (changed !== null && changed.length === 0) return;
    const trees = changed === null ? null : new Set(changed);
    for (const [key, pile] of this.piles)
      if (pile.tree && (trees === null || trees.has(pile.tree.id)))
        this.piles.set(key, { ...pile, base: this.logsBase(pile.tree) });
    this.dirty = true;
  }

  private draw(focus: Vector3, now: number) {
    this.leaving = this.leaving.filter((pile) => this.sizeOf(pile, now) > 0);
    this.nextLanding = Infinity;
    const byLook = new Map<StackLook, Matrix4[]>(
      [...this.looks.keys()].map((look) => [look, []]),
    );
    this.shown = [];
    this.easing = false;
    for (const pile of [...this.piles.values(), ...this.leaving]) {
      if (this.falling(pile, now)) continue;
      const position = scratch.setFromMatrixPosition(pile.base);
      if (position.distanceTo(focus) > REACH) continue;
      const scale = this.sizeOf(pile, now);
      if (now - pile.since < EASE_SECONDS) this.easing = true;
      if (scale <= 0) continue;
      const models = byLook.get(pile.look);
      if (!models) throw new Error(`no meshes for the stack look ${pile.look}`);
      models.push(this.matrixOf(pile, scale, new Matrix4()));
      if (!pile.target) continue;
      this.shown.push({ pile, scale });
    }
    for (const [look, models] of byLook)
      fillMeshes(this.looks.get(look)!.meshes, models, `stacks ${look}`);
  }

  /** Advances to client time `now` (seconds) around `focus`; `hidden` (the camera too high) draws nothing. */
  frame(focus: Vector3, hidden: boolean, now: number) {
    if (hidden) {
      if (!this.hidden)
        for (const { meshes } of this.looks.values()) hideMeshes(meshes);
      this.hidden = true;
      this.splitAt = null;
      this.shown = [];
      return;
    }
    if (this.stages.version !== this.seen) this.refell();
    if (
      this.hidden ||
      this.dirty ||
      this.easing ||
      now >= this.nextLanding ||
      !this.splitAt ||
      this.splitAt.distanceTo(focus) > RESPLIT
    ) {
      this.hidden = false;
      this.dirty = false;
      this.splitAt = focus.clone();
      this.draw(focus, now);
    }
  }

  /** The piles drawn now (leaving ones apart). */
  drawn(): DrawnStack[] {
    return this.shown.map(({ pile, scale }) => ({
      ids: pile.ids,
      item: pile.item,
      count: pile.count,
      look: pile.look,
      tree: pile.tree?.id ?? null,
      position: new Vector3().setFromMatrixPosition(pile.base).toArray(),
      scale,
    }));
  }

  /** How many instances each look draws now (0 for a hidden look). */
  instances(): Partial<Record<StackLook, number>> {
    return Object.fromEntries(
      [...this.looks.values()].map(({ look, meshes }) => [
        look,
        meshes[0]?.visible ? meshes[0].count : 0,
      ]),
    );
  }

  /** Every instanced mesh, to mount once. */
  meshes() {
    return [...this.looks.values()].flatMap(({ meshes }) => meshes);
  }
}
