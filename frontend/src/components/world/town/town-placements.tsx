import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useEffect, useId, useMemo } from 'react';
import { Matrix4, Vector3 } from 'three';

import { kindModel, type KindModel } from '@/components/world/kind-parts';
import { LivingKind } from '@/components/world/living-kind';
import type { TownPlacement } from '@/lib/client/types.gen';
import { assetBaseY, assetUrl, kindScale } from '@/lib/world/assets';
import { assetIdForKind } from '@/lib/world/collision';
import { FLAT_MAPPING, type LocalMapping } from '@/lib/world/local-mapping';
import { isProcedural, proceduralScene } from '@/lib/world/procedural-props';
import { advanceProps } from '@/lib/world/prop-motion';

/*
 * Every placement of one kind is drawn as instances: one InstancedMesh per part of the kind's model (kind-parts:
 * its sub-meshes merged per material, so mostly one), placed at assetBaseY with the gatehouse's doors open,
 * exactly like the walker's colliders, so what you see is what blocks you. The mapping places local metres in the
 * world (flat on the town page, wrapped onto the planet on the globe). Their moving parts live (living-kind.ts).
 */

type PlacementsProps = {
  placements: TownPlacement[];
  mapping: LocalMapping;
  /** Extra local height per placement (e.g. to stand it on uneven terrain). */
  lift?: (placement: TownPlacement) => number;
};

type KindProps = PlacementsProps & { kind: string; id: string };

function ModelInstances(props: KindProps) {
  const { scene, animations } = useGLTF(assetUrl(props.id));
  return (
    <KindInstances {...props} model={kindModel(scene, props.id, animations)} />
  );
}

function ProceduralInstances(props: KindProps) {
  return (
    <KindInstances
      {...props}
      model={kindModel(proceduralScene(props.id), props.id)}
    />
  );
}

function KindInstances({
  kind,
  id,
  model,
  placements,
  mapping,
  lift,
}: KindProps & { model: KindModel }) {
  const key = useId();
  const living = useMemo(() => {
    const baseY = assetBaseY(id);
    const scale = kindScale(kind);
    const placed = placements.map((placement) =>
      mapping
        .matrix(
          placement.x,
          baseY + (lift?.(placement) ?? 0),
          placement.z,
          (placement.rotation_deg * Math.PI) / 180,
          new Matrix4(),
        )
        .scale(new Vector3(scale, scale, scale)),
    );
    return new LivingKind(key, kind, model, placements, placed);
  }, [key, model, id, kind, placements, mapping, lift]);

  // the geometry and material belong to the shared model (kind-parts); only the instance buffers are ours
  useEffect(() => () => living.dispose(), [living]);

  useFrame(({ camera, clock }, delta) => {
    advanceProps(clock.elapsedTime);
    living.frame(camera.position, clock.elapsedTime, Math.min(delta, 0.1));
  });

  return (
    <>
      {living.meshes.map((instances) => (
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
  useGLTF(
    [...byKind.keys()]
      .map(assetIdForKind)
      .filter((id) => !isProcedural(id))
      .map(assetUrl),
  );

  useEffect(() => onReady?.(), [onReady]);

  return (
    <>
      {[...byKind].map(([kind, group]) => {
        const id = assetIdForKind(kind);
        const Instances = isProcedural(id)
          ? ProceduralInstances
          : ModelInstances;
        return (
          <Instances
            key={kind}
            kind={kind}
            id={id}
            placements={group}
            mapping={mapping}
            lift={lift}
          />
        );
      })}
    </>
  );
}
