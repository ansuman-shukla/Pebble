/*
 * The nodes around the camera's focus, drawn by stage (10 §1.1, §5.2): the cells within FAR_REACH + REBUILD are
 * gathered when the focus moves more than REBUILD metres; the instances are split into tiers (within SHADOW_REACH
 * the set that casts shadows, then each look's reach) every RESPLIT metres and whenever a node's stage changes.
 * A standing tree shakes while someone chops it, falls FALL_SECONDS along its bearing when felled, then lies as
 * logs beside its stump until it grows back as a sapling; other nodes draw their stock through the staged
 * material (staged-material.ts).
 */
import { type InstancedMesh, Matrix4, Vector3 } from 'three';

import type { PropKind } from './assets';
import { LOGS_LOOK, STUMP_LOOK, TREE_NODES } from './biome-props';
import { fillMeshes, hideMeshes } from './instanced-tiers';
import { isSapling, isStump, type NodeStages } from './node-stages';
import { type NodeInstance, type Scatter, scatterMatrix } from './scatter';
import {
  FULL_STAGE,
  nodeStage,
  type Stage,
  type StageTexture,
} from './staged-material';
import { tangentFrame } from './globe';

const SHADOW_REACH = 70;
const REBUILD = 100;
const RESPLIT = 20;
/** The farthest any look is drawn (metres from the focus). */
export const FAR_REACH = 500;
/** A felled tree falls this long (real seconds), then its stump stands (10 §1.1: falling 2 s along `yaw`). */
export const FALL_SECONDS = 2;
/** A chopped tree sways this far (radians) this often (per second). */
const SHAKE_ANGLE = 0.035;
const SHAKE_HZ = 3;
/** A stump is drawn at this share of its tree's scale, a sapling at this one. */
const STUMP_SCALE = 0.9;
export const SAPLING_SCALE = 0.3;
/** The logs lie this far (× the tree's scale) out along the fall from the trunk. */
const LOGS_OFFSET = 2;

/** One look's instanced meshes (one per merged part) per tier, and its stage rows when it is drawn by stage. */
export interface NodeLook {
  kind: PropKind;
  reach: number;
  /** The model's stage pieces (kind-parts.ts). */
  pieces: number;
  near: InstancedMesh[];
  far: InstancedMesh[];
  stages: { near: StageTexture; far: StageTexture } | null;
}

type Motion = 'fall' | 'shake';

/** One thing drawn for a node: the node itself, or a felled tree's logs. */
interface Draw {
  node: NodeInstance;
  look: PropKind;
  model: Matrix4;
  stage: Stage | null;
  motion: Motion | null;
  role: 'node' | 'logs';
}

/** A drawn instance whose matrix moves every frame. */
interface Moving {
  meshes: InstancedMesh[];
  slot: number;
  draw: Draw;
}

/** What the page's test hooks read of a drawn node. */
export interface DrawnNode {
  id: string;
  look: PropKind;
  role: 'node' | 'logs';
  /** World metres of the instance's origin. */
  position: [number, number, number];
  stage: Stage | null;
  motion: Motion | null;
}

const up = new Vector3();
const along = new Vector3();
const axis = new Vector3();
const across = new Vector3();
const turn = new Matrix4();
const shift = new Matrix4();
const back = new Matrix4();
const moved = new Matrix4();
const unit = new Vector3();

/** The way a tree at `position` falls: its compass bearing on the tangent plane. */
function fallDirection(position: Vector3, bearing: number, target: Vector3) {
  const { east, north } = tangentFrame(position);
  return target
    .copy(north)
    .multiplyScalar(Math.cos(bearing))
    .addScaledVector(east, Math.sin(bearing));
}

/** `model` turned `angle` about the horizontal axis through the node's base that tips its top along its fall. */
function tipped(
  node: NodeInstance,
  model: Matrix4,
  angle: number,
  target: Matrix4,
) {
  up.copy(node.position).normalize();
  fallDirection(node.position, node.bearing, along);
  axis.crossVectors(up, along).normalize();
  const { x, y, z } = node.position;
  return target
    .copy(shift.makeTranslation(x, y, z))
    .multiply(turn.makeRotationAxis(axis, angle))
    .multiply(back.makeTranslation(-x, -y, -z))
    .multiply(model);
}

/** The felled tree's logs: lying along its fall beside the trunk. */
function logsMatrix(node: NodeInstance) {
  up.copy(node.position).normalize();
  fallDirection(node.position, node.bearing, along);
  across.crossVectors(along, up);
  const model = new Matrix4().makeBasis(along, up, across);
  model.scale(unit.setScalar(node.scale));
  return model.setPosition(
    node.position.clone().addScaledVector(along, LOGS_OFFSET * node.scale),
  );
}

export class NodeField {
  private looks: Map<PropKind, NodeLook>;
  private builtAt: Vector3 | null = null;
  private splitAt: Vector3 | null = null;
  private seen = -1;
  private gathered: { node: NodeInstance; model: Matrix4 }[] = [];
  private moving: Moving[] = [];
  /** The client time the next fall in view ends (a split then draws its stump). */
  private nextLanding = Infinity;
  private shown: Draw[] = [];
  private hidden = true;

  constructor(
    looks: readonly NodeLook[],
    private readonly scatter: Scatter,
    private readonly stages: NodeStages,
  ) {
    this.looks = new Map(looks.map((look) => [look.kind, look]));
  }

  /** What one node draws now: its look by stage, a falling or shaking tree, a stump and logs, a sapling. */
  private drawsOf(node: NodeInstance, model: Matrix4, now: number): Draw[] {
    const state = this.stages.state(node.id);
    if (TREE_NODES.has(node.node)) {
      const fell = this.stages.fellAt(node.id);
      // a felled tree falls the way the feed said (else along its table bearing)
      node = {
        ...node,
        bearing: this.stages.fallBearing(node.id) ?? node.bearing,
      };
      const plain = { node, stage: null, motion: null, role: 'node' } as const;
      if (fell !== undefined && now - fell < FALL_SECONDS) {
        this.nextLanding = Math.min(this.nextLanding, fell + FALL_SECONDS);
        return [{ ...plain, look: node.kind, model, motion: 'fall' }];
      }
      if (fell !== undefined || isStump(state?.stage ?? null)) {
        const stump = scatterMatrix({
          ...node,
          kind: STUMP_LOOK,
          scale: node.scale * STUMP_SCALE,
        });
        const draws: Draw[] = [{ ...plain, look: STUMP_LOOK, model: stump }];
        if (fell !== undefined)
          draws.push({
            ...plain,
            look: LOGS_LOOK,
            model: logsMatrix(node),
            role: 'logs',
          });
        return draws;
      }
      if (isSapling(state?.stage ?? null))
        return [
          {
            ...plain,
            look: node.kind,
            model: scatterMatrix({
              ...node,
              scale: node.scale * SAPLING_SCALE,
            }),
          },
        ];
      return [
        {
          ...plain,
          look: node.kind,
          model,
          motion: this.stages.worked(node.id) ? 'shake' : null,
        },
      ];
    }
    const look = this.looks.get(node.kind)!;
    return [
      {
        node,
        motion: null,
        role: 'node',
        look: node.kind,
        model,
        stage: look.stages
          ? nodeStage(node.node, state?.fill ?? 1, look.pieces)
          : null,
      },
    ];
  }

  private split(focus: Vector3, now: number) {
    this.splitAt = focus.clone();
    this.seen = this.stages.version;
    this.nextLanding = Infinity;
    const tiers = new Map<PropKind, { near: Draw[]; far: Draw[] }>(
      [...this.looks.keys()].map((kind) => [kind, { near: [], far: [] }]),
    );
    for (const { node, model } of this.gathered) {
      const distance = node.position.distanceTo(focus);
      for (const draw of this.drawsOf(node, model, now)) {
        const look = this.looks.get(draw.look)!;
        if (distance < SHADOW_REACH) tiers.get(draw.look)!.near.push(draw);
        else if (distance < look.reach) tiers.get(draw.look)!.far.push(draw);
      }
    }
    this.moving = [];
    this.shown = [];
    for (const [kind, { near, far }] of tiers) {
      const look = this.looks.get(kind)!;
      for (const [tier, meshes, draws, rows] of [
        ['near', look.near, near, look.stages?.near],
        ['far', look.far, far, look.stages?.far],
      ] as const) {
        // fillMeshes reports a tier that overflows; what fits is drawn
        fillMeshes(
          meshes,
          draws.map((draw) => draw.model),
          `nodes ${kind} ${tier}`,
        );
        const drawn = draws.slice(0, meshes[0]?.instanceMatrix.count ?? 0);
        drawn.forEach((draw, slot) => {
          rows?.set(slot, draw.stage ?? FULL_STAGE);
          if (draw.motion)
            this.moving.push({ meshes: [...meshes], slot, draw });
        });
        rows?.flush();
        this.shown.push(...drawn);
      }
    }
  }

  private animate(now: number) {
    for (const { meshes, slot, draw } of this.moving) {
      const fell = this.stages.fellAt(draw.node.id);
      const angle =
        draw.motion === 'fall' && fell !== undefined
          ? (Math.PI / 2) * Math.min((now - fell) / FALL_SECONDS, 1) ** 2
          : SHAKE_ANGLE * Math.sin(2 * Math.PI * SHAKE_HZ * now);
      tipped(draw.node, draw.model, angle, moved);
      for (const mesh of meshes) {
        mesh.setMatrixAt(slot, moved);
        mesh.instanceMatrix.needsUpdate = true;
      }
    }
  }

  /** Advances to client time `now` (seconds) around `focus`; `hidden` (the camera too high) draws nothing. */
  frame(focus: Vector3, hidden: boolean, now: number) {
    if (hidden) {
      if (!this.hidden)
        for (const look of this.looks.values())
          hideMeshes([...look.near, ...look.far]);
      this.hidden = true;
      this.splitAt = null;
      this.shown = [];
      this.moving = [];
      return;
    }
    this.hidden = false;
    if (!this.builtAt || this.builtAt.distanceTo(focus) > REBUILD) {
      this.builtAt = focus.clone();
      this.splitAt = null;
      this.gathered = [];
      for (const cell of this.scatter.cellsAround(focus, FAR_REACH + REBUILD))
        for (const node of this.scatter.nodes(cell))
          this.gathered.push({ node, model: scatterMatrix(node) });
    }
    if (
      !this.splitAt ||
      this.splitAt.distanceTo(focus) > RESPLIT ||
      this.stages.version !== this.seen ||
      now >= this.nextLanding
    )
      this.split(focus, now);
    this.animate(now);
  }

  /** The nodes drawn now and the focus they were split around (null while none are drawn). */
  drawn(): { focus: [number, number, number]; nodes: DrawnNode[] } | null {
    if (!this.splitAt) return null;
    return {
      focus: this.splitAt.toArray(),
      nodes: this.shown.map(({ node, look, model, stage, motion, role }) => ({
        id: node.id,
        look,
        role,
        position: new Vector3().setFromMatrixPosition(model).toArray(),
        stage,
        motion,
      })),
    };
  }

  /** Every instanced mesh, to mount once. */
  meshes() {
    return [...this.looks.values()].flatMap((look) => [
      ...look.near,
      ...look.far,
    ]);
  }

  dispose() {
    for (const look of this.looks.values()) {
      for (const mesh of [...look.near, ...look.far]) mesh.dispose();
      look.stages?.near.dispose();
      look.stages?.far.dispose();
    }
  }
}
