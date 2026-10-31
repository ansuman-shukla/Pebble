import { expect, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { TownView, WorldView } from '../../src/lib/client/types.gen';
import { GROUND_COVER } from '../../src/lib/world/biome-props';
import { buildWalkWorld, raycastBlockers } from '../../src/lib/world/collision';
import {
  anchorMapping,
  cellDirection,
  tangent,
  tangentFrame,
} from '../../src/lib/world/globe';
import {
  createGlobeWalk,
  type WalkTerrain,
} from '../../src/lib/world/globe-walk';
import { pickSurface } from '../../src/lib/world/globe-pick';
import { clipWater } from '../../src/lib/world/ground-shape';
import type { ScatterInstance } from '../../src/lib/world/scatter';
import {
  type Explore,
  explore,
  metres,
  TOWN_URL,
  walkTowards,
  WORLD_URL,
  TOWN_GROUND_RADIUS,
} from './explore-helpers';
import { FLORA_URL, floraOf } from './globe-helpers';

/*
 * The globe walker's collisions outside the town and the exploring helpers, without a browser, on the real
 * world: flora trees, camp and landmark placements and citizens block; ground cover doesn't; cliffs
 * can't be climbed; the camera's spring arm sees walls; drops refuse water. The page builds the same walk.
 */

let world: Explore;

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const [worldResponse, townResponse, floraResponse] = await Promise.all([
    api.get(WORLD_URL),
    api.get(TOWN_URL),
    api.get(FLORA_URL),
  ]);
  const view = (await worldResponse.json()) as WorldView;
  const town = (await townResponse.json()) as TownView;
  const flora = floraOf(view, await floraResponse.body());
  await api.dispose();
  world = explore(view, town, flora);
});

/** A point `distance` metres from a direction along a bearing (degrees from north). */
function offset(direction: Vector3, bearing: number, distance: number) {
  const { east, north } = tangentFrame(direction);
  const angle = (bearing * Math.PI) / 180;
  return direction
    .clone()
    .normalize()
    .multiplyScalar(world.R)
    .addScaledVector(north, Math.cos(angle) * distance)
    .addScaledVector(east, Math.sin(angle) * distance)
    .normalize();
}

const flatness = (direction: Vector3) => {
  const { east, north } = tangentFrame(direction);
  const at = (dx: number, dz: number) =>
    world.terrain.heightAt(
      direction
        .clone()
        .multiplyScalar(world.R)
        .addScaledVector(east, dx)
        .addScaledVector(north, dz),
    );
  return Math.max(
    Math.abs(at(3, 0) - at(-3, 0)),
    Math.abs(at(0, 3) - at(0, -3)),
  );
};

/** Scattered instances of a kind on fairly level ground with nothing else that blocks within `clear` metres. */
function loneInstances(kind: string, clear: number, limit = 3) {
  const { globe } = world.terrain;
  const found: ScatterInstance[] = [];
  for (
    let cell = 0;
    cell < globe.cellCount && found.length < limit;
    cell += 7
  ) {
    const grown = world.scatter.cell(cell);
    for (const instance of grown) {
      if (instance.kind !== kind) continue;
      const direction = instance.position.clone().normalize();
      if (flatness(direction) > 2) continue;
      const neighbours = world.scatter
        .cellsAround(direction, clear + 40)
        .flatMap((other) => world.scatter.cell(other))
        .filter(
          (other) =>
            // the cell grows fresh copies: skip the instance itself
            other.position.distanceTo(instance.position) > 1e-6 &&
            !GROUND_COVER.has(other.kind) &&
            other.position.distanceTo(instance.position) < clear,
        );
      if (
        neighbours.length === 0 &&
        instance.position.distanceTo(
          new Vector3(...world.site('town').anchor.position).multiplyScalar(
            world.R,
          ),
        ) > 400
      ) {
        found.push(instance);
        break;
      }
    }
  }
  if (found.length === 0) throw new Error(`no lone ${kind}`);
  return found;
}

test('a flora tree blocks the walk; without props the walk goes through it', () => {
  const walk = world.walk();
  const free = world.walk({ props: false });
  for (const tree of loneInstances('oak_tree', 4)) {
    const trunk = tree.position.clone().normalize();
    for (const bearing of [0, 120, 240]) {
      const start = offset(trunk, bearing, 3.5);
      const blocked = walkTowards(world, walk, start, trunk);
      const open = walkTowards(world, free, start, trunk);
      const end = blocked[blocked.length - 1];
      expect(metres(world, open[open.length - 1], trunk)).toBeLessThan(0.1);
      expect(metres(world, end, trunk)).toBeGreaterThan(0.4);
      // it got close to the trunk before stopping (not blocked by something else on the way)
      expect(metres(world, end, trunk)).toBeLessThan(1.5);
    }
  }
});

test('ground cover and soft plants never block, even tall reed beds', () => {
  const walk = world.walk();
  for (const kind of ['cattail', 'reed_bed', 'root_patch']) {
    const [tuft] = loneInstances(kind, 4, 1);
    const spot = tuft.position.clone().normalize();
    const path = walkTowards(world, walk, offset(spot, 90, 2.5), spot);
    expect(metres(world, path[path.length - 1], spot)).toBeLessThan(0.1);
  }
});

/*
 * Slopes on a synthetic terrain (the smoothed world has hardly any faces over 45°): east of the origin
 * direction the ground rises gently (0.3 per metre), then from s = 0 a 58° cliff (1.6 per metre) up to a flat
 * top at s = 30 m. Heights are exact, so a face edge sits exactly at s = 0.
 */
const GENTLE = 0.3;
const CLIFF = 1.6;

/** The synthetic terrain with its uphill direction turned `turn` degrees from east towards north. */
function cliffWalk(turn = 0) {
  const radius = 2000;
  const angle = (turn * Math.PI) / 180;
  /** Local metres east and north of the origin direction. */
  const local = (direction: Vector3) => {
    const unit = direction.clone().normalize();
    return {
      x: radius * Math.atan2(unit.x, unit.z),
      y: radius * Math.asin(unit.y),
    };
  };
  /** Metres uphill (across the cliff) from its foot. */
  const across = (direction: Vector3) => {
    const { x, y } = local(direction);
    return x * Math.cos(angle) + y * Math.sin(angle);
  };
  const profile = (s: number) =>
    s <= 0 ? 50 + GENTLE * s : 50 + CLIFF * Math.min(s, 30);
  const terrain: WalkTerrain = {
    globe: { radius, biomes: new Uint8Array([3]) },
    nearestCell: () => 0,
    heightAt: (direction) => profile(across(direction)),
    biomeAt: () => 3,
  };
  const walk = createGlobeWalk(terrain, [], null);
  /**
   * Walks east from `s0` metres across the cliff (on its fall line) in strides of `stride` metres; returns the
   * rise and how far the player got.
   */
  return (s0: number, distance: number, stride: number, travel = false) => {
    let direction = new Vector3(
      Math.sin((s0 * Math.cos(angle)) / radius),
      Math.sin((s0 * Math.sin(angle)) / radius),
      1,
    ).normalize();
    const start = direction.clone();
    const steps = Math.round(distance / stride);
    for (let k = 0; k < steps; k++) {
      const ground = terrain.heightAt(direction);
      const heading = tangentFrame(direction).east.multiplyScalar(stride);
      direction = walk.move(
        direction.clone().multiplyScalar(radius + ground),
        heading,
        ground,
        travel,
      );
    }
    return {
      rise: terrain.heightAt(direction) - terrain.heightAt(start),
      run: across(direction) - s0,
      moved: start.angleTo(direction) * radius,
    };
  };
}

test('cliffs steeper than 45° cannot be climbed, gentle slopes can (travel climbs anything)', () => {
  const walkEast = cliffWalk();
  // up the gentle slope: all the way, at its grade
  const gentle = walkEast(-10, 2, 0.05);
  expect(gentle.run).toBeCloseTo(2, 1);
  expect(gentle.rise).toBeCloseTo(2 * GENTLE, 1);
  // straight at the cliff face: no height gained
  const cliff = walkEast(10, 2, 0.05);
  expect(cliff.rise).toBeLessThan(0.05);
  // walking into the cliff from the gentle slope stops at its foot (sensing it half a metre ahead)
  const foot = walkEast(-2, 4, 0.05);
  expect(foot.run).toBeGreaterThan(1.4);
  expect(foot.run).toBeLessThan(2.05);
  // travel mode climbs it
  expect(walkEast(10, 2, 0.05, true).rise).toBeGreaterThan(1.9 * CLIFF);
});

test('walking obliquely into a cliff slides along it', () => {
  // the cliff faces 30° off the walking direction: the step's uphill part is dropped, the rest slides on
  const walkEast = cliffWalk(30);
  const slide = walkEast(10, 2, 0.05);
  expect(slide.rise).toBeLessThan(0.05);
  expect(slide.moved).toBeGreaterThan(0.8);
});

test('a long stride from gentle ground stops at the foot of a cliff', () => {
  const walkEast = cliffWalk();
  // one long step (a slow frame at a run): the ground just ahead is gentle, the cliff starts 0.8 m on
  const stride = walkEast(-0.8, 1.2, 1.2);
  // (without the per-step rise check it would end 0.4 m up the face, 0.88 m higher)
  expect(stride.rise).toBeLessThan(0.45);
  expect(stride.run).toBeLessThan(0.9);
});

/** World direction of a site's local point. */
const siteAt = (id: string, x: number, z: number) =>
  anchorMapping(world.site(id).anchor, world.R)
    .toWorld(x, 0, z, new Vector3())
    .normalize();

test('a camp lean-to, the elder tree and a hot spring pool block from every side', () => {
  const walk = world.walk();
  const placed = (siteId: string, kind: string) => {
    const site = world.site(siteId);
    const placement = site.placements!.find((p) => p.kind === kind)!;
    return siteAt(siteId, placement.x, placement.z);
  };
  for (const [centre, from, stop] of [
    [placed('band_a_camp', 'lean_to'), 3.5, 0.6],
    [placed('elder_tree', 'giant_tree'), 7, 1.2],
    // the pool's rim is 3 x 2.5 m
    [placed('hot_springs', 'hot_spring_pool'), 4, 1.2],
  ] as const) {
    let sides = 0;
    for (const bearing of [0, 90, 180, 270]) {
      const start = offset(centre, bearing, from);
      if (!walk.isFree(start)) continue;
      sides += 1;
      const path = walkTowards(world, walk, start, centre);
      expect(metres(world, path[path.length - 1], centre)).toBeGreaterThan(
        stop,
      );
    }
    expect(sides).toBeGreaterThanOrEqual(2);
  }
});

test('a citizen blocks the way, and pushes a standing player aside', () => {
  const walk = world.walk();
  const { townMapping: mapping, people } = world;
  const at = (x: number, z: number) =>
    mapping.toWorld(x, 0, z, new Vector3()).normalize();
  const stand = (x: number, z: number) =>
    people.set('genzo', mapping.toWorld(x, 0, z, new Vector3()));
  people.clear();
  stand(0, 70);
  const path = walkTowards(world, walk, at(0, 74), at(0, 66), { steps: 200 });
  const local = path.map((d) =>
    mapping.toLocal(d.clone().multiplyScalar(world.R + 8), new Vector3()),
  );
  for (const point of local)
    expect(Math.hypot(point.x, point.z - 70)).toBeGreaterThan(0.55);
  // without the person the same walk passes the spot
  people.clear();
  const clear = walkTowards(world, walk, at(0, 74), at(0, 66), { steps: 200 });
  expect(metres(world, clear[clear.length - 1], at(0, 66))).toBeLessThan(0.1);
  // a person walking into a standing player moves the player
  stand(0.2, 70);
  const standing = at(0, 70).multiplyScalar(world.R + 8);
  const after = walk.move(standing, new Vector3(), 8, false);
  const moved = mapping.toLocal(
    after.multiplyScalar(world.R + 8),
    new Vector3(),
  );
  expect(Math.hypot(moved.x - 0.2, moved.z - 70)).toBeGreaterThan(0.55);
  people.clear();
});

test('a citizen out in the wild blocks the way too', () => {
  const walk = world.walk();
  const { people, R } = world;
  // open ground 40 m south of band A's camp (outside its chart: the wild chart resolves the steps)
  const camp = world.site('band_a_camp');
  const mapping = anchorMapping(camp.anchor, R);
  const spot = [...Array(40).keys()]
    .map((k) => mapping.toWorld(0, 0, 45 + k, new Vector3()).normalize())
    .find(
      (direction) =>
        walk.isFree(direction) &&
        walk.isFree(offset(direction, 0, 4)) &&
        walk.isFree(offset(direction, 0, 2)),
    )!;
  expect(spot).toBeDefined();
  const feet = spot.clone().multiplyScalar(R + world.terrain.heightAt(spot));
  people.clear();
  people.set('lio', feet);
  const path = walkTowards(world, walk, offset(spot, 0, 4), spot, {
    steps: 200,
  });
  for (const point of path)
    expect(metres(world, point, spot)).toBeGreaterThan(0.55);
  people.clear();
  const clear = walkTowards(world, walk, offset(spot, 0, 4), spot, {
    steps: 200,
  });
  expect(metres(world, clear[clear.length - 1], spot)).toBeLessThan(0.1);
});

test('the spring arm stops at the townhouses beside the main street and clears the camera', () => {
  const walk = world.walk();
  const { townMapping: mapping } = world;
  const houses = buildWalkWorld(
    world.town.placements.filter((p) => p.kind === 'townhouse'),
    [],
    world.colliders,
  );
  for (const z of [50, 69, 78, 87]) {
    const eye = mapping.toWorld(0, 1.4, z, new Vector3());
    // looking east: the camera sits west, inside the west townhouse row (x -7.9..-4.1)
    const behind = mapping.toWorld(-5.6, 3.4, z, new Vector3());
    const reach = walk.cameraReach(eye, behind, 1);
    expect(reach).toBeLessThan(0.8);
    const camera = eye.clone().lerp(behind, reach);
    walk.clearCamera(camera, 0.25);
    const local = mapping.toLocal(camera, new Vector3());
    const head = mapping.toLocal(eye, new Vector3());
    expect(local.x).toBeGreaterThan(-4.1);
    // nothing between the camera and the player, so the camera isn't inside a house either
    expect(
      raycastBlockers(
        houses,
        [head.x, head.y, head.z],
        [local.x, local.y, local.z],
      ),
    ).toBe(1);
    // along the street nothing is in the way
    const along = mapping.toWorld(0, 3.4, z + 5.6, new Vector3());
    expect(walk.cameraReach(eye, along, 1)).toBe(1);
  }
});

test('drops land on free ground near the pick and refuse water', () => {
  const walk = world.walk();
  const { globe } = world.terrain;
  const ocean = [...globe.biomes.keys()].find(
    (cell) => globe.biomes[cell] === 0,
  )!;
  expect(walk.dropSpot(cellDirection(globe, ocean, new Vector3()))).toBeNull();
  // the moat is water too
  const { townMapping: mapping } = world;
  expect(walk.dropSpot(mapping.toWorld(12, 0, 34, new Vector3()))).toBeNull();
  // inside a townhouse: the nearest free spot outside it
  const house = mapping.toWorld(-6, 0, 78, new Vector3()).normalize();
  const spot = walk.dropSpot(house)!;
  expect(walk.isFree(spot)).toBe(true);
  expect(metres(world, spot, house)).toBeGreaterThan(1.5);
  expect(metres(world, spot, house)).toBeLessThan(5);
  // open street: right there
  const street = mapping.toWorld(0, 0, 75, new Vector3()).normalize();
  expect(metres(world, walk.dropSpot(street)!, street)).toBeLessThan(0.01);
});

test('a ray picks the ground under it, or the sea', () => {
  const walk = world.walk();
  const { globe } = world.terrain;
  for (let cell = 11; cell < globe.cellCount; cell += 4001) {
    const direction = cellDirection(globe, cell, new Vector3());
    const from = direction.clone().multiplyScalar(world.R + 3000);
    // a slanted ray towards the cell
    const aim = tangent(new Vector3(1, 0.3, 0.2), direction);
    const origin = from.clone().addScaledVector(aim, 800);
    const ray = direction
      .clone()
      .multiplyScalar(world.R)
      .sub(origin)
      .normalize();
    const hit = pickSurface(origin, ray, world.R, walk.floorAt)!;
    expect(hit).not.toBeNull();
    const floor = world.R + walk.floorAt(hit);
    expect(Math.abs(hit.length() - floor)).toBeLessThan(0.05);
  }
  expect(
    pickSurface(
      new Vector3(0, 0, world.R * 3),
      new Vector3(1, 0, 0),
      world.R,
      walk.floorAt,
    ),
  ).toBeNull();
});

test("the town's water ends at its ground disc, the moat is untouched", () => {
  const water = world.town.water;
  const clipped = clipWater(water, TOWN_GROUND_RADIUS);
  const radiusOf = ([x, z]: [number, number]) => Math.hypot(x, z);
  const area = (polygon: [number, number][]) =>
    Math.abs(
      polygon.reduce((sum, [x1, z1], i) => {
        const [x2, z2] = polygon[(i + 1) % polygon.length];
        return sum + x1 * z2 - x2 * z1;
      }, 0),
    ) / 2;
  // the stream's corners stick out of the disc before clipping
  expect(
    Math.max(...water.flatMap((w) => w.polygon.map(radiusOf))),
  ).toBeGreaterThan(TOWN_GROUND_RADIUS);
  expect(clipped).toHaveLength(water.length);
  for (const [k, area0] of water.entries()) {
    const cut = clipped[k];
    for (const point of [...cut.polygon, ...(cut.holes ?? []).flat()])
      expect(radiusOf(point)).toBeLessThanOrEqual(TOWN_GROUND_RADIUS + 1e-6);
    // only a sliver goes: the stream keeps nearly all of its 8 x 320 m, the moat all of it
    expect(area(cut.polygon)).toBeGreaterThan(area(area0.polygon) * 0.99);
    expect(area(cut.polygon)).toBeLessThanOrEqual(area(area0.polygon) + 1e-6);
    expect(cut.holes).toEqual(area0.holes ?? []);
  }
});
