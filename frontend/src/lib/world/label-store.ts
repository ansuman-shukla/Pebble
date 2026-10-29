import { type Object3D, Vector3 } from 'three';

/*
 * Where screen labels hang and what they say, written by two sides that never meet:
 * - 3D bodies write anchors (`anchor`): the scene object a subject's labels hang over and how far above it, e.g. a
 *   citizen's body lifted to head height, or its head bone.
 * - The UI writes content (`describe`): name tags and speech bubbles, each naming the subject it hangs over.
 * The projector (components/world/labels.tsx) joins them every frame; a label is drawn only once its subject has
 * an anchor.
 */

/** "Up" at a world point, for lifting a label above its anchor (flat scenes: +y; the planet: away from its centre). */
export type UpAt = (at: Vector3, out: Vector3) => Vector3;

const FLAT_UP: UpAt = (_at, out) => out.set(0, 1, 0);

const lifted = new Vector3();

export interface LabelAnchor {
  object: Object3D;
  /** Metres above the object's world position, along `up` there. */
  lift: number;
  /** Among a subject's anchors the highest priority wins, the newest among equals. */
  priority: number;
}

type LabelKind = 'name' | 'speech';

/** One label: a DOM element over its subject's anchor. */
export interface LabelContent {
  /** Unique among labels (e.g. `npc-pip`, `say-pip`). */
  id: string;
  /** Whose anchor it hangs over (e.g. a citizen id). */
  subject: string;
  /** A name tag or a speech bubble (white, wraps long text, drawn above the tags). */
  kind: LabelKind;
  text: string;
}

export class LabelStore {
  readonly elements = new Map<string, HTMLElement>();
  private anchors = new Map<string, LabelAnchor[]>();
  private groups = new Map<string, readonly LabelContent[]>();
  private listeners = new Set<() => void>();
  private snapshot: readonly LabelContent[] = [];

  constructor(private readonly up: UpAt = FLAT_UP) {}

  /**
   * Hangs `subject`'s labels `lift` metres above `object` until the returned function is called. A subject keeps
   * every live anchor: the highest `priority` wins and the newest among equals, so a head bone (priority 1) stays in
   * front of a body (0) that re-anchors with a new lift; removing the winner falls back to the next one.
   */
  anchor(subject: string, object: Object3D, lift = 0, priority = 0) {
    const entry = { object, lift, priority };
    const live = this.anchors.get(subject) ?? [];
    live.push(entry);
    this.anchors.set(subject, live);
    return () => {
      const index = live.indexOf(entry);
      if (index < 0) return;
      live.splice(index, 1);
      if (!live.length) this.anchors.delete(subject);
    };
  }

  /** Where `subject`'s labels hang (world coordinates) into `out`, or null while it has no anchor. */
  anchorPosition(subject: string, out: Vector3): Vector3 | null {
    const entry = this.anchors
      .get(subject)
      ?.reduce((best, next) => (next.priority >= best.priority ? next : best));
    if (!entry) return null;
    entry.object.getWorldPosition(out);
    return out.addScaledVector(this.up(out, lifted), entry.lift);
  }

  /** Shows `contents` under `group`, replacing what that group showed, until the returned function is called. */
  describe(group: string, contents: readonly LabelContent[]) {
    this.groups.set(group, contents);
    this.emit();
    return () => {
      if (this.groups.get(group) !== contents) return;
      this.groups.delete(group);
      this.emit();
    };
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Every label described, in group order. */
  getSnapshot = () => this.snapshot;

  private emit() {
    this.snapshot = [...this.groups.values()].flat();
    this.listeners.forEach((listener) => listener());
  }
}
