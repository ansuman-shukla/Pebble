import { expect, test } from '@playwright/test';

test('gallery shows all 22 citizens animated and every animal labelled', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });

  await page.goto('/gallery');

  const gallery = page.getByTestId('gallery');
  await expect(gallery).toHaveAttribute('data-citizens-ready', '22', {
    timeout: 20_000,
  });
  await expect(page.locator('[data-label]')).toHaveCount(37);
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

test('gallery shows every landmark kind in the plants and rocks view', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await page.goto('/gallery');
  await page.getByRole('button', { name: 'plants & rocks' }).click();

  for (const kind of [
    'giant_tree',
    'rock_spire',
    'boulder',
    'basalt_column',
    'lava_rock',
    'fumarole',
    'geyser',
    'hot_spring_pool',
    'obsidian',
    'snowy_spruce',
    'ice_block',
  ]) {
    await expect(page.locator(`[data-label="prop-${kind}"]`)).toHaveText(
      kind.replaceAll('_', ' '),
      { timeout: 20_000 },
    );
  }
  await expect(page.locator('[data-label="prop-oak_tree"]')).toBeVisible();
  expect(errors).toEqual([]);
});
