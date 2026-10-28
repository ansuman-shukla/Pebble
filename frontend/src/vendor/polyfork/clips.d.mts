import type { AnimationAction, AnimationMixer, Object3D } from 'three';

export interface CharacterAnimation {
  mixer: AnimationMixer;
  actions: Record<string, AnimationAction>;
  names: string[];
  play(name: string, options?: { fade?: number; loop?: boolean; timeScale?: number }): AnimationAction;
  /** Picks Idle, Walk or Run and paces the feet to the speed (metres per second). */
  locomotion(speed: number): AnimationAction;
  update(delta: number): void;
}

/** Loads Polyfork's humanoid clips (from their CDN) and binds them to a character. */
export function animate(
  character: Object3D,
  options?: { clips?: string[]; inPlace?: boolean; fade?: number },
): Promise<CharacterAnimation>;
