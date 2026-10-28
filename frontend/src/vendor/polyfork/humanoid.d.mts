import type { Group } from 'three';

/** One garment: a WARDROBE name, optionally with that garment's own options. */
export type Garment = string | ({ name: string } & Record<string, unknown>);

export type WearSlot =
  | 'hair'
  | 'eyes'
  | 'face'
  | 'hat'
  | 'top'
  | 'coat'
  | 'bottom'
  | 'feet'
  | 'hands'
  | 'belt'
  | 'neck'
  | 'back'
  | 'lefthand'
  | 'righthand';

export interface CharacterConfig {
  age?: 'kid' | 'teen' | 'adult' | 'old';
  figure?: 'masculine' | 'feminine';
  build?: number;
  expression?: string;
  browScale?: number;
  greyHair?: boolean;
  /** Colour per zone (hex numbers); zones not given use the engine's defaults. */
  palette?: Record<string, number>;
  wear: Partial<Record<WearSlot, Garment>>;
}

/** Polyfork's shared humanoid engine: builds a rigged, Mixamo-named character from a config. */
export function createCharacter(config: CharacterConfig): Group;
