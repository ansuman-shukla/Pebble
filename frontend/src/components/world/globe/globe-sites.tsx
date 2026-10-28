import { useMemo } from 'react';

import {
  type CitizenSpots,
  TownCitizens,
} from '@/components/world/town/town-citizens';
import { TownGround } from '@/components/world/town/town-ground';
import { TownPlacements } from '@/components/world/town/town-placements';
import type { Site, TownView } from '@/lib/client/types.gen';
import type { WalkWater } from '@/lib/world/collision';
import { discOutline } from '@/lib/world/ground-shape';
import {
  anchorMapping,
  type GlobeTerrain,
  type SiteMapping,
} from '@/lib/world/globe';
import type { LabelStore } from '@/lib/world/label-store';
import { terrainLift } from '@/lib/world/walk-charts';

/*
 * Sites on the planet. The town lays its own ground disc at the plateau height (the terrain leaves a hole for
 * it) and renders its full placement set, ground areas, water and townspeople through the site mapping. Camps
 * and landmarks have no ground of their own: each placement stands on the rendered terrain under it.
 */

/** Edges of the town's round ground disc. */
const DISC_SEGMENTS = 96;
/** Wall hanging from the disc's edge down to the terrain. */
const DISC_SKIRT = 4;

export function GlobeTown({
  town,
  water,
  mapping,
  groundRadius,
  grass,
  labels,
  citizenSpots,
  onPlacementsReady,
  onCitizenReady,
}: {
  town: TownView;
  /** The town's water cut to its ground disc. */
  water: WalkWater[];
  mapping: SiteMapping;
  groundRadius: number;
  /** Colour of the ground disc, matched to the terrain around it. */
  grass: string;
  labels: LabelStore;
  /** Filled with where the townspeople stand, for the walker's collisions. */
  citizenSpots: CitizenSpots;
  onPlacementsReady: () => void;
  onCitizenReady: (id: string) => void;
}) {
  const outline = useMemo(
    () => discOutline(groundRadius, DISC_SEGMENTS),
    [groundRadius],
  );
  return (
    <>
      <TownGround
        areas={town.areas}
        water={water}
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
        spots={citizenSpots}
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
  const lift = useMemo(
    () => terrainLift(terrain, mapping, site.anchor.height_m),
    [terrain, mapping, site],
  );
  return (
    <TownPlacements
      placements={site.placements ?? []}
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
        .filter(
          (site) => site.kind !== 'town' && (site.placements?.length ?? 0) > 0,
        )
        .map((site) => (
          <SitePlacements key={site.id} site={site} terrain={terrain} />
        ))}
    </>
  );
}
