import { Vector3 } from 'three';

import type { WalkSpawn } from '@/lib/world/collision';

/** The player's live pose, mutated every frame by the player and read by the cameras. */
export interface PlayerState {
  position: Vector3;
  /** Radians, three.js rotation.y (0 = facing +z). */
  heading: number;
}

/** What pages get about the player, about 10 times a second. */
export interface PlayerMove {
  x: number;
  y: number;
  z: number;
  heading_deg: number;
}

export const createPlayerState = (spawn: WalkSpawn): PlayerState => ({
  position: new Vector3(spawn.x, 0, spawn.z),
  heading: (spawn.heading_deg * Math.PI) / 180,
});

/** Where the cameras look at the player: about head height. */
export const PLAYER_EYE_HEIGHT = 1.4;
