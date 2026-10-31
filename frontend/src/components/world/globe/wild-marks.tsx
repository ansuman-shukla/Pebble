import { useEffect } from 'react';
import type { InstancedMesh, Material } from 'three';

import {
  useFixedInstances,
  useProceduralInstances,
} from '@/components/world/globe/fixed-instances';
import { PROPS } from '@/lib/world/assets';
import type { WildMarks } from '@/lib/world/wild-marks';

/*
 * The dens (a cave mouth, bones before it) and the claimed hotspots' markers (the town's boundary stone and banner,
 * a band's cairn and hide streamer) on the roadside, standing on the drawn ground (wild-marks.ts). Five dens and
 * three markers: one instanced mesh per model part for all of each kind; the banner and the streamer's hide wave in
 * the wind like the town's banners.
 */

type Kind = keyof WildMarks;

declare global {
  interface Window {
    /** How many of each wild mark are drawn, and which kinds wave in the wind (cloth). */
    __pebbleWildMarks?: { counts: Record<Kind, number>; waving: Kind[] };
  }
}

const waves = (material: Material & { defines?: Record<string, unknown> }) =>
  material.defines?.WIND_CLOTH !== undefined;

/** The world's wild marks (laid with the road marks in globe-sites, from the drawn routes). */
export function GlobeWildMarks({ marks }: { marks: WildMarks }) {
  const byKind: Record<Kind, InstancedMesh[]> = {
    caves: useFixedInstances(PROPS.cave_mouth, marks.caves),
    bones: useFixedInstances(PROPS.bone_scatter, marks.bones),
    stones: useFixedInstances(PROPS.boundary_stone, marks.stones),
    banners: useFixedInstances(PROPS.banner, marks.banners),
    cairns: useFixedInstances(PROPS.cairn, marks.cairns),
    streamers: useProceduralInstances(PROPS.hide_streamer, marks.streamers),
  };
  const meshes = Object.values(byKind).flat();
  const waving = (Object.keys(byKind) as Kind[])
    .filter((kind) =>
      byKind[kind].some((mesh) => waves(mesh.material as Material)),
    )
    .join(',');
  useEffect(() => {
    const counts = Object.fromEntries(
      Object.entries(marks).map(([kind, list]) => [kind, list.length]),
    ) as Record<Kind, number>;
    window.__pebbleWildMarks = {
      counts,
      waving: waving ? (waving.split(',') as Kind[]) : [],
    };
    return () => {
      delete window.__pebbleWildMarks;
    };
  }, [marks, waving]);
  return (
    <>
      {meshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
    </>
  );
}
