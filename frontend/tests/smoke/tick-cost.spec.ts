import { expect, type Page, test, type WebSocketRoute } from '@playwright/test';

import type { LiveAnimal, LiveFrame } from '../../src/lib/live/live-contract';
import type { EntitiesAnswer } from '../../src/lib/live/live-state';
import { openGlobe } from './globe-helpers';

/*
 * What a live tick costs the globe page (critic round 1: every tick froze a frame for 85-118 ms, the whole scene
 * rendering again for it). The test plays the engine's feed: a snapshot of the backend's world now, then ticks
 * that change one animal and the citizens' needs (as every engine tick does). A tick renders only what it changed:
 * never the world around the bodies, never the animals it left alone; and with thousands of still animals it still
 * doesn't stall a frame.
 */

/** Components a tick never touches: the world around the bodies, the walker and the props. */
const UNTOUCHED = [
  'GlobeSky',
  'GlobeSurface',
  'Waterfalls',
  'GlobeTown',
  'GlobeSites',
  'BiomeScatter',
  'GlobeNodes',
  'LivingProps',
  'GlobeWalker',
];

/**
 * Counts every function component each React root renders (react-dom's and the Canvas's), by name, through the
 * hook React DevTools uses: a commit's fibers rendered when they mounted or performed work, and only subtrees whose
 * children were worked on are visited (an untouched subtree keeps its old fibers and their old flags).
 */
const RENDER_COUNTER = `(() => {
  const renders = new Map();
  window.__renders = renders;
  const PERFORMED_WORK = 1;
  const visit = (fiber) => {
    const before = fiber.alternate;
    if (typeof fiber.type === 'function' && (before === null || fiber.flags & PERFORMED_WORK)) {
      const name = fiber.type.displayName || fiber.type.name;
      renders.set(name, (renders.get(name) ?? 0) + 1);
    }
    if (before !== null && fiber.child === before.child) return;
    for (let child = fiber.child; child; child = child.sibling) visit(child);
  };
  let id = 0;
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
    renderers: new Map(),
    supportsFiber: true,
    isDisabled: false,
    inject(renderer) { id += 1; this.renderers.set(id, renderer); return id; },
    checkDCE() {},
    onScheduleFiberRoot() {},
    onCommitFiberRoot(_id, root) { visit(root.current); },
    onPostCommitFiberRoot() {},
    onCommitFiberUnmount() {},
    setStrictMode() {},
  };
})()`;

/** Plays the engine's feed from the backend's entities now; `send` sends the next tick and returns its number. */
async function playFeed(
  page: Page,
  change: (frame: LiveFrame, tick: number) => LiveFrame,
) {
  let base: EntitiesAnswer | null = null;
  let socket: WebSocketRoute | null = null;
  // the snapshot goes out once both the entities answer and the socket are there
  const snapshot = () => {
    if (base && socket)
      socket.send(JSON.stringify(change(frameOf(base, 0), 0)));
  };
  await page.route(/\/api\/v1\/entities$/, async (route) => {
    const response = await route.fetch();
    base = (await response.json()) as EntitiesAnswer;
    await route.fulfill({ response, json: change(frameOf(base, 0), 0) });
    snapshot();
  });
  await page.routeWebSocket(/\/api\/v1\/live$/, (route) => {
    socket = route;
    snapshot();
  });
  let tick = 0;
  return {
    get ready() {
      return base !== null && socket !== null;
    },
    get firstTick() {
      return base?.tick ?? 0;
    },
    send() {
      if (!base || !socket) throw new Error('the feed is not up yet');
      tick += 1;
      socket.send(JSON.stringify(change(frameOf(base, tick), tick)));
      return base.tick + tick;
    },
  };
}

/** The backend's entities as the feed's frame `step` ticks later (a snapshot first). */
function frameOf(base: EntitiesAnswer, step: number): LiveFrame {
  return {
    type: step === 0 ? 'snapshot' : 'tick',
    run_id: base.run_id,
    tick: base.tick + step,
    day: base.day,
    time: base.time,
    speed: 60,
    paused: false,
    tick_elapsed_s: 0,
    citizens: base.citizens.map((citizen) => ({
      ...citizen,
      needs: { ...citizen.needs, hunger: citizen.needs.hunger + step / 10 },
    })),
    animals: base.animals,
    fires: base.fires,
  };
}

/** The first animal turns a degree a tick: the one thing a tick changes besides the citizens' needs. */
function turnOne(animals: LiveAnimal[], step: number): LiveAnimal[] {
  const [first, ...rest] = animals;
  return [{ ...first, heading_deg: (first.heading_deg + step) % 360 }, ...rest];
}

async function waitForTick(page: Page, tick: number) {
  await expect(page.getByTestId('world')).toHaveAttribute(
    'data-live-tick',
    String(tick),
  );
}

test('a tick renders only what it changed: not the world around the bodies, not the animals it left alone', async ({
  page,
}) => {
  test.setTimeout(120_000);
  await page.addInitScript(RENDER_COUNTER);
  const feed = await playFeed(page, (frame, step) => ({
    ...frame,
    animals: turnOne(frame.animals, step),
  }));
  const errors: string[] = [];
  await openGlobe(page, errors);
  await expect.poll(() => feed.ready).toBe(true);
  await waitForTick(page, feed.firstTick);
  const animals = Number(
    await page.getByTestId('animals').getAttribute('data-animals'),
  );
  expect(animals).toBeGreaterThan(50);
  await page.waitForTimeout(3_000); // models and clips load

  const worst = new Map<string, number>();
  let citizensRendered = Infinity;
  for (let k = 0; k < 5; k++) {
    await page.evaluate('window.__renders.clear()');
    await waitForTick(page, feed.send());
    await page.waitForTimeout(500);
    const renders = new Map(
      await page.evaluate<[string, number][]>('[...window.__renders]'),
    );
    for (const [name, count] of renders)
      worst.set(name, Math.max(worst.get(name) ?? 0, count));
    citizensRendered = Math.min(citizensRendered, renders.get('Npc') ?? 0);
  }
  // the counter sees the ticks: every citizen's needs moved, so each citizen rendered again
  expect(citizensRendered).toBeGreaterThan(0);
  for (const name of UNTOUCHED) expect(worst.get(name) ?? 0, name).toBe(0);
  // the one animal turned (an animal first coming near the camera may render once more)
  expect(worst.get('Animal') ?? 0).toBeLessThanOrEqual(3);
  expect(errors).toEqual([]);
});

/** Still copies of the backend's animals (about 2,000 animals then): a big world whose ticks change little. */
const COPIES = 6;

/** The longest frame (ms) from now until `ms` later, by animation frames (browser code as a string). */
const LONGEST_FRAME = (ms: number) => `new Promise((resolve) => {
  let last = performance.now();
  let longest = 0;
  const end = last + ${ms};
  const step = (now) => {
    longest = Math.max(longest, now - last);
    last = now;
    if (now < end) requestAnimationFrame(step);
    else resolve(longest);
  };
  requestAnimationFrame(step);
})`;

/** The WebGL renderer's name (browser code as a string: the test TypeScript has no DOM types). */
const RENDERER = `(() => {
  const gl = document.createElement('canvas').getContext('webgl2');
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  return info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
})()`;

const median = (values: number[]) =>
  [...values].sort((a, b) => a - b)[values.length >> 1];

test('a tick that changes little does not stall a frame, however many animals stand still', async ({
  page,
}) => {
  test.setTimeout(180_000);
  // a software renderer (headless Chrome off macOS) draws every frame on the CPU: its frame times say nothing
  const renderer = await page.evaluate<string>(RENDERER);
  test.skip(
    /swiftshader|llvmpipe|software/i.test(renderer),
    `no GPU (${renderer})`,
  );
  const feed = await playFeed(page, (frame, step) => ({
    ...frame,
    animals: turnOne(
      [
        ...frame.animals,
        ...Array.from({ length: COPIES }, (_, copy) =>
          frame.animals.map((animal) => ({
            ...animal,
            id: `copy-${copy}:${animal.id}`,
          })),
        ).flat(),
      ],
      step,
    ),
  }));
  const errors: string[] = [];
  await openGlobe(page, errors);
  await expect.poll(() => feed.ready).toBe(true);
  await waitForTick(page, feed.firstTick);
  await page.waitForTimeout(3_000); // models and clips load
  // the longest frame of a quiet stretch, then of the same stretch with a tick in it, eight times over: other work
  // on the machine slows both alike
  const quiet: number[] = [];
  const ticked: number[] = [];
  for (let k = 0; k < 8; k++) {
    quiet.push(await page.evaluate<number>(LONGEST_FRAME(700)));
    const longest = page.evaluate<number>(LONGEST_FRAME(700));
    feed.send();
    ticked.push(await longest);
  }
  test.info().annotations.push({
    type: 'frames',
    description: `quiet ${quiet.map(Math.round)}; with a tick ${ticked.map(Math.round)}`,
  });
  // a tick may cost two frames more than the quiet stretch. Calibrated on an M-series Mac, 4 runs at once: no frame
  // longer than the quiet ones now; 67-117 ms (median 83) at every tick when each one drew the whole scene and every
  // animal again, 167-200 ms with the CPU slowed 2x
  expect(median(ticked)).toBeLessThanOrEqual(median(quiet) + 34);
  expect(errors).toEqual([]);
});
