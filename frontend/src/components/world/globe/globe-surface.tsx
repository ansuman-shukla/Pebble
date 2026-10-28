import { useEffect, useMemo } from 'react';
import { IcosahedronGeometry, MeshStandardMaterial, type Vector3 } from 'three';

import { type GlobeTerrain as Terrain, WATER_SURFACE } from '@/lib/world/globe';
import { riverGeometry, terrainGeometry } from '@/lib/world/globe-mesh';

/*
 * The planet surface: the refined terrain mesh (with a round hole where the town's own ground lies), a translucent
 * ocean sphere just above sea level, and the rivers.
 */

const OCEAN_DETAIL = 48;

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
  rivers: number[][];
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
  const ocean = useMemo(
    () => new IcosahedronGeometry(globe.radius + WATER_SURFACE, OCEAN_DETAIL),
    [globe],
  );
  const water = useMemo(
    () => riverGeometry(terrain, rivers),
    [terrain, rivers],
  );
  useEffect(() => () => land.dispose(), [land]);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => ocean.dispose(), [ocean]);
  useEffect(() => () => water.dispose(), [water]);

  return (
    <>
      <mesh geometry={land} material={material} receiveShadow />
      <mesh geometry={ocean} renderOrder={1}>
        <meshStandardMaterial
          color="#3a7db3"
          transparent
          opacity={0.78}
          roughness={0.3}
        />
      </mesh>
      <mesh geometry={water}>
        <meshStandardMaterial
          color="#4b8fc2"
          roughness={0.35}
          polygonOffset
          polygonOffsetFactor={-2}
          polygonOffsetUnits={-2}
        />
      </mesh>
    </>
  );
}
