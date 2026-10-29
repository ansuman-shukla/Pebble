import { expect, test } from '@playwright/test';

import {
  type BubbleAnchor,
  type ChipAnchor,
  type ChipSizer,
  type ChipView,
  ICON_M,
  layoutBubbles,
  layoutChips,
  MAX_BUBBLES,
  MAX_CHIPS,
  type PlacedChip,
} from '../../src/lib/world/label-layout';

/* Chip layout (no browser): tiers by distance, clusters instead of towers, pinned chips whole, caps. */

const SIZES: Record<ChipView, { width: number; height: number }> = {
  full: { width: 60, height: 20 },
  icon: { width: 20, height: 20 },
  cluster: { width: 150, height: 20 },
  'cluster-icon': { width: 40, height: 20 },
};
const sizer: ChipSizer = (_id, view) => SIZES[view];

const anchor = (id: string, change: Partial<ChipAnchor> = {}): ChipAnchor => ({
  id,
  x: 300,
  y: 300,
  distance: 10,
  pinned: false,
  ...change,
});

interface Box {
  id: string;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const chipBox = (chip: PlacedChip): Box => ({
  id: chip.leader,
  left: chip.x - chip.width / 2,
  right: chip.x + chip.width / 2,
  top: chip.bottom - chip.height,
  bottom: chip.bottom,
});

function overlapping(boxes: Box[]) {
  return boxes.flatMap((a, i) =>
    boxes
      .slice(i + 1)
      .filter(
        (b) =>
          a.left < b.right &&
          b.left < a.right &&
          a.top < b.bottom &&
          b.top < a.bottom,
      )
      .map((b) => `${a.id} / ${b.id}`),
  );
}

/** A small seeded random (mulberry32), so a failing layout can be replayed. */
function random(seed: number) {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test('a near anchor gets a full chip on its spot, a farther one an icon chip, a far one none', () => {
  const chips = layoutChips(
    [
      anchor('near', { x: 100, distance: 29 }),
      anchor('mid', { x: 300, distance: 30 }),
      anchor('edge', { x: 500, distance: ICON_M }),
      anchor('far', { x: 700, distance: ICON_M + 1 }),
    ],
    sizer,
  );
  expect(
    chips.map(({ leader, view, x, bottom, width }) => ({
      leader,
      view,
      x,
      bottom,
      width,
    })),
  ).toEqual([
    { leader: 'near', view: 'full', x: 100, bottom: 300, width: 60 },
    { leader: 'mid', view: 'icon', x: 300, bottom: 300, width: 20 },
    { leader: 'edge', view: 'icon', x: 500, bottom: 300, width: 20 },
  ]);
});

test('a pinned subject always gets a full chip, however far', () => {
  const [chip] = layoutChips(
    [anchor('lord', { distance: 900, pinned: true })],
    sizer,
  );
  expect(chip).toMatchObject({
    leader: 'lord',
    view: 'full',
    members: ['lord'],
  });
});

test('five citizens on one spot make one cluster chip led by the nearest', () => {
  const five = [12, 8, 15, 9, 11].map((distance, k) =>
    anchor(`p${k}`, { distance, x: 300 + k, y: 300 - k }),
  );
  const chips = layoutChips(five, sizer);
  expect(chips).toHaveLength(1);
  expect(chips[0]).toMatchObject({
    leader: 'p1',
    view: 'cluster',
    x: 301,
    bottom: 299,
    width: 150,
  });
  expect([...chips[0].members].sort()).toEqual(['p0', 'p1', 'p2', 'p3', 'p4']);
  const far = layoutChips(
    five.map((one) => ({ ...one, distance: one.distance + 60 })),
    sizer,
  );
  expect(far).toHaveLength(1);
  expect(far[0].view).toBe('cluster-icon');
});

test('chips that only touch stay apart', () => {
  const chips = layoutChips(
    [
      anchor('a', { x: 100 }),
      anchor('b', { x: 160 }),
      anchor('c', { x: 100, y: 280 }),
    ],
    sizer,
  );
  expect(chips.map((chip) => chip.view)).toEqual(['full', 'full', 'full']);
});

test('a growing cluster swallows the chip it grows into', () => {
  // a and b stand 70 px apart (no overlap at 60 px); c joins a and the 150 px cluster reaches b
  const chips = layoutChips(
    [
      anchor('a', { x: 100, distance: 5 }),
      anchor('b', { x: 170, distance: 6 }),
      anchor('c', { x: 102, distance: 7 }),
    ],
    sizer,
  );
  expect(chips).toHaveLength(1);
  expect(chips[0].leader).toBe('a');
  expect(chips[0].members).toEqual(['a', 'c', 'b']);
});

test('a cluster that swallows a nearer chip hands it the lead and its spot', () => {
  // b (5 m) stands alone; c joins a (6 m) and the cluster grows into b, the nearest of the three
  const chips = layoutChips(
    [
      anchor('b', { x: 170, y: 290, distance: 5 }),
      anchor('a', { x: 100, distance: 6 }),
      anchor('c', { x: 102, distance: 7 }),
    ],
    sizer,
  );
  expect(chips).toHaveLength(1);
  expect(chips[0]).toMatchObject({
    leader: 'b',
    members: ['b', 'a', 'c'],
    x: 170,
    bottom: 290,
  });
});

test('the pinned chip stays whole and the others cluster just above it', () => {
  const chips = layoutChips(
    [
      anchor('x', { distance: 5 }),
      anchor('followed', { distance: 9, pinned: true }),
      anchor('y', { distance: 6, x: 305 }),
      anchor('z', { distance: 7, x: 295 }),
    ],
    sizer,
  );
  expect(chips).toHaveLength(2);
  const [followed, rest] = chips;
  expect(followed).toMatchObject({
    leader: 'followed',
    members: ['followed'],
    view: 'full',
    bottom: 300,
  });
  expect(rest).toMatchObject({ leader: 'x', view: 'cluster', bottom: 278 });
  expect([...rest.members].sort()).toEqual(['x', 'y', 'z']);
});

test('two pinned chips on one spot stack', () => {
  const chips = layoutChips(
    [
      anchor('selected', { distance: 5, pinned: true }),
      anchor('followed', { distance: 9, pinned: true }),
    ],
    sizer,
  );
  expect(chips.map(({ leader, bottom }) => ({ leader, bottom }))).toEqual([
    { leader: 'selected', bottom: 300 },
    { leader: 'followed', bottom: 278 },
  ]);
});

test('at most fourteen chips: the nearest', () => {
  const spread = Array.from({ length: 20 }, (_, k) =>
    anchor(`p${k}`, { x: 40 + k * 80, distance: 20 - k }),
  );
  const chips = layoutChips(spread, sizer);
  expect(chips).toHaveLength(MAX_CHIPS);
  expect(chips.map((chip) => chip.leader).sort()).toEqual(
    spread
      .slice(20 - MAX_CHIPS)
      .map((one) => one.id)
      .sort(),
  );
});

test('randomized 40-label layouts: no overlaps, at most 14 chips, everyone in range accounted for', () => {
  for (let seed = 1; seed <= 300; seed++) {
    const next = random(seed);
    // a crowd in a 600 x 300 px patch: the plaza at noon, with a few pinned
    const anchors = Array.from({ length: 40 }, (_, k) =>
      anchor(`c${k}`, {
        x: 100 + next() * 600,
        y: 200 + next() * 300,
        distance: next() * 200,
        pinned: next() < 0.05,
      }),
    );
    const sized: ChipSizer = (id, view) =>
      view === 'full'
        ? { width: 50 + (Number(id.slice(1)) % 7) * 15, height: 22 }
        : SIZES[view];
    const chips = layoutChips(anchors, sized);
    const label = `seed ${seed}`;
    expect(chips.length, label).toBeLessThanOrEqual(MAX_CHIPS);
    expect(overlapping(chips.map(chipBox)), label).toEqual([]);
    const members = chips.flatMap((chip) => chip.members);
    expect(new Set(members).size, label).toBe(members.length);
    const inRange = anchors.filter(
      (one) => one.pinned || one.distance <= ICON_M,
    );
    // only a new chip past the cap is left out, so the first fourteen (pinned, then nearest) always show
    const order = [...inRange].sort(
      (a, b) => Number(b.pinned) - Number(a.pinned) || a.distance - b.distance,
    );
    const shown = new Set(members);
    for (const one of order.slice(0, MAX_CHIPS))
      expect(shown.has(one.id), `${label} ${one.id}`).toBe(true);
    const inRangeIds = new Set(inRange.map((one) => one.id));
    for (const id of members)
      expect(inRangeIds.has(id), `${label} ${id}`).toBe(true);
    const distanceOf = new Map(anchors.map((one) => [one.id, one.distance]));
    for (const chip of chips) {
      expect(chip.members[0], label).toBe(chip.leader);
      const nearest = Math.min(
        ...chip.members.map((id) => distanceOf.get(id)!),
      );
      expect(distanceOf.get(chip.leader), `${label} leader`).toBe(nearest);
      const lead = anchors.find((one) => one.id === chip.leader)!;
      expect(chip.x, label).toBe(lead.x);
      expect(chip.bottom, label).toBeLessThanOrEqual(lead.y);
    }
    const bubbles = layoutBubbles(
      anchors.slice(0, 6).map((one): BubbleAnchor => ({
        ...one,
        id: `say-${one.id}`,
        width: 120,
        height: 40,
      })),
      chips,
    );
    expect(bubbles.length, label).toBeLessThanOrEqual(MAX_BUBBLES);
    const bubbleBoxes = bubbles.map((bubble) => ({
      id: bubble.id,
      left: bubble.x - 60,
      right: bubble.x + 60,
      top: bubble.bottom - 40,
      bottom: bubble.bottom,
    }));
    expect(overlapping([...chips.map(chipBox), ...bubbleBoxes]), label).toEqual(
      [],
    );
  }
});

test('speech bubbles: the three nearest speakers in range, each above the chips it would cover', () => {
  const speakers = [5, 50, 20, 200, 10].map((distance, k) =>
    anchor(`s${k}`, { x: 100 + k * 150, distance }),
  );
  const chips = layoutChips(speakers, sizer);
  const bubbles = layoutBubbles(
    speakers.map((one): BubbleAnchor => ({
      ...one,
      id: `say-${one.id}`,
      width: 100,
      height: 30,
    })),
    chips,
  );
  expect(bubbles).toEqual([
    { id: 'say-s0', x: 100, bottom: 278 },
    { id: 'say-s4', x: 700, bottom: 278 },
    { id: 'say-s2', x: 400, bottom: 278 },
  ]);
  const pinnedFar = layoutBubbles(
    [
      {
        ...anchor('lord', { distance: 500, pinned: true }),
        id: 'say-lord',
        width: 100,
        height: 30,
      },
    ],
    [],
  );
  expect(pinnedFar).toEqual([{ id: 'say-lord', x: 300, bottom: 300 }]);
});
