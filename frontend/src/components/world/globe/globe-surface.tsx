import { useEffect, useMemo } from 'react';
import { IcosahedronGeometry, MeshStandardMaterial, type Vector3 } from 'three';

import { type GlobeTerrain as Terrain, WATER_SURFACE } from '@/lib/world/globe';
import { riverGeometry, terrainGeometry } from '@/lib/world/globe-mesh';

/*
 * The planet surface: the terrain mesh (with a round hole where the town's own ground lies), a translucent
 * ocean sphere just above sea level, and the rivers.
 */

const OCEAN_DETAIL = 48;

/** A cone of directions where the terrain is not drawn because a site lays its own ground there. */
export interface TerrainHole {
  up: Vector3;
  /** Angular radius, radians. */
  angle: number;
}

function holedMaterial(hole: TerrainHole | null) {
  const material = new MeshStandardMaterial({
    vertexColors: true,
    flatShading: true,
    roughness: 0.95,
  });
  if (!hole) return material;
  material.onBeforeCompile = (shader) => {
    shader.uniforms.holeUp = { value: hole.up };
    shader.uniforms.holeCos = { value: Math.cos(hole.angle) };
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
    () => terrainGeometry(globe, biomeNames),
    [globe, biomeNames],
  );
  const material = useMemo(() => holedMaterial(hole), [hole]);
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
