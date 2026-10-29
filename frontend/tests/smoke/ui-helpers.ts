import { expect, type Locator, type Page } from '@playwright/test';
import { Vector3 } from 'three';

import type { EntitiesView } from '../../src/lib/client/types.gen';
import { openGlobe } from './globe-helpers';

/* Shared by the spectator UI browser tests (ui-*.spec.ts): the mock feed, drawn citizens, the camera. */

export type MockLiveWindow = {
  __pebbleMockLive: {
    restartRun(): void;
    setClock(change: { speed?: number; paused?: boolean }): void;
    entities(): EntitiesView;
  };
};

/** The globe on the mock feed, held still: a fresh run with the clock paused. */
export async function openHeld(page: Page, errors: string[], query = '') {
  const world = await openGlobe(page, errors, `?mockLive=1${query}`);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    '15',
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  await page.evaluate(() => {
    const mock = (globalThis as unknown as MockLiveWindow).__pebbleMockLive;
    mock.restartRun();
    mock.setClock({ paused: true });
  });
  await expect(world).toHaveAttribute('data-live-connects', '2');
  return world;
}

/** Waits for a camera flight (follow, go to) to start and land. */
export async function landed(world: Locator) {
  await expect(world).toHaveAttribute('data-camera-flying', 'true');
  await expect(world).toHaveAttribute('data-camera-flying', 'false', {
    timeout: 10_000,
  });
}

export const cameraOf = async (world: Locator) =>
  new Vector3(
    ...(await world.getAttribute('data-camera'))!.split(',').map(Number),
  );

/** Where each citizen is drawn (world metres) and what they do, from the page's hidden hooks. */
export async function drawn(page: Page) {
  const rows = await page.locator('[data-npc]').evaluateAll((nodes) =>
    nodes.map((node) => {
      const data = (
        node as unknown as { dataset: Record<string, string | undefined> }
      ).dataset;
      return {
        id: data.npc!,
        at: [data.npcX, data.npcY, data.npcZ].map(Number),
        activity: data.npcActivity ?? '',
      };
    }),
  );
  return new Map(
    rows.map((row) => [
      row.id,
      { at: new Vector3(...row.at), activity: row.activity },
    ]),
  );
}

/** Goes to a citizen from the People panel and waits for the camera to land. */
export async function goToPerson(page: Page, world: Locator, id: string) {
  await page.getByRole('button', { name: 'people', exact: true }).click();
  await page
    .locator(`[data-person="${id}"]`)
    .getByRole('button', { name: 'go to' })
    .click();
  await landed(world);
}
