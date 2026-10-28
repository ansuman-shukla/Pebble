import { useMemo } from 'react';
import { Vector3 } from 'three';

import { TownCitizens } from '@/components/world/town/town-citizens';
import { TownGround } from '@/components/world/town/town-ground';
import { TownPlacements } from '@/components/world/town/town-placements';
import type { TownPlacement, TownView } from '@/lib/client/types.gen';
import type { Point } from '@/lib/world/collision';
import {
  anchorMapping,
  type GlobeTerrain,
  type SiteMapping,
} from '@/lib/world/globe';
import type { LabelStore } from '@/lib/world/label-store';
import type { Site } from '@/lib/world/world-view';

/*
 * Sites on the planet. The town lays its own ground disc at the plateau height (the terrain leaves a hole for
 * it) and renders its full placement set, ground areas, water and townspeople through the site mapping. Camps
 * and landmarks have no ground of their own: each placement stands on the rendered terrain under it.
 */

/** Edges of the town's round ground disc. */
const DISC_SEGMENTS = 96;
/** Wall hanging from the disc's edge down to the terrain. */
const DISC_SKIRT = 4;

function circle(radius: number, segments = DISC_SEGMENTS): Point[] {
  return Array.from({ length: segments }, (_, i) => {
    const angle = (i / segments) * Math.PI * 2;
    return [Math.cos(angle) * radius, -Math.sin(angle) * radius];
  });
}

export function GlobeTown({
  town,
  mapping,
  groundRadius,
  grass,
  labels,
  onPlacementsReady,
  onCitizenReady,
}: {
  town: TownView;
  mapping: SiteMapping;
  groundRadius: number;
  /** Colour of the ground disc, matched to the terrain around it. */
  grass: string;
  labels: LabelStore;
  onPlacementsReady: () => void;
  onCitizenReady: (id: string) => void;
}) {
  const outline = useMemo(() => circle(groundRadius), [groundRadius]);
  return (
    <>
      <TownGround
        areas={town.areas}
        water={town.water}
        mapping={mapping}
        outline={outline}
        skirt={DISC_SKIRT}
        grass={grass}
      />
      <TownPlacements
        placements={town.placements}
        mapping={mapping}
        onReady={onPlacementsReady}
      />
      <TownCitizens
        citizens={town.citizens}
        mapping={mapping}
        labels={labels}
        onReady={onCitizenReady}
      />
    </>
  );
}

function SitePlacements({
  site,
  terrain,
}: {
  site: Site;
  terrain: GlobeTerrain;
}) {
  const mapping = useMemo(
    () => anchorMapping(site.anchor, terrain.globe.radius),
    [site, terrain],
  );
  const lift = useMemo(() => {
    const at = new Vector3();
    return (placement: TownPlacement) =>
      terrain.heightAt(mapping.toWorld(placement.x, 0, placement.z, at)) -
      site.anchor.height_m;
  }, [terrain, mapping, site]);
  return (
    <TownPlacements
      placements={site.placements}
      mapping={mapping}
      lift={lift}
    />
  );
}

/** Placements of every camp and landmark. */
export function GlobeSites({
  sites,
  terrain,
}: {
  sites: Site[];
  terrain: GlobeTerrain;
}) {
  return (
    <>
      {sites
        .filter((site) => site.kind !== 'town' && site.placements.length > 0)
        .map((site) => (
          <SitePlacements key={site.id} site={site} terrain={terrain} />
        ))}
    </>
  );
}
