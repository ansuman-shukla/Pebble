import { expect, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  buildTerrain,
  decodeWorld,
  type GlobeTerrain,
} from '../../src/lib/world/globe';
import { SCENE_IDS } from '../../src/lib/live/mock-animal-scenes';
import { DRAW_CALL_BUDGET, openGlobe, WORLD_URL } from './globe-helpers';

/*
 * Animals and fires of the live feed on the planet (the dev/test mock feed, `?mockLive=1`): the deer on the
 * town's approach are drawn on the ground playing their clips, animals far away aren't loaded, and fires burn
 * where the feed says they're lit (the camps' pits by day, the gate's baskets from dusk), lighting their
 * surroundings.
 */

let terrain: GlobeTerrain;
let R: number;

test.describe.configure({ timeout: 120_000 });

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const view = (await (await api.get(WORLD_URL)).json()) as WorldView;
  await api.dispose();
  terrain = buildTerrain(decodeWorld(view));
  R = view.radius_m;
});

type MockLiveWindow = { __pebbleMockLive: { skip(ticks: number): void } };

const data = async (page: Page, testId: string, name: string) =>
  (await page.getByTestId(testId).getAttribute(`data-${name}`)) ?? '';

/** Every animal drawn near the camera: id, kind, activity and the clip it plays. */
async function nearAnimals(page: Page) {
  return (await data(page, 'animals', 'near-clips'))
    .split(' ')
    .filter(Boolean)
    .map((entry) => {
      const [kind, number, activity, clip] = entry.split(':');
      return { id: `${kind}:${number}`, kind, activity, clip };
    });
}

test('animals near the camera are drawn on the ground playing their clips', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors, '?mockLive=1');
  await expect(world).toHaveAttribute('data-live-status', 'live');
  // ten wandering animals and the scripted scenes by band A's camp (`mock-animal-scenes.ts`)
  await expect(page.getByTestId('animals')).toHaveAttribute(
    'data-animals',
    String(10 + SCENE_IDS.size),
  );
  // the herd and the fox on the town's approach are within reach of the gate; band A's camp is kilometres away
  await expect
    .poll(async () => data(page, 'animals', 'near-kinds'), { timeout: 30_000 })
    .toBe('deer,fox');
  await expect
    .poll(
      async () =>
        (await nearAnimals(page)).filter(({ clip }) => clip !== '').length,
      { timeout: 30_000 },
    )
    .toBe(5);
  for (const animal of await nearAnimals(page)) {
    expect(animal.id).not.toMatch(/^wolf/);
    // a gait clip while the body moves, Idle once it stands (a walker that got there plays no walk on the spot)
    expect(
      animal.activity === 'walking'
        ? ['Walk', 'Idle']
        : animal.activity === 'running'
          ? ['Run', 'Idle']
          : ['Idle'],
    ).toContain(animal.clip);
  }
  const positions = (await data(page, 'animals', 'near-positions'))
    .split(' ')
    .map((entry) =>
      entry
        .slice(entry.lastIndexOf(':') + 1)
        .split(',')
        .map(Number),
    );
  for (const [x, y, z] of positions) {
    const at = new Vector3(x, y, z);
    expect(
      Math.abs(at.length() - (R + terrain.heightAt(at.clone().normalize()))),
    ).toBeLessThan(0.05);
  }
  expect(Number(await world.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );
  expect(errors).toEqual([]);
});

test('fires burn where the feed lights them and the nearest ones cast light', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors, '?mockLive=1');
  await expect(world).toHaveAttribute('data-live-status', 'live');
  const fires = page.getByTestId('fires');
  await expect(fires).toHaveAttribute('data-fires', '4');
  // 08:00: only the camps' pits burn, kilometres from the gate: nothing drawn here
  await expect(fires).toHaveAttribute(
    'data-lit',
    'band_a_camp:fire-pit,band_b_camp:fire-pit',
  );
  await expect(fires).toHaveAttribute('data-drawn', '');

  // to 19:00: the gate's baskets are lit, drawn and lighting the gate
  await page.evaluate(() =>
    (globalThis as unknown as MockLiveWindow).__pebbleMockLive.skip(11 * 60),
  );
  await expect(fires).toHaveAttribute(
    'data-lit',
    'band_a_camp:fire-pit,band_b_camp:fire-pit,main-gate-fire-e,main-gate-fire-w',
  );
  await expect(fires).toHaveAttribute(
    'data-drawn',
    'main-gate-fire-e,main-gate-fire-w',
  );
  await expect(fires).toHaveAttribute(
    'data-lighted',
    'main-gate-fire-e,main-gate-fire-w',
  );
  expect(Number(await world.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );
  expect(errors).toEqual([]);
});
