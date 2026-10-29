import type { Doing } from './drawn-track';

/*
 * What each drawn citizen is shown doing (`drawn-track.ts` shownDoing): written by the bodies in the scene, read by
 * their labels outside it, so a label says what the body does, not what the feed already says (D100): a walker's
 * label says "walking …" until the drawn body gets where its tick ended.
 */
export class ShownDoings {
  private doings = new Map<string, Doing>();
  private listeners = new Set<() => void>();
  private snapshot: ReadonlyMap<string, Doing> = new Map();

  /** Shows citizen `id` doing `doing` until the returned function is called (or another doing replaces it). */
  show(id: string, doing: Doing) {
    this.doings.set(id, doing);
    this.emit();
    return () => {
      if (this.doings.get(id) !== doing) return;
      this.doings.delete(id);
      this.emit();
    };
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Each shown citizen's doing, by citizen id (a new map after every change). */
  getSnapshot = () => this.snapshot;

  private emit() {
    this.snapshot = new Map(this.doings);
    this.listeners.forEach((listener) => listener());
  }
}
