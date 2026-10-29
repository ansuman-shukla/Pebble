import { expect, type Page, test } from '@playwright/test';
import { PerspectiveCamera, Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import { latLonFromDirection } from '../../src/lib/world/globe';
import { WORLD_URL } from './globe-helpers';
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
  const box = (await page.locator('canvas[data-engine]').boundingBox())!;
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

  // the ground in the lower middle of the scene, above the clock and between the panels: nobody there
  const box = (await page.locator('canvas[data-engine]').boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height * 0.85);
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
  const nth = (at: number) => order[(at + order.length) % order.length];
  await page.keyboard.press('Tab');
  await expect(world).toHaveAttribute('data-selected', /./);
  const first = order.indexOf((await world.getAttribute('data-selected'))!);
  await page.keyboard.press('Tab');
  await expect(world).toHaveAttribute('data-selected', nth(first + 1));
  await page.keyboard.press('Tab');
  await expect(world).toHaveAttribute('data-selected', nth(first + 2));
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Shift+Tab');
  await expect(world).toHaveAttribute('data-selected', nth(first - 1));
  const last = nth(first - 1);

  await page.keyboard.press('KeyI');
  await expect(inspector(page)).toHaveCount(0);
  await page.keyboard.press('KeyI');
  await expect(inspector(page)).toHaveAttribute('data-inspect', last);

  await page.keyboard.press('KeyF');
  await expect(world).toHaveAttribute('data-follow', last);
  await landed(world);
  await page.keyboard.press('KeyG');
  await expect(world).not.toHaveAttribute('data-follow');
  await landed(world);
  const subject = (await drawn(page)).get(last)!.at;
  expect((await cameraOf(world)).distanceTo(subject)).toBeLessThan(45);
  expect(errors).toEqual([]);
});

test('with nobody selected Tab starts at the citizen nearest where the camera looks: the followed one, or the nearest', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  // following Pip (last in the list, at band B): Tab and Shift+Tab both start at Pip
  await page.getByRole('button', { name: 'people', exact: true }).click();
  await page
    .locator('[data-person="pip"]')
    .getByRole('button', { name: 'follow' })
    .click();
  await landed(world);
  await page.getByRole('button', { name: 'people', exact: true }).click();
  for (const key of ['Tab', 'Shift+Tab']) {
    await page.keyboard.press(key);
    await expect(world).toHaveAttribute('data-selected', 'pip');
    // closing the inspector lets go of the selection only
    await inspector(page)
      .getByRole('button', { name: 'close inspector' })
      .click();
    await expect(world).not.toHaveAttribute('data-selected');
    await expect(world).toHaveAttribute('data-follow', 'pip');
  }

  // not following: from the camera at Haru's stall, Tab picks whoever is drawn nearest the look-at point
  await page.keyboard.press('Escape');
  await goToPerson(page, world, 'haru');
  await page.getByRole('button', { name: 'people', exact: true }).click();
  const avatar = new Vector3(
    ...(await world.getAttribute('data-avatar'))!.split(',').map(Number),
  );
  const byDistance = [...(await drawn(page))]
    .map(([id, { at }]) => ({ id, away: at.distanceTo(avatar) }))
    .sort((a, b) => a.away - b.away);
  expect(byDistance[1].away - byDistance[0].away).toBeGreaterThan(0.5);
  await page.keyboard.press('Tab');
  await expect(world).toHaveAttribute('data-selected', byDistance[0].id);
  expect(errors).toEqual([]);
});

test('keys pressed with Ctrl, Cmd or Alt are left to the browser', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  const speed = page.getByTestId('live-speed');
  await expect(speed).toHaveText('paused');
  for (const modifier of ['Control', 'Meta', 'Alt'])
    for (const key of ['Tab', 'Space', 'Digit3', 'KeyT'])
      await page.keyboard.press(`${modifier}+${key}`);
  await expect(world).not.toHaveAttribute('data-selected');
  await expect(speed).toHaveText('paused');
  await expect(world).toHaveAttribute('data-travel', 'false');
  // the same keys alone drive the scene
  await page.keyboard.press('Tab');
  await expect(world).toHaveAttribute('data-selected', /./);
  await page.keyboard.press('Digit3');
  await expect(speed).toHaveText('×60');
  await page.keyboard.press('KeyT');
  await expect(world).toHaveAttribute('data-travel', 'true');
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

test('Tab and Space on a focused button work the button, not the scene', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  const speed = page.getByTestId('live-speed');
  await expect(speed).toHaveText('paused');
  await page.getByRole('button', { name: '×10', exact: true }).focus();
  await page.keyboard.press('Space');
  await expect(speed).toHaveText('×10');
  const sixty = page.getByRole('button', { name: '×60', exact: true });
  await sixty.focus();
  await page.keyboard.press('Tab');
  await expect(sixty).not.toBeFocused();
  await expect(world).not.toHaveAttribute('data-selected');
  await expect(speed).toHaveText('×10');
  expect(errors).toEqual([]);
});

test('the hint line names the spectator keys', async ({ page }) => {
  const errors: string[] = [];
  await openHeld(page, errors);
  await expect(page.getByTestId('spectator-keys')).toHaveText(
    'Tab select, F follow, G go to, I inspector, L events, Space pause, 1-4 speed, Esc let go',
  );
  expect(errors).toEqual([]);
});

test('at 1280x800 the toolbar ends above the inspector and the People panel, however many lines it wraps onto', async ({
  page,
}) => {
  const errors: string[] = [];
  await page.setViewportSize({ width: 1280, height: 800 });
  const world = await openHeld(page, errors);
  await page.keyboard.press('Tab');
  await page.getByRole('button', { name: 'people', exact: true }).click();
  const panels = [
    inspector(page),
    page.getByRole('region', { name: 'People' }),
  ];
  const toolbarEnd = async () => {
    const keys = (await page.getByTestId('spectator-keys').boundingBox())!;
    return keys.y + keys.height;
  };
  const panelsBelow = async (end: number) => {
    for (const panel of panels) {
      await expect(panel).toBeVisible();
      await expect
        .poll(async () => (await panel.boundingBox())!.y)
        .toBeGreaterThan(end);
    }
  };
  const twoLines = await toolbarEnd();
  await panelsBelow(twoLines);
  await page.screenshot({ path: test.info().outputPath('toolbar-1280.png') });

  // fly mode's keys and the drop hint wrap the hint onto a second line: the panels move down with the keys line
  await page.getByRole('button', { name: 'fly', exact: true }).click();
  await page.getByRole('button', { name: 'drop', exact: true }).click();
  await expect(world).toHaveAttribute('data-dropping', 'true');
  await expect.poll(toolbarEnd).toBeGreaterThan(twoLines + 10);
  await panelsBelow(await toolbarEnd());
  await page.screenshot({
    path: test.info().outputPath('toolbar-fly-drop-1280.png'),
  });
  expect(errors).toEqual([]);
});

test('going to a site stops following (F18); footer and clock tell the camera place and its time (F19, F20)', async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  const view = (await (await request.get(WORLD_URL)).json()) as WorldView;
  const lonOf = (id: string) =>
    latLonFromDirection(
      new Vector3(
        ...view.sites.find((site) => site.id === id)!.anchor.position,
      ),
    ).lon;
  const DAY = 24 * 60;
  // local time runs 4 minutes behind per degree of longitude west of the town
  const bandBBehind =
    ((((lonOf('town') - lonOf('band_b_camp')) * 4) % DAY) + DAY) % DAY;
  expect(bandBBehind).toBeGreaterThan(60);
  const world = await openHeld(page, errors);
  const footer = page.getByTestId('camera-place');
  // in town: town time only
  await expect(world).toHaveAttribute('data-camera-site', 'town');
  await expect(page.getByTestId('site-time')).toHaveCount(0);
  const townTime = (await page.getByTestId('live-time').textContent())!.match(
    /\d\d:\d\d/,
  )![0];
  // anywhere in town the footer tells town time (one time across a site): at Haru's stall too
  await goToPerson(page, world, 'haru');
  await expect(footer).toContainText(/town -?\d+, -?\d+/);
  await expect(footer).toHaveText(new RegExp(`^${townTime}`));
  await page.getByRole('button', { name: 'people', exact: true }).click();

  // following Pip at band B's camp, behind the town by its longitude
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
    (townHours * 60 + townMinutes - (hours * 60 + minutes) + DAY) % DAY;
  // both clocks show whole minutes
  expect(Math.abs(behind - bandBBehind)).toBeLessThanOrEqual(1);
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
