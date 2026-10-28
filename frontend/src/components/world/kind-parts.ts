import type { BufferGeometry, Material, Matrix4, Mesh, Object3D } from 'three';

import { openDoors } from '@/lib/world/doors';

/** One sub-mesh of a kind's GLB: drawn once per instance with its transform inside the model baked in. */
export interface KindPart {
  geometry: BufferGeometry;
  material: Material;
  inModel: Matrix4;
}

/** The sub-meshes of a loaded model, doors opened first like the walker's colliders. */
export function kindParts(scene: Object3D, id: string): KindPart[] {
  const source = scene.clone(true);
  openDoors(source, id);
  source.updateMatrixWorld(true);
  const parts: KindPart[] = [];
  source.traverse((object) => {
    const mesh = object as Mesh;
    if (mesh.isMesh)
      parts.push({
        geometry: mesh.geometry,
        material: mesh.material as Material,
        inModel: mesh.matrixWorld.clone(),
      });
  });
  return parts;
}
