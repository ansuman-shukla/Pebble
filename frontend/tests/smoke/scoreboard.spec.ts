import { expect, type Page, test } from '@playwright/test';

import { openGlobe } from './globe-helpers';
import { goToPerson, openHeld } from './ui-helpers';

/*
 * The inspector's why line, purse and standing (10-world-v1 §5.4) on the mock feed, and on the engine's run the
 * scoreboard tab (§7): sortable, a click on a row selects, and the inspector shows that citizen's ambition.
 */

const inspector = (page: Page) =>
  page.getByRole('region', { name: 'Inspector' });
const scoreboard = (page: Page) =>
  page.getByRole('region', { name: 'Scoreboard' });

test('the inspector tells why they act, their purse, rank and standing', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  await goToPerson(page, world, 'genzo');
  const select = async (id: string, name: RegExp) => {
    await page
      .locator(`[data-person="${id}"]`)
      .getByRole('button', { name })
      .click();
    await expect(world).toHaveAttribute('data-selected', id);
  };
  await select('genzo', /Genzo/);
  const panel = inspector(page);
  // the mock feed's farmer starts at work in the paddies
  await expect(panel.getByTestId('inspector-why')).toHaveText(
    'get the day’s work done · duty',
  );
  await expect(panel.getByTestId('inspector-status')).toHaveText('60 coins');
  await expect(panel).toContainText('rank 2 (commoner)');
  await expect(panel).toContainText('standing (50)');

  await select('tadamasa', /Tadamasa/);
  await expect(panel.getByRole('heading', { level: 2 })).toHaveText(
    'Lord Tadamasa',
  );
  await expect(panel.getByTestId('inspector-status')).toHaveText('2015 coins');
  await expect(panel).toContainText('rank 5 (lord)');
  // the mock feed has no backend run: no scoreboard to show
  await expect(page.getByRole('button', { name: 'scores' })).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("B opens the scoreboard: it sorts, a row selects, the inspector shows the citizen's ambition", async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors);
  await expect(world).toHaveAttribute('data-live-status', 'live', {
    timeout: 30_000,
  });
  await page.keyboard.press('KeyB');
  const board = scoreboard(page);
  await expect(board.getByTestId('scoreboard-money')).toContainText('✓');
  const rows = board.locator('[data-row]');
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThanOrEqual(15);
  await expect(board.getByTestId('scoreboard-groups')).toContainText(
    'Castle town',
  );
  await expect(board.getByTestId('scoreboard-stall')).toContainText('rice');

  await board.getByRole('button', { name: 'Coins' }).click();
  const coins = async () =>
    (await rows.locator('[data-col="coins"]').allTextContents()).map(Number);
  const descending = await coins();
  expect(descending).toEqual([...descending].sort((a, b) => b - a));
  await board.getByRole('button', { name: /Coins/ }).click();
  const ascending = await coins();
  expect(ascending).toEqual([...ascending].sort((a, b) => a - b));

  const richest = descending[0];
  const row = rows.filter({
    has: page.locator(`[data-col="coins"]:text-is("${richest}")`),
  });
  const id = (await row.first().getAttribute('data-row'))!;
  await row.first().click();
  await expect(world).toHaveAttribute('data-selected', id);
  await expect(row.first()).toHaveAttribute('aria-selected', 'true');
  await expect(inspector(page).getByTestId('inspector-ambition')).toContainText(
    /%|done/,
  );
  await expect(inspector(page).getByTestId('inspector-status')).toContainText(
    'worth',
  );

  await page.keyboard.press('KeyB');
  await expect(board).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('a replay shows the scoreboard of its tick', async ({ page }) => {
  const errors: string[] = [];
  await openGlobe(page, errors, '?tick=1000');
  const badge = page.getByTestId('replay-badge');
  await expect(badge).toContainText(/day \d+ · \d\d:\d\d/);
  const [, day, time] = (await badge.textContent())!.match(
    /day (\d+) · (\d\d:\d\d)/,
  )!;
  await page.getByRole('button', { name: 'scores' }).click();
  const board = scoreboard(page);
  await expect(board.locator('[data-row]').first()).toBeVisible();
  await expect(board.locator('header')).toContainText(`day ${day} ${time}`);
  expect(errors).toEqual([]);
});
