import {
  type Browser,
  expect,
  type Page,
  test,
  type TestInfo,
} from '@playwright/test';
import { Vector3 } from 'three';

import type {
  EntitiesView,
  Feature,
  Furniture,
  LiveState,
  TownView,
  WorldView,
} from '../src/lib/client/types.gen';
import { snapMetres } from '../src/lib/live/walk-path';
import type { PropKind } from '../src/lib/world/assets';
import {
  anchorMapping,
  buildTerrain,
  decodeWorld,
  type GlobeTerrain,
  type SiteMapping,
} from '../src/lib/world/globe';
import type { DrawnNode } from '../src/lib/world/node-field';
import { isTimeLapse } from '../src/lib/world/visual-rate';
import { TOWN_GROUND_RADIUS } from './smoke/explore-helpers';
import {
  atParam,
  DRAW_CALL_BUDGET,
  openGlobe,
  WORLD_URL,
} from './smoke/globe-helpers';
import { inView, viewOf } from './smoke/ui-helpers';

/*
 * The world audit's browser probes (World v1 Q1) on the engine's real feed: what the page DRAWS, read from its hidden
 * hooks (`[data-npc]`, `window.__pebbleNodes`) and its scene, against the world data it draws from. Bodies never
 * stack, work happens at a drawn node, sitters and sleepers stay above the ground and on something to sit or lie on,
 * the crowded plaza stays in the draw-call budget, and nobody jumps, in real time and in time-lapse.
 *
 * It drives the engine's clock (×10, ×60, ×600, then back), so it runs in its own project after the smoke tests.
 */

const API_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1`;

test.describe.configure({ timeout: 300_000 });

/** Known defect: resting about camp, out in the wild or in town (#107) sits on bare ground far from any seat. */
const GROUND_RESTS_ISSUE = 133;
/** Known defect: a sitter sinks into the ground in its first frames, until its rest pose is laid. */
const APPEARING_SINK_ISSUE = 134;
/** Known defect: at ×10 and up a walker passes others closer than 0.5 m (the push apart is slower than the walker). */
const TIME_LAPSE_BRUSH_ISSUE = 136;
/** Known defect: at ×600 a rester is drawn in its rest pose while still sliding along its walk. */
const GLIDING_RESTERS_ISSUE = 137;

/** Two drawn bodies closer than this (m) stand inside each other (the audit's "exact overlaps"). */
const OVERLAP_M = 0.5;
/** ...and closer than this (half a body) one is drawn through the other. */
const THROUGH_M = 0.25;
/** The activities of someone on the move. */
const MOVING = ['walking', 'running', 'hunting'];
/** Work (gather, fish, farm, mine, fell) needs the body this close (m) to a drawn node of what it takes. */
const WORK_REACH_M = 3.2;
/** A vertex of a sitter or sleeper this far (m) under the drawn ground is sunk into it. */
const SUNK_M = 0.03;
/** A resting body this close (m) to a seat's, log's or mat's outline rests on it. */
const SEAT_REACH_M = 0.6;
/** The fastest gait (backend: 210 m a game minute) and how fast the drawing pushes bodies apart (separation.ts). */
const RUN_MPS = 210 / 60;
const PUSH_MPS = 0.9;
/** Hooks refresh every 100 ms and round to 1 cm; the sampler adds up to 20 ms of lag at each end. */
const SAMPLE_LAG_S = 0.04;
const ROUNDING_M = 0.02;

type Dataset = { dataset: Record<string, string | undefined> };

interface Body {
  id: string;
  position: Vector3;
  hidden: boolean;
  activity: string;
  /** How the body is drawn resting (`BodyPose`). */
  pose: string;
  motion: string;
  /** The feed's action label: what the work takes ("berries", "wood"...). */
  label: string;
  loaded: boolean;
  clip: string;
  /** Height of the ground the body stands on, as the page draws it. */
  ground: number;
}

/** Every drawn citizen as the page's hooks show it now. */
async function bodies(page: Page): Promise<Body[]> {
  const raw = await page
    .locator('[data-npc]')
    .evaluateAll((nodes) =>
      nodes.map((node) => ({ ...(node as unknown as Dataset).dataset })),
    );
  return raw.map((data) => ({
    id: data.npc!,
    position: new Vector3(
      Number(data.npcX),
      Number(data.npcY),
      Number(data.npcZ),
    ),
    hidden: data.npcHidden === 'true',
    activity: data.npcActivity ?? '',
    pose: data.npcPosture ?? 'standing',
    motion: data.npcMotion ?? 'idle',
    label: data.npcLabel ?? '',
    loaded: data.npcLoaded === 'true',
    clip: data.npcClip ?? '',
    ground: Number(data.npcGround),
  }));
}

/** A trace: when (real ms) and each body as drawn then. */
type Trace = { t: number; bodies: Body[] }[];

/**
 * Samples the hooks in the page every 20 ms for `seconds`, keeping each change: the hooks refresh every 100 ms, so
 * each kept sample is one refresh, stamped within 20 ms of it.
 */
async function traceFor(page: Page, seconds: number): Promise<Trace> {
  const rows = await page.evaluate<
    [number, string[][]][]
  >(`new Promise((done) => {
    const kept = [];
    let last = '';
    const start = performance.now();
    const timer = setInterval(() => {
      const rows = [...document.querySelectorAll('[data-npc]')].map((node) => {
        const d = node.dataset;
        return [d.npc, d.npcX, d.npcY, d.npcZ, d.npcHidden, d.npcActivity, d.npcPosture, d.npcMotion, d.npcLabel ?? ''];
      });
      const key = rows.map((row) => row.slice(1, 5).join(',')).join('|');
      const now = performance.now();
      if (key !== last) kept.push([now, rows]);
      last = key;
      if (now - start > ${seconds * 1000}) {
        clearInterval(timer);
        done(kept);
      }
    }, 20);
  })`);
  return rows.map(([t, all]) => ({
    t,
    bodies: all.map(([id, x, y, z, hidden, activity, pose, motion, label]) => ({
      id,
      position: new Vector3(Number(x), Number(y), Number(z)),
      hidden: hidden === 'true',
      activity,
      pose,
      motion,
      label,
      loaded: false,
      clip: '',
      ground: NaN,
    })),
  }));
}

let R: number;
let terrain: GlobeTerrain;
let town: {
  id: string;
  mapping: SiteMapping;
  height: number;
  view: TownView;
};
let features: Feature[];
/** Every site's chart by id (camps, landmarks, the town). */
let sites: Map<string, { mapping: SiteMapping; up: Vector3 }>;
let furniture: Furniture[];

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  const get = async <T>(url: string) =>
    (await (await api.get(url)).json()) as T;
  const view = await get<WorldView>(WORLD_URL);
  const townView = await get<TownView>(`${API_URL}/town`);
  furniture = await get<Furniture[]>(`${API_URL}/world/furniture`);
  await api.dispose();
  R = view.radius_m;
  terrain = buildTerrain(decodeWorld(view));
  features = view.places.features;
  sites = new Map(
    view.sites.map((site) => [
      site.id,
      {
        mapping: anchorMapping(site.anchor, R),
        up: new Vector3(...site.anchor.position),
      },
    ]),
  );
  const site = view.sites.find((candidate) => candidate.kind === 'town')!;
  town = {
    id: site.id,
    mapping: sites.get(site.id)!.mapping,
    height: site.anchor.height_m,
    view: townView,
  };
});

/** Metres along the ground between two points (world metres or unit directions). */
const apart = (a: Vector3, b: Vector3) =>
  a.clone().normalize().angleTo(b.clone().normalize()) * R;

/** The drawn ground under a direction: the town's disc at its plateau, else the rendered terrain. */
function groundUnder(direction: Vector3) {
  const local = town.mapping.toLocal(
    direction.clone().multiplyScalar(R),
    new Vector3(),
  );
  return Math.hypot(local.x, local.z) < TOWN_GROUND_RADIUS
    ? town.height
    : terrain.heightAt(direction);
}

const shown = (body: Body) => !body.hidden && body.position.lengthSq() > 0;

/** The closest two drawn bodies came in a trace, for each pair closer than OVERLAP_M at some refresh. */
function overlaps(trace: Trace) {
  const found = new Map<
    string,
    { metres: number; a: Body; b: Body; rate?: number }
  >();
  for (const { bodies: all } of trace) {
    const drawn = all.filter(shown);
    for (let i = 0; i < drawn.length; i++)
      for (let j = i + 1; j < drawn.length; j++) {
        const [a, b] = [drawn[i], drawn[j]];
        const metres = a.position.distanceTo(b.position);
        const pair = `${a.id}/${b.id}`;
        if (metres < Math.min(OVERLAP_M, found.get(pair)?.metres ?? Infinity))
          found.set(pair, { metres, a, b });
      }
  }
  return [...found.entries()].map(([pair, { metres, a, b }]) => ({
    pair,
    metres,
    walker: MOVING.includes(a.activity) || MOVING.includes(b.activity),
    words: `${pair} ${metres.toFixed(2)} m (${a.activity}, ${b.activity})`,
  }));
}

/**
 * Steps in a trace longer than the fastest gait (at the clock's rate) and the drawing's push could cover between two
 * refreshes ("kenji 12.3 m in 0.10 s"); in time-lapse, longer than a resync at running pace (a teleport). A body going
 * in or out of a house is skipped (it comes out at the door).
 */
function jumps(trace: Trace, rate: number) {
  const found: string[] = [];
  let biggest = 0;
  for (let k = 1; k < trace.length; k++) {
    const seconds = (trace[k].t - trace[k - 1].t) / 1000;
    // in time-lapse a body may ease onto a late tick's route faster than it walks; past snapMetres it would fade across
    const most = isTimeLapse(rate)
      ? snapMetres(RUN_MPS, rate)
      : (RUN_MPS * rate + PUSH_MPS) * (seconds + SAMPLE_LAG_S) + ROUNDING_M;
    for (const body of trace[k].bodies) {
      const was = trace[k - 1].bodies.find((other) => other.id === body.id);
      if (!was || !shown(body) || !shown(was)) continue;
      const metres = body.position.distanceTo(was.position);
      biggest = Math.max(biggest, metres / (seconds + SAMPLE_LAG_S));
      if (metres > most)
        found.push(
          `${body.id} ${metres.toFixed(2)} m in ${seconds.toFixed(2)} s (${was.activity} → ${body.activity})`,
        );
    }
  }
  return { found, fastest: biggest };
}

/** Something drawn to sit or lie on: a segment (log seat, mat, bench) or a point (stool, the lord's seat), in a chart. */
interface Seat {
  id: string;
  site: string;
  /** Chart metres of its middle and the half-segment along its length. */
  x: number;
  z: number;
  dx: number;
  dz: number;
}

/** Chart (x east, z south) of a heading in degrees (0 north, 90 east). */
const facingOf = (degrees: number) => {
  const radians = (degrees * Math.PI) / 180;
  return { x: Math.sin(radians), z: -Math.cos(radians) };
};

/** The furniture (log seats, mats, stools, the lord's seat) and the town's benches, as drawn. */
function seats(): Seat[] {
  const pieces = furniture.map((piece): Seat => {
    const facing = facingOf(piece.heading_deg);
    // a log seat runs across the way its sitters face, a mat along the way its sleeper lies
    const half =
      piece.kind === 'log_seat'
        ? { x: -facing.z, z: facing.x, length: (piece.span_m ?? 0) / 2 }
        : piece.kind === 'sleeping_mat'
          ? { ...facing, length: 1 }
          : { x: 0, z: 0, length: 0 };
    return {
      id: piece.id,
      site: piece.site,
      x: piece.x,
      z: piece.z,
      dx: half.x * half.length,
      dz: half.z * half.length,
    };
  });
  const benches = town.view.placements
    .filter((placement) => placement.kind === 'bench')
    .map((bench): Seat => {
      const across = bench.rotation_deg % 180 === 0;
      const half = bench.footprint.x / 2;
      return {
        id: bench.id,
        site: town.id,
        x: bench.x,
        z: bench.z,
        dx: across ? half : 0,
        dz: across ? 0 : half,
      };
    });
  return [...pieces, ...benches];
}

/** Metres from a world point to a seat's outline, on its site's chart (Infinity for a site far away). */
function offSeat(position: Vector3, seat: Seat) {
  const chart = sites.get(seat.site)!;
  if (position.clone().normalize().angleTo(chart.up) * R > 1000)
    return Infinity;
  const local = chart.mapping.toLocal(position, new Vector3());
  const span = seat.dx * seat.dx + seat.dz * seat.dz;
  const along =
    span === 0
      ? 0
      : Math.max(
          -1,
          Math.min(
            1,
            ((local.x - seat.x) * seat.dx + (local.z - seat.z) * seat.dz) /
              span,
          ),
        );
  return Math.hypot(
    local.x - (seat.x + along * seat.dx),
    local.z - (seat.z + along * seat.dz),
  );
}

/** Drawn as resting on something: seated on a seat, or sitting or lying on the ground to rest or sleep. */
const resting = (body: Body) =>
  shown(body) &&
  (body.pose === 'seated' ||
    (['sitting', 'sleeping', 'lying'].includes(body.pose) &&
      ['resting', 'sleeping'].includes(body.activity)));

/** Resting bodies in a trace that rest on nothing drawn (each once), and whether they were drawn moving then. */
function restingOnNothing(trace: Trace) {
  const all = seats();
  const found = new Map<
    string,
    { body: Body; moving: boolean; words: string }
  >();
  trace.forEach(({ bodies: drawn }, k) => {
    for (const body of drawn.filter(resting)) {
      const nearest = all
        .map((seat) => ({ seat, metres: offSeat(body.position, seat) }))
        .sort((a, b) => a.metres - b.metres)[0];
      if (nearest.metres <= SEAT_REACH_M || found.has(body.id)) continue;
      const was = trace[Math.max(k - 1, 0)].bodies.find(
        (other) => other.id === body.id,
      );
      const moving = !!was && was.position.distanceTo(body.position) > 0.05;
      found.set(body.id, {
        body,
        moving,
        words: `${body.id} ${body.activity} ${body.pose}${moving ? ' moving' : ''} ${nearest.metres.toFixed(1)} m from ${nearest.seat.id}`,
      });
    }
  });
  return [...found.values()];
}

const TREES: PropKind[] = [
  'oak_tree',
  'birch_tree',
  'pine_tree',
  'young_pine',
  'snowy_spruce',
  'acacia_tree',
  'dwarf_pine',
  'tree_fern',
  'nut_tree',
  'dead_tree',
];

/** What each kind of work takes from (by its item, or by the motion for felling and farming), as drawn. */
const WORK_SPOTS: Record<
  string,
  { nodes?: PropKind[]; features?: Feature['kind'][]; paddies?: true }
> = {
  berries: { nodes: ['berry_bush'] },
  nuts: { nodes: ['nut_tree'] },
  roots: { nodes: ['root_patch'] },
  reeds: { nodes: ['reed_bed'] },
  wood: { nodes: [...TREES, 'fallen_log', 'driftwood', 'tree_stump'] },
  rice: { paddies: true },
  fish: { features: ['fishing_spot'] },
  flint: { nodes: ['flint_seam'] },
  obsidian: { nodes: ['obsidian_field'] },
  'iron sand': { features: ['iron_sand_bar'] },
  gold: { features: ['gold_pool'] },
};
/** The motions of work at a node. */
const WORK_MOTIONS = [
  'gather_low',
  'gather_high',
  'chop',
  'mine',
  'pan',
  'farm',
  'fish',
];
const workOf = (body: Body) =>
  body.motion === 'farm'
    ? 'rice'
    : body.motion === 'chop'
      ? 'wood'
      : body.label;
const working = (body: Body) =>
  shown(body) && WORK_MOTIONS.includes(body.motion);

/** Metres from a body to the nearest drawn thing its work takes from, or why there is none. */
function offWork(body: Body, nodes: DrawnNode[]) {
  const spots = WORK_SPOTS[workOf(body)];
  if (!spots) return `${body.id} ${body.motion} "${body.label}": no known node`;
  const points = [
    ...nodes
      .filter((node) => spots.nodes?.includes(node.look))
      .map((node) => new Vector3(...node.position)),
    ...features
      .filter((feature) => spots.features?.includes(feature.kind))
      .map((feature) => new Vector3(...feature.position)),
    ...(spots.paddies
      ? town.view.placements
          .filter((placement) => placement.kind === 'rice_paddy')
          .map((paddy) =>
            town.mapping.toWorld(paddy.x, 0, paddy.z, new Vector3()),
          )
      : []),
  ];
  const nearest = Math.min(
    ...points.map((point) => apart(point, body.position)),
  );
  return nearest <= WORK_REACH_M
    ? null
    : `${body.id} ${body.motion} "${body.label}": nearest drawn node ${nearest.toFixed(1)} m`;
}

/** Engine clock at the start, so the test leaves it as it found it. */
async function engineClock(page: Page) {
  return (await (await page.request.get(`${API_URL}/clock`)).json()) as {
    speed: number;
    paused: boolean;
  };
}

const setSpeed = (page: Page, speed: number) =>
  page.request.post(`${API_URL}/admin/clock`, { data: { speed } });

/** Opens the globe on the engine's real feed with every citizen placed. */
async function openReal(page: Page, errors: string[], query = '') {
  const world = await openGlobe(page, errors, query);
  await expect(page.getByTestId('npcs')).toHaveAttribute(
    'data-npcs-ready',
    /^[1-9]\d*$/,
    { timeout: 30_000 },
  );
  await expect(world).toHaveAttribute('data-live-status', 'live');
  await expect
    .poll(async () => (await bodies(page)).filter(shown).length, {
      timeout: 15_000,
    })
    .toBeGreaterThan(0);
  return world;
}

/** Follows a citizen from the People panel until the nodes are drawn round them. */
async function follow(page: Page, id: string) {
  const panel = page.getByRole('region', { name: 'People' });
  if (!(await panel.isVisible()))
    await page.getByRole('button', { name: 'people', exact: true }).click();
  await page
    .locator(`[data-person="${id}"]`)
    .getByRole('button', { name: 'follow' })
    .click();
  await expect(page.getByTestId('world')).toHaveAttribute('data-follow', id);
  await expect
    .poll(
      async () => {
        const body = (await bodies(page)).find((other) => other.id === id)!;
        const focus = await drawnNodes(page);
        return focus ? apart(new Vector3(...focus.focus), body.position) : 1e9;
      },
      { timeout: 20_000 },
    )
    .toBeLessThan(50);
  // posed (its motion drawn) once its model is in
  await expect
    .poll(
      async () => (await bodies(page)).find((other) => other.id === id)!.loaded,
      { timeout: 30_000 },
    )
    .toBe(true);
}

const drawnNodes = (page: Page) =>
  page.evaluate<{
    focus: [number, number, number];
    nodes: DrawnNode[];
  } | null>(`window.__pebbleNodes?.drawn() ?? null`);

/**
 * Catches the page's scenes and calls `window.__onRender(scene)` after every frame the renderer draws (browser code as
 * a string: no DOM types here).
 */
const CATCH_SCENE = `
window.__THREE_DEVTOOLS__ = new EventTarget();
window.__scenes = [];
window.__THREE_DEVTOOLS__.addEventListener('observe', ({ detail }) => {
  if (detail.isScene) window.__scenes.push(detail);
  if (detail.isWebGLRenderer) {
    const render = detail.render.bind(detail);
    detail.render = (scene, camera) => {
      render(scene, camera);
      if (window.__onRender && scene.isScene) window.__onRender(scene);
    };
  }
});`;

/** One drawn frame of a body: its clip and pose (hooks) and the lowest of its skinned vertices (world metres). */
interface BodyFrame {
  /** Real ms since the first frame that showed it. */
  t: number;
  clip: string;
  pose: string;
  points: number[][];
}

/**
 * An init script (after CATCH_SCENE) that records a citizen's body in every frame drawn from the first that shows it
 * (the group drawn at its spot holding a visible skinned mesh) for `seconds` into `window.__bodyFrames`: the `lowest`
 * vertices nearest the ground plane under its feet, of every `every`-th vertex. Every frame, so a body that sinks for
 * a moment as it appears can't slip between samples.
 */
const recordBody = (id: string, seconds: number, every = 4, lowest = 40) => `
  (() => {
    const frames = [];
    let body = null;
    let start = 0;
    window.__onRender = (scene) => {
      const hooks = document.querySelector('[data-npc="${id}"]');
      if (!hooks || !hooks.dataset.npcX) return;
      const Vec = scene.position.constructor;
      const spot = new Vec(+hooks.dataset.npcX, +hooks.dataset.npcY, +hooks.dataset.npcZ);
      const where = new Vec();
      if (!body) {
        let best = 0.3;
        scene.traverse((object) => {
          if (!object.isGroup || !object.children.length) return;
          const metres = object.getWorldPosition(where).distanceTo(spot);
          if (metres >= best) return;
          let skinned = false;
          object.traverse((child) => { if (child.isSkinnedMesh && child.visible) skinned = true; });
          if (skinned) { body = object; best = metres; }
        });
        if (!body) return;
        start = performance.now();
      }
      const up = spot.clone().normalize();
      const v = new Vec();
      const points = [];
      body.traverse((mesh) => {
        if (!mesh.isSkinnedMesh || !mesh.visible) return;
        for (let p = mesh; p; p = p.parent) if (!p.visible) return;
        const count = mesh.geometry.attributes.position.count;
        for (let i = 0; i < count; i += ${every}) {
          mesh.getVertexPosition(i, v);
          mesh.localToWorld(v);
          points.push([v.x, v.y, v.z, v.clone().sub(spot).dot(up)]);
        }
      });
      points.sort((a, b) => a[3] - b[3]);
      frames.push({
        t: performance.now() - start,
        clip: hooks.dataset.npcClip ?? '',
        pose: hooks.dataset.npcPosture ?? '',
        points: points.slice(0, ${lowest}).map((point) => point.slice(0, 3)),
      });
      if (performance.now() - start > ${seconds * 1000}) {
        window.__onRender = null;
        window.__bodyFrames = frames;
      }
    };
  })()`;

/** The frames `recordBody` recorded, once it is done. */
async function bodyFrames(page: Page) {
  await page.waitForFunction('window.__bodyFrames', null, { timeout: 60_000 });
  return page.evaluate<BodyFrame[]>('window.__bodyFrames');
}

/** How far (m) the lowest of `points` lies under the drawn ground (negative: all above it). */
const sunk = (points: number[][]) =>
  Math.max(
    ...points.map(([x, y, z]) => {
      const point = new Vector3(x, y, z);
      const direction = point.clone().normalize();
      return R + groundUnder(direction) - point.length();
    }),
  );

/** A fresh page in a context of its own (the project's viewport and base URL): nothing cached. */
async function freshPage(browser: Browser, info: TestInfo) {
  const context = await browser.newContext({
    baseURL: info.project.use.baseURL,
    viewport: info.project.use.viewport,
  });
  return context.newPage();
}

/** Vertices of the time-lapse trails drawn now (the one LineSegments with a colour per vertex). */
const trailed = (page: Page) =>
  page.evaluate<number>(`(() => {
    let vertices = 0;
    for (const scene of window.__scenes)
      scene.traverse((object) => {
        const color = object.isLineSegments && object.geometry.getAttribute('color');
        if (color && color.itemSize === 4 && object.visible) vertices += object.geometry.drawRange.count;
      });
    return vertices;
  })()`);

/** The ids that moved in a trace. */
const movers = (trace: Trace, metres = 0.01) =>
  new Set(
    trace
      .at(-1)!
      .bodies.filter((body) => {
        const first = trace[0].bodies.find((other) => other.id === body.id)!;
        return shown(body) && body.position.distanceTo(first.position) > metres;
      })
      .map((body) => body.id),
  );

test.describe('every drawn body over 150 s at ×1, then at ×10, ×60 and ×600', () => {
  /** One trace per clock rate, and the trail vertices drawn at its end. */
  const runs: { rate: number; trace: Trace; trail: number }[] = [];
  const errors: string[] = [];

  test.beforeAll(async ({ browser }, info) => {
    test.setTimeout(420_000);
    const page = await freshPage(browser, info);
    await page.addInitScript({ content: CATCH_SCENE });
    const world = await openReal(page, errors);
    const clock = await engineClock(page);
    if (clock.paused) return; // the tests skip
    try {
      for (const [rate, seconds] of [
        [1, 150],
        [10, 30],
        [60, 20],
        [600, 10],
      ]) {
        if (rate !== 1 || clock.speed !== 1) {
          await setSpeed(page, rate);
          // the page takes the new speed with the next frame (at ×1 that is the speed change's own frame)
          const tick = Number(await world.getAttribute('data-live-tick'));
          if (rate > 1)
            await expect
              .poll(
                async () => Number(await world.getAttribute('data-live-tick')),
                { timeout: 10_000 },
              )
              .toBeGreaterThan(tick);
          await page.waitForTimeout(2_000);
        }
        const trace = await traceFor(page, seconds);
        runs.push({ rate, trace, trail: await trailed(page) });
      }
    } finally {
      await setSpeed(page, clock.speed);
      await page.context().close();
    }
  });

  test.beforeEach(() => {
    test.skip(runs.length === 0, 'the engine is paused');
    for (const { rate, trace, trail } of runs)
      test.info().annotations.push({
        type: `trace ×${rate}`,
        description: `${trace.length} refreshes, ${movers(trace).size} moved, fastest ${jumps(trace, rate).fastest.toFixed(1)} m/s, ${trail} trail vertices`,
      });
  });

  test('no two drawn bodies come within 0.5 m of each other, walking or not, at any clock rate', () => {
    expect(runs.map(({ rate }) => rate)).toEqual([1, 10, 60, 600]);
    expect(errors).toEqual([]);
    const found = runs.flatMap(({ rate, trace }) =>
      overlaps(trace).map((pair) => ({ ...pair, rate })),
    );
    // at ×10 and up a walker brushing past someone (but not through them) is a known defect; anything else fails as it is
    const brushing = (pair: (typeof found)[number]) =>
      pair.rate >= 10 && pair.walker && pair.metres >= THROUGH_M;
    const words = found.map((pair) => `×${pair.rate} ${pair.words}`);
    if (found.length > 0 && found.every(brushing))
      test.fail(true, `issue #${TIME_LAPSE_BRUSH_ISSUE}: ${words.join('; ')}`);
    expect(words).toEqual([]);
  });

  test('at ×1 no drawn body moves further between two refreshes than a run covers', () => {
    const { trace } = runs[0];
    test.skip(movers(trace).size === 0, 'nobody moved at ×1 (all asleep?)');
    expect(jumps(trace, 1).found).toEqual([]);
  });

  test('in time-lapse nobody teleports, and walkers drag trails at ×60 and ×600 but not at ×10', () => {
    for (const { rate, trace, trail } of runs.slice(1)) {
      expect.soft(jumps(trace, rate).found, `×${rate} teleports`).toEqual([]);
      if (rate === 10) expect.soft(trail, '×10 trails').toBe(0);
      else if (movers(trace, 5).size > 0)
        expect.soft(trail, `×${rate} trails`).toBeGreaterThan(0);
    }
  });

  test('every resting, seated or sleeping body rests on a drawn seat, log seat, stool or mat', () => {
    const found = runs.flatMap(({ rate, trace }) =>
      restingOnNothing(trace).map((rester) => ({ ...rester, rate })),
    );
    // known defects: resting still on bare ground away from any seat; in time-lapse, a rest pose drawn while the body
    // still slides along its walk. Anything else fails as it is
    const onTheGround = ({ body, moving }: (typeof found)[number]) =>
      body.activity === 'resting' && body.pose === 'sitting' && !moving;
    const gliding = ({ rate, moving }: (typeof found)[number]) =>
      isTimeLapse(rate) && moving;
    const words = found.map(({ rate, words }) => `×${rate} ${words}`);
    if (
      found.length > 0 &&
      found.every((rester) => onTheGround(rester) || gliding(rester))
    )
      test.fail(
        true,
        `issues #${GROUND_RESTS_ISSUE} (on the ground), #${GLIDING_RESTERS_ISSUE} (gliding): ${words.join('; ')}`,
      );
    expect(words).toEqual([]);
  });
});

test('every drawn gatherer, fisher, farmer, miner and feller works within 3.2 m of a drawn node of what it takes', async ({
  page,
}) => {
  const errors: string[] = [];
  await openReal(page, errors);
  // a body far from the camera isn't posed (no motion): follow everyone the feed has at work, then read the drawn motion
  const workers = (await bodies(page)).filter(
    (body) =>
      shown(body) &&
      ['gathering', 'fishing', 'working'].includes(body.activity),
  );
  test.skip(workers.length === 0, 'nobody works now');
  const far: string[] = [];
  const checked: string[] = [];
  for (const { id } of workers) {
    await follow(page, id);
    // the body may have finished meanwhile; a miss must hold for 2 s (a tick's motion and label change together)
    let miss: string | null = null;
    for (let k = 0; k < 2; k++) {
      const body = (await bodies(page)).find((other) => other.id === id)!;
      if (!working(body)) break;
      miss = offWork(body, (await drawnNodes(page))!.nodes);
      if (k === 0) checked.push(`${id} ${body.motion} ${workOf(body)}`);
      if (!miss) break;
      await page.waitForTimeout(2_000);
    }
    if (miss) far.push(miss);
  }
  test.info().annotations.push({
    type: 'workers',
    description: checked.join(', '),
  });
  test.skip(checked.length === 0, 'nobody drawn works at a node now');
  expect(far).toEqual([]);
  expect(errors).toEqual([]);
});

/** Sitters and sleepers (a kneeler's long robe hem lies spread on the ground by design, rest-posture.ts). */
const SITTING_OR_LYING = ['seated', 'sitting', 'sleeping', 'lying'];

/** Polyfork's rest clips: held back on a fresh page so the first sit of the session loads late. */
const REST_CLIPS = /anim-(sitting|sit-down|lying)[^/]*\.json/i;
const CLIP_DELAY_MS = 1_500;
/** Real seconds a body is recorded from its first frame: its clips come in, then a last second settled. */
const RECORD_S = 4;

test('no vertex of a drawn sitter or sleeper sinks more than 3 cm under the ground, even while its first rest clip loads', async ({
  page,
  browser,
}) => {
  const errors: string[] = [];
  await openReal(page, errors);
  const restingNow = (await bodies(page)).filter(
    (body) => shown(body) && SITTING_OR_LYING.includes(body.pose),
  );
  test.skip(restingNow.length === 0, 'nobody sits or lies now');
  /** Sunk once settled (its last second) and sunk only while it appears (before that). */
  const settled: string[] = [];
  const appearing: string[] = [];
  const probed: string[] = [];
  for (const { id } of restingNow.slice(0, 6)) {
    // a fresh page: the body appears with its clips loading late (the rest-pose lift once sank a first sitter 0.34 m)
    const fresh = await freshPage(browser, test.info());
    await fresh.addInitScript({
      content: CATCH_SCENE + recordBody(id, RECORD_S),
    });
    await fresh.route(REST_CLIPS, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, CLIP_DELAY_MS));
      await route.continue();
    });
    const freshErrors: string[] = [];
    await openReal(fresh, freshErrors, `?follow=${id}`);
    const drawn = (await bodyFrames(fresh)).filter(
      (frame) => SITTING_OR_LYING.includes(frame.pose) && frame.points.length,
    );
    expect(drawn.length, `${id} frames`).toBeGreaterThan(30);
    const worstOf = (frames: BodyFrame[]) =>
      frames
        .map((frame) => ({ frame, depth: sunk(frame.points) }))
        .sort((a, b) => b.depth - a.depth)[0];
    const late = (frame: BodyFrame) => frame.t > (RECORD_S - 1) * 1000;
    const last = worstOf(drawn.filter(late));
    const first = worstOf(drawn.filter((frame) => !late(frame)));
    const word = ({ frame, depth }: typeof first) =>
      `${depth.toFixed(3)} m at ${(frame.t / 1000).toFixed(2)} s (${frame.clip || 'no clip'})`;
    probed.push(
      `${id} ${drawn.at(-1)!.pose}: deepest appearing ${word(first)}, settled ${word(last)}`,
    );
    if (last.depth > SUNK_M) settled.push(`${id}: ${word(last)}`);
    if (first.depth > SUNK_M) appearing.push(`${id}: ${word(first)}`);
    expect(freshErrors).toEqual([]);
    await fresh.context().close();
  }
  test.info().annotations.push({
    type: 'probed (depth under the ground)',
    description: probed.join('; '),
  });
  expect(probed.length).toBeGreaterThan(0);
  expect.soft(settled, 'sunk once settled').toEqual([]);
  // sinking only while a body appears is a known defect; sinking once settled fails as it is
  if (settled.length === 0 && appearing.length > 0)
    test.fail(true, `issue #${APPEARING_SINK_ISSUE}: ${appearing.join('; ')}`);
  expect(appearing, 'sunk while appearing').toEqual([]);
  expect(errors).toEqual([]);
});

/** The market plaza (town chart, metres): 22 bodies on a 1.5 m grid round its middle, the camera south of it. */
const PLAZA = { x: 20, z: 50 };

test('the town plaza at noon with all 22 citizens in view stays under 300 draw calls (fps reported)', async ({
  page,
}) => {
  const spot = (k: number) =>
    town.mapping
      .toWorld(
        PLAZA.x + ((k % 6) - 2.5) * 1.5,
        0,
        PLAZA.z + (Math.floor(k / 6) - 1.5) * 1.5,
        new Vector3(),
      )
      .normalize()
      .toArray();
  // the real feed, every citizen moved onto the plaza standing about at noon
  const crowd = (citizens: EntitiesView['citizens']) =>
    citizens.forEach((citizen, k) => {
      citizen.position.unit = spot(k);
      citizen.route = [];
      citizen.speed_mps = 0;
      citizen.activity = 'idle';
      citizen.motion = 'idle';
      citizen.posture = 'standing';
      citizen.slot_heading = null;
      citizen.heading_deg = 0;
    });
  await page.route(/\/api\/v1\/entities$/, async (route) => {
    const response = await route.fetch();
    const view = (await response.json()) as EntitiesView;
    crowd(view.citizens);
    await route.fulfill({ response, json: { ...view, time: '12:00' } });
  });
  await page.routeWebSocket(/\/api\/v1\/live$/, (socket) => {
    const server = socket.connectToServer();
    server.onMessage((message) => {
      const frame = JSON.parse(String(message)) as LiveState;
      if (!Array.isArray(frame.citizens)) return socket.send(message);
      crowd(frame.citizens);
      socket.send(JSON.stringify({ ...frame, time: '12:00' }));
    });
    socket.onMessage((message) => server.send(message));
  });
  const errors: string[] = [];
  const from = town.mapping
    .toWorld(PLAZA.x, 0, PLAZA.z + 14, new Vector3())
    .normalize();
  const middle = town.mapping
    .toWorld(PLAZA.x, 0, PLAZA.z, new Vector3())
    .normalize();
  const world = await openReal(
    page,
    errors,
    `?at=${atParam(from, middle.clone().sub(from))}`,
  );
  await expect
    .poll(
      async () => (await bodies(page)).filter((body) => body.loaded).length,
      {
        timeout: 30_000,
      },
    )
    .toBe(22);
  const drawn = await bodies(page);
  expect(
    drawn.filter((body) => apart(body.position, middle) > 6).map((b) => b.id),
  ).toEqual([]);
  const camera = await viewOf(page, world);
  expect(
    inView(
      camera,
      drawn.map((body) => body.position),
    ),
  ).toBe(true);
  await page.waitForTimeout(3_000); // the draw calls are sampled once a second
  const calls = Number(await world.getAttribute('data-draw-calls'));
  const fps = await page.evaluate<number>(`new Promise((done) => {
    const start = performance.now();
    let frames = 0;
    const frame = (now) => {
      frames += 1;
      if (now - start < 3000) requestAnimationFrame(frame);
      else done((frames * 1000) / (now - start));
    };
    requestAnimationFrame(frame);
  })`);
  // fps is only reported: headless Chrome's frame rate says little about a real browser's (vsync, GPU)
  test.info().annotations.push({
    type: 'plaza',
    description: `${calls} draw calls, ${fps.toFixed(0)} fps (headless)`,
  });
  expect(calls).toBeGreaterThan(0);
  expect(calls).toBeLessThan(DRAW_CALL_BUDGET);
  expect(errors).toEqual([]);
});
