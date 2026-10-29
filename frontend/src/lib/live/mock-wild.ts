/*
 * DEV/TEST ONLY: the animals and fires of the mock live feed (`?mockLive=1`). A herd of deer grazes and wanders
 * on the town's approach and a fox trots past; by band A's camp deer graze and two wolves prowl at night (sleeping
 * by day), and scripted scenes play out every behaviour the globe draws (`mock-animal-scenes.ts`). Both camp fires
 * burn; the main gate's fire baskets burn from dusk to dawn. Shapes are the feed's.
 */
import { Vector3 } from 'three';

import {
  type AnimalActivity,
  type LiveAnimal,
  type LiveFire,
  TICK_SECONDS,
} from './live-contract';
import { sceneAnimals } from './mock-animal-scenes';
import type { Site, WorldView } from '@/lib/client/types.gen';
import {
  anchorMapping,
  latLonFromDirection,
  type SiteMapping,
} from '@/lib/world/globe';

type Spot = [number, number];
type SiteId = 'town' | 'band_a_camp' | 'band_b_camp';

interface MockAnimal {
  id: string;
  kind: LiveAnimal['kind'];
  group: string;
  site: SiteId;
  /** Waypoints it walks round (local metres of its site, x east, z south). */
  route: Spot[];
  /** Metres per tick. */
  pace: number;
  /** Ticks it grazes (or stands) at each waypoint. */
  graze: number;
  /** Awake at night and asleep by day (predators); the others sleep at night. */
  nocturnal?: boolean;
}

const herd = (
  kind: LiveAnimal['kind'],
  group: string,
  site: SiteId,
  first: number,
  route: Spot[],
  count: number,
  extra: Partial<MockAnimal> = {},
): MockAnimal[] =>
  Array.from({ length: count }, (_, k) => ({
    id: `${kind}:${first + k}`,
    kind,
    group,
    site,
    route: route.map(([x, z]) => [x + 4 * k, z + 3 * (k % 2)] as Spot),
    pace: 30,
    graze: 5 + k,
    ...extra,
  }));

const ANIMALS: MockAnimal[] = [
  ...herd('deer', 'deer-group:1', 'town', 1, [[30, 175], [70, 190], [55, 215]], 4),
  ...herd('fox', 'fox-group:2', 'town', 5, [[-50, 180], [-20, 210]], 1, { pace: 20, graze: 3 }),
  ...herd('deer', 'deer-group:3', 'band_a_camp', 6, [[45, 35], [70, 60]], 3),
  ...herd('wolf', 'wolf-group:4', 'band_a_camp', 9, [[140, -60], [110, 30]], 2, {
    pace: 45,
    nocturnal: true,
  }),
]; // prettier-ignore

/** Fires at their sites' local metres: camps' pits (always burning) and the main gate's baskets (at night). */
const FIRES: { id: string; kind: LiveFire['kind']; site: SiteId; at: Spot }[] =
  [
    {
      id: 'band_a_camp:fire-pit',
      kind: 'pit',
      site: 'band_a_camp',
      at: [0, 0],
    },
    {
      id: 'band_b_camp:fire-pit',
      kind: 'pit',
      site: 'band_b_camp',
      at: [0, 0],
    },
    { id: 'main-gate-fire-w', kind: 'basket', site: 'town', at: [-4.5, 103.5] },
    { id: 'main-gate-fire-e', kind: 'basket', site: 'town', at: [4.5, 103.5] },
  ];

interface AnimalState {
  animal: MockAnimal;
  at: Spot;
  heading: number;
  next: number;
  /** Ticks left grazing at the waypoint reached. */
  left: number;
  /** Where it stood when the last tick began, when it moved in it. */
  from: Spot | null;
}

export class MockWild {
  private readonly mappings: Map<
    string,
    { mapping: SiteMapping; height: number }
  >;
  private states: AnimalState[];
  /** Ticks stepped: the clock of the scripted scenes (`mock-animal-scenes.ts`). */
  private ticks = 0;

  constructor(world: WorldView) {
    this.mappings = new Map(
      world.sites.map((site: Site) => [
        site.id,
        { mapping: anchorMapping(site.anchor, world.radius_m), height: site.anchor.height_m },
      ]),
    ); // prettier-ignore
    this.states = ANIMALS.map((animal) => ({
      animal,
      at: [...animal.route[0]],
      heading: 0,
      next: 1,
      left: animal.graze,
      from: null,
    }));
  }

  step(night: boolean) {
    this.ticks += 1;
    for (const state of this.states) {
      const { animal } = state;
      state.from = null;
      if (night !== Boolean(animal.nocturnal)) continue; // asleep
      if (state.left > 0) {
        state.left -= 1;
        continue;
      }
      const [tx, tz] = animal.route[state.next];
      const [x, z] = state.at;
      const distance = Math.hypot(tx - x, tz - z);
      if (distance > 1e-6)
        state.heading = (Math.atan2(tx - x, tz - z) * 180) / Math.PI;
      state.from = [x, z];
      if (distance <= animal.pace) {
        state.at = [tx, tz];
        state.next = (state.next + 1) % animal.route.length;
        state.left = animal.graze;
      } else
        state.at = [
          x + ((tx - x) * animal.pace) / distance,
          z + ((tz - z) * animal.pace) / distance,
        ];
    }
  }

  animals(night: boolean): LiveAnimal[] {
    const scripted = sceneAnimals(this.ticks, (spot) =>
      this.position('band_a_camp', spot),
    );
    const wandering = this.states.map(({ animal, at, heading, left, from }) => {
      const asleep = night !== Boolean(animal.nocturnal);
      const activity: AnimalActivity = asleep
        ? 'sleeping'
        : left > 0
          ? animal.nocturnal
            ? 'idle'
            : 'grazing'
          : 'walking';
      return {
        id: animal.id,
        kind: animal.kind,
        group: animal.group,
        position: this.position(animal.site, at),
        heading_deg: heading,
        activity,
        // the engine's drawn path (D100): from where it stood when the tick began, timed at its pace
        route: from ? this.route(animal, from, at) : [],
        speed_mps: from ? animal.pace / TICK_SECONDS : 0,
        gait: 'walk',
        goal: asleep
          ? 'asleep'
          : animal.nocturnal
            ? 'prowling'
            : left > 0
              ? 'grazing'
              : 'wandering',
        target: null,
      } satisfies LiveAnimal;
    });
    return [...wandering, ...scripted];
  }

  private route(animal: MockAnimal, from: Spot, at: Spot) {
    const metres = Math.hypot(at[0] - from[0], at[1] - from[1]);
    return [
      { ...this.point(animal.site, from), t_s: 0 },
      {
        ...this.point(animal.site, at),
        t_s: (metres / animal.pace) * TICK_SECONDS,
      },
    ];
  }

  private point(site: SiteId, spot: Spot) {
    const { unit, height_m } = this.position(site, spot);
    return { unit, height_m };
  }

  fires(night: boolean): LiveFire[] {
    return FIRES.map(({ id, kind, site, at }) => {
      const lit = kind === 'pit' || night;
      return {
        id,
        kind,
        position: this.position(site, at),
        lit,
        strength: lit ? 1 : 0,
      };
    });
  }

  private position(site: SiteId, [x, z]: Spot) {
    const found = this.mappings.get(site);
    if (!found) throw new Error(`the world has no ${site} site`);
    const unit = found.mapping.toWorld(x, 0, z, new Vector3()).normalize();
    const { lat, lon } = latLonFromDirection(unit);
    return { unit: unit.toArray(), height_m: found.height, lat, lon };
  }
}
