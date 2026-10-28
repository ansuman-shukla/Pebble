import { expect, test } from '@playwright/test';

/*
 * The world must load from any origin that reaches the frontend (a preview proxy, 127.0.0.1 instead of localhost),
 * so the browser only ever calls its own origin and vite proxies /api to the backend.
 */

test.describe.configure({ timeout: 120_000 });

test('the world loads and walks when opened from another origin', async ({
  page,
  baseURL,
}) => {
  const otherOrigin = new URL(baseURL ?? '');
  expect(otherOrigin.hostname).toBe('localhost');
  otherOrigin.hostname = '127.0.0.1';

  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.goto(otherOrigin.href);
  const world = page.getByTestId('world');
  await expect(world).toHaveAttribute('data-world-ready', 'true', {
    timeout: 60_000,
  });

  const startZ = Number(await world.getAttribute('data-player-z'));
  await page.keyboard.down('KeyW');
  await page.waitForTimeout(2_000);
  await page.keyboard.up('KeyW');
  expect(Number(await world.getAttribute('data-player-z'))).toBeLessThan(
    startZ - 1,
  );
  expect(errors).toEqual([]);
});
