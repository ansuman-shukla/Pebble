import { expect, type Locator, type Page, test } from '@playwright/test';

/*
 * /dev/walk: spawn (0, 8) facing north; plaster wall along z = -10 with the gatehouse in the gap at x = 0;
 * moat z -22..-16 crossed by the bridge at x = 0; townhouse east of the path at (10, 0).
 */

interface Position {
  x: number;
  y: number;
  z: number;
}

const WALL_FACE_Z = -9.45; // coping at z = -9.68 + player radius 0.3, small tolerance

async function openSandbox(page: Page, errors: string[]) {
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.goto('/dev/walk');
  const sandbox = page.getByTestId('walk-sandbox');
  await expect(sandbox).toHaveAttribute('data-walk-ready', 'true', {
    timeout: 30_000,
  });
  return sandbox;
}

async function position(sandbox: Locator): Promise<Position> {
  const [x, y, z] = await Promise.all(
    ['x', 'y', 'z'].map((axis) => sandbox.getAttribute(`data-player-${axis}`)),
  );
  return { x: Number(x), y: Number(y), z: Number(z) };
}

/** Polls the player position until `done` holds, keeping every sample. */
async function track(
  sandbox: Locator,
  done: (position: Position) => boolean,
  timeout = 20_000,
) {
  const samples: Position[] = [];
  await expect
    .poll(
      async () => {
        const sample = await position(sandbox);
        samples.push(sample);
        return done(sample);
      },
      { timeout, intervals: [100] },
    )
    .toBe(true);
  return samples;
}

test.describe.configure({ timeout: 60_000 });

test('walks north through the gatehouse and over the bridge', async ({
  page,
}) => {
  const errors: string[] = [];
  const sandbox = await openSandbox(page, errors);
  expect(await position(sandbox)).toEqual({ x: 0, y: 0, z: 8 });

  await page.keyboard.down('Shift');
  await page.keyboard.down('KeyW');
  const samples = await track(sandbox, ({ z }) => z < -19);
  await page.keyboard.up('KeyW');
  await page.keyboard.up('Shift');

  // the handrail stands about 0.65 m above the deck: too high a step, so it stops a sideways walk
  await page.keyboard.down('KeyD');
  await page.waitForTimeout(1_000);
  await page.keyboard.up('KeyD');
  const atRail = await position(sandbox);
  expect(atRail.x).toBeGreaterThan(0.3);
  expect(atRail.x).toBeLessThan(0.75);
  expect(atRail.y).toBeLessThan(0.6);

  await page.keyboard.down('KeyA');
  await track(sandbox, ({ x }) => x < 0.1);
  await page.keyboard.up('KeyA');
  await page.keyboard.down('Shift');
  await page.keyboard.down('KeyW');
  samples.push(...(await track(sandbox, ({ z }) => z < -23)));
  await page.keyboard.up('KeyW');
  await page.keyboard.up('Shift');

  // straight through the passage and along the deck, never pushed aside
  for (const { x } of samples) expect(Math.abs(x)).toBeLessThan(0.3);
  // the deck crown is about 0.45 m above the banks
  const onBridge = samples.filter(({ z }) => z < -18 && z > -20);
  expect(onBridge.length).toBeGreaterThan(0);
  expect(Math.max(...onBridge.map(({ y }) => y))).toBeGreaterThan(0.3);
  // north of the moat, back on the ground
  await expect.poll(async () => (await position(sandbox)).y).toBeLessThan(0.05);
  expect(errors).toEqual([]);
});

test('the wall stops the player away from the gate', async ({ page }) => {
  const errors: string[] = [];
  const sandbox = await openSandbox(page, errors);

  await page.keyboard.down('Shift');
  await page.keyboard.down('KeyD');
  await track(sandbox, ({ x }) => x > 15);
  await page.keyboard.up('KeyD');

  await page.keyboard.down('KeyW');
  const approach = await track(sandbox, ({ z }) => z < -9);
  await page.waitForTimeout(1_500);
  const pressed = await position(sandbox);
  await page.keyboard.up('KeyW');
  await page.keyboard.up('Shift');

  for (const { z } of [...approach, pressed])
    expect(z).toBeGreaterThan(WALL_FACE_Z);
  expect(pressed.z).toBeLessThan(-9.2);
  expect(pressed.x).toBeGreaterThan(15);
  expect(errors).toEqual([]);
});

test('C cycles the cameras and only the follow camera walks', async ({
  page,
}) => {
  const errors: string[] = [];
  const sandbox = await openSandbox(page, errors);
  const pressedMode = page.locator('button[aria-pressed="true"]');
  await expect(pressedMode).toHaveText('follow');

  for (const mode of ['orbit', 'fly']) {
    await page.keyboard.press('KeyC');
    await expect(pressedMode).toHaveText(mode);
    await page.keyboard.down('KeyW');
    await page.waitForTimeout(700);
    await page.keyboard.up('KeyW');
    expect(await position(sandbox)).toEqual({ x: 0, y: 0, z: 8 });
  }

  await page.keyboard.press('KeyC');
  await expect(pressedMode).toHaveText('follow');
  await page.getByRole('button', { name: 'orbit' }).click();
  await expect(pressedMode).toHaveText('orbit');
  await page.getByRole('button', { name: 'follow' }).click();
  await page.keyboard.down('KeyW');
  await track(sandbox, ({ z }) => z < 7);
  await page.keyboard.up('KeyW');
  expect(errors).toEqual([]);
});
