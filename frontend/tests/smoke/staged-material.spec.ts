import { expect, test } from '@playwright/test';

/*
 * The staged material's shader on a real GPU: 128 instanced squares in a 16 × 8 grid, each reading its own stage
 * row (rows lie 64 to a texture line), so instances past the first line must read the second line, not the first.
 */

/** Renders the grid with pieces shown = 9 for instances in `shown`, 0 for the rest; returns which are drawn. */
const RENDER = `(async () => {
  const source = await (await fetch('/src/lib/world/staged-material.ts')).text();
  const threeUrl = /from "([^"]*three\\.js[^"]*)"/.exec(source)[1];
  const THREE = await import(threeUrl);
  const { StageTexture } = await import('/src/lib/world/staged-material.ts');
  const { withChunks } = await import('/src/lib/world/vertex-chunks.ts');
  const COLUMNS = 16, COUNT = 128, SIZE = 8;
  const canvas = document.createElement('canvas');
  canvas.width = COLUMNS * SIZE;
  canvas.height = (COUNT / COLUMNS) * SIZE;
  const renderer = new THREE.WebGLRenderer({ canvas, preserveDrawingBuffer: true });
  const geometry = new THREE.PlaneGeometry(0.8, 0.8);
  geometry.setAttribute('stagePiece', new THREE.Float32BufferAttribute(new Float32Array(geometry.attributes.position.count).fill(1), 1));
  const rows = new StageTexture(COUNT);
  const material = withChunks(new THREE.MeshBasicMaterial({ color: 0xffffff }), [rows.chunk(10, true)]);
  const mesh = new THREE.InstancedMesh(geometry, material, COUNT);
  const matrix = new THREE.Matrix4();
  const shown = (i) => i % 3 === 0;
  for (let i = 0; i < COUNT; i++) {
    mesh.setMatrixAt(i, matrix.makeTranslation((i % COLUMNS) + 0.5, Math.floor(i / COLUMNS) + 0.5, 0));
    rows.set(i, { pieces: shown(i) ? 9 : 0, level: 1, growth: 1, tint: 0 });
  }
  rows.flush();
  const scene = new THREE.Scene();
  scene.add(mesh);
  const camera = new THREE.OrthographicCamera(0, COLUMNS, COUNT / COLUMNS, 0, -1, 1);
  renderer.render(scene, camera);
  const gl = renderer.getContext();
  const pixels = new Uint8Array(4);
  const drawn = [];
  for (let i = 0; i < COUNT; i++) {
    const x = (i % COLUMNS) * SIZE + SIZE / 2;
    const y = Math.floor(i / COLUMNS) * SIZE + SIZE / 2;
    gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    drawn.push(pixels[0] > 128);
  }
  renderer.dispose();
  return { drawn, expected: Array.from({ length: COUNT }, (_, i) => shown(i)) };
})()`;

test('every instance reads its own stage row, past the first line of the texture too', async ({
  page,
}) => {
  await page.goto('/status');
  const { drawn, expected } = await page.evaluate<{
    drawn: boolean[];
    expected: boolean[];
  }>(RENDER);
  expect(drawn.slice(64)).toEqual(expected.slice(64));
  expect(drawn).toEqual(expected);
});
