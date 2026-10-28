import { useGLTF } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import {
  type BufferGeometry,
  InstancedMesh,
  type Material,
  Matrix4,
  type Mesh,
  Quaternion,
  Vector3,
} from 'three';

import type { TownPlacement } from '@/lib/client/types.gen';
import { assetBaseY, assetUrl } from '@/lib/world/assets';
import { assetIdForKind } from '@/lib/world/collision';
import { openDoors } from '@/lib/world/doors';

/*
 * Every placement of one kind is drawn as instances: one InstancedMesh per sub-mesh of the kind's GLB, with
 * the sub-mesh's transform inside the model baked into each instance matrix. Doors are opened on the source
 * first and models sit at assetBaseY, exactly like the walker's colliders, so what you see is what blocks you.
 */

/** Kinds lying flat on the ground: their shadows would be invisible, so they skip the shadow pass. */
const FLAT_KINDS = new Set(['rice_paddy', 'paving_tile']);

const Y_AXIS = new Vector3(0, 1, 0);

function placementMatrix(placement: TownPlacement, baseY: number) {
  return new Matrix4().compose(
    new Vector3(placement.x, baseY, placement.z),
    new Quaternion().setFromAxisAngle(
      Y_AXIS,
      (placement.rotation_deg * Math.PI) / 180,
    ),
    new Vector3(1, 1, 1),
  );
}

function KindInstances({
  kind,
  placements,
}: {
  kind: string;
  placements: TownPlacement[];
}) {
  const id = assetIdForKind(kind);
  const { scene } = useGLTF(assetUrl(id));

  const meshes = useMemo(() => {
    const source = scene.clone(true);
    openDoors(source, id);
    source.updateMatrixWorld(true);
    const parts: {
      geometry: BufferGeometry;
      material: Material;
      inModel: Matrix4;
    }[] = [];
    source.traverse((object) => {
      const mesh = object as Mesh;
      if (mesh.isMesh)
        parts.push({
          geometry: mesh.geometry,
          material: mesh.material as Material,
          inModel: mesh.matrixWorld.clone(),
        });
    });
    const baseY = assetBaseY(id);
    const placed = placements.map((placement) =>
      placementMatrix(placement, baseY),
    );
    const matrix = new Matrix4();
    return parts.map(({ geometry, material, inModel }) => {
      const instances = new InstancedMesh(geometry, material, placed.length);
      placed.forEach((placementMatrix, index) =>
        instances.setMatrixAt(
          index,
          matrix.multiplyMatrices(placementMatrix, inModel),
        ),
      );
      instances.computeBoundingSphere();
      instances.castShadow = !FLAT_KINDS.has(kind);
      instances.receiveShadow = true;
      return instances;
    });
  }, [scene, id, kind, placements]);

  // the geometry and material belong to the cached GLB; only the instance buffers are ours
  useEffect(
    () => () => meshes.forEach((instances) => instances.dispose()),
    [meshes],
  );

  return (
    <>
      {meshes.map((instances) => (
        <primitive key={instances.uuid} object={instances} />
      ))}
    </>
  );
}

/** All town placements, grouped by kind; suspends until every GLB is loaded, then calls onReady. */
export function TownPlacements({
  placements,
  onReady,
}: {
  placements: TownPlacement[];
  onReady?: () => void;
}) {
  const byKind = useMemo(() => {
    const groups = new Map<string, TownPlacement[]>();
    for (const placement of placements) {
      const group = groups.get(placement.kind);
      if (group) group.push(placement);
      else groups.set(placement.kind, [placement]);
    }
    return groups;
  }, [placements]);
  // load every model at once rather than one kind after another
  useGLTF([...byKind.keys()].map((kind) => assetUrl(assetIdForKind(kind))));

  useEffect(() => onReady?.(), [onReady]);

  return (
    <>
      {[...byKind].map(([kind, group]) => (
        <KindInstances key={kind} kind={kind} placements={group} />
      ))}
    </>
  );
}
