/* The subdivided icosahedron the planet grid is made of (the backend builds the real one; tests and the mock use this). */
import { Vector3 } from 'three';

function icosahedron() {
  const t = (1 + Math.sqrt(5)) / 2;
  const vertices = [
    [-1, t, 0],
    [1, t, 0],
    [-1, -t, 0],
    [1, -t, 0],
    [0, -1, t],
    [0, 1, t],
    [0, -1, -t],
    [0, 1, -t],
    [t, 0, -1],
    [t, 0, 1],
    [-t, 0, -1],
    [-t, 0, 1],
  ].map(([x, y, z]) => new Vector3(x, y, z).normalize());
  const faces = [
    [0, 11, 5],
    [0, 5, 1],
    [0, 1, 7],
    [0, 7, 10],
    [0, 10, 11],
    [1, 5, 9],
    [5, 11, 4],
    [11, 10, 2],
    [10, 7, 6],
    [7, 1, 8],
    [3, 9, 4],
    [3, 4, 2],
    [3, 2, 6],
    [3, 6, 8],
    [3, 8, 9],
    [4, 9, 5],
    [2, 4, 11],
    [6, 2, 10],
    [8, 6, 7],
    [9, 8, 1],
  ];
  return { vertices, faces };
}

/** Subdivided icosahedron: 10·f² + 2 unit vectors and 20·f² triangles, counter-clockwise from outside. */
export function icosphere(frequency: number) {
  const { vertices, faces } = icosahedron();
  const points: number[] = [];
  const index = new Map<string, number>();
  const pointAt = (p: Vector3) => {
    p.normalize();
    const key = `${Math.round(p.x * 1e7)},${Math.round(p.y * 1e7)},${Math.round(p.z * 1e7)}`;
    let found = index.get(key);
    if (found === undefined) {
      found = points.length / 3;
      points.push(p.x, p.y, p.z);
      index.set(key, found);
    }
    return found;
  };
  const triangles: number[] = [];
  const ab = new Vector3();
  const ac = new Vector3();
  for (const face of faces) {
    const a = vertices[face[0]];
    let [b, c] = [vertices[face[1]], vertices[face[2]]];
    if (ab.subVectors(b, a).cross(ac.subVectors(c, a)).dot(a) < 0)
      [b, c] = [c, b];
    const grid: number[][] = [];
    for (let i = 0; i <= frequency; i++) {
      grid.push([]);
      for (let j = 0; i + j <= frequency; j++) {
        const p = a
          .clone()
          .addScaledVector(ab.subVectors(b, a), i / frequency)
          .addScaledVector(ac.subVectors(c, a), j / frequency);
        grid[i].push(pointAt(p));
      }
    }
    for (let i = 0; i < frequency; i++) {
      for (let j = 0; i + j < frequency; j++) {
        triangles.push(grid[i][j], grid[i + 1][j], grid[i][j + 1]);
        if (i + j + 1 < frequency)
          triangles.push(grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]);
      }
    }
  }
  return {
    positions: new Float32Array(points),
    triangles: new Uint32Array(triangles),
  };
}
