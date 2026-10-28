import { expect, test } from '@playwright/test';

test('gallery shows all 15 citizens animated and every animal labelled', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });

  await page.goto('/gallery');

  const gallery = page.getByTestId('gallery');
  await expect(gallery).toHaveAttribute('data-citizens-ready', '15', {
    timeout: 20_000,
  });
  await expect(page.locator('[data-label]')).toHaveCount(30);
  await expect(page.locator('[data-label="town-lord"]')).toHaveText(
    'Lord of the castle',
  );
  await expect(page.locator('[data-label="polar_bear"]')).toHaveText(
    'polar bear',
  );

  await page.getByRole('button', { name: 'Walk' }).click();
  await expect(page.getByRole('button', { name: 'Stand still' })).toBeVisible();
  expect(errors).toEqual([]);
});
