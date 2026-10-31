import { useGLTF } from '@react-three/drei';
import { Suspense, useEffect, useMemo } from 'react';
import { type BufferGeometry, InstancedMesh, Matrix4, Vector3 } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import { TownGround } from '@/components/world/town/town-ground';
import {
  type Placed,
  TownPlacements,
} from '@/components/world/town/town-placements';
import type {
  Feature,
  Furniture,
  Site,
  TownView,
  WorldPlaces,
} from '@/lib/client/types.gen';
import { assetUrl, PROPS } from '@/lib/world/assets';
import type { PlacementLift, WalkWater } from '@/lib/world/collision';
import { furniturePlacements } from '@/lib/world/furniture';
import {
  anchorMapping,
  type GlobeTerrain,
  type SiteMapping,
  tangent,
} from '@/lib/world/globe';
import {
  type BridgeSpan,
  buildMarks,
  globeMarkGround,
  type MarkGround,
  type PlanetMarks,
  planetMarks,
} from '@/lib/world/ground-marks';
import { discOutline } from '@/lib/world/ground-shape';
import type { LocalMapping } from '@/lib/world/local-mapping';
import type { RiverLayout } from '@/lib/world/river-courses';
import { terrainLift } from '@/lib/world/walk-charts';

/*
 * Sites on the planet. The town lays its own ground disc at the plateau height (the terrain leaves a hole for
 * it) and renders its full placement set, ground areas and water through the site mapping (its people are the
 * live citizens, drawn by globe-npcs). Its ground carries the world's ground marks too, in the same merged mesh:
 * every road and path of the network, camp ground and work spots, draped on the town disc or the terrain; and the
 * roads' log bridges over the rivers and signposts at their junctions stand with them. Camps and landmarks have no
 * ground of their own: each placement stands on the rendered terrain under it. The furniture people sit and lie on
 * (log seats, mats, the loom's stool, the lord's seat) comes later, drawn when it arrives.
 */

/** Edges of the town's round ground disc. */
const DISC_SEGMENTS = 96;
/** Wall hanging from the disc's edge down to the terrain. */
const DISC_SKIRT = 4;
/** The log bridge model's span and deck width (metres; it lies along its x axis). */
const BRIDGE_MODEL = { length: 4, width: 1.72 };
/** A bridge's deck is never narrower than this (metres), however narrow the path it carries. */
const BRIDGE_MIN_WIDTH = 1.6;

interface WorldMarks {
  /** The marks draped on the ground (owned here: kept for the world's lifetime). */
  geometry: BufferGeometry;
  /** Where the bridges and signposts stand. */
  bridges: Matrix4[];
  signposts: Matrix4[];
}

/*
 * The world's marks, built once per terrain (one per world view): every model that loads retries the scene's
 * Suspense boundary, which renders the town afresh, and rebuilding the marks on each retry stalled the globe's load
 * by ~10 s.
 */
const worldMarks = new WeakMap<GlobeTerrain, WorldMarks>();

/** A model's frame at a unit direction: x along `along`, y up, standing `height` above sea level. */
function standing(
  direction: Vector3,
  along: Vector3,
  height: number,
  radius: number,
  scale: Vector3,
) {
  const x = tangent(along.clone(), direction);
  const z = new Vector3().crossVectors(x, direction);
  return new Matrix4()
    .makeBasis(x, direction, z)
    .scale(scale)
    .setPosition(direction.clone().multiplyScalar(radius + height));
}

/** Each bridge across its river, its ends on the higher bank. */
function bridgeMatrices(bridges: BridgeSpan[], ground: MarkGround) {
  const end = new Vector3();
  return bridges.map(({ centre, along, length, width }) => {
    const banks = [-1, 1].map(
      (side) =>
        ground.heightAt(
          end
            .copy(centre)
            .multiplyScalar(ground.radius)
            .addScaledVector(along, (side * length) / 2)
            .normalize(),
        ) ?? 0,
    );
    return standing(
      centre,
      along,
      Math.max(...banks),
      ground.radius,
      new Vector3(
        length / BRIDGE_MODEL.length,
        1,
        Math.max(width, BRIDGE_MIN_WIDTH) / BRIDGE_MODEL.width,
      ),
    );
  });
}

/** Each signpost beside its road, facing the nearest point of a road or path. */
function signpostMatrices(
  signposts: Feature[],
  marks: PlanetMarks,
  ground: MarkGround,
) {
  return signposts.map((signpost) => {
    const at = new Vector3(...signpost.position);
    let nearest = at;
    for (const ribbon of marks.ribbons)
      for (const point of ribbon.points)
        if (point.angleTo(at) < nearest.angleTo(at) || nearest === at)
          nearest = point;
    const facing = new Vector3().subVectors(nearest, at);
    // x across the road, so the model's front (+z) faces it
    const across = new Vector3().crossVectors(at, facing);
    return standing(
      at,
      across,
      ground.heightAt(at) ?? 0,
      ground.radius,
      new Vector3(1, 1, 1),
    );
  });
}

/** One instanced mesh per part of a kind's model, placed at fixed matrices. */
function useFixedInstances(id: string, matrices: Matrix4[]) {
  const { scene } = useGLTF(assetUrl(id));
  const meshes = useMemo(() => {
    // the parts are baked into model space, so each instance's matrix is the model's
    return kindParts(scene, id).map(({ geometry, material }) => {
      const mesh = new InstancedMesh(geometry, material, matrices.length);
      matrices.forEach((matrix, i) => mesh.setMatrixAt(i, matrix));
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.computeBoundingSphere();
      return mesh;
    });
  }, [scene, id, matrices]);
  // the geometry and material belong to the shared model (kind-parts); only the instance buffers are ours
  useEffect(() => () => meshes.forEach((mesh) => mesh.dispose()), [meshes]);
  return meshes;
}

function RoadFurniture({
  bridges,
  signposts,
}: Pick<WorldMarks, 'bridges' | 'signposts'>) {
  const meshes = [
    ...useFixedInstances(PROPS.log_bridge, bridges),
    ...useFixedInstances(PROPS.signpost, signposts),
  ];
  return (
    <>
      {meshes.map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
    </>
  );
}

/** A site's furniture, in its own boundary so its arrival never hides what is already drawn. */
function SiteFurniture({
  furniture,
  site,
  mapping,
  lift,
}: {
  furniture: readonly Furniture[];
  site: string;
  mapping: LocalMapping;
  lift?: PlacementLift;
}) {
  const placed: Placed[] = useMemo(
    () => furniturePlacements(furniture, site),
    [furniture, site],
  );
  if (placed.length === 0) return null;
  return (
    <Suspense fallback={null}>
      <TownPlacements placements={placed} mapping={mapping} lift={lift} />
    </Suspense>
  );
}

export function GlobeTown({
  town,
  water,
  mapping,
  groundRadius,
  grass,
  furniture,
  terrain,
  sites,
  places,
  rivers,
  onPlacementsReady,
}: {
  town: TownView;
  /** The town's water cut to its ground disc. */
  water: WalkWater[];
  mapping: SiteMapping;
  groundRadius: number;
  /** Colour of the ground disc, matched to the terrain around it. */
  grass: string;
  furniture: readonly Furniture[];
  terrain: GlobeTerrain;
  /** Every site (camps lay their ground marks) and the world's places (roads, bridges, work spots). */
  sites: Site[];
  places: WorldPlaces;
  rivers: RiverLayout;
  onPlacementsReady: () => void;
}) {
  const outline = useMemo(
    () => discOutline(groundRadius, DISC_SEGMENTS),
    [groundRadius],
  );
  let world = worldMarks.get(terrain);
  if (!world) {
    const height = sites.find((site) => site.kind === 'town')!.anchor.height_m;
    const ground = globeMarkGround({
      terrain,
      rivers,
      town: { mapping, groundRadius, height, water },
    });
    const marks = planetMarks({ globe: terrain.globe, places, sites, rivers });
    const signposts = places.features.filter(
      (feature) => feature.kind === 'signpost',
    );
    world = {
      geometry: buildMarks({ planet: { marks, ground } }),
      bridges: bridgeMatrices(marks.bridges, ground),
      signposts: signpostMatrices(signposts, marks, ground),
    };
    worldMarks.set(terrain, world);
  }
  return (
    <>
      <TownGround
        areas={town.areas}
        water={water}
        mapping={mapping}
        outline={outline}
        skirt={DISC_SKIRT}
        grass={grass}
        marks={world.geometry}
      />
      <TownPlacements
        placements={town.placements}
        mapping={mapping}
        onReady={onPlacementsReady}
      />
      <SiteFurniture furniture={furniture} site="town" mapping={mapping} />
      <RoadFurniture bridges={world.bridges} signposts={world.signposts} />
    </>
  );
}

function SitePlacements({
  site,
  terrain,
  furniture,
}: {
  site: Site;
  terrain: GlobeTerrain;
  furniture: readonly Furniture[];
}) {
  const mapping = useMemo(
    () => anchorMapping(site.anchor, terrain.globe.radius),
    [site, terrain],
  );
  const lift = useMemo(
    () => terrainLift(terrain, mapping, site.anchor.height_m),
    [terrain, mapping, site],
  );
  return (
    <>
      <TownPlacements
        placements={site.placements ?? []}
        mapping={mapping}
        lift={lift}
      />
      <SiteFurniture
        furniture={furniture}
        site={site.id}
        mapping={mapping}
        lift={lift}
      />
    </>
  );
}

/** Placements (and furniture) of every camp and landmark. */
export function GlobeSites({
  sites,
  terrain,
  furniture,
}: {
  sites: Site[];
  terrain: GlobeTerrain;
  furniture: readonly Furniture[];
}) {
  return (
    <>
      {sites
        .filter(
          (site) => site.kind !== 'town' && (site.placements?.length ?? 0) > 0,
        )
        .map((site) => (
          <SitePlacements
            key={site.id}
            site={site}
            terrain={terrain}
            furniture={furniture}
          />
        ))}
    </>
  );
}
