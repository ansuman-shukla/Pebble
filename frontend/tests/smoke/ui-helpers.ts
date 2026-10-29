import { expect, type Locator, type Page } from '@playwright/test';
import { PerspectiveCamera, Quaternion, Vector3 } from 'three';

import type { EntitiesView } from '../../src/lib/client/types.gen';
import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { openGlobe } from './globe-helpers';

/* Shared by the spectator UI browser tests (ui-*.spec.ts): the mock feed, drawn citizens, the camera. */

export type MockLiveWindow = {
  __pebbleMockLive: {
    restartRun(): void;
    setClock(change: { speed?: number; paused?: boolean }): void;
    entities(): EntitiesView;
    sayNow(actor: string, words: string): void;
    feel(actor: string, words: string[]): void;
  };
};

/** How many citizens the mock feed runs: one per look (live-feed.spec.ts checks it). */
export const MOCK_CITIZENS = CITIZEN_LOOKS.length;

/** The globe on the mock feed, held still: a fresh run with the clock paused. */
export async function openHeld(page: Page, errors: string[], query = '') {
  const world = await openGlobe(page, errors, `?mockLive=1${query}`);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    String(MOCK_CITIZENS),
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

/** The globe's camera as it is now (fov 50, as globe-page.tsx sets it up), sized like the scene's canvas. */
export async function viewOf(page: Page, world: Locator) {
  const pose = (await world.getAttribute('data-camera'))!
    .split(',')
    .map(Number);
  const { width, height } = (await page
    .locator('canvas[data-engine]')
    .boundingBox())!;
  const camera = new PerspectiveCamera(50, width / height, 0.1, 3000);
  camera.position.set(pose[0], pose[1], pose[2]);
  camera.quaternion.copy(new Quaternion(pose[3], pose[4], pose[5], pose[6]));
  camera.updateMatrixWorld();
  return camera;
}

/** Whether `points` all project inside the view (a margin short of the chip projector's 1.1 edge). */
export const inView = (camera: PerspectiveCamera, points: Vector3[]) =>
  points.every((point) => {
    const { x, y, z } = point.clone().project(camera);
    return z < 1 && Math.abs(x) < 1 && Math.abs(y) < 1;
  });

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
