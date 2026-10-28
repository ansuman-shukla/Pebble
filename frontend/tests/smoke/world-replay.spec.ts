import { expect, type Page, test } from '@playwright/test';
import { Vector3 } from 'three';

import type { ClockView, EntitiesView } from '../../src/lib/client/types.gen';
import { openGlobe } from './globe-helpers';

/*
 * The World opened from the spectator pages against the running engine: `/?tick=N` draws everyone where they were
 * at tick N with the live feed off, `?follow=id` follows a citizen on load.
 */

const API_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1`;

test.describe.configure({ timeout: 120_000 });

type Dataset = { dataset: Record<string, string | undefined> };

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);
  expect(response.ok, path).toBe(true);
  return (await response.json()) as T;
}

/** Where each citizen is drawn (direction from the planet's centre), from the page's hidden hooks. */
async function drawn(page: Page): Promise<Map<string, Vector3>> {
  const raw = await page
    .locator('[data-npc]')
    .evaluateAll((nodes) =>
      nodes.map((node) => ({ ...(node as unknown as Dataset).dataset })),
    );
  return new Map(
    raw
      .filter((data) => data.npcX !== undefined)
      .map((data) => [
        data.npc!,
        new Vector3(
          Number(data.npcX),
          Number(data.npcY),
          Number(data.npcZ),
        ).normalize(),
      ]),
  );
}

/** Metres along the ground between where citizens are drawn and where the replayed entities say they were. */
function offsets(
  shown: Map<string, Vector3>,
  view: EntitiesView,
  radius: number,
): number[] {
  return view.citizens.map((citizen) => {
    const at = shown.get(citizen.id);
    if (!at) return Infinity;
    const unit = new Vector3(...citizen.position.unit);
    return at.angleTo(unit) * radius;
  });
}

test('?tick= draws the citizens where they were then and keeps the feed off', async ({
  page,
}) => {
  const errors: string[] = [];
  const clock = await get<ClockView>('/clock');
  const tick = Math.max(0, clock.tick - 600);
  const then = await get<EntitiesView>(`/entities?at=${tick}`);
  const now = await get<EntitiesView>('/entities');
  const world = await openGlobe(page, errors, `?tick=${tick}`);
  const { radius_m: radius } = await get<{ radius_m: number }>('/world');
  await expect(world).toHaveAttribute('data-replay-tick', String(tick));
  await expect(world).toHaveAttribute('data-live-tick', String(tick));
  await expect(world).toHaveAttribute('data-live-status', 'off');
  await expect(page.getByTestId('replay-badge')).toContainText(
    `day ${then.day} · ${then.time}`,
  );
  await expect
    .poll(async () => Math.max(...offsets(await drawn(page), then, radius)), {
      timeout: 20_000,
    })
    .toBeLessThan(1);
  // someone has moved since: the page shows the past, not now
  const moved = then.citizens.filter((citizen) => {
    const later = now.citizens.find((other) => other.id === citizen.id)!;
    return (
      new Vector3(...citizen.position.unit).angleTo(
        new Vector3(...later.position.unit),
      ) *
        radius >
      5
    );
  });
  expect(moved.length).toBeGreaterThan(0);
  // and it stays there: no feed moves anyone on
  await page.waitForTimeout(2500);
  await expect(world).toHaveAttribute('data-live-tick', String(tick));
  expect(Math.max(...offsets(await drawn(page), then, radius))).toBeLessThan(1);
  await page.getByRole('link', { name: 'back to live' }).click();
  await expect(world).not.toHaveAttribute('data-replay-tick');
  await expect(world).toHaveAttribute('data-live-status', 'live', {
    timeout: 20_000,
  });
  expect(errors).toEqual([]);
});

test('?follow= follows a citizen once they are drawn, live or replayed', async ({
  page,
}) => {
  const errors: string[] = [];
  const now = await get<EntitiesView>('/entities');
  const id = now.citizens[now.citizens.length - 1].id;
  const world = await openGlobe(page, errors, `?follow=${id}`);
  await expect(world).toHaveAttribute('data-follow', id, { timeout: 20_000 });
  await expect(world).toHaveAttribute('data-camera-mode', 'follow');
  await expect(
    page.getByText(`following ${now.citizens.at(-1)!.name}`),
  ).toBeVisible();

  const replayed = await openGlobe(page, errors, `?tick=60&follow=${id}`);
  await expect(replayed).toHaveAttribute('data-follow', id, {
    timeout: 20_000,
  });
  await expect(replayed).toHaveAttribute('data-live-tick', '60');
  expect(errors).toEqual([]);
});
