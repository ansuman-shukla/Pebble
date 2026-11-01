import { useEffect, useMemo } from 'react';
import type { Vector3 } from 'three';

import type { GlobeTerrain as Terrain } from '@/lib/world/globe';
import { terrainGeometry } from '@/lib/world/globe-mesh';
import { groundMaterial, groundQuality } from '@/lib/world/ground-shader';
import type { RiverLayout } from '@/lib/world/river-courses';
import { riverGeometry, stillWaterGeometry } from '@/lib/world/water-mesh';
import { waterMaterial } from '@/lib/world/water-material';
import {
  poolGeometry,
  poolHoles,
  type WaterholePool,
} from '@/lib/world/waterholes';

/*
 * The planet surface: the refined terrain mesh on the ground shader (with a round hole where the town's own
 * ground lies and one where each waterhole's pool lies; `?ground=flat|low` picks its quality), the sea and the lakes
 * (one water surface that knows the depth under it: clear at the shore, deep blue offshore), the rivers (flowing
 * ribbons) and the waterholes' pools (a level pool in a muddy bowl, waterholes.ts).
 */

/** A cone of directions where the terrain is not drawn because a site lays its own ground there. */
export interface TerrainHole {
  up: Vector3;
  /** Angular radius, radians. */
  angle: number;
}

/**
 * The hole stops this far (metres) inside the site's ground edge: that edge is a polygon whose chords cut up
 * to ~0.12 m inside the circle, and terrain must show under those slivers.
 */
const HOLE_MARGIN = 0.2;

export function GlobeSurface({
  terrain,
  biomeNames,
  rivers,
  hole,
  pools,
}: {
  terrain: Terrain;
  biomeNames: readonly string[];
  rivers: RiverLayout;
  hole: TerrainHole | null;
  pools: readonly WaterholePool[];
}) {
  const { globe } = terrain;
  const land = useMemo(
    () => terrainGeometry(terrain, biomeNames),
    [terrain, biomeNames],
  );
  const material = useMemo(
    () =>
      groundMaterial({
        quality: groundQuality(window.location.search),
        hole: hole && {
          up: hole.up,
          cos: Math.cos(hole.angle - HOLE_MARGIN / globe.radius),
        },
        holes: poolHoles(pools, globe.radius),
      }),
    [hole, pools, globe],
  );
  const bowls = useMemo(
    () => poolGeometry(pools, terrain, biomeNames),
    [pools, terrain, biomeNames],
  );
  const bankMaterial = useMemo(
    () => groundMaterial({ quality: groundQuality(window.location.search) }),
    [],
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
  useEffect(
    () => () => {
      bowls.bank.dispose();
      bowls.water.dispose();
    },
    [bowls],
  );
  useEffect(() => () => bankMaterial.dispose(), [bankMaterial]);

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
      <mesh geometry={bowls.bank} material={bankMaterial} receiveShadow />
      <mesh
        geometry={bowls.water}
        material={stillMaterial}
        renderOrder={1}
        receiveShadow
      />
    </>
  );
}
