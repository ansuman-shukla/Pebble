/*
 * Wild kinds drawn instanced in distance tiers around the camera's focus (decor and nodes): one InstancedMesh per
 * merged part of a kind (kind-parts.ts, one per material) and tier, sized for the most instances a tier holds.
 */
import { InstancedMesh, type Material, type Matrix4 } from 'three';

import type { KindModel } from '@/components/world/kind-parts';

export type KindPart = KindModel['parts'][number];

/** Colour and shadow materials for a part's meshes (default: the part's own, shared: never dispose them). */
export type PartLooks = (part: KindPart) => {
  material: Material;
  depthMaterial?: Material;
};

const sharedLooks: PartLooks = ({ material, depthMaterial }) => ({
  material,
  depthMaterial,
});

/** One hidden, empty instanced mesh per part, casting shadows or not. */
export function tierMeshes(
  parts: readonly KindPart[],
  capacity: number,
  shadow: boolean,
  looks: PartLooks = sharedLooks,
) {
  return parts.map((part) => {
    const { material, depthMaterial } = looks(part);
    const mesh = new InstancedMesh(part.geometry, material, capacity);
    if (depthMaterial) mesh.customDepthMaterial = depthMaterial;
    mesh.count = 0;
    mesh.visible = false;
    mesh.castShadow = shadow;
    mesh.receiveShadow = true;
    return mesh;
  });
}

/** Draws `models` (instance matrices) with every part's mesh; an empty mesh is hidden (it would still cost a call). */
export function fillMeshes(
  meshes: readonly InstancedMesh[],
  models: readonly Matrix4[],
) {
  for (const mesh of meshes) {
    const count = Math.min(models.length, mesh.instanceMatrix.count);
    for (let i = 0; i < count; i++) mesh.setMatrixAt(i, models[i]);
    mesh.count = count;
    mesh.visible = count > 0;
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }
}

export function hideMeshes(meshes: readonly InstancedMesh[]) {
  for (const mesh of meshes) mesh.visible = false;
}
