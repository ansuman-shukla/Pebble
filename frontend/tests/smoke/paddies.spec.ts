import { expect, test } from '@playwright/test';

import type { TownView } from '../../src/lib/client/types.gen';
import { buildMarks } from '../../src/lib/world/ground-marks';
import { FLAT_MAPPING } from '../../src/lib/world/local-mapping';
import {
  type PaddyField,
  paddyFields,
  paddyOutline,
  paddyStage,
} from '../../src/lib/world/paddies';
import { TOWN_URL } from './explore-helpers';
import { DRAW_CALL_BUDGET, openGlobe } from './globe-helpers';

/*
 * The rice paddies (10 §1.4): six paddies, each one basin with a bund round its rim only, drawn at the stage the
 * feed names (seedlings, green, gold, stubble), with no ground mark under their water.
 */

let town: TownView;

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  town = (await (await api.get(TOWN_URL)).json()) as TownView;
  await api.dispose();
});

/** The rects of `backend/data/town/town.yaml`'s paddy tiles. */
const PADDY_RECTS: Record<string, PaddyField['rect']> = {
  'paddy-1': [-148, 22, -130, 42],
  'paddy-2': [-148, 46, -130, 66],
  'paddy-3': [-148, 70, -130, 90],
  'paddy-4': [-126, 22, -114, 42],
  'paddy-5': [-126, 46, -114, 66],
  'paddy-6': [-126, 70, -114, 90],
};

/** The tile edges (n, e, s, w) a tile's bund lies on once turned by its yaw. */
function bundedEdges(shape: string, yaw: number) {
  const own = shape === 'corner' ? ['n', 'w'] : shape === 'side' ? ['n'] : [];
  const outward = { n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] } as const;
  return own.map((edge) => {
    const [x, z] = outward[edge as keyof typeof outward];
    // a turn by yaw about up (three.js): x' = x cos + z sin, z' = -x sin + z cos
    const [tx, tz] = [
      Math.round(x * Math.cos(yaw) + z * Math.sin(yaw)),
      Math.round(-x * Math.sin(yaw) + z * Math.cos(yaw)),
    ];
    return tz === -1 ? 'n' : tz === 1 ? 's' : tx === 1 ? 'e' : 'w';
  });
}

test('the town lays six paddies, each bunded round its rim and open inside', () => {
  const fields = paddyFields(town.placements);
  expect(
    Object.fromEntries(fields.map((field) => [field.id, field.rect])),
  ).toEqual(PADDY_RECTS);
  const faults: string[] = [];
  for (const field of fields) {
    const [x0, z0, x1, z1] = field.rect;
    expect(field.tiles.length).toBe(((x1 - x0) / 2) * ((z1 - z0) / 2));
    for (const tile of field.tiles) {
      const rim = [
        ...(tile.z - 1 === z0 ? ['n'] : []),
        ...(tile.z + 1 === z1 ? ['s'] : []),
        ...(tile.x - 1 === x0 ? ['w'] : []),
        ...(tile.x + 1 === x1 ? ['e'] : []),
      ].sort();
      const bunded = bundedEdges(tile.shape, tile.yaw).sort();
      if (bunded.join() !== rim.join())
        faults.push(
          `${field.id} tile at ${tile.x},${tile.z}: bunds ${bunded.join() || 'none'}, rim ${rim.join() || 'none'}`,
        );
    }
  }
  expect(faults).toEqual([]);
});

test('a paddy is drawn at the stage the feed named, and ripe while it was never named', () => {
  expect(paddyStage(undefined)).toBe('gold');
  expect(paddyStage(null)).toBe('gold');
  for (const stage of ['seedlings', 'green', 'gold', 'stubble'])
    expect(paddyStage(stage)).toBe(stage);
  expect(() => paddyStage('picked')).toThrow(/unknown rice paddy stage/);
});

test('the rice fields mark furrowed earth between the paddies, none under them', () => {
  const fields = paddyFields(town.placements);
  const holes = fields.map((field) => paddyOutline(field, 0.25));
  const position = buildMarks({
    areas: { areas: town.areas, mapping: FLAT_MAPPING, holes },
  }).getAttribute('position');
  const field = town.areas.find((area) => area.kind === 'field')!;
  const [fx0, fx1] = [
    Math.min(...field.polygon.map(([x]) => x)),
    Math.max(...field.polygon.map(([x]) => x)),
  ];
  let between = 0;
  const under: string[] = [];
  for (let i = 0; i < position.count; i += 3) {
    const x =
      (position.getX(i) + position.getX(i + 1) + position.getX(i + 2)) / 3;
    const z =
      (position.getZ(i) + position.getZ(i + 1) + position.getZ(i + 2)) / 3;
    const paddy = fields.find(
      ({ rect: [x0, z0, x1, z1] }) =>
        x > x0 + 0.25 && x < x1 - 0.25 && z > z0 + 0.25 && z < z1 - 0.25,
    );
    if (paddy) under.push(`${paddy.id} at ${x.toFixed(1)},${z.toFixed(1)}`);
    else if (x > fx0 + 1 && x < fx1 - 1 && z > 22 && z < 90) between += 1;
  }
  expect(under).toEqual([]);
  expect(between).toBeGreaterThan(50);
});

type PaddiesWindow = {
  __pebblePaddies?: {
    drawn: () => Record<string, string>;
    looks: () => { look: string; count: number }[];
  };
  __pebbleMockLive: {
    sendNow: (
      type: string,
      actor: string,
      payload: Record<string, unknown>,
    ) => void;
  };
};

/** Gold and paddy-water pixels (blue, darker than the sky) on the scene canvas (browser code: the test TypeScript
 * has no DOM types). */
const CROP_PIXELS = `(() => {
  const scene = document.querySelector('canvas[data-engine]');
  const copy = document.createElement('canvas');
  copy.width = scene.width;
  copy.height = scene.height;
  const context = copy.getContext('2d');
  context.drawImage(scene, 0, 0);
  const { data } = context.getImageData(0, 0, copy.width, copy.height);
  let gold = 0, water = 0;
  for (let i = 0; i < data.length; i += 4) {
    const [r, g, b] = [data[i], data[i + 1], data[i + 2]];
    if (r > 110 && g > 70 && r > 1.2 * g && g > 1.5 * b) gold += 1;
    if (b > r + 20 && b > g + 5 && r < 110) water += 1;
  }
  return { gold: gold / (data.length / 4), water: water / (data.length / 4) };
})()`;

/** On the bund south of paddies 3 and 6, facing north over the rice fields, on the mock feed. */
const BY_THE_PADDIES = '?mockLive=1&at=35.2378,7.5377,0';

test('every paddy follows its stage on screen within a second of the feed', async ({
  page,
}) => {
  const errors: string[] = [];
  const world = await openGlobe(page, errors, BY_THE_PADDIES);
  const drawn = () =>
    page.evaluate(() =>
      (globalThis as unknown as PaddiesWindow).__pebblePaddies?.drawn(),
    );
  const pixels = () =>
    page.evaluate<{ gold: number; water: number }>(CROP_PIXELS);
  const setAll = (stage: string) =>
    page.evaluate((stage) => {
      for (let n = 1; n <= 6; n++)
        (globalThis as unknown as PaddiesWindow).__pebbleMockLive.sendNow(
          'node_changed',
          'tokuji',
          {
            node: `paddy-${n}`,
            kind: 'rice_paddy',
            item: 'rice',
            before: 0,
            after: 0,
            stage,
          },
        );
    }, stage);
  const all = (stage: string) =>
    Object.fromEntries(Object.keys(PADDY_RECTS).map((paddy) => [paddy, stage]));

  // the mock feed names no paddy: every one is full, so ripe
  await expect.poll(drawn, { timeout: 30_000 }).toEqual(all('gold'));
  await page.waitForTimeout(1500);
  const ripe = await pixels();
  expect(ripe.gold).toBeGreaterThan(0.05); // measured 0.097

  await setAll('seedlings');
  await expect
    .poll(drawn, { intervals: [100], timeout: 1000 })
    .toEqual(all('seedlings'));
  await page.waitForTimeout(500);
  const planted = await pixels();
  expect(planted.gold).toBeLessThan(ripe.gold / 4);
  // open water in every basin (measured 0.16 of the view; the field's marks showing through it halved that)
  expect(planted.water).toBeGreaterThan(0.12);
  // one stage showing: a look per tile shape (open, side, corner)
  const looks = await page.evaluate(() =>
    (globalThis as unknown as PaddiesWindow)
      .__pebblePaddies!.looks()
      .filter(({ count }) => count > 0)
      .map(({ look }) => look)
      .sort(),
  );
  expect(looks).toEqual([
    'seedlings:corner',
    'seedlings:open',
    'seedlings:side',
  ]);

  await setAll('stubble');
  await expect
    .poll(drawn, { intervals: [100], timeout: 1000 })
    .toEqual(all('stubble'));
  await page.waitForTimeout(500);
  // drained: no water left (measured 0.001; the kit's flooded tiles drawn as well showed 0.067)
  expect((await pixels()).water).toBeLessThan(0.01);
  await setAll('seedlings');
  await page.evaluate(() =>
    (globalThis as unknown as PaddiesWindow).__pebbleMockLive.sendNow(
      'node_changed',
      'tokuji',
      {
        node: 'paddy-3',
        kind: 'rice_paddy',
        item: 'rice',
        before: 0,
        after: 0,
        stage: 'stubble',
      },
    ),
  );
  await expect
    .poll(async () => (await drawn())?.['paddy-3'], { timeout: 1000 })
    .toBe('stubble');
  expect((await drawn())?.['paddy-6']).toBe('seedlings');
  expect(Number(await world.getAttribute('data-draw-calls'))).toBeLessThan(
    DRAW_CALL_BUDGET,
  );
  expect(errors).toEqual([]);
});
