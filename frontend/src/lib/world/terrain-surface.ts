/*
 * The rendered terrain surface. Every grid triangle is split into DIVISIONS² flat faces whose corners lie on a
 * smooth height patch through the cell heights: a quadratic triangle over the three cell heights and one height
 * per grid edge middle (bent a little towards the curvature its two opposite cells suggest, never past a
 * quarter of the edge's rise, so flats such as lakes and plateaus stay exactly flat and an edge never dips or
 * bulges past its ends). Edge middles are shared by the two triangles of an edge, so the patches meet without
 * cracks. The mesh (globe-mesh.ts) and the height lookup (globe.ts) both place faces through `vertex`, so the
 * walker stands exactly on what is drawn.
 */
import type { Globe } from './globe';

/** Faces per grid triangle edge. */
const SURFACE_DIVISIONS = 4;
/** How far an edge middle bends by (a + b − c − d) (a, b its ends; c, d the cells facing it). */
const BEND = 1 / 8;

export interface TerrainSurface {
  divisions: number;
  edgeCount: number;
  /** Edge ids of each triangle, edges AB, BC, CA of its corners A, B, C. */
  triangleEdges: Uint32Array;
  /** The two cells of each edge, lower index first. */
  edgeCells: Uint32Array;
  /** Surface height on grid triangle `t` at barycentric weights (corners A, B, C). */
  height(t: number, b0: number, b1: number, b2: number): number;
  /**
   * The face corner at lattice point (i, j) of triangle `t` (weights (N − i − j, i, j) / N on A, B, C):
   * writes its world position into `out` at `offset`.
   */
  vertex(
    t: number,
    i: number,
    j: number,
    out: Float32Array | Float64Array,
    offset: number,
  ): void;
}

export function createSurface(
  globe: Globe,
  divisions = SURFACE_DIVISIONS,
): TerrainSurface {
  const { positions, heights, triangles, cellCount, radius } = globe;
  const triangleCount = triangles.length / 3;
  const triangleEdges = new Uint32Array(triangleCount * 3);
  const edgeIds = new Map<number, number>();
  const ends: number[] = [];
  const facing: number[] = [];
  for (let t = 0; t < triangleCount; t++) {
    for (let k = 0; k < 3; k++) {
      const a = triangles[t * 3 + k];
      const b = triangles[t * 3 + ((k + 1) % 3)];
      const opposite = triangles[t * 3 + ((k + 2) % 3)];
      const [low, high] = a < b ? [a, b] : [b, a];
      const key = low * cellCount + high;
      let edge = edgeIds.get(key);
      if (edge === undefined) {
        edge = ends.length / 2;
        edgeIds.set(key, edge);
        ends.push(low, high);
        facing.push(opposite, opposite);
      } else facing[edge * 2 + 1] = opposite;
      triangleEdges[t * 3 + k] = edge;
    }
  }
  const edgeCount = ends.length / 2;
  const edgeCells = Uint32Array.from(ends);
  const edgeFacing = Uint32Array.from(facing);

  /** Surface height at an edge's middle (read from the current heights, so a caller may still shape them). */
  function middle(e: number) {
    const a = heights[edgeCells[e * 2]];
    const b = heights[edgeCells[e * 2 + 1]];
    const bent =
      (a + b) / 2 +
      BEND *
        (a + b - heights[edgeFacing[e * 2]] - heights[edgeFacing[e * 2 + 1]]);
    const low = Math.min(a, b);
    const high = Math.max(a, b);
    return Math.min(Math.max(bent, (3 * low + high) / 4), (low + 3 * high) / 4);
  }

  function height(t: number, b0: number, b1: number, b2: number) {
    const hA = heights[triangles[t * 3]];
    const hB = heights[triangles[t * 3 + 1]];
    const hC = heights[triangles[t * 3 + 2]];
    const mAB = middle(triangleEdges[t * 3]);
    const mBC = middle(triangleEdges[t * 3 + 1]);
    const mCA = middle(triangleEdges[t * 3 + 2]);
    return (
      hA * b0 * (2 * b0 - 1) +
      hB * b1 * (2 * b1 - 1) +
      hC * b2 * (2 * b2 - 1) +
      4 * (mAB * b0 * b1 + mBC * b1 * b2 + mCA * b2 * b0)
    );
  }

  function vertex(
    t: number,
    i: number,
    j: number,
    out: Float32Array | Float64Array,
    offset: number,
  ) {
    const b1 = i / divisions;
    const b2 = j / divisions;
    const b0 = (divisions - i - j) / divisions;
    const a = triangles[t * 3] * 3;
    const b = triangles[t * 3 + 1] * 3;
    const c = triangles[t * 3 + 2] * 3;
    const x = b0 * positions[a] + b1 * positions[b] + b2 * positions[c];
    const y =
      b0 * positions[a + 1] + b1 * positions[b + 1] + b2 * positions[c + 1];
    const z =
      b0 * positions[a + 2] + b1 * positions[b + 2] + b2 * positions[c + 2];
    const scale = (radius + height(t, b0, b1, b2)) / Math.hypot(x, y, z);
    out[offset] = x * scale;
    out[offset + 1] = y * scale;
    out[offset + 2] = z * scale;
  }

  return {
    divisions,
    edgeCount,
    triangleEdges,
    edgeCells,
    height,
    vertex,
  };
}
