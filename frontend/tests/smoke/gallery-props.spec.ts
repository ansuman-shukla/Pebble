import { expect, test } from '@playwright/test';

import { HAND_PROPS, PROPS } from '../../src/lib/world/assets';
import { KIT_LOOKS } from '../../src/lib/world/kit-looks';

test('gallery shows every World v1 prop, hand prop and kit look in the props and tools view', async ({
  page,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));

  await page.goto('/gallery');
  await page.getByRole('button', { name: 'props & tools' }).click();

  // the shelf's labels appear only once every model on it has loaded
  for (const kind of [
    'berry_bush',
    'root_patch',
    'reed_bed',
    'tree_stump',
    'flint_seam',
    'obsidian_field',
    'cave_mouth',
    'bone_scatter',
    'signpost',
    'log_bridge',
    'boundary_stone',
    'cairn',
    'market_stall',
    'forge',
    'anvil',
    'chest',
    'grain_sack',
    'coin_pouch',
    'camp_drying_rack',
    'sleeping_mat',
    'field_barricade',
    'castle_keep',
  ] satisfies (keyof typeof PROPS)[]) {
    await expect(page.locator(`[data-label="prop-${kind}"]`)).toHaveText(
      kind.replaceAll('_', ' '),
      { timeout: 30_000 },
    );
  }
  for (const kind of Object.keys(HAND_PROPS))
    await expect(page.locator(`[data-label="hand-${kind}"]`)).toHaveText(
      kind.replaceAll('_', ' '),
    );
  for (const id of Object.keys(KIT_LOOKS))
    await expect(page.locator(`[data-label="kit-${id}"]`)).toHaveText(
      id.replaceAll('_', ' '),
    );
  // the wild kinds keep their own view
  await expect(page.locator('[data-label="prop-oak_tree"]')).toHaveCount(0);
  expect(errors).toEqual([]);
});
