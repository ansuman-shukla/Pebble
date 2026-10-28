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
  WATER_BIOMES,
} from '../../src/lib/world/globe';
import { MAX_GRADE } from '../../src/lib/world/globe-walk';
import { pickSurface } from '../../src/lib/world/globe-pick';
import type { ScatterInstance } from '../../src/lib/world/scatter';
import {
  type Explore,
  explore,
  metres,
  TOWN_URL,
  walkTowards,
  WORLD_URL,
} from './explore-helpers';

/*
 * The globe walker's collisions outside the town and the exploring helpers, without a browser, on the real
 * world: scattered trees, camp and landmark placements and townspeople block; ground cover doesn't; cliffs
 * can't be climbed; the camera's spring arm sees walls; drops refuse water. The page builds the same walk.
 */

let world: Explore;

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const [worldResponse, townResponse] = await Promise.all([
    api.get(WORLD_URL),
    api.get(TOWN_URL),
  ]);
  const view = (await worldResponse.json()) as WorldView;
  const town = (await townResponse.json()) as TownView;
  await api.dispose();
  world = explore(view, town);
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

test('a scattered tree blocks the walk; without props the walk goes through it', () => {
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

test('ground cover never blocks, even tall reeds', () => {
  const walk = world.walk();
  for (const kind of ['cattail', 'reeds']) {
    const [tuft] = loneInstances(kind, 4, 1);
    const spot = tuft.position.clone().normalize();
    const path = walkTowards(world, walk, offset(spot, 90, 2.5), spot);
    expect(metres(world, path[path.length - 1], spot)).toBeLessThan(0.1);
  }
});

/** The steepest land point (rise per metre along the gradient) away from sites, sampled over the cells. */
function slopes() {
  const { globe } = world.terrain;
  const sites = world.view.sites.map(
    (site) => new Vector3(...site.anchor.position),
  );
  const steep: { at: Vector3; uphill: Vector3; grade: number }[] = [];
  const gentle: typeof steep = [];
  for (let cell = 0; cell < globe.cellCount; cell += 5) {
    if (WATER_BIOMES.has(globe.biomes[cell]) || globe.heights[cell] < 5)
      continue;
    const at = cellDirection(globe, cell, new Vector3());
    if (sites.some((site) => site.angleTo(at) * world.R < 350)) continue;
    const { east, north } = tangentFrame(at);
    const base = at.clone().multiplyScalar(world.R);
    const h = (v: Vector3) => world.terrain.heightAt(v);
    const ge = (h(base.clone().addScaledVector(east, 0.5)) - h(base)) / 0.5;
    const gn = (h(base.clone().addScaledVector(north, 0.5)) - h(base)) / 0.5;
    const grade = Math.hypot(ge, gn);
    const uphill = east
      .multiplyScalar(ge)
      .addScaledVector(north, gn)
      .normalize();
    // the same slope must hold for a few metres uphill: every half metre rises by grade·0.5
    const rises = [0, 0.5, 1, 1.5, 2, 2.5].map((d) =>
      h(base.clone().addScaledVector(uphill, d)),
    );
    const grades = rises.slice(1).map((r, k) => (r - rises[k]) / 0.5);
    if (grades.every((g) => g > 1.4) && steep.length < 4)
      steep.push({ at, uphill, grade });
    if (grades.every((g) => g > 0.15 && g < 0.6) && gentle.length < 4)
      gentle.push({ at, uphill, grade });
    if (steep.length >= 4 && gentle.length >= 4) break;
  }
  return { steep, gentle };
}

test('cliffs steeper than 45° cannot be climbed, gentle slopes can (travel climbs anything)', () => {
  const walk = world.walk({ props: false });
  const { steep, gentle } = slopes();
  expect(steep.length).toBeGreaterThan(0);
  expect(gentle.length).toBeGreaterThan(0);
  const climb = (at: Vector3, uphill: Vector3, travel: boolean) => {
    const target = at
      .clone()
      .multiplyScalar(world.R)
      .addScaledVector(uphill, 2)
      .normalize();
    const path = walkTowards(world, walk, at, target, { steps: 80, travel });
    const end = path[path.length - 1];
    return {
      rise: world.terrain.heightAt(end) - world.terrain.heightAt(at),
      run: metres(world, at, end),
    };
  };
  for (const { at, uphill } of steep) {
    const walked = climb(at, uphill, false);
    // never up the face: at most a contour slide gains a little height
    expect(walked.rise).toBeLessThanOrEqual(walked.run * MAX_GRADE + 0.05);
    expect(walked.rise).toBeLessThan(1);
    expect(climb(at, uphill, true).rise).toBeGreaterThan(2);
  }
  for (const { at, uphill, grade } of gentle) {
    const walked = climb(at, uphill, false);
    expect(walked.run).toBeGreaterThan(1.9);
    expect(walked.rise).toBeGreaterThan(grade * 2 * 0.5);
  }
});

/** Points where gentle ground meets a cliff within a metre uphill (a face edge of the terrain mesh). */
function cliffEdges() {
  const { globe } = world.terrain;
  const sites = world.view.sites.map(
    (site) => new Vector3(...site.anchor.position),
  );
  const edges: { at: Vector3; uphill: Vector3 }[] = [];
  for (let cell = 0; cell < globe.cellCount && edges.length < 3; cell += 2) {
    if (WATER_BIOMES.has(globe.biomes[cell]) || globe.heights[cell] < 5)
      continue;
    const centre = cellDirection(globe, cell, new Vector3());
    if (sites.some((site) => site.angleTo(centre) * world.R < 350)) continue;
    const { east, north } = tangentFrame(centre);
    for (let k = 0; k < 48 && edges.length < 3; k++) {
      // points around the cell, every way
      const base = centre
        .clone()
        .multiplyScalar(world.R)
        .addScaledVector(east, ((k % 4) - 1.5) * 4)
        .addScaledVector(north, ((Math.floor(k / 4) % 3) - 1) * 4);
      const angle = (Math.floor(k / 12) / 4) * Math.PI * 2 + (k % 3);
      const uphill = east
        .clone()
        .multiplyScalar(Math.cos(angle))
        .addScaledVector(north, Math.sin(angle));
      const heights = Array.from({ length: 13 }, (_, i) =>
        world.terrain.heightAt(base.clone().addScaledVector(uphill, i * 0.1)),
      );
      const grade = (i: number) => (heights[i + 1] - heights[i]) / 0.1;
      const gentle = [0, 1, 2, 3].every((i) => Math.abs(grade(i)) < 0.8);
      const cliff = [5, 6, 7, 8, 9, 10, 11].every((i) => grade(i) > 1.4);
      if (gentle && cliff) edges.push({ at: base.normalize(), uphill });
    }
  }
  return edges;
}

test('a long stride from gentle ground stops at the foot of a cliff', () => {
  const walk = world.walk({ props: false });
  const edges = cliffEdges();
  expect(edges.length).toBeGreaterThan(0);
  for (const { at, uphill } of edges) {
    // one long step (a slow frame at a run): the slope just ahead is gentle, the cliff starts 0.5 m on
    const position = at
      .clone()
      .multiplyScalar(world.R + world.terrain.heightAt(at));
    const end = walk.move(
      position,
      uphill.clone().multiplyScalar(1.2),
      world.terrain.heightAt(at),
      false,
    );
    const rise = world.terrain.heightAt(end) - world.terrain.heightAt(at);
    expect(rise).toBeLessThan(0.6);
  }
});

/** World direction of a site's local point. */
const siteAt = (id: string, x: number, z: number) =>
  anchorMapping(world.site(id).anchor, world.R)
    .toWorld(x, 0, z, new Vector3())
    .normalize();

test('a camp lean-to and the elder tree block from every side', () => {
  const walk = world.walk();
  const camp = world.site('band_a_camp');
  const leanTo = camp.placements!.find((p) => p.kind === 'lean_to')!;
  const elder = world.site('elder_tree');
  const tree = elder.placements!.find((p) => p.kind === 'giant_tree')!;
  for (const [id, placement, from, stop] of [
    [camp.id, leanTo, 3.5, 0.6],
    [elder.id, tree, 7, 1.2],
  ] as const) {
    const centre = siteAt(id, placement.x, placement.z);
    for (const bearing of [0, 90, 180, 270]) {
      const start = offset(centre, bearing, from);
      if (!walk.isFree(start)) continue;
      const path = walkTowards(world, walk, start, centre);
      expect(metres(world, path[path.length - 1], centre)).toBeGreaterThan(
        stop,
      );
    }
  }
});

test('a townsperson blocks the way, and pushes a standing player aside', () => {
  const walk = world.walk();
  const { townMapping: mapping, citizens } = world;
  const at = (x: number, z: number) =>
    mapping.toWorld(x, 0, z, new Vector3()).normalize();
  citizens.clear();
  citizens.set('town-lord', [0, 70]);
  const path = walkTowards(world, walk, at(0, 74), at(0, 66), { steps: 200 });
  const local = path.map((d) =>
    mapping.toLocal(d.clone().multiplyScalar(world.R + 8), new Vector3()),
  );
  for (const point of local)
    expect(Math.hypot(point.x, point.z - 70)).toBeGreaterThan(0.55);
  // without the person the same walk passes the spot
  citizens.clear();
  const clear = walkTowards(world, walk, at(0, 74), at(0, 66), { steps: 200 });
  expect(metres(world, clear[clear.length - 1], at(0, 66))).toBeLessThan(0.1);
  // a person walking into a standing player moves the player
  citizens.set('town-lord', [0.2, 70]);
  const standing = at(0, 70).multiplyScalar(world.R + 8);
  const after = walk.move(standing, new Vector3(), 8, false);
  const moved = mapping.toLocal(
    after.multiplyScalar(world.R + 8),
    new Vector3(),
  );
  expect(Math.hypot(moved.x - 0.2, moved.z - 70)).toBeGreaterThan(0.55);
  citizens.clear();
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
