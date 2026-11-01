/*
 * What the client knows of nodes' stocks (10 §1.1, §6.3), from the live feed: `node_changed` (a node's stock and
 * drawn stage after a take, a regrowth, a harvest), `tree_felled` (a tree falls and leaves its stump) and the
 * gathers in progress (`action_started` with a node target until the actor's `action_finished`: a chopped tree
 * shakes). A node the feed never mentioned is full. A new run (a snapshot of another run) starts every node full
 * again.
 *
 * The live snapshot lists every node that differs from full (`nodes`, N1's D150), so a page opened mid-run starts
 * from the exact stocks; changes then come as `node_changed` and `tree_felled`.
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
  rice_paddy: 60, // the bible's (D180)
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

/** Changes remembered for `changedSince` (older ones count as "anything may have changed"). */
const LOG_KEEP = 256;

export class NodeStages {
  /** Bumped by every change a drawing must follow. */
  version = 0;
  /** The node each version changed (null: every node, a reset). */
  private log: { version: number; node: string | null }[] = [];
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

  /**
   * The nodes changed since `version` ([] when none), or null when any may have (a reset, or more changes ago than
   * are remembered): a drawing re-draws only when one of its own nodes changed.
   */
  changedSince(version: number): string[] | null {
    if (version >= this.version) return [];
    if (this.log.length === 0 || this.log[0].version > version + 1) return null;
    const nodes: string[] = [];
    for (const entry of this.log) {
      if (entry.version <= version) continue;
      if (entry.node === null) return null;
      nodes.push(entry.node);
    }
    return nodes;
  }

  private touch(node: string | null) {
    this.version += 1;
    this.log.push({ version: this.version, node });
    if (this.log.length > LOG_KEEP)
      this.log.splice(0, this.log.length - LOG_KEEP);
  }

  /** Every node full and standing again, except `states` (the non-full nodes of a snapshot). */
  reset(states: ReadonlyMap<string, NodeState> = new Map()) {
    this.states = new Map(states);
    this.falls.clear();
    this.work = [];
    this.touch(null);
  }

  /** `actor` now works `node` (null: nothing): the node they left and the one they took change. */
  private setWork(actor: string, node: string | null) {
    const before = this.work.find((work) => work.actor === actor)?.node ?? null;
    if (before === node) return;
    this.work = this.work.filter((work) => work.actor !== actor);
    if (node !== null) this.work.push({ actor, node });
    if (before !== null) this.touch(before);
    if (node !== null) this.touch(node);
  }

  /** Follows one feed message; `now` is the client clock in seconds (falls are timed by it). */
  apply(message: LiveMessage, now: number) {
    if (message.type !== 'event') {
      // a snapshot lists every node that differs from full (N1, D150): the record starts from it exactly
      const listed = message.type === 'snapshot' ? message.nodes : undefined;
      if (
        message.type === 'snapshot' &&
        (message.run_id !== this.runId || listed !== undefined)
      ) {
        this.runId = message.run_id;
        this.reset(
          new Map(
            (listed ?? []).map((node) => [
              node.id,
              {
                fill: node.cap > 0 ? node.stock / node.cap : 0,
                stage: node.stage,
              },
            ]),
          ),
        );
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
      this.touch(node);
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
      this.touch(node);
    } else if (type === 'action_started' && actor) {
      // the live feed never sends `action_interrupted`: an actor's next action ends whatever they worked before
      const target = payload.target as { kind?: string; id?: string } | null;
      this.setWork(
        actor,
        target?.kind === 'node' && target.id ? target.id : null,
      );
    } else if (
      (type === 'action_finished' ||
        type === 'action_interrupted' ||
        type === 'died') &&
      actor
    )
      this.setWork(actor, null);
  }
}

/** A tree's stage that draws it as a stump (`node_stages.yaml`'s words: "stump", "a stump", ...). */
export const isStump = (stage: string | null) =>
  stage !== null && /stump/.test(stage);
/** ... and as a sapling. */
export const isSapling = (stage: string | null) =>
  stage !== null && /sapling/.test(stage);
