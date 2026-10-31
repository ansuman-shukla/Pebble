import { useMemo } from 'react';

import { useFixedInstances } from '@/components/world/globe/fixed-instances';
import type { WorldPlaces } from '@/lib/client/types.gen';
import { PROPS } from '@/lib/world/assets';
import type { GlobeTerrain } from '@/lib/world/globe';
import { wildMarks } from '@/lib/world/wild-marks';

/*
 * The dens (a cave mouth, bones before it) and the claimed hotspots' markers (the town's boundary stone and banner,
 * a band's cairn), standing on the drawn ground (wild-marks.ts). Five dens and three markers: one instanced mesh per
 * model part for all of each kind.
 */
export function GlobeWildMarks({
  places,
  terrain,
}: {
  places: WorldPlaces;
  terrain: GlobeTerrain;
}) {
  const marks = useMemo(
    () =>
      wildMarks(
        places,
        (direction) => terrain.heightAt(direction),
        terrain.globe.radius,
      ),
    [places, terrain],
  );
  const meshes = [
    ...useFixedInstances(PROPS.cave_mouth, marks.caves),
    ...useFixedInstances(PROPS.bone_scatter, marks.bones),
    ...useFixedInstances(PROPS.boundary_stone, marks.stones),
    ...useFixedInstances(PROPS.banner, marks.banners),
    ...useFixedInstances(PROPS.cairn, marks.cairns),
  ];
  return (
    <>
      {meshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
    </>
  );
}
