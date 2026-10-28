import { expect, type Page, test, type WebSocketRoute } from '@playwright/test';

import { tickLabel } from '../../src/lib/spectator/time';

/*
 * The spectator pages against the real backend and its running simulation: people, a citizen's life, the
 * conversations, the replay scrubber and the stats. Every page must load without console errors.
 */

const API_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1`;

interface CitizenRow {
  id: string;
  name: string;
  alive: boolean;
}

async function api<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);
  expect(response.ok, `${path}: ${response.status}`).toBe(true);
  return (await response.json()) as T;
}

function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  return errors;
}

test('people lists everyone with a portrait and what they are doing', async ({
  page,
}) => {
  const errors = watchErrors(page);
  const { citizens } = await api<{ citizens: CitizenRow[] }>('/citizens');
  await page.goto('/people');
  // the engine's real feed keeps the page current (through the dev server's proxy)
  await expect(page.getByTestId('people-page')).toHaveAttribute(
    'data-live-feed',
    'live',
  );
  const people = page.getByTestId('person');
  await expect(people).toHaveCount(citizens.length);
  for (const citizen of citizens)
    await expect(
      page.locator(`[data-citizen="${citizen.id}"]`).getByText(citizen.name),
    ).toBeVisible();
  await expect(people.first().getByTestId('doing')).not.toBeEmpty();
  // portraits are rendered from the 3D looks (the clips come from the Polyfork CDN)
  await expect(
    page.locator('[data-testid="portrait"][data-ready="true"]'),
  ).toHaveCount(citizens.length, { timeout: 20_000 });
  await people.first().click();
  await expect(page).toHaveURL(new RegExp(`/people/${citizens[0].id}$`));
  await expect(page.getByTestId('citizen-page')).toBeVisible();
  // replaying keeps the moment on the way to a citizen
  await page.goto('/people?at=600');
  await expect(page.getByTestId('replay-banner')).toBeVisible();
  await expect(people.first()).toHaveAttribute(
    'href',
    `/people/${citizens[0].id}?at=600`,
  );
  expect(errors).toEqual([]);
});

test('a citizen page shows their needs and a timeline that loads more as you scroll', async ({
  page,
}) => {
  const errors = watchErrors(page);
  const { citizens } = await api<{ citizens: CitizenRow[] }>('/citizens');
  const id = citizens[0].id;
  const profile = await api<{
    name: string;
    known_people: { id: string; name: string }[];
  }>(`/citizens/${id}`);
  const newest = await api<{
    entries: { summary: string }[];
    next_cursor: number | null;
  }>(`/citizens/${id}/timeline?order=desc&limit=60`);
  await page.goto(`/people/${id}`);
  await expect(page.getByRole('heading', { name: profile.name })).toBeVisible();
  const entries = page.getByTestId('timeline-entry');
  await expect(entries.first()).toBeVisible();
  expect(await entries.count()).toBeGreaterThan(5);
  // a recent line is among the first ones shown (the run moves on while the page loads)
  await expect(
    page.getByTestId('timeline').getByText(newest.entries[5].summary).first(),
  ).toBeVisible();
  await expect(page.locator('[data-testid="needs-chart"] path')).toHaveCount(4);
  for (const person of profile.known_people)
    await expect(
      page.getByTestId('known-people').getByText(person.name),
    ).toBeVisible();
  await expect(page.getByTestId('show-on-map')).toHaveAttribute(
    'href',
    `/?follow=${id}`,
  );
  await expect(page.getByTestId('activity')).not.toBeEmpty();
  if (newest.next_cursor !== null) {
    const first = await entries.count();
    const main = page.getByTestId('citizen-page');
    await expect
      .poll(
        async () => {
          await main.evaluate((element) => {
            const scroller = element as unknown as {
              scrollTo(x: number, y: number): void;
              scrollHeight: number;
            };
            scroller.scrollTo(0, scroller.scrollHeight);
          });
          return entries.count();
        },
        { timeout: 10_000 },
      )
      .toBeGreaterThan(first);
  }
  expect(errors).toEqual([]);
});

test('a citizen page replays a past tick', async ({ page }) => {
  const errors = watchErrors(page);
  const { citizens } = await api<{ citizens: CitizenRow[] }>('/citizens');
  const id = citizens[0].id;
  const then = await api<{ tick: number; time: string; day: number }>(
    `/citizens/${id}?at=600`,
  );
  await page.goto(`/people/${id}?at=600`);
  await expect(page.getByTestId('replay-banner')).toContainText(
    `day ${then.day}, ${then.time}`,
  );
  await expect(page.locator('[data-tick="600"]')).toBeVisible();
  await expect(page.getByTestId('timeline-entry').first()).toBeVisible();
  await expect(page.getByTestId('show-on-map')).toHaveAttribute(
    'href',
    `/?tick=600&follow=${id}`,
  );
  const links = await page.getByTestId('timeline-entry').locator('a').all();
  const ticks = await Promise.all(
    links.map(async (link) =>
      Number(
        new URLSearchParams(
          ((await link.getAttribute('href')) ?? '').split('?')[1],
        ).get('tick'),
      ),
    ),
  );
  expect(ticks.length).toBeGreaterThan(0);
  expect(Math.max(...ticks)).toBeLessThanOrEqual(600);
  expect(errors).toEqual([]);
});

test('conversations show threads of speech and jump to the moment', async ({
  page,
}) => {
  const errors = watchErrors(page);
  const { threads } = await api<{
    threads: {
      start_tick: number;
      lines: { words: string; speaker: { id: string } }[];
    }[];
  }>('/conversations?from_tick=0&limit=100');
  expect(threads.length).toBeGreaterThan(0);
  const day = await api<{ day: number }>(`/stats?at=${threads[0].start_tick}`);
  await page.goto(`/conversations?day=${day.day}`);
  const shown = page.getByTestId('thread');
  await expect(shown.first()).toBeVisible();
  const first = shown.first();
  const start = Number(await first.getAttribute('data-start-tick'));
  await expect(first.getByTestId('line').first()).toContainText('“');
  const href = await first.getByTestId('jump').getAttribute('href');
  expect(href).toMatch(new RegExp(`^/\\?tick=${start}&follow=[a-z-]+$`));
  await page.goto('/conversations');
  await expect(page.getByTestId('conversations-page')).toBeVisible();
  expect(errors).toEqual([]);
});

test('the replay scrubber changes the shown tick and the moment follows it', async ({
  page,
}) => {
  const errors = watchErrors(page);
  await page.goto('/timeline?at=2000');
  const tick = page.getByTestId('replay-tick');
  await expect(tick).toHaveAttribute('data-tick', '2000');
  await expect(page.getByTestId('open-world')).toHaveAttribute(
    'href',
    '/?tick=2000',
  );
  const atTwoThousand = await api<{ citizens: { name: string }[] }>(
    '/citizens?at=2000',
  );
  await expect(page.getByTestId('moment-citizens').locator('li')).toHaveCount(
    atTwoThousand.citizens.length,
  );
  await page.getByRole('button', { name: '−1 h' }).click();
  await expect(tick).toHaveAttribute('data-tick', '1940');
  await expect(page).toHaveURL(/\?at=1940$/);
  await page.getByRole('button', { name: '+1 day' }).click();
  await expect(tick).toHaveAttribute('data-tick', String(1940 + 1440));
  // the slider itself: Home goes back to the first tick
  await page.getByRole('slider').focus();
  await page.keyboard.press('Home');
  await expect(tick).toHaveAttribute('data-tick', '0');
  await expect(page).toHaveURL(/\?at=0$/);
  await expect(page.getByTestId('replay-banner')).toContainText('day 0, 08:00');
  await page.keyboard.press('ArrowRight');
  await expect(tick).toHaveAttribute('data-tick', '1');
  expect(errors).toEqual([]);
});

test('stats count the living, the food and the days', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/stats');
  const stats = await api<{
    population: { alive: number; dead: number };
    days: unknown[];
  }>('/stats');
  await expect(page.getByTestId('alive')).toHaveText(
    String(stats.population.alive),
  );
  await expect(page.getByTestId('dead')).toHaveText(
    String(stats.population.dead),
  );
  await expect(page.getByTestId('food')).toContainText('the storehouse');
  await expect(page.getByTestId('resources')).toContainText('berries');
  await expect(
    page.getByTestId('columns').first().locator('> div'),
  ).toHaveCount(stats.days.length);
  await page.goto('/stats?at=0');
  await expect(page.getByTestId('day')).toHaveText('0');
  await expect(page.getByTestId('food')).toContainText('400 rice');
  expect(errors).toEqual([]);
});

test('the menu reaches every spectator page', async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto('/stats');
  for (const [name, testId] of [
    ['People', 'people-page'],
    ['Conversations', 'conversations-page'],
    ['Timeline', 'timeline-page'],
    ['Stats', 'stats-page'],
  ]) {
    await page.getByRole('navigation').getByRole('link', { name }).click();
    await expect(page.getByTestId(testId)).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test('pages refresh within 2 s of a live tick and poll only while the feed is down', async ({
  page,
}) => {
  const errors = watchErrors(page);
  // the test plays the engine's feed: the page's socket is answered here, not by the backend
  const sockets: WebSocketRoute[] = [];
  let refuse = false;
  await page.routeWebSocket(/\/api\/v1\/live$/, (socket) => {
    if (refuse) socket.close({ code: 1011 });
    else sockets.push(socket);
  });
  const isCitizens = (url: string) =>
    new URL(url).pathname === '/api/v1/citizens';
  let asked = 0;
  page.on('request', (request) => {
    if (isCitizens(request.url())) asked += 1;
  });
  await page.goto('/people');
  const main = page.getByTestId('people-page');
  await expect(main).toHaveAttribute('data-live-feed', 'live');
  await expect(page.getByTestId('person').first()).toBeVisible();

  // a quiet feed: nothing is polled
  const quiet = asked;
  await page.waitForTimeout(3_000);
  expect(asked).toBe(quiet);

  // a tick: the page asks again and shows the new answer
  const clock = await api<{
    run_id: string;
    tick: number;
    day: number;
    time: string;
    speed: number;
    paused: boolean;
  }>('/clock');
  const refetched = page.waitForResponse(
    (response) => isCitizens(response.url()),
    { timeout: 2_000 },
  );
  sockets.at(-1)!.send(
    JSON.stringify({
      type: 'tick',
      run_id: clock.run_id,
      tick: clock.tick,
      day: clock.day,
      time: clock.time,
      speed: clock.speed,
      paused: clock.paused,
      citizens: [],
    }),
  );
  const answer = (await (await refetched).json()) as { tick: number };
  await expect(main.locator('header p')).toContainText(tickLabel(answer.tick), {
    timeout: 1_000,
  });

  // the feed drops (and stays down): the page falls back to polling
  refuse = true;
  sockets.at(-1)!.close({ code: 1011 });
  await expect(main).toHaveAttribute('data-live-feed', 'down');
  const polled = asked;
  await expect.poll(() => asked, { timeout: 5_000 }).toBeGreaterThan(polled);
  expect(errors).toEqual([]);
});
