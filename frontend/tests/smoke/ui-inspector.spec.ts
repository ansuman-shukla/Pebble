import { expect, type Page, test } from '@playwright/test';
import { PerspectiveCamera, Vector3 } from 'three';

import { cameraOf, drawn, goToPerson, landed, openHeld } from './ui-helpers';

/*
 * Selection, the inspector and the spectator keys on the mock feed, and the audit's UI faults: going to a site
 * stops following (F18), the footer describes where the camera is (F19), the clock shows that place's local
 * time (F20).
 */

/** Where a world point shows on the page (CSS px), from the camera the page reports (fov 50, like the Canvas). */
async function onPage(page: Page, point: Vector3) {
  const world = page.getByTestId('world');
  const [x, y, z, qx, qy, qz, qw] = (await world.getAttribute('data-camera'))!
    .split(',')
    .map(Number);
  const box = (await page.locator('canvas').boundingBox())!;
  const camera = new PerspectiveCamera(50, box.width / box.height, 0.1, 3000);
  camera.position.set(x, y, z);
  camera.quaternion.set(qx, qy, qz, qw);
  camera.updateMatrixWorld();
  const projected = point.clone().project(camera);
  return {
    x: box.x + ((projected.x + 1) / 2) * box.width,
    y: box.y + ((1 - projected.y) / 2) * box.height,
  };
}

const inspector = (page: Page) =>
  page.getByRole('region', { name: 'Inspector' });

test('a click on a body selects them and opens the inspector; a click on the ground or Esc lets go', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  await goToPerson(page, world, 'tak');
  // the People panel covers the right of the scene: close it
  await page.getByRole('button', { name: 'people', exact: true }).click();
  const tak = (await drawn(page)).get('tak')!.at;
  const chest = tak.clone().addScaledVector(tak.clone().normalize(), 1.2);
  const spot = await onPage(page, chest);
  // a little off the chest still picks the body
  await page.mouse.click(spot.x + 15, spot.y + 5);
  await expect(world).toHaveAttribute('data-selected', 'tak');
  await expect(inspector(page)).toHaveAttribute('data-inspect', 'tak');
  await expect(inspector(page).getByTestId('inspector-now')).not.toBeEmpty();

  // the ground far below the body: nobody there
  const below = await onPage(page, tak.clone().multiplyScalar(0.99995));
  await page.mouse.click(below.x, Math.min(below.y + 120, 860));
  await expect(world).not.toHaveAttribute('data-selected');
  await expect(inspector(page)).toHaveCount(0);

  await page.mouse.click(spot.x, spot.y);
  await expect(world).toHaveAttribute('data-selected', 'tak');
  await page.keyboard.press('Escape');
  await expect(world).not.toHaveAttribute('data-selected');
  expect(errors).toEqual([]);
});

test('a click on a chip or a row of the People panel selects; the selected chip stays whole', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  await goToPerson(page, world, 'oru');
  await page
    .locator('[data-person="mena"]')
    .getByRole('button', { name: /Mena/ })
    .click();
  await expect(world).toHaveAttribute('data-selected', 'mena');
  await expect(inspector(page)).toContainText('Mena');
  await expect(page.locator('[data-person="mena"]')).toHaveAttribute(
    'aria-selected',
    'true',
  );
  // pinned: Mena's own chip shows, whole, never inside a cluster
  const mena = page.locator('[data-label="npc-mena"]');
  await expect(mena).toBeVisible();
  await expect(mena).toHaveAttribute('data-members', 'mena');
  await expect(mena).toHaveAttribute('data-view', 'full');

  await page.getByRole('button', { name: 'people', exact: true }).click();
  const chip = page.locator('[data-label^="npc-"]:visible').first();
  const leader = (await chip.getAttribute('data-members'))!.split(' ')[0];
  await chip.click();
  await expect(world).toHaveAttribute('data-selected', leader);
  expect(errors).toEqual([]);
});

test('Tab cycles the selection, F follows it, G goes to it, I hides and shows the inspector', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  const order = await page
    .locator('[data-npc]')
    .evaluateAll((nodes) =>
      nodes.map(
        (node) =>
          (node as unknown as { dataset: Record<string, string> }).dataset.npc,
      ),
    );
  await page.keyboard.press('Tab');
  await expect(world).toHaveAttribute('data-selected', order[0]);
  await page.keyboard.press('Tab');
  await expect(world).toHaveAttribute('data-selected', order[1]);
  await page.keyboard.press('Shift+Tab');
  await expect(world).toHaveAttribute('data-selected', order[0]);
  await page.keyboard.press('Shift+Tab');
  await expect(world).toHaveAttribute('data-selected', order.at(-1)!);

  await page.keyboard.press('KeyI');
  await expect(inspector(page)).toHaveCount(0);
  await page.keyboard.press('KeyI');
  await expect(inspector(page)).toHaveAttribute('data-inspect', order.at(-1)!);

  await page.keyboard.press('KeyF');
  await expect(world).toHaveAttribute('data-follow', order.at(-1)!);
  await landed(world);
  await page.keyboard.press('KeyG');
  await expect(world).not.toHaveAttribute('data-follow');
  await landed(world);
  const subject = (await drawn(page)).get(order.at(-1)!)!.at;
  expect((await cameraOf(world)).distanceTo(subject)).toBeLessThan(45);
  expect(errors).toEqual([]);
});

test('Space pauses and 1-4 pick the clock speeds', async ({ page }) => {
  const errors: string[] = [];
  await openHeld(page, errors);
  const speed = page.getByTestId('live-speed');
  await expect(speed).toHaveText('paused');
  await page.keyboard.press('Space');
  await expect(speed).toHaveText('real time');
  await page.keyboard.press('Space');
  await expect(speed).toHaveText('paused');
  for (const [key, words] of [
    ['Digit3', '×60'],
    ['Digit2', '×10'],
    ['Digit4', '×600'],
    ['Digit1', 'real time'],
  ])
    await page.keyboard.press(key).then(() => expect(speed).toHaveText(words));
  expect(errors).toEqual([]);
});

test('going to a site stops following (F18); footer and clock tell the camera place and its time (F19, F20)', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  const footer = page.getByTestId('camera-place');
  // in town: town time only
  await expect(world).toHaveAttribute('data-camera-site', 'town');
  await expect(page.getByTestId('site-time')).toHaveCount(0);
  const townTime = (await page.getByTestId('live-time').textContent())!.match(
    /\d\d:\d\d/,
  )![0];

  // following Pip at band B's camp, 11 hours behind the town
  await page.getByRole('button', { name: 'people', exact: true }).click();
  await page
    .locator('[data-person="pip"]')
    .getByRole('button', { name: 'follow' })
    .click();
  await landed(world);
  await expect(world).toHaveAttribute('data-camera-site', 'band_b_camp');
  await expect(footer).toContainText('Band B camp');
  await expect(footer).not.toContainText('town ');
  const siteTime = page.getByTestId('site-time');
  await expect(siteTime).toContainText('Band B camp');
  const [hours, minutes] = (await siteTime.textContent())!
    .match(/(\d\d):(\d\d)/)!
    .slice(1)
    .map(Number);
  const [townHours, townMinutes] = townTime.split(':').map(Number);
  const behind =
    (townHours * 60 + townMinutes - (hours * 60 + minutes) + 24 * 60) %
    (24 * 60);
  expect(behind / 60).toBeGreaterThan(9);
  expect(behind / 60).toBeLessThan(13);
  // the footer starts with the same local time (the clock is held)
  const pad = (value: number) => String(value).padStart(2, '0');
  await expect(footer).toHaveText(new RegExp(`^${pad(hours)}:${pad(minutes)}`));

  // go to band A's camp from the menu: the camera stops following Pip and lands there
  await page.getByRole('button', { name: /go to/ }).first().click();
  await page.getByRole('menuitem', { name: /Band A/i }).click();
  await expect(world).not.toHaveAttribute('data-follow');
  await expect(world).toHaveAttribute('data-camera-site', 'band_a_camp', {
    timeout: 10_000,
  });
  await expect(footer).toContainText(/Band A/i);
  expect(errors).toEqual([]);
});
