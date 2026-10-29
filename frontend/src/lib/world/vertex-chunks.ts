/*
 * Small vertex shader additions that stack on a built-in three.js material: each chunk declares what it needs
 * (`common`), may turn the normal (`normal`, after `beginnormal_vertex`) and moves the model-space position
 * (`position`, after `begin_vertex`), in the order given. Living props stack the part moves (prop-motion.ts) and
 * the wind (wind.ts).
 */
import type { Material, WebGLProgramParametersWithUniforms } from 'three';

export interface VertexChunk {
  /** Names the chunk in the program cache key: chunks with the same key compile to the same code. */
  key: string;
  defines?: Record<string, string>;
  uniforms: Record<string, { value: unknown }>;
  common: string;
  normal?: string;
  position: string;
}

/** `material` (changed in place: pass a fresh copy) drawn with `chunks` added to its vertex shader. */
export function withChunks<T extends Material>(
  material: T,
  chunks: VertexChunk[],
): T {
  const baseKey = material.customProgramCacheKey();
  material.defines = Object.assign(
    { ...material.defines },
    ...chunks.map((chunk) => chunk.defines ?? {}),
  );
  material.onBeforeCompile = (shader: WebGLProgramParametersWithUniforms) => {
    for (const chunk of chunks) Object.assign(shader.uniforms, chunk.uniforms);
    const join = (part: 'common' | 'normal' | 'position') =>
      chunks.map((chunk) => chunk[part] ?? '').join('\n');
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\n${join('common')}`)
      .replace(
        '#include <beginnormal_vertex>',
        `#include <beginnormal_vertex>\n${join('normal')}`,
      )
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>\n${join('position')}`,
      );
  };
  material.customProgramCacheKey = () =>
    [baseKey, ...chunks.map((chunk) => chunk.key)].join('-');
  return material;
}
