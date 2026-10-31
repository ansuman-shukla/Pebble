import { useGLTF } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import { InstancedMesh, type Matrix4, type Object3D } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import { assetUrl } from '@/lib/world/assets';
import { proceduralScene } from '@/lib/world/procedural-props';

/**
 * One instanced mesh per part of a model's scene, placed at fixed matrices. A part that sways or waves (a banner's
 * cloth) keeps the wind on its colour and shadow materials (kind-parts, wind.ts).
 */
function useSceneInstances(scene: Object3D, id: string, matrices: Matrix4[]) {
  const meshes = useMemo(() => {
    // the parts are baked into model space, so each instance's matrix is the model's
    return kindParts(scene, id).map(({ geometry, material, depthMaterial }) => {
      const mesh = new InstancedMesh(geometry, material, matrices.length);
      matrices.forEach((matrix, i) => mesh.setMatrixAt(i, matrix));
      if (depthMaterial) mesh.customDepthMaterial = depthMaterial;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.computeBoundingSphere();
      return mesh;
    });
  }, [scene, id, matrices]);
  // the geometry and material belong to the shared model (kind-parts); only the instance buffers are ours
  useEffect(() => () => meshes.forEach((mesh) => mesh.dispose()), [meshes]);
  return meshes;
}

/** A vendored model's instances at fixed matrices. */
export function useFixedInstances(id: string, matrices: Matrix4[]) {
  const { scene } = useGLTF(assetUrl(id));
  return useSceneInstances(scene, id, matrices);
}

/** A prop drawn from code (procedural-props.ts), its instances at fixed matrices. */
export function useProceduralInstances(id: string, matrices: Matrix4[]) {
  return useSceneInstances(proceduralScene(id), id, matrices);
}
