import { expect, type Page, test } from '@playwright/test';

import {
  MAP_PX,
  mapPixel,
  mapPoint,
  METRES_PER_PX,
} from '../../src/lib/world/minimap';
import { cameraOf, drawn, landed, openHeld } from './ui-helpers';

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
