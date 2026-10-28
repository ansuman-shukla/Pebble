import { useGLTF } from '@react-three/drei';
import { useMemo } from 'react';
import { type Object3D, Raycaster, Vector3 } from 'three';

import { assetBaseY, assetUrl } from '@/lib/world/assets';
import {
  assetIdForKind,
  type Point,
  surfacesAt,
  type WalkPlacement,
  type WalkWorld,
} from '@/lib/world/collision';

/** Placement id -> an unrendered copy of that surface's model, placed in world space, for height raycasts. */
export type GroundProxies = ReadonlyMap<string, Object3D>;

/** Loads the walkable surfaces (bridges, stairs, paving, paddies) as invisible ground proxies; suspends. */
export function useGroundProxies(placements: WalkPlacement[]): GroundProxies {
  const surfaces = useMemo(
    () => placements.filter((placement) => placement.walk === 'surface'),
    [placements],
  );
  const ids = useMemo(
    () => [...new Set(surfaces.map(({ kind }) => assetIdForKind(kind)))],
    [surfaces],
  );
  const models = useGLTF(ids.map(assetUrl));

  return useMemo(() => {
    const scenes = new Map(ids.map((id, index) => [id, models[index].scene]));
    const proxies = new Map<string, Object3D>();
    for (const placement of surfaces) {
      const id = assetIdForKind(placement.kind);
      const proxy = scenes.get(id)!.clone(true);
      proxy.position.set(placement.x, assetBaseY(id), placement.z);
      proxy.rotation.y = (placement.rotation_deg * Math.PI) / 180;
      proxy.updateMatrixWorld(true);
      proxies.set(placement.id, proxy);
    }
    return proxies;
  }, [ids, models, surfaces]);
}

const raycaster = new Raycaster();
const origin = new Vector3();
const DOWN = new Vector3(0, -1, 0);

/** Height of the walkable ground at a point, looking down from `fromY` (flat ground at y = 0 elsewhere). */
export function groundHeight(
  world: WalkWorld,
  proxies: GroundProxies,
  [x, z]: Point,
  fromY: number,
) {
  const objects = [
    ...new Set(
      surfacesAt(world, [x, z]).map((shape) => proxies.get(shape.placementId)!),
    ),
  ];
  if (objects.length === 0) return 0;
  raycaster.set(origin.set(x, fromY, z), DOWN);
  const [hit] = raycaster.intersectObjects(objects, true);
  return Math.max(hit?.point.y ?? 0, 0);
}
