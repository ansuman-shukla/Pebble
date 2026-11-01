/*
 * Props that move on their own (10 §5.3): the `tick` loop many Polyfork models carry (a mill wheel, tree crowns,
 * rack sheaves, a well's rope, a bell striker, torch flames, fumarole billows), baked once per model and played on
 * the instanced parts, and the shared clock every living prop reads. Clips play at natural speed × `visualRate`,
 * so a paused clock stills them and past ×10 they keep that cadence (D83); loops that are wind sway (tree crowns,
 * reeds, cloth, ropes) play on wind time, × `windRate`.
 */
import {
  type AnimationClip,
  AnimationMixer,
  DataTexture,
  FloatType,
  Matrix4,
  type Object3D,
  Quaternion,
  RGBAFormat,
  Vector3,
} from 'three';

import { START_MINUTES } from './game-clock';
import type { VertexChunk } from './vertex-chunks';
import { visualRate, windRate } from './visual-rate';
import { setWind } from './wind';

/** Clips play for instances within this distance of the camera ... */
export const CLIP_REACH = 120;
/** ... the nearest this many a frame (kinds that always move don't count). */
export const CLIP_BUDGET = 64;
/** The nearest instances are picked again this often (seconds): they change slowly. */
const REPICK = 0.25;
/** A clip is sampled this many times a second of its length (Polyfork bakes theirs at 24 fps) ... */
const SAMPLE_RATE = 24;
/** ... at most this many times. */
const MAX_SAMPLES = 256;
/** Floats per sample: position, quaternion, scale. */
const FLOATS = 10;
/** A frame longer than this (a hidden tab) advances the clock no further. */
const MAX_FRAME = 0.1;

/** A loop baked for some meshes of a model: each mesh's move from its rest pose, at evenly spaced times. */
export interface ClipTrack {
  /** Seconds of one loop at natural speed. */
  duration: number;
  samples: number;
  /** One array per mesh: `samples` × (position, quaternion, scale) of the move. */
  moves: Float32Array[];
}

const move = new Matrix4();
const position = new Vector3();
const turn = new Quaternion();
const nextTurn = new Quaternion();
const scale = new Vector3();

/**
 * Bakes `clip` on `root` (a private copy: it is left posed) for `meshes` inside it: at each sample the mesh's
 * model-space matrix times the inverse of its rest matrix, so a part whose geometry was baked at rest is moved
 * by `placement × move`.
 */
export function bakeClip(
  root: Object3D,
  clip: AnimationClip,
  meshes: Object3D[],
): ClipTrack {
  root.updateMatrixWorld(true);
  const toModel = root.matrixWorld.clone().invert();
  const relative = (mesh: Object3D, target: Matrix4) =>
    target.multiplyMatrices(toModel, mesh.matrixWorld);
  const rests = meshes.map((mesh) => relative(mesh, new Matrix4()).invert());
  const samples = Math.min(
    MAX_SAMPLES,
    Math.max(2, Math.ceil(clip.duration * SAMPLE_RATE)),
  );
  const moves = meshes.map(() => new Float32Array(samples * FLOATS));
  const mixer = new AnimationMixer(root);
  mixer.clipAction(clip).play();
  for (let sample = 0; sample < samples; sample++) {
    mixer.setTime((sample / samples) * clip.duration);
    root.updateMatrixWorld(true);
    meshes.forEach((mesh, index) => {
      relative(mesh, move)
        .multiply(rests[index])
        .decompose(position, turn, scale);
      const at = sample * FLOATS;
      position.toArray(moves[index], at);
      turn.toArray(moves[index], at + 3);
      scale.toArray(moves[index], at + 7);
    });
  }
  mixer.stopAllAction();
  mixer.uncacheRoot(root);
  return { duration: clip.duration, samples, moves };
}

/** The move of mesh `index` of `track` at `time` seconds into the loop (wraps; blends neighbouring samples). */
export function sampleClip(
  track: ClipTrack,
  index: number,
  time: number,
  target: Matrix4,
): Matrix4 {
  const { duration, samples } = track;
  const moves = track.moves[index];
  const loop = ((time % duration) + duration) % duration;
  const at = (loop / duration) * samples;
  const from = Math.floor(at) % samples;
  const to = (from + 1) % samples;
  const blend = at - Math.floor(at);
  const [a, b] = [from * FLOATS, to * FLOATS];
  const mix = (offset: number) =>
    moves[a + offset] + (moves[b + offset] - moves[a + offset]) * blend;
  position.set(mix(0), mix(1), mix(2));
  turn.fromArray(moves, a + 3);
  nextTurn.fromArray(moves, b + 3);
  turn.slerp(nextTurn, blend);
  scale.set(mix(7), mix(8), mix(9));
  return target.compose(position, turn, scale);
}

const PART_MOVE_COMMON = /* glsl */ `
uniform highp sampler2D partMoves;
attribute float partIndex;
mat4 partMove() {
  int part = int(partIndex + 0.5);
  if (part == 0) return mat4(1.0);
  int x = (part - 1) * 4;
#ifdef USE_INSTANCING
  int y = gl_InstanceID;
#else
  int y = 0;
#endif
  return mat4(
    texelFetch(partMoves, ivec2(x, y), 0),
    texelFetch(partMoves, ivec2(x + 1, y), 0),
    texelFetch(partMoves, ivec2(x + 2, y), 0),
    texelFetch(partMoves, ivec2(x + 3, y), 0)
  );
}
`;

/**
 * The moves of a model's moving parts for each of its instances, so a whole model draws in one call: a float
 * texture with a row per instance and four texels (a matrix's columns) per moving part, read in the vertex
 * shader by the part's `partIndex` (0 = still, n = moving part n). Every move starts as the identity (at rest).
 */
export class PartMoves {
  readonly texture: DataTexture;
  private readonly data: Float32Array;
  private readonly width: number;
  private dirty = false;

  constructor(
    readonly parts: number,
    count: number,
  ) {
    this.width = parts * 4;
    this.data = new Float32Array(this.width * count * 4);
    const identity = new Matrix4().elements;
    for (let at = 0; at < this.data.length; at += 16)
      this.data.set(identity, at);
    this.texture = new DataTexture(
      this.data,
      this.width,
      count,
      RGBAFormat,
      FloatType,
    );
    this.texture.needsUpdate = true;
  }

  /** Moves part `part` (0-based among the moving parts) of instance `instance` by `move` (model space). */
  set(instance: number, part: number, move: Matrix4) {
    this.data.set(move.elements, (instance * this.width + part * 4) * 4);
    this.dirty = true;
  }

  /** The move part `part` of instance `instance` has now. */
  get(instance: number, part: number, target: Matrix4) {
    return target.fromArray(this.data, (instance * this.width + part * 4) * 4);
  }

  /** Sends this frame's moves to the GPU, if any changed. */
  flush() {
    if (!this.dirty) return;
    this.texture.needsUpdate = true;
    this.dirty = false;
  }

  /** The vertex chunk that applies these moves (vertex-chunks.ts). */
  chunk(): VertexChunk {
    return {
      key: 'part-moves',
      uniforms: { partMoves: { value: this.texture } },
      common: PART_MOVE_COMMON,
      normal: 'objectNormal = mat3(partMove()) * objectNormal;',
      position: 'transformed = (partMove() * vec4(transformed, 1.0)).xyz;',
    };
  }

  dispose() {
    this.texture.dispose();
  }
}

/** Where in its loop an instance starts (seconds), from its id: neighbours don't sway in step. */
export function clipPhase(id: string, duration: number) {
  let hash = 2166136261;
  for (let i = 0; i < id.length; i++)
    hash = Math.imul(hash ^ id.charCodeAt(i), 16777619);
  return ((hash >>> 0) / 4294967296) * duration;
}

/** The indices of the nearest `max` distances within `reach`, nearest first. */
export function nearestWithin(
  distances: ArrayLike<number>,
  reach: number,
  max: number,
) {
  const within: number[] = [];
  for (let i = 0; i < distances.length; i++)
    if (distances[i] < reach) within.push(i);
  return within.sort((a, b) => distances[a] - distances[b]).slice(0, max);
}

/**
 * Shares the clip budget between kinds: every kind offers its instances' distances each frame and plays the ones
 * it was given, picked from the latest offers every REPICK seconds (the nearest CLIP_BUDGET within CLIP_REACH).
 */
export class ClipBudget {
  private offers = new Map<string, ArrayLike<number>>();
  private picks = new Map<string, number[]>();
  private pickedAt = -Infinity;

  constructor(
    private readonly reach = CLIP_REACH,
    private readonly max = CLIP_BUDGET,
  ) {}

  offer(key: string, distances: ArrayLike<number>) {
    this.offers.set(key, distances);
  }

  forget(key: string) {
    this.offers.delete(key);
    this.picks.delete(key);
  }

  /** The instances of `key` that play now (`now` in seconds). */
  picked(key: string, now: number): readonly number[] {
    if (now - this.pickedAt >= REPICK || now < this.pickedAt) this.pick(now);
    return this.picks.get(key) ?? [];
  }

  private pick(now: number) {
    this.pickedAt = now;
    const keys = [...this.offers.keys()];
    const owners: number[] = [];
    const indices: number[] = [];
    const distances: number[] = [];
    keys.forEach((key, owner) => {
      const offered = this.offers.get(key)!;
      for (let i = 0; i < offered.length; i++) {
        owners.push(owner);
        indices.push(i);
        distances.push(offered[i]);
      }
    });
    this.picks = new Map(keys.map((key) => [key, []]));
    for (const at of nearestWithin(distances, this.reach, this.max))
      this.picks.get(keys[owners[at]])!.push(indices[at]);
  }
}

/** What living props read of the world, written by the page (LivingProps) and advanced once a frame. */
export interface PropWorld {
  /** The clock's rate: game seconds per real second (0 while paused). Pages without a clock run at ×1. */
  rate: number;
  /** Town time in game minutes (drives the wind of the day). */
  minutes: number;
  /** Seconds of clip played so far (real seconds × visualRate). */
  clipTime: number;
  /** Seconds of wind played so far (real seconds × windRate). */
  windTime: number;
  /** Where the citizens' feet are drawn (world metres), by id. */
  people: ReadonlyMap<string, Vector3>;
  /** The live fires as drawn, by id: lit or not, and where (world metres). */
  fires: ReadonlyMap<string, { lit: boolean; position: Vector3 }>;
  /** The citizens shown crafting now (at the anvil, the loom...), by id: their feet are in `people`. */
  crafters: ReadonlySet<string>;
  /**
   * The hearths' chimneys (a forge's), by `placement:chimney`: whether the hearth burns, how hot (1 worked … 0 cold)
   * and the chimney's top (world metres), for the smoke. Written by the hearths themselves (living-kind.ts).
   */
  chimneys: Map<string, { lit: boolean; strength: number; position: Vector3 }>;
  /** `placement:node` → whether a dressing part shows (a stall's `crates`, …); unlisted parts show. */
  dressing: Map<string, boolean>;
  /** "Up" where the camera is, for the wind to blow across (null: a flat page, +y). */
  up: Vector3 | null;
  /** The scene clock's elapsed time at the last advance. */
  elapsed: number;
}

export const propWorld: PropWorld = {
  rate: 1,
  minutes: START_MINUTES,
  clipTime: 0,
  windTime: 0,
  people: new Map(),
  fires: new Map(),
  crafters: new Set(),
  chimneys: new Map(),
  dressing: new Map(),
  up: null,
  elapsed: Number.NaN,
};

/**
 * Advances the prop clock to the scene clock's `elapsed` seconds; every living prop calls it first in its frame,
 * so it moves once a frame whoever calls first.
 */
export function advanceProps(elapsed: number) {
  if (elapsed === propWorld.elapsed) return;
  const delta = Number.isNaN(propWorld.elapsed)
    ? 0
    : Math.min(Math.max(elapsed - propWorld.elapsed, 0), MAX_FRAME);
  propWorld.elapsed = elapsed;
  propWorld.clipTime += delta * visualRate(propWorld.rate);
  propWorld.windTime += delta * windRate(propWorld.rate);
  propWorld.minutes += (delta * propWorld.rate) / 60;
  setWind(propWorld.minutes, propWorld.windTime, propWorld.up ?? undefined);
}

/**
 * Shows or hides a named part of one placement (dressing by stock: a stall's `crates`, a chest's `lid`, a rack's
 * sheaves), e.g. `dressPart('market-stall', 'crates', false)` when the stall is empty.
 */
export function dressPart(placement: string, node: string, shown: boolean) {
  propWorld.dressing.set(`${placement}:${node}`, shown);
}

/** What the page's test hooks read of living props, kept up to date by the props themselves. */
export const propViews = {
  /** Instances whose loop plays now, by the kind group that plays them. */
  playing: new Map<string, { kind: string; count: number }>(),
  /** Placement id → how far (radians) its first looping part is turned from rest now: the mill wheel's angle. */
  turns: new Map<string, number>(),
  /** Placement ids whose doors stand open now (even partly). */
  openDoors: new Set<string>(),
  /** `placement:node` of the parts hidden now (a cold fire's `flame`). */
  hidden: new Set<string>(),
  /** Placement id → how hot its hearth is now (1 worked … 0 cold), for the hearths drawn. */
  hearths: new Map<string, number>(),
  /** Smoke puffs and sparks drawn now. */
  puffs: 0,
  sparks: 0,
};
