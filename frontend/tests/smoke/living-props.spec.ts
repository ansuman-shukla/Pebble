import { expect, type Page, test } from '@playwright/test';

import { openGlobe } from './globe-helpers';

/*
 * Living props on the planet with the mock feed (`?mockLive=1`, starting 08:00 at the town's main gate): the mill
 * wheel turns and the nearest props play their loops at the clock's visual rate, cold fires hide their fuel and
 * burning ones smoke and spark, a door opens while a citizen passes, and the gate stays within its draw calls.
 */

/** The town gate's draw-call budget (World v1 plan, L4). */
const GATE_DRAW_CALLS = 180;

type MockLiveWindow = {
  __pebbleMockLive: {
    skip(ticks: number): void;
    setClock(change: { speed?: number; paused?: boolean }): void;
  };
};

test.describe.configure({ timeout: 120_000 });

const props = async (page: Page, name: string) =>
  (await page.getByTestId('props').getAttribute(`data-${name}`)) ?? '';

/** The mill wheel's angle from rest now (radians). */
async function wheelAngle(page: Page) {
  const turn = (await props(page, 'turns'))
    .split(' ')
    .find((entry) => entry.startsWith('water-wheel:'));
  return turn ? Number(turn.split(':')[1]) : null;
}

const setClock = (page: Page, change: { speed?: number; paused?: boolean }) =>
  page.evaluate(
    (clock) =>
      (globalThis as unknown as MockLiveWindow).__pebbleMockLive.setClock(
        clock,
      ),
    change,
  );

test('the mill wheel turns and the nearest props play their loops, still while paused', async ({
  page,
}) => {
  const errors: string[] = [];
  await openGlobe(page, errors, '?mockLive=1');
  await expect.poll(() => wheelAngle(page), { timeout: 30_000 }).not.toBeNull();
  const first = await wheelAngle(page);
  await page.waitForTimeout(400);
  expect(await wheelAngle(page)).not.toBe(first);
  // the gate's trees and fences play, within the budget
  const playing = Number(await props(page, 'playing'));
  expect(playing).toBeGreaterThan(5);
  expect(playing).toBeLessThanOrEqual(64 + 1);
  expect((await props(page, 'playing-kinds')).split(',')).toEqual(
    expect.arrayContaining(['water_wheel', 'sculpted_pine', 'bamboo_fence']),
  );
  const windTime = Number(await props(page, 'wind-time'));
  await page.waitForTimeout(300);
  expect(Number(await props(page, 'wind-time'))).toBeGreaterThan(windTime);

  // paused: clips and wind hold still
  await setClock(page, { paused: true });
  await page.waitForTimeout(500);
  const paused = [await wheelAngle(page), await props(page, 'wind-time')];
  await page.waitForTimeout(500);
  expect([await wheelAngle(page), await props(page, 'wind-time')]).toEqual(
    paused,
  );
  expect(errors).toEqual([]);
});

test('cold fires hide their fuel; burning ones smoke and spark, and the gate stays in budget', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors, '?mockLive=1');
  // 08:00: the gate's baskets are cold, their fuel hidden; the camps' burning pits are kilometres away
  await expect
    .poll(() => props(page, 'hidden'), { timeout: 30_000 })
    .toBe('main-gate-fire-e:fuel,main-gate-fire-w:fuel');
  expect(await props(page, 'puffs')).toBe('0');
  await expect(world).toHaveAttribute('data-draw-calls', /\d+/);
  expect(
    Number(await world.getAttribute('data-draw-calls')),
  ).toBeLessThanOrEqual(GATE_DRAW_CALLS);

  // to 19:00: the baskets burn: fuel shown, ten puffs and eight sparks each
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.skip(11 * 60),
  );
  await expect.poll(() => props(page, 'hidden')).toBe('');
  await expect.poll(() => props(page, 'puffs')).toBe('20');
  expect(await props(page, 'sparks')).toBe('16');
  await page.waitForTimeout(1500);
  expect(
    Number(await world.getAttribute('data-draw-calls')),
  ).toBeLessThanOrEqual(GATE_DRAW_CALLS);
  expect(errors).toEqual([]);
});

test('a door opens while a citizen passes and shuts behind them', async ({
  page,
}) => {
  const errors: string[] = [];
  await openGlobe(page, errors, '?mockLive=1');
  await setClock(page, { speed: 10 });
  // the first walkers pass a townhouse door on the cross street within the first game minutes
  await expect
    .poll(() => props(page, 'open-doors'), { timeout: 60_000, intervals: [50] })
    .not.toBe('');
  const opened = (await props(page, 'open-doors')).split(',');
  expect(
    opened.every((id) =>
      /^cross-|^farmhouse|^storehouse|^temple|^pagoda/.test(id),
    ),
  ).toBe(true);
  await expect
    .poll(async () => (await props(page, 'open-doors')).split(','), {
      timeout: 10_000,
      intervals: [50],
    })
    .not.toEqual(expect.arrayContaining(opened));
  expect(errors).toEqual([]);
});
