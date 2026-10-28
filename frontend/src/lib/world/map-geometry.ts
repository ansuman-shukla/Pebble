/*
 * Flat local geometry (metres, x east, y up, z south) carried through a LocalMapping. On a curved mapping the
 * triangles are split first (longest edge in half) so they follow the planet instead of cutting chords under it.
 */
import { BufferGeometry, Float32BufferAttribute, Vector3 } from 'three';

import type { LocalMapping } from './local-mapping';

/** Longest triangle edge kept on a curved mapping; sags under 1 cm on a 2 km planet. */
const MAX_EDGE = 8;

type Triangle = [Vector3, Vector3, Vector3];

function split(triangle: Triangle, maxEdge: number, out: Triangle[]) {
  const stack = [triangle];
  while (stack.length) {
    const [a, b, c] = stack.pop()!;
    const edges: [number, Vector3, Vector3, Vector3][] = [
      [a.distanceToSquared(b), a, b, c],
      [b.distanceToSquared(c), b, c, a],
      [c.distanceToSquared(a), c, a, b],
    ];
    const [length, p, q, r] = edges.reduce((longest, edge) =>
      edge[0] > longest[0] ? edge : longest,
    );
    if (length <= maxEdge * maxEdge) {
      out.push([a, b, c]);
      continue;
    }
    const middle = p.clone().add(q).multiplyScalar(0.5);
    stack.push([p, middle, r], [middle, q, r]);
  }
}

/** A new geometry (position + normal) with the vertices of `local` mapped; the input is left untouched. */
export function mapGeometry(local: BufferGeometry, mapping: LocalMapping) {
  const source = local.index ? local.toNonIndexed() : local;
  const position = source.getAttribute('position');
  const triangles: Triangle[] = [];
  for (let i = 0; i < position.count; i += 3) {
    const triangle = [0, 1, 2].map((k) =>
      new Vector3().fromBufferAttribute(position, i + k),
    ) as Triangle;
    if (mapping.curved) split(triangle, MAX_EDGE, triangles);
    else triangles.push(triangle);
  }
  if (source !== local) source.dispose();
  const values = new Float32Array(triangles.length * 9);
  const at = new Vector3();
  triangles.flat().forEach((vertex, index) => {
    mapping.toWorld(vertex.x, vertex.y, vertex.z, at);
    at.toArray(values, index * 3);
  });
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(values, 3));
  geometry.computeVertexNormals();
  return geometry;
}
