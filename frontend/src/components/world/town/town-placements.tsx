import { useGLTF } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import { InstancedMesh, Matrix4 } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import type { TownPlacement } from '@/lib/client/types.gen';
import { assetBaseY, assetUrl } from '@/lib/world/assets';
import { assetIdForKind } from '@/lib/world/collision';
import { FLAT_MAPPING, type LocalMapping } from '@/lib/world/local-mapping';

/*
 * Every placement of one kind is drawn as instances: one InstancedMesh per sub-mesh of the kind's GLB, with
 * the sub-mesh's transform inside the model baked into each instance matrix. Doors are opened on the source
 * first and models sit at assetBaseY, exactly like the walker's colliders, so what you see is what blocks you.
 * The mapping places local metres in the world (flat on the town page, wrapped onto the planet on the globe).
 */

/** Kinds lying flat on the ground: their shadows would be invisible, so they skip the shadow pass. */
const FLAT_KINDS = new Set(['rice_paddy', 'paving_tile']);

type PlacementsProps = {
  placements: TownPlacement[];
  mapping: LocalMapping;
  /** Extra local height per placement (e.g. to stand it on uneven terrain). */
  lift?: (placement: TownPlacement) => number;
};

function KindInstances({
  kind,
  placements,
  mapping,
  lift,
}: PlacementsProps & { kind: string }) {
  const id = assetIdForKind(kind);
  const { scene } = useGLTF(assetUrl(id));

  const meshes = useMemo(() => {
    const parts = kindParts(scene, id);
    const baseY = assetBaseY(id);
    const placed = placements.map((placement) =>
      mapping.matrix(
        placement.x,
        baseY + (lift?.(placement) ?? 0),
        placement.z,
        (placement.rotation_deg * Math.PI) / 180,
        new Matrix4(),
      ),
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
  }, [scene, id, kind, placements, mapping, lift]);

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

/** All placements of a place, grouped by kind; suspends until every GLB is loaded, then calls onReady. */
export function TownPlacements({
  placements,
  mapping = FLAT_MAPPING,
  lift,
  onReady,
}: Omit<PlacementsProps, 'mapping'> & {
  mapping?: LocalMapping;
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
        <KindInstances
          key={kind}
          kind={kind}
          placements={group}
          mapping={mapping}
          lift={lift}
        />
      ))}
    </>
  );
}
