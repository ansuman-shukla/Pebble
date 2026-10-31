/*
 * Nodes drawn by their stage (10 §1.1, §5.2): what is said of a node is what is drawn. A float texture holds a row
 * per instance (pieces shown, level, growth, tint; ROW_WIDTH rows a line), read in the vertex shader by
 * gl_InstanceID, so every stage of a kind draws in the same call:
 *   - pieces: the model's stage pieces (`fruit-N`, `leaf-N`, ...: kind-parts.ts `stagePiece`) past the count shown
 *     collapse to nothing;
 *   - level: the model is flattened to that fraction of its height (a deadwood pile, a log stack);
 *   - growth: the model is drawn that tall (reeds cut down, a seam's heap worked down to rubble);
 *   - tint: its colours turn towards dug earth (a dug-out root patch).
 * `nodeStage` turns a node's stock into these numbers, per node kind.
 */
import { Color, DataTexture, FloatType, RGBAFormat } from 'three';

import type { VertexChunk } from './vertex-chunks';

/** Rows per texture line: the texture is ROW_WIDTH × ⌈count / ROW_WIDTH⌉ (WebGL caps a side at 4096 or so). */
export const ROW_WIDTH = 64;

export interface Stage {
  /** Stage pieces shown (pieces ranked past it collapse). */
  pieces: number;
  /** Fraction of the model's height kept (1: whole). */
  level: number;
  /** Height factor (1: full grown). */
  growth: number;
  /** 0..1 towards DUG_EARTH. */
  tint: number;
}

/** Every piece, whole, full grown, its own colours. */
export const FULL_STAGE: Stage = { pieces: 1e4, level: 1, growth: 1, tint: 0 };

/** The colour a dug-out patch turns to. */
const DUG_EARTH = new Color('#6b4a2e');
/** Reeds cut to the ground still show their stubble. */
const REED_STUBBLE = 0.12;
/** A seam's heap by stock: whole above 3/4, then 3/4, 1/2, and rubble when worked out (10 §1.1). */
const SEAM_HEAPS: [number, number][] = [
  [0.75, 1],
  [0.5, 0.75],
  [0, 0.5],
];
const SEAM_RUBBLE = 0.2;

/**
 * How a node of kind `node` with `fill` = stock / cap (0..1) is drawn, for a look with `pieces` stage pieces.
 * Kinds without a drawn stage (standing trees: their stages are looks, nodes.tsx) are drawn full.
 */
export function nodeStage(node: string, fill: number, pieces: number): Stage {
  const f = Math.min(Math.max(fill, 0), 1);
  switch (node) {
    case 'berry_bush': {
      // round(8 × stock / cap) of 8 (10 §1.1), shown over the model's own fruit pieces
      const eighths = Math.round(8 * f);
      return { ...FULL_STAGE, pieces: Math.round((pieces * eighths) / 8) };
    }
    case 'root_patch':
      // leafy, thinning, dug earth
      return {
        ...FULL_STAGE,
        pieces: Math.ceil(pieces * f),
        tint: f === 0 ? 1 : 0,
      };
    case 'reed_bed':
      // ⌈5 × stock / cap⌉ of 5 reeds shown, as the bed's height
      return {
        ...FULL_STAGE,
        growth: Math.max(Math.ceil(5 * f) / 5, REED_STUBBLE),
      };
    case 'deadwood':
      return { ...FULL_STAGE, level: f };
    case 'flint_seam':
    case 'obsidian_field': {
      const heap = SEAM_HEAPS.find(([above]) => f > above);
      return { ...FULL_STAGE, growth: heap ? heap[1] : SEAM_RUBBLE };
    }
    default:
      return FULL_STAGE;
  }
}

const STAGE_COMMON = /* glsl */ `
uniform highp sampler2D nodeStages;
uniform float stageHeight;
uniform vec3 stageTint;
#ifdef STAGE_PIECES
attribute float stagePiece;
#endif
vec4 nodeStage() {
#ifdef USE_INSTANCING
  return texelFetch(nodeStages, ivec2(gl_InstanceID % ${ROW_WIDTH}, gl_InstanceID / ${ROW_WIDTH}), 0);
#else
  return vec4(1e4, 1.0, 1.0, 0.0);
#endif
}
`;

const STAGE_POSITION = /* glsl */ `
vec4 shownStage = nodeStage();
#ifdef STAGE_PIECES
if (stagePiece > shownStage.x + 0.5) transformed = vec3(0.0);
#endif
transformed.y = min(transformed.y, shownStage.y * stageHeight) * shownStage.z;
#ifdef USE_COLOR
vColor.rgb = mix(vColor.rgb, stageTint, shownStage.w);
#endif
`;

/** The stages of a kind's instances in one tier: a row per instance, every row full until set. */
export class StageTexture {
  readonly texture: DataTexture;
  private readonly data: Float32Array;
  private dirty = false;

  constructor(readonly count: number) {
    const lines = Math.ceil(count / ROW_WIDTH);
    this.data = new Float32Array(ROW_WIDTH * lines * 4);
    for (let i = 0; i < ROW_WIDTH * lines; i++) this.write(i, FULL_STAGE);
    this.texture = new DataTexture(
      this.data,
      ROW_WIDTH,
      lines,
      RGBAFormat,
      FloatType,
    );
    this.texture.needsUpdate = true;
  }

  private write(instance: number, stage: Stage) {
    this.data.set(
      [stage.pieces, stage.level, stage.growth, stage.tint],
      instance * 4,
    );
  }

  set(instance: number, stage: Stage) {
    this.write(instance, stage);
    this.dirty = true;
  }

  /** The stage instance `instance` is drawn with. */
  get(instance: number): Stage {
    const [pieces, level, growth, tint] = this.data.subarray(
      instance * 4,
      instance * 4 + 4,
    );
    return { pieces, level, growth, tint };
  }

  /** Sends the rows set since the last flush to the GPU. */
  flush() {
    if (!this.dirty) return;
    this.texture.needsUpdate = true;
    this.dirty = false;
  }

  /** The vertex chunk that draws these stages, for a model `height` metres tall, with stage pieces or not. */
  chunk(height: number, pieces: boolean): VertexChunk {
    return {
      key: pieces ? 'node-stage-pieces' : 'node-stage',
      defines: pieces ? { STAGE_PIECES: '' } : {},
      uniforms: {
        nodeStages: { value: this.texture },
        stageHeight: { value: height },
        stageTint: { value: DUG_EARTH },
      },
      common: STAGE_COMMON,
      position: STAGE_POSITION,
    };
  }

  dispose() {
    this.texture.dispose();
  }
}
