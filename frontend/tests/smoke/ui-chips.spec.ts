import { expect, test } from '@playwright/test';

import { FULL_M, ICON_M } from '../../src/lib/world/label-layout';
import { cameraOf, drawn, goToPerson, openHeld } from './ui-helpers';

/* The globe's chips in the browser: tiers by distance, icons, clusters that never cover each other. */

/** Distances this close to a tier's edge are skipped: the chip hangs a little above the feet. */
const EDGE_M = 4;

test('near citizens get full chips, farther ones icon chips, none past 150 m', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  // band A's camp: Tak, Ana and the others close by, the rest of the world far away
  await goToPerson(page, world, 'tak');
  await expect
    .poll(async () => page.locator('[data-label^="npc-"]:visible').count())
    .toBeGreaterThan(0);

  const camera = await cameraOf(world);
  const people = await drawn(page);
  const chips = await page
    .locator('[data-label^="npc-"]:visible')
    .evaluateAll((nodes) =>
      nodes.map((node) => {
        const element = node as unknown as {
          dataset: Record<string, string | undefined>;
          querySelector(selector: string): {
            getAttribute(name: string): string | null;
          } | null;
        };
        return {
          leader: element.dataset.label!.slice('npc-'.length),
          view: element.dataset.view!,
          members: element.dataset.members!.split(' '),
          icon:
            element
              .querySelector('[data-chip-icon]')
              ?.getAttribute('data-chip-icon') ?? null,
        };
      }),
    );
  const distance = (id: string) => people.get(id)!.at.distanceTo(camera);
  const shown = new Set(chips.flatMap((chip) => chip.members));
  for (const [id] of people)
    if (distance(id) > ICON_M + EDGE_M)
      expect(shown.has(id), `${id} at ${distance(id).toFixed(0)} m`).toBe(
        false,
      );
  for (const [id] of people)
    if (distance(id) < ICON_M - EDGE_M)
      expect(shown.has(id), `${id} at ${distance(id).toFixed(0)} m`).toBe(true);
  let tiers = 0;
  for (const chip of chips) {
    const far = distance(chip.leader);
    const clustered = chip.members.length > 1;
    if (far < FULL_M - EDGE_M) {
      expect(chip.view, chip.leader).toBe(clustered ? 'cluster' : 'full');
      tiers |= 1;
    } else if (far > FULL_M + EDGE_M) {
      expect(chip.view, chip.leader).toBe(clustered ? 'cluster-icon' : 'icon');
      tiers |= 2;
    }
    // the leader is the nearest of its cluster
    for (const member of chip.members)
      expect(distance(member) + 0.5).toBeGreaterThanOrEqual(far);
  }
  expect(tiers & 1, 'a full chip near the camera').toBe(1);
  const tak = chips.find((chip) => chip.members.includes('tak'))!;
  expect(tak.icon).not.toBeNull();
  expect(errors).toEqual([]);
});
