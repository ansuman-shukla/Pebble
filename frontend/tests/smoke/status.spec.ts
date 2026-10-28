import { expect, test } from '@playwright/test';

test('status page shows the api and database are up', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Pebble' })).toBeVisible();
  await expect(page.getByLabel('API: ok')).toBeVisible();
  await expect(page.getByLabel('Database: up')).toBeVisible();
});
