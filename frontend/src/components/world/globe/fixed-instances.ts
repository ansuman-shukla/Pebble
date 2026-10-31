import { useGLTF } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import { InstancedMesh, type Matrix4 } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import { assetUrl } from '@/lib/world/assets';

/** One instanced mesh per part of a kind's model, placed at fixed matrices. */
export function useFixedInstances(id: string, matrices: Matrix4[]) {
  const { scene } = useGLTF(assetUrl(id));
  const meshes = useMemo(() => {
    // the parts are baked into model space, so each instance's matrix is the model's
    return kindParts(scene, id).map(({ geometry, material }) => {
      const mesh = new InstancedMesh(geometry, material, matrices.length);
      matrices.forEach((matrix, i) => mesh.setMatrixAt(i, matrix));
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
