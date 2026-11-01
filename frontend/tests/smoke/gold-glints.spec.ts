import { expect, test } from '@playwright/test';

import { GLINTS, glintCount } from '../../src/lib/world/gold-glints';
import { openGlobe } from './globe-helpers';

/*
 * A gold pool glints (10 §1.1: "a pool glinting with gold", stage `glints-N` of 4): the panning spot reads from the
 * bank, fewer glints as it is panned out, none once empty (critic round 1: no glints on the falls pool).
 */

test('a gold pool shows the glints its stage names, all of them while full', () => {
  expect(GLINTS).toBe(4);
  expect(glintCount(undefined)).toBe(4);
  expect(glintCount({ fill: 0.6, stage: 'glints-3' })).toBe(3);
  expect(glintCount({ fill: 0, stage: 'glints-0' })).toBe(0);
  // a stage the feed didn't name: its share of the 4, rounded up like the backend's
  expect(glintCount({ fill: 0.3, stage: null })).toBe(2);
  expect(glintCount({ fill: 0.25, stage: null })).toBe(1);
});

type GlintsWindow = {
  __pebbleGlints?: () => Record<string, number>;
  __pebbleMockLive: {
    sendNow: (
      type: string,
      actor: string,
      payload: Record<string, unknown>,
    ) => void;
  };
};

/** By the falls pool's gold pool, on the mock feed. */
const BY_THE_GOLD = '?mockLive=1&at=-1.5706,14.9092,0';

test('the falls pool loses its glints as it is panned out', async ({
  page,
}) => {
  const errors: string[] = [];
  await openGlobe(page, errors, BY_THE_GOLD);
  const glints = () =>
    page.evaluate(() =>
      (globalThis as unknown as GlintsWindow).__pebbleGlints?.(),
    );
  await expect.poll(glints, { timeout: 30_000 }).toEqual({
    'falls_pool:gold_pool': 4,
  });
  for (const [after, stage, shown] of [
    [12, 'glints-2', 2],
    [0, 'glints-0', 0],
  ] as const) {
    await page.evaluate(
      ([after, stage]) =>
        (globalThis as unknown as GlintsWindow).__pebbleMockLive.sendNow(
          'node_changed',
          'kaz',
          {
            node: 'falls_pool:gold_pool',
            kind: 'gold_pool',
            item: 'gold',
            before: 40,
            after,
            stage,
          },
        ),
      [after, stage] as const,
    );
    await expect
      .poll(async () => (await glints())?.['falls_pool:gold_pool'])
      .toBe(shown);
  }
  expect(errors).toEqual([]);
});
