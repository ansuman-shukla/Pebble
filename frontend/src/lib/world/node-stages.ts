/*
 * What the client knows of nodes' stocks (10 §1.1, §6.3), from the live feed: `node_changed` (a node's stock and
 * drawn stage after a take, a regrowth, a harvest), `tree_felled` (a tree falls and leaves its stump) and the
 * gathers in progress (`action_started` with a node target until the actor's `action_finished`: a chopped tree
 * shakes). A node the feed never mentioned is full. A new run (a snapshot of another run) starts every node full
 * again.
 *
 * Seam for N1: the feed tells changes only, so a page opened mid-run draws nodes taken before it opened as full
 * until they change again; a `nodes` list of the non-full nodes on the live snapshot (bible §1.1: snapshots store
 * only nodes that differ from full) would make it exact through `reset`.
 */
import type { LiveMessage } from '@/lib/live/live-contract';

/** Stock caps by node kind (10 §1.1), for `node_changed` payloads that don't carry their own `cap`. */
const NODE_CAPS: Record<string, number> = {
  berry_bush: 12,
  root_patch: 8,
  reed_bed: 20,
  deadwood: 6,
  nut_tree: 15,
  tree: 10,
  fishing_spot: 20,
  flint_seam: 30,
  obsidian_field: 40,
  iron_sand_bar: 60,
  gold_pool: 40,
  rice_paddy: 60,
};

export interface NodeState {
  /** stock / cap, 0..1. */
  fill: number;
  /** The drawn stage the simulation named (`node_stages.yaml`), when it named one. */
  stage: string | null;
}

/** What a gather in progress is about: its actor and the node it works. */
interface Work {
  actor: string;
  node: string;
}

export class NodeStages {
  /** Bumped by every change a drawing must follow. */
  version = 0;
  private runId: string | null = null;
  private states = new Map<string, NodeState>();
  private falls = new Map<string, { at: number; bearing: number | null }>();
  private work: Work[] = [];

  /** `caps`: caps that differ from the kind's, by node id (fixed features: `WorldPlaces.features[].cap`). */
  constructor(private readonly caps: ReadonlyMap<string, number> = new Map()) {}

  /** The node's state, or undefined while it is full (never changed). */
  state(id: string): NodeState | undefined {
    return this.states.get(id);
  }

  /** When (seconds, the clock `apply` was given) the tree began to fall, if it was felled. */
  fellAt(id: string): number | undefined {
    return this.falls.get(id)?.at;
  }

  /** The compass bearing (radians, 0 north, π/2 east) the felled tree fell along, when the feed said. */
  fallBearing(id: string): number | null {
    return this.falls.get(id)?.bearing ?? null;
  }

  /** Someone is gathering at the node now (a tree being chopped). */
  worked(id: string) {
    return this.work.some(({ node }) => node === id);
  }

  /** Every node full and standing again, except `states` (the non-full nodes of a snapshot). */
  reset(states: ReadonlyMap<string, NodeState> = new Map()) {
    this.states = new Map(states);
    this.falls.clear();
    this.work = [];
    this.version += 1;
  }

  /** Follows one feed message; `now` is the client clock in seconds (falls are timed by it). */
  apply(message: LiveMessage, now: number) {
    if (message.type !== 'event') {
      if (message.type === 'snapshot' && message.run_id !== this.runId) {
        this.runId = message.run_id;
        this.reset();
      }
      return;
    }
    const { type, actor_id: actor, payload } = message.event;
    if (type === 'node_changed') {
      const node = String(payload.node);
      const kind = String(payload.kind);
      const cap = Number(payload.cap ?? this.caps.get(node) ?? NODE_CAPS[kind]);
      if (!(cap > 0))
        throw new Error(`no stock cap for node ${node} (${kind})`);
      this.states.set(node, {
        fill: Math.min(Math.max(Number(payload.after) / cap, 0), 1),
        stage: typeof payload.stage === 'string' ? payload.stage : null,
      });
      // the felled tree's logs lie by its stump until it grows again
      if (isSapling(this.states.get(node)!.stage)) this.falls.delete(node);
    } else if (type === 'tree_felled') {
      const node = String(payload.node);
      // `yaw_deg` is a heading (0 south, 90 east, like citizens'): bearing = 180° − heading
      const yaw = Number(payload.yaw_deg);
      const bearing = Number.isFinite(yaw)
        ? ((180 - yaw) * Math.PI) / 180
        : null;
      this.falls.set(node, { at: now, bearing });
      this.states.set(node, { fill: 0, stage: 'stump' });
      this.work = this.work.filter((work) => work.node !== node);
    } else if (type === 'action_started') {
      const target = payload.target as { kind?: string; id?: string } | null;
      if (!actor || target?.kind !== 'node' || !target.id) return;
      this.work = [
        ...this.work.filter((work) => work.actor !== actor),
        { actor, node: target.id },
      ];
    } else if (
      type === 'action_finished' ||
      type === 'action_interrupted' ||
      type === 'died'
    ) {
      if (!this.work.some((work) => work.actor === actor)) return;
      this.work = this.work.filter((work) => work.actor !== actor);
    } else return;
    this.version += 1;
  }
}

/** A tree's stage that draws it as a stump (`node_stages.yaml`'s words: "stump", "a stump", ...). */
export const isStump = (stage: string | null) =>
  stage !== null && /stump/.test(stage);
/** ... and as a sapling. */
export const isSapling = (stage: string | null) =>
  stage !== null && /sapling/.test(stage);
