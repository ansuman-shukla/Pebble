import type { Group } from 'three';

/** Registry of scene label anchors and their DOM elements (see components/world/labels.tsx). */
export interface LabelEntry {
  id: string;
  text: string;
  anchor: Group;
  /** A name tag (default) or a speech bubble (white, wraps long text). */
  kind?: 'name' | 'speech';
}

export class LabelStore {
  readonly elements = new Map<string, HTMLElement>();
  private entries = new Map<string, LabelEntry>();
  private listeners = new Set<() => void>();
  private snapshot: LabelEntry[] = [];

  add(entry: LabelEntry) {
    this.entries.set(entry.id, entry);
    this.emit();
    return () => {
      this.entries.delete(entry.id);
      this.emit();
    };
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = () => this.snapshot;

  private emit() {
    this.snapshot = [...this.entries.values()];
    this.listeners.forEach((listener) => listener());
  }
}
