import { expect, type Page, test } from '@playwright/test';

import { FULL_M, ICON_M } from '../../src/lib/world/label-layout';
import {
  cameraOf,
  drawn,
  goToPerson,
  inView,
  type MockLiveWindow,
  openHeld,
  viewOf,
} from './ui-helpers';

/* The globe's chips in the browser: tiers by distance, icons, clusters that never cover each other. */

/** Distances this close to a tier's edge are skipped: the chip hangs a little above the feet. */
const EDGE_M = 4;
/** A chip hangs at most this high above the drawn feet. */
const CHIP_LIFT_M = 2.2;

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
  const view = await viewOf(page, world);
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
  // drawn a tick behind the sim, someone close by can stand behind the camera or beside the view: only those in
  // view must have a chip
  const seen = (id: string) => {
    const feet = people.get(id)!.at;
    const head = feet
      .clone()
      .addScaledVector(feet.clone().normalize(), CHIP_LIFT_M);
    return inView(view, [feet, head]);
  };
  let near = 0;
  for (const [id] of people)
    if (distance(id) < ICON_M - EDGE_M && seen(id)) {
      expect(shown.has(id), `${id} at ${distance(id).toFixed(0)} m`).toBe(true);
      near++;
    }
  expect(near, 'someone near in view').toBeGreaterThan(0);
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

type Element = {
  dataset: Record<string, string | undefined>;
  querySelector(selector: string): {
    getAttribute(name: string): string | null;
  } | null;
};

/** The visible chips: who leads, who they stand for, the icon and ring drawn, and each member's own icon. */
async function chipsOn(page: Page) {
  const all = await page.locator('[data-label^="npc-"]').evaluateAll((nodes) =>
    nodes.map((node) => {
      const element = node as unknown as Element;
      return {
        id: element.dataset.label!.slice('npc-'.length),
        visible:
          element.dataset.members !== undefined &&
          (node as unknown as { style: { display: string } }).style.display !==
            'none',
        members: element.dataset.members?.split(' ') ?? [],
        icon: element.dataset.icon,
        ring: element.dataset.ring,
        own: element
          .querySelector('[data-chip-icon]')
          ?.getAttribute('data-chip-icon'),
      };
    }),
  );
  const ownIcon = new Map(all.map((chip) => [chip.id, chip.own]));
  return all
    .filter((chip) => chip.visible)
    .map(({ id, members, icon, ring }) => ({
      leader: id,
      members,
      icon,
      ring,
      icons: members.map((member) => ownIcon.get(member)),
    }));
}

test('a mixed cluster shows a neutral icon and the worst need ring among its members', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  // band A's camp at 08:00: people doing different things by the fire pit cluster
  await goToPerson(page, world, 'tak');
  let cluster: Awaited<ReturnType<typeof chipsOn>>[number] | undefined;
  await expect
    .poll(async () => {
      cluster = (await chipsOn(page)).find((chip) => chip.members.length > 1);
      return cluster !== undefined;
    })
    .toBe(true);
  const { leader, members, icons } = cluster!;
  const mixed = new Set(icons).size > 1;
  expect(cluster!.icon).toBe(mixed ? 'people' : icons[0]);
  expect(cluster!.ring).toBe('');

  // a member who is not the leader gets hungry, then another is hurt: the cluster rings, hurt over hungry
  const follower = members.find((id: string) => id !== leader)!;
  const feel = (actor: string, words: string[]) =>
    page.evaluate(
      ([actor, words]) =>
        (globalThis as unknown as MockLiveWindow).__pebbleMockLive.feel(
          actor as string,
          words as string[],
        ),
      [actor, words] as const,
    );
  const ringOfCluster = async () =>
    (await chipsOn(page)).find((chip) => chip.members.includes(follower))?.ring;
  await feel(follower, ['hungry']);
  await expect.poll(ringOfCluster).toBe('need');
  await feel(leader, ['weak and aching']);
  await expect.poll(ringOfCluster).toBe('hurt');
  expect(errors).toEqual([]);
});

test('a bubble names its speaker when the speaker has no chip of their own under it', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openHeld(page, errors);
  await goToPerson(page, world, 'tak');
  let cluster: Awaited<ReturnType<typeof chipsOn>>[number] | undefined;
  await expect
    .poll(async () => {
      cluster = (await chipsOn(page)).find((chip) => chip.members.length > 1);
      return cluster !== undefined;
    })
    .toBe(true);
  const { leader, members } = cluster!;
  const follower = members.find((id: string) => id !== leader)!;
  const say = (actor: string, words: string) =>
    page.evaluate(
      ([actor, words]) =>
        (globalThis as unknown as MockLiveWindow).__pebbleMockLive.sayNow(
          actor,
          words,
        ),
      [actor, words],
    );
  const names = new Map(
    (await page.evaluate(() =>
      (globalThis as unknown as MockLiveWindow).__pebbleMockLive
        .entities()
        .citizens.map((citizen) => [citizen.id, citizen.name]),
    )) as [string, string][],
  );

  await say(follower, 'The berries are ripe.');
  const followerBubble = page.locator(`[data-label="say-${follower}"]`);
  await expect(followerBubble).toBeVisible();
  await expect(followerBubble).toHaveText(
    `${names.get(follower)}: The berries are ripe.`,
  );
  await say(leader, 'Good.');
  const leaderBubble = page.locator(`[data-label="say-${leader}"]`);
  await expect(leaderBubble).toBeVisible();
  await expect(leaderBubble).toHaveText('Good.');
  expect(errors).toEqual([]);
});
