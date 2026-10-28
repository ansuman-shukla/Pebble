import { Color, type Mesh, type Object3D } from 'three';

const TOLERANCE = 0.004;

/**
 * Replaces baked vertex colours (Polyfork models are flat-shaded vertex colours) zone by zone.
 * Keys are the asset's own palette hex values (its -params.json defaults); geometry is cloned first.
 */
export function recolor(root: Object3D, map: Record<string, string>) {
  const pairs = Object.entries(map).map(
    ([from, to]) => [new Color(from), new Color(to)] as const,
  );
  const current = new Color();
  root.traverse((object) => {
    const mesh = object as Mesh;
    if (!mesh.isMesh || !mesh.geometry.getAttribute('color')) return;
    mesh.geometry = mesh.geometry.clone();
    const colors = mesh.geometry.getAttribute('color');
    for (let i = 0; i < colors.count; i++) {
      current.fromBufferAttribute(colors, i);
      const match = pairs.find(([from]) => distance(from, current) < TOLERANCE);
      if (match) colors.setXYZ(i, match[1].r, match[1].g, match[1].b);
    }
    colors.needsUpdate = true;
  });
}

const distance = (a: Color, b: Color) =>
  Math.abs(a.r - b.r) + Math.abs(a.g - b.g) + Math.abs(a.b - b.b);
