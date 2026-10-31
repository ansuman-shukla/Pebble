import { Suspense, useMemo } from 'react';

import { TownGround } from '@/components/world/town/town-ground';
import {
  type Placed,
  TownPlacements,
} from '@/components/world/town/town-placements';
import type { Furniture, Site, TownView } from '@/lib/client/types.gen';
import type { PlacementLift, WalkWater } from '@/lib/world/collision';
import { furniturePlacements } from '@/lib/world/furniture';
import { discOutline } from '@/lib/world/ground-shape';
import {
  anchorMapping,
  type GlobeTerrain,
  type SiteMapping,
} from '@/lib/world/globe';
import type { LocalMapping } from '@/lib/world/local-mapping';
import { terrainLift } from '@/lib/world/walk-charts';

/*
 * Sites on the planet. The town lays its own ground disc at the plateau height (the terrain leaves a hole for
 * it) and renders its full placement set, ground areas and water through the site mapping (its people are the
 * live citizens, drawn by globe-npcs). Camps
 * and landmarks have no ground of their own: each placement stands on the rendered terrain under it. The furniture
 * people sit and lie on (log seats, mats, the loom's stool, the lord's seat) comes later, drawn when it arrives.
 */

/** Edges of the town's round ground disc. */
const DISC_SEGMENTS = 96;
/** Wall hanging from the disc's edge down to the terrain. */
const DISC_SKIRT = 4;

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
  onPlacementsReady: () => void;
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
      <SiteFurniture furniture={furniture} site="town" mapping={mapping} />
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
