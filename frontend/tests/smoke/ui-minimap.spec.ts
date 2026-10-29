import { expect, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  latLonFromDirection,
  siteMapping,
  tangentFrame,
} from '../../src/lib/world/globe';
import {
  MAP_PX,
  mapPixel,
  mapPixelOf,
  mapPoint,
  METRES_PER_PX,
} from '../../src/lib/world/minimap';
import { WORLD_URL } from './globe-helpers';
import {
  cameraOf,
  drawn,
  landed,
  type MockLiveWindow,
  openHeld,
} from './ui-helpers';

/* The minimap: its geometry (no browser) and, on the mock feed, every citizen drawn and a click that goes there. */

test('1 px is 2 m around the centre, north up; the pixel and the point invert', () => {
  const centre = MAP_PX / 2;
  expect(mapPixel(0, 0)).toEqual({ x: centre, y: centre, edge: false });
  // 100 m east and 60 m north
  expect(mapPixel(100, -60)).toEqual({
    x: centre + 100 / METRES_PER_PX,
    y: centre - 60 / METRES_PER_PX,
    edge: false,
  });
  expect(mapPoint(centre + 50, centre - 30)).toEqual({ x: 100, z: -60 });
});

test('whoever is off the map sits on its edge, toward where they are', () => {
  const centre = MAP_PX / 2;
  const far = mapPixel(2000, 1000);
  expect(far.edge).toBe(true);
  expect(far.x).toBeCloseTo(MAP_PX - 4);
  expect(far.y).toBeCloseTo(centre + (centre - 4) / 2);
  const north = mapPixel(0, -5000);
  expect(north).toEqual({ x: centre, y: 4, edge: true });
  // half again past the edge is on it, not beyond
  expect(mapPixel(300, 0)).toEqual({ x: MAP_PX - 4, y: centre, edge: true });
  // just inside the edge stays where it is
  expect(mapPixel((centre - 4) * METRES_PER_PX, 0).edge).toBe(false);
});

const DEG = Math.PI / 180;

/** The compass direction on the map (x east, y south) of a point `angle` from a site's anchor, bearing `bearing`. */
function seen(angleDeg: number, bearingDeg: number) {
  const anchor = new Vector3(0.3, 0.8, 0.52).normalize();
  const frame = tangentFrame(anchor);
  const mapping = siteMapping(frame, 2000);
  const toward = frame.north
    .clone()
    .multiplyScalar(Math.cos(bearingDeg * DEG))
    .addScaledVector(frame.east, Math.sin(bearingDeg * DEG));
  const point = anchor
    .clone()
    .multiplyScalar(Math.cos(angleDeg * DEG))
    .addScaledVector(toward, Math.sin(angleDeg * DEG))
    .multiplyScalar(2000);
  const pixel = mapPixelOf(mapping, point);
  const centre = MAP_PX / 2;
  return {
    ...pixel,
    bearing: (Math.atan2(pixel.x - centre, centre - pixel.y) / DEG + 360) % 360,
  };
}

test('on a planet, a point on the map is where its site metres say; one off it sits on the edge toward it', () => {
  // 40 m north-east: on the map, 20 px each way
  const near = seen(40 / 2000 / DEG, 45);
  expect(near.edge).toBe(false);
  expect(near.x - MAP_PX / 2).toBeCloseTo(40 / Math.SQRT2 / METRES_PER_PX, 1);
  expect(MAP_PX / 2 - near.y).toBeCloseTo(40 / Math.SQRT2 / METRES_PER_PX, 1);
  for (const angle of [10, 60, 89, 91, 120, 145, 175, 179.9])
    for (const bearing of [0, 45, 135, 200, 315]) {
      const far = seen(angle, bearing);
      expect(far.edge, `${angle}° away, bearing ${bearing}°`).toBe(true);
      expect(
        Math.abs(((far.bearing - bearing + 540) % 360) - 180),
        `${angle}° away, bearing ${bearing}°`,
      ).toBeLessThan(0.5);
    }
});

async function dots(page: Page) {
  return page
    .getByTestId('minimap-dots')
    .locator('[data-minimap-dot]')
    .evaluateAll((nodes) =>
      nodes.map((node) => {
        const data = (
          node as unknown as { dataset: Record<string, string | undefined> }
        ).dataset;
        return {
          id: data.minimapDot!,
          x: Number(data.x),
          y: Number(data.y),
          edge: data.edge === 'true',
        };
      }),
    );
}

const minimap = (page: Page) => page.getByRole('region', { name: 'Minimap' });

test('the minimap draws every citizen, follows the camera to its site and goes where it is clicked', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  // the town: its folk on the map, the bands on its edge
  await expect(minimap(page)).toHaveAttribute('data-minimap-site', 'town');
  await expect.poll(async () => (await dots(page)).length).toBe(15);
  const inTown = await dots(page);
  expect(inTown.find((dot) => dot.id === 'genzo')!.edge).toBe(false);
  expect(inTown.find((dot) => dot.id === 'pip')!.edge).toBe(true);

  // a click on Genzo's dot: the camera lands next to him
  const genzo = inTown.find((dot) => dot.id === 'genzo')!;
  const canvas = minimap(page).locator('canvas');
  const box = (await canvas.boundingBox())!;
  await page.mouse.click(
    box.x + (genzo.x / MAP_PX) * box.width,
    box.y + (genzo.y / MAP_PX) * box.height,
  );
  await landed(world);
  const at = (await drawn(page)).get('genzo')!.at;
  expect((await cameraOf(world)).distanceTo(at)).toBeLessThan(45);

  // following Pip: the map moves to band B's camp, Pip on it
  await page.getByRole('button', { name: 'people', exact: true }).click();
  await page
    .locator('[data-person="pip"]')
    .getByRole('button', { name: 'follow' })
    .click();
  await landed(world);
  await expect(minimap(page)).toHaveAttribute(
    'data-minimap-site',
    'band_b_camp',
  );
  await expect
    .poll(async () => (await dots(page)).find((dot) => dot.id === 'pip')?.edge)
    .toBe(false);

  await page.keyboard.press('KeyM');
  await expect(minimap(page)).toHaveCount(0);
  await page.keyboard.press('KeyM');
  await expect(minimap(page)).toBeVisible();
  expect(errors).toEqual([]);
});

/** Initial great-circle bearing (degrees from north, clockwise) from one lat/lon to another. */
function bearingDeg(
  from: { lat: number; lon: number },
  to: { lat: number; lon: number },
) {
  const [a, b] = [from.lat * DEG, to.lat * DEG];
  const dLon = (to.lon - from.lon) * DEG;
  const y = Math.sin(dLon) * Math.cos(b);
  const x =
    Math.cos(a) * Math.sin(b) - Math.sin(a) * Math.cos(b) * Math.cos(dLon);
  return (Math.atan2(y, x) / DEG + 360) % 360;
}

test('seen from the town, band B (145° away) and band A sit on the edge toward where they are', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  const world: WorldView = await (await request.get(WORLD_URL)).json();
  const anchor = world.sites.find((site) => site.id === 'town')!.anchor;
  const town = latLonFromDirection(new Vector3(...anchor.position));
  await openHeld(page, errors);
  await expect(minimap(page)).toHaveAttribute('data-minimap-site', 'town');
  await expect.poll(async () => (await dots(page)).length).toBe(15);
  const where = new Map(
    (
      await page.evaluate(() =>
        (globalThis as unknown as MockLiveWindow).__pebbleMockLive
          .entities()
          .citizens.map((citizen) => [citizen.id, citizen.position] as const),
      )
    ).map(([id, position]) => [id, position]),
  );
  const centre = MAP_PX / 2;
  for (const id of ['brak', 'pip', 'tak']) {
    const position = where.get(id)!;
    const away =
      new Vector3(...position.unit).angleTo(new Vector3(...anchor.position)) /
      DEG;
    const dot = (await dots(page)).find((one) => one.id === id)!;
    expect(dot.edge, id).toBe(true);
    const drawnBearing =
      (Math.atan2(dot.x - centre, centre - dot.y) / DEG + 360) % 360;
    const expected = bearingDeg(town, position);
    expect(
      Math.abs(((drawnBearing - expected + 540) % 360) - 180),
      `${id} ${away.toFixed(0)}° away: drawn at ${drawnBearing.toFixed(0)}°, toward ${expected.toFixed(0)}°`,
    ).toBeLessThan(3);
  }
  expect(errors).toEqual([]);
});

for (const [width, height] of [
  [1280, 800],
  [1920, 1080],
]) {
  test(`at ${width}x${height} the People panel ends above the minimap and the clock`, async ({
    page,
  }) => {
    const errors: string[] = [];
    await page.setViewportSize({ width, height });
    const world = await openHeld(page, errors);
    await page.keyboard.press('Tab');
    await page.keyboard.press('KeyF');
    await landed(world);
    await page.getByRole('button', { name: 'people', exact: true }).click();
    const people = page.getByRole('region', { name: 'People' });
    await expect(people).toBeVisible();
    await expect(minimap(page)).toBeVisible();
    const box = async (locator: ReturnType<Page['locator']>) =>
      (await locator.boundingBox())!;
    const panel = await box(people);
    const below = [
      await box(minimap(page)),
      await box(page.getByTestId('live-clock')),
      await box(page.getByRole('button', { name: 'stop following' })),
    ];
    for (const other of below) {
      expect(panel.y + panel.height).toBeLessThanOrEqual(other.y);
      // all of it on screen, not pushed off the bottom
      expect(other.y + other.height).toBeLessThanOrEqual(height);
    }
    // still a useful list: several people without scrolling
    expect(panel.height).toBeGreaterThan(150);
    // the column between and beside its boxes lets clicks through to the scene
    const [map] = below;
    const hits = await page.evaluate(
      (points) =>
        points.map(
          ([x, y]) =>
            (
              globalThis as unknown as {
                document: {
                  elementFromPoint(
                    x: number,
                    y: number,
                  ): { tagName: string } | null;
                };
              }
            ).document.elementFromPoint(x, y)?.tagName,
        ),
      [
        [map.x - 20, map.y + map.height / 2],
        [panel.x + 20, (panel.y + panel.height + map.y) / 2],
      ],
    );
    expect(hits).toEqual(['CANVAS', 'CANVAS']);
    await page.screenshot({
      path: test.info().outputPath(`all-open-${width}.png`),
    });
    expect(errors).toEqual([]);
  });
}

test('a click on the minimap lets go of a followed citizen', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  await page.keyboard.press('Tab');
  await page.keyboard.press('KeyF');
  await expect(world).toHaveAttribute('data-follow');
  await landed(world);
  const box = (await minimap(page).locator('canvas').boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.3);
  await expect(world).not.toHaveAttribute('data-follow');
  await landed(world);
  expect(errors).toEqual([]);
});
