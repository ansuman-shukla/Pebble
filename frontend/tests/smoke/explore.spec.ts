import { expect, type Locator, type Page, test } from '@playwright/test';
import { PerspectiveCamera, Quaternion, Vector3 } from 'three';

import type { TownView, WorldView } from '../../src/lib/client/types.gen';
import {
  buildWalkWorld,
  raycastBlockers,
  type WalkWorld,
} from '../../src/lib/world/collision';
import {
  anchorMapping,
  cellDirection,
  directionFromLatLon,
  type SiteMapping,
  tangentFrame,
  WATER_BIOMES,
} from '../../src/lib/world/globe';
import { type Explore, explore, TOWN_URL, WORLD_URL } from './explore-helpers';
import {
  atParam,
  directionOf,
  DRAW_CALL_BUDGET,
  hold,
  openGlobe,
  sample,
  sampleFor,
} from './globe-helpers';

/*
 * Exploring the real planet at /: drop the player anywhere from orbit (click or drag the pegman), refuse
 * water, "Go to" every site, keep the follow camera out of the townhouses along the main street, and walk
 * into a lean-to and the elder tree without passing through them (citizens: live-npcs.spec.ts).
 */

const FOV = 50;
const EYE_HEIGHT = 1.4;

let world: Explore;
let townMapping: SiteMapping;
let townWorld: WalkWorld;

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const [worldResponse, townResponse] = await Promise.all([
    api.get(WORLD_URL),
    api.get(TOWN_URL),
  ]);
  world = explore(
    (await worldResponse.json()) as WorldView,
    (await townResponse.json()) as TownView,
  );
  await api.dispose();
  townMapping = world.townMapping;
  townWorld = buildWalkWorld(world.town.placements, [], world.colliders);
});

/** The live camera from the world element (position and quaternion). */
async function cameraOf(element: Locator, page: Page) {
  const values = (await element.getAttribute('data-camera'))!
    .split(',')
    .map(Number);
  const size = page.viewportSize()!;
  const box = (await page.locator('canvas[data-engine]').boundingBox())!;
  const camera = new PerspectiveCamera(FOV, box.width / box.height, 0.1, 1e5);
  camera.position.set(values[0], values[1], values[2]);
  camera.quaternion.copy(
    new Quaternion(values[3], values[4], values[5], values[6]),
  );
  camera.updateMatrixWorld();
  return {
    camera,
    /** Client pixel of a world point, or null if it is off screen or behind the planet. */
    screenOf(point: Vector3) {
      const ndc = point.clone().project(camera);
      if (Math.abs(ndc.x) > 0.9 || Math.abs(ndc.y) > 0.8 || ndc.z > 1)
        return null;
      // hidden behind the planet's limb?
      const toPoint = point.clone().sub(camera.position);
      if (point.clone().normalize().dot(toPoint.normalize()) > -0.05)
        return null;
      const x = box.x + ((ndc.x + 1) / 2) * box.width;
      const y = box.y + ((1 - ndc.y) / 2) * box.height;
      return y > 120 && y < size.height - 40 ? { x, y } : null;
    },
  };
}

/** Opens the planet, switches to orbit and waits for the orbit camera to settle. */
async function orbit(page: Page, errors: string[]) {
  const element = await openGlobe(page, errors);
  await page.keyboard.press('KeyC');
  await expect(element).toHaveAttribute('data-camera-mode', 'orbit');
  await expect
    .poll(
      async () => Number(await element.getAttribute('data-camera-distance')),
      {
        timeout: 10_000,
      },
    )
    .toBeGreaterThan(5990);
  await page.waitForTimeout(300);
  return element;
}

/** Visible cells (land or water) away from every site, nearest the screen's middle first. */
async function visibleCells(
  element: Locator,
  page: Page,
  water: boolean,
  count: number,
) {
  const { screenOf } = await cameraOf(element, page);
  const { globe } = world.terrain;
  const sites = world.view.sites.map(
    (site) => new Vector3(...site.anchor.position),
  );
  const found: { direction: Vector3; screen: { x: number; y: number } }[] = [];
  for (let cell = 0; cell < globe.cellCount; cell += 3) {
    const wet = WATER_BIOMES.has(globe.biomes[cell]);
    if (wet !== water || (!water && globe.heights[cell] < 3)) continue;
    if (water && globe.biomes[cell] !== 0) continue;
    const direction = cellDirection(globe, cell, new Vector3());
    if (sites.some((site) => site.angleTo(direction) * world.R < 500)) continue;
    // all neighbours alike, so a few pixels of error can't cross a shore
    if (
      [...world.terrain.neighbours(cell)].some(
        (other) => WATER_BIOMES.has(globe.biomes[other]) !== water,
      )
    )
      continue;
    const surface = direction
      .clone()
      .multiplyScalar(world.R + Math.max(globe.heights[cell], 0));
    const screen = screenOf(surface);
    if (screen) found.push({ direction, screen });
  }
  const middle = { x: 640, y: 450 };
  found.sort(
    (a, b) =>
      Math.hypot(a.screen.x - middle.x, a.screen.y - middle.y) -
      Math.hypot(b.screen.x - middle.x, b.screen.y - middle.y),
  );
  // spread the picks: skip the ones right next to the middle (the player stands there)
  return found
    .filter(
      (cell) => cell.direction.angleTo(found[0].direction) * world.R > 300,
    )
    .slice(0, count);
}

const metresTo = (
  element: Awaited<ReturnType<typeof sample>>,
  direction: Vector3,
) => directionOf(element).angleTo(direction) * world.R;

/** Waits for the camera's flight into the follow view (after a drop) to start and end. */
async function expectFlight(element: Locator) {
  await expect(element).toHaveAttribute('data-camera-flying', 'true');
  await expect(element).toHaveAttribute('data-camera-mode', 'follow');
  await expect(element).toHaveAttribute('data-camera-flying', 'false', {
    timeout: 5_000,
  });
}

test('the pegman drops the player on land clicked from orbit and flies the camera down into follow', async ({
  page,
}) => {
  const errors: string[] = [];
  const element = await orbit(page, errors);
  const [target] = await visibleCells(element, page, false, 1);
  const before = await sample(element);
  expect(metresTo(before, target.direction)).toBeGreaterThan(250);

  await page.getByRole('button', { name: 'drop' }).click();
  await expect(element).toHaveAttribute('data-dropping', 'true');
  await page.mouse.click(target.screen.x, target.screen.y);
  // the camera is still on its way down...
  await expect(element).toHaveAttribute('data-camera-flying', 'true');
  expect(
    Number(await element.getAttribute('data-camera-distance')),
  ).toBeGreaterThan(world.R + 300);
  // ...and ends behind the player, in the follow view
  await expect(element).toHaveAttribute('data-camera-mode', 'follow');
  await expect(element).toHaveAttribute('data-camera-flying', 'false', {
    timeout: 5_000,
  });
  await expect(element).toHaveAttribute('data-dropping', 'false');
  const after = await sample(element);
  expect(metresTo(after, target.direction)).toBeLessThan(25);
  const distance = Number(await element.getAttribute('data-camera-distance'));
  expect(distance - world.R - after.ground).toBeLessThan(12);
  // the spot went into the URL
  const at = new URL(page.url()).searchParams.get('at')!.split(',').map(Number);
  expect(
    directionFromLatLon(at[0], at[1]).angleTo(directionOf(after)) * world.R,
  ).toBeLessThan(1);
  // the player walks from there
  await hold(page, ['KeyW'], () => page.waitForTimeout(1_000));
  expect(metresTo(await sample(element), directionOf(after))).toBeGreaterThan(
    0.8,
  );
  await expect(element).toHaveAttribute('data-draw-calls-mode', 'follow', {
    timeout: 10_000,
  });
  expect(Number(await element.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );
  expect(errors).toEqual([]);
});

test('a drop on water is refused with a message and leaves the player where it was', async ({
  page,
}) => {
  const errors: string[] = [];
  const element = await orbit(page, errors);
  const [sea] = await visibleCells(element, page, true, 1);
  const before = await sample(element);
  await page.getByRole('button', { name: 'drop' }).click();
  await page.mouse.click(sea.screen.x, sea.screen.y);
  await expect(page.getByRole('status')).toHaveText(
    "That's water. Pick a spot on land.",
  );
  await page.waitForTimeout(500);
  const after = await sample(element);
  expect(metresTo(after, directionOf(before))).toBeLessThan(0.01);
  await expect(element).toHaveAttribute('data-camera-mode', 'orbit');
  // still dropping: the next click on land works
  await expect(element).toHaveAttribute('data-dropping', 'true');
  expect(new URL(page.url()).searchParams.get('at')).toBeNull();
  expect(errors).toEqual([]);
});

test('dragging the pegman onto the planet drops the player there', async ({
  page,
}) => {
  const errors: string[] = [];
  const element = await orbit(page, errors);
  const [target] = await visibleCells(element, page, false, 1);
  const box = (await page.locator('canvas[data-engine]').boundingBox())!;
  await page
    .getByRole('button', { name: 'drop' })
    .dragTo(page.locator('canvas[data-engine]'), {
      targetPosition: {
        x: target.screen.x - box.x,
        y: target.screen.y - box.y,
      },
    });
  await expectFlight(element);
  const here = await sample(element);
  expect(metresTo(here, target.direction)).toBeLessThan(25);
  expect(errors).toEqual([]);
});

test('"Go to" drops the player at every named site', async ({ page }) => {
  const errors: string[] = [];
  const element = await openGlobe(page, errors);
  const town = world.site('town');
  await page.getByRole('button', { name: /go to/ }).click();
  const items = page.getByRole('menuitem');
  await expect(items).toHaveText(world.view.sites.map((site) => site.name));
  await page.keyboard.press('Escape');
  for (const site of [...world.view.sites.slice(1), town]) {
    await page.getByRole('button', { name: /go to/ }).click();
    await page.getByRole('menuitem', { name: site.name, exact: true }).click();
    await expectFlight(element);
    const here = await sample(element);
    const anchor = new Vector3(...site.anchor.position);
    if (site.kind === 'town') {
      // the town spawn on the approach road by the main gate
      expect(here.townX).toBeCloseTo(0, 0);
      expect(here.townZ).toBeCloseTo(world.town.spawn.z, 0);
    } else {
      expect(metresTo(here, anchor)).toBeLessThan(30);
      expect(metresTo(here, anchor)).toBeGreaterThan(4);
    }
    expect(here.site).toBe(site.id);
    const at = new URL(page.url()).searchParams
      .get('at')!
      .split(',')
      .map(Number);
    expect(
      directionFromLatLon(at[0], at[1]).angleTo(directionOf(here)) * world.R,
    ).toBeLessThan(1);
  }
  expect(errors).toEqual([]);
});

/** `?at=` for a town local point facing along (dx, dz). */
function townAt(x: number, z: number, dx: number, dz: number) {
  const from = townMapping.toWorld(x, 0, z, new Vector3());
  const to = townMapping.toWorld(x + dx, 0, z + dz, new Vector3());
  return atParam(from.clone().normalize(), to.sub(from));
}

test('the follow camera stays out of the townhouses along the main street', async ({
  page,
}) => {
  const errors: string[] = [];
  // on the main street facing east: the camera hangs west, over the west row of townhouses
  const element = await openGlobe(page, errors, `?at=${townAt(0, 90, 1, 0)}`);
  await page.waitForTimeout(500);
  const arms: number[] = [];
  let checked = 0;
  // A walks left = north up the street, past the houses at z 87, 78, 69 and 50
  await hold(page, ['ShiftLeft', 'KeyA'], async () => {
    for (let k = 0; k < 90; k++) {
      const [values, player, arm] = await Promise.all([
        element.getAttribute('data-camera'),
        sample(element),
        element.getAttribute('data-camera-arm'),
      ]);
      const camera = new Vector3(...values!.split(',').slice(0, 3).map(Number));
      const feet = new Vector3(player.x, player.y, player.z);
      const eye = feet.clone().setLength(feet.length() + EYE_HEIGHT);
      const head = townMapping.toLocal(eye, new Vector3());
      const lens = townMapping.toLocal(camera, new Vector3());
      // nothing of the town stands between camera and player, so the camera is in no building either
      expect(
        raycastBlockers(
          townWorld,
          [head.x, head.y, head.z],
          [lens.x, lens.y, lens.z],
        ),
      ).toBe(1);
      checked += 1;
      arms.push(Number(arm));
      if (player.townZ! < 52) break;
      await page.waitForTimeout(100);
    }
  });
  expect(checked).toBeGreaterThan(20);
  // the houses pulled the arm in (it wants 6 m)...
  expect(Math.min(...arms)).toBeLessThan(4.5);
  // ...and the gaps between them let it out again
  expect(Math.max(...arms)).toBeGreaterThan(5);
  expect(errors).toEqual([]);
});

/** Walks forward (W) from `?at=` for `ms` and returns the distances to `centre`. */
async function walkAt(page: Page, query: string, centre: Vector3, ms: number) {
  const errors: string[] = [];
  const element = await openGlobe(page, errors, `?at=${query}`);
  await page.waitForTimeout(300);
  let samples: Awaited<ReturnType<typeof sampleFor>> = [];
  await hold(page, ['KeyW'], async () => {
    samples = await sampleFor(element, page, ms);
  });
  expect(errors).toEqual([]);
  return samples.map((current) => metresTo(current, centre));
}

/** `?at=` `distance` m from a site placement on the first free side, facing it. */
function facing(siteId: string, kind: string, distance: number) {
  const site = world.site(siteId);
  const placement = site.placements!.find((p) => p.kind === kind)!;
  const mapping = anchorMapping(site.anchor, world.R);
  const centre = mapping
    .toWorld(placement.x, 0, placement.z, new Vector3())
    .normalize();
  const walk = world.walk();
  const { east, north } = tangentFrame(centre);
  for (const bearing of [180, 90, 270, 0]) {
    const angle = (bearing * Math.PI) / 180;
    const start = centre
      .clone()
      .multiplyScalar(world.R)
      .addScaledVector(north, Math.cos(angle) * distance)
      .addScaledVector(east, Math.sin(angle) * distance)
      .normalize();
    if (walk.isFree(start))
      return { at: atParam(start, centre.clone().sub(start)), centre };
  }
  throw new Error(`no free side at ${kind}`);
}

test('a camp lean-to is solid', async ({ page }) => {
  const { at, centre } = facing('band_a_camp', 'lean_to', 4);
  const distances = await walkAt(page, at, centre, 4_000);
  expect(Math.min(...distances)).toBeGreaterThan(0.6);
  expect(distances[distances.length - 1]).toBeLessThan(2.5);
});

test('the elder tree is solid', async ({ page }) => {
  const { at, centre } = facing('elder_tree', 'giant_tree', 7);
  const distances = await walkAt(page, at, centre, 6_000);
  expect(Math.min(...distances)).toBeGreaterThan(1.2);
  expect(distances[distances.length - 1]).toBeLessThan(4);
});
