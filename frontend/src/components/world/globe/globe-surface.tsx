import { useEffect, useMemo } from 'react';
import { MeshStandardMaterial, type Vector3 } from 'three';

import type { GlobeTerrain as Terrain } from '@/lib/world/globe';
import { terrainGeometry } from '@/lib/world/globe-mesh';
import type { RiverLayout } from '@/lib/world/river-courses';
import { riverGeometry, stillWaterGeometry } from '@/lib/world/water-mesh';
import { waterMaterial } from '@/lib/world/water-material';

/*
 * The planet surface: the refined terrain mesh (with a round hole where the town's own ground lies), the sea and
 * the lakes (one water surface that knows the depth under it: clear at the shore, deep blue offshore) and the
 * rivers (flowing ribbons).
 */

/** A cone of directions where the terrain is not drawn because a site lays its own ground there. */
export interface TerrainHole {
  up: Vector3;
  /** Angular radius, radians. */
  angle: number;
}

/** How much of each face's own flat normal shows through the smooth normals: a hint of the low-poly facets. */
const FACETS = 0.35;
/** The facets fade out between these view distances (metres), where faces shrink to a few pixels. */
const FACETS_FADE: [number, number] = [250, 1200];
/**
 * The hole stops this far (metres) inside the site's ground edge: that edge is a polygon whose chords cut up
 * to ~0.12 m inside the circle, and terrain must show under those slivers.
 */
const HOLE_MARGIN = 0.2;

/**
 * Smooth-shaded terrain with a hint of facets (the face normal from screen derivatives mixed into the
 * interpolated one), and no fragments inside the hole.
 */
function terrainMaterial(hole: TerrainHole | null, radius: number) {
  const material = new MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.95,
  });
  material.onBeforeCompile = (shader) => {
    shader.uniforms.facets = { value: FACETS };
    shader.uniforms.facetsFade = { value: FACETS_FADE };
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nuniform float facets;\nuniform vec2 facetsFade;',
      )
      .replace(
        '#include <normal_fragment_begin>',
        [
          '#include <normal_fragment_begin>',
          'vec3 facet = normalize(cross(dFdx(vViewPosition), dFdy(vViewPosition)));',
          'float fade = 1.0 - smoothstep(facetsFade.x, facetsFade.y, length(vViewPosition));',
          'normal = normalize(mix(normal, facet, facets * fade));',
        ].join('\n'),
      );
    if (!hole) return;
    shader.uniforms.holeUp = { value: hole.up };
    shader.uniforms.holeCos = {
      value: Math.cos(hole.angle - HOLE_MARGIN / radius),
    };
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vPlanet;')
      .replace(
        '#include <begin_vertex>',
        '#include <begin_vertex>\nvPlanet = position;',
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        '#include <common>\nvarying vec3 vPlanet;\nuniform vec3 holeUp;\nuniform float holeCos;',
      )
      .replace(
        'void main() {',
        'void main() {\nif (dot(normalize(vPlanet), holeUp) > holeCos) discard;',
      );
  };
  return material;
}

export function GlobeSurface({
  terrain,
  biomeNames,
  rivers,
  hole,
}: {
  terrain: Terrain;
  biomeNames: readonly string[];
  rivers: RiverLayout;
  hole: TerrainHole | null;
}) {
  const { globe } = terrain;
  const land = useMemo(
    () => terrainGeometry(terrain, biomeNames),
    [terrain, biomeNames],
  );
  const material = useMemo(
    () => terrainMaterial(hole, globe.radius),
    [hole, globe],
  );
  const still = useMemo(() => stillWaterGeometry(terrain), [terrain]);
  const stillMaterial = useMemo(() => waterMaterial('still'), []);
  const flowing = useMemo(
    () => riverGeometry(terrain, rivers),
    [terrain, rivers],
  );
  const flowingMaterial = useMemo(() => waterMaterial('flowing'), []);
  useEffect(() => () => land.dispose(), [land]);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => still.dispose(), [still]);
  useEffect(() => () => stillMaterial.dispose(), [stillMaterial]);
  useEffect(() => () => flowing.dispose(), [flowing]);
  useEffect(() => () => flowingMaterial.dispose(), [flowingMaterial]);

  return (
    <>
      <mesh geometry={land} material={material} receiveShadow />
      <mesh
        geometry={still}
        material={stillMaterial}
        renderOrder={1}
        receiveShadow
      />
      <mesh
        geometry={flowing}
        material={flowingMaterial}
        renderOrder={2}
        receiveShadow
      />
    </>
  );
}
