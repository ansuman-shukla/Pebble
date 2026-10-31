import {
  expect,
  type Page,
  type PlaywrightWorkerArgs,
  test,
} from '@playwright/test';
import { type BufferGeometry, Vector3 } from 'three';

import type { TownView, WorldView } from '../../src/lib/client/types.gen';
import {
  buildWalkWorld,
  isWater,
  type Point,
} from '../../src/lib/world/collision';
import {
  anchorMapping,
  buildTerrain,
  decodeWorld,
  latLonFromDirection,
  type SiteMapping,
  tangentFrame,
} from '../../src/lib/world/globe';
import {
  buildMarks,
  globeMarkGround,
  CAMP_WORN_RADIUS,
  MARK_KINDS,
  type MarkGround,
  type MarkKind,
  type PlanetMarks,
  planetMarks,
  ROUTE_WIDTH,
  routeChains,
  SCORCH_RADIUS,
} from '../../src/lib/world/ground-marks';
import { clipWater, TOWN_WATER_Y } from '../../src/lib/world/ground-shape';
import { FLAT_MAPPING } from '../../src/lib/world/local-mapping';
import {
  type RiverLayout,
  riverLayout,
  streamChannels,
} from '../../src/lib/world/river-courses';
import { TOWN_URL, WORLD_URL } from './explore-helpers';
import { openGlobe, stillWorld } from './globe-helpers';

/*
 * Ground marks (bible §5.1): the network's roads and paths as ribbons through their cells, junction patches, camp
 * ground, work spots and the town's areas, all in one mesh whose vertices tell the material their kind, how far in
 * from the border they lie and how far from the middle line; then the mesh and its pixels on the globe.
 */

/** The town's ground disc (globe-page.tsx TOWN_GROUND_RADIUS). */
const TOWN_GROUND_RADIUS = 225;

const kindOf = (value: number) => MARK_KINDS[Math.round(value)];

interface MarkVertex {
  position: Vector3;
  kind: MarkKind;
  edge: number;
  across: number;
  half: number;
}

/** Every vertex of a marks mesh that some triangle uses. */
function vertices(geometry: BufferGeometry): MarkVertex[] {
  const position = geometry.getAttribute('position');
  const mark = geometry.getAttribute('mark');
  const used = new Set(geometry.index!.array);
  return [...used].map((i) => ({
    position: new Vector3().fromBufferAttribute(position, i),
    kind: kindOf(mark.getX(i)),
    edge: mark.getY(i),
    across: mark.getZ(i),
    half: mark.getW(i),
  }));
}

/** The served world and town with their marks laid and draped as the globe draws them. */
async function loadWorld(playwright: PlaywrightWorkerArgs['playwright']) {
  const api = await playwright.request.newContext();
  const [world, townAnswer] = await Promise.all([
    api.get(WORLD_URL),
    api.get(TOWN_URL),
  ]);
  const view = (await world.json()) as WorldView;
  const town = (await townAnswer.json()) as TownView;
  await api.dispose();
  const globe = decodeWorld(view);
  const terrain = buildTerrain(globe);
  const site = view.sites.find((candidate) => candidate.kind === 'town')!;
  const height = site.anchor.height_m;
  const mapping = anchorMapping(site.anchor, globe.radius);
  const rivers = riverLayout(
    terrain,
    view.rivers.map((river) => river.cells),
    {
      hole: {
        up: new Vector3(...site.anchor.position),
        angle: Math.atan(TOWN_GROUND_RADIUS / (globe.radius + height)),
      },
      channels: streamChannels(town.water, mapping, height, TOWN_WATER_Y),
    },
  );
  const marks = planetMarks({
    globe,
    places: view.places,
    sites: view.sites,
    rivers,
  });
  const water = clipWater(town.water, TOWN_GROUND_RADIUS);
  const ground = globeMarkGround({
    terrain,
    rivers,
    town: {
      mapping,
      groundRadius: TOWN_GROUND_RADIUS,
      height,
      water,
      areas: town.areas,
    },
  });
  const geometry = buildMarks({ planet: { marks, ground } });
  return {
    view,
    town,
    terrain,
    mapping,
    rivers,
    marks,
    ground,
    geometry,
    water,
  };
}

test.describe('route chains', () => {
  test('each step is drawn once, a road over a path; chains break at junctions and kind changes', () => {
    const { chains, ends } = routeChains([
      { kind: 'road', cells: [1, 2, 3, 4] },
      // shares the step 2-3 with the road and branches off at 3
      { kind: 'path', cells: [2, 3, 5, 6] },
      // the road goes on as a path from 4
      { kind: 'path', cells: [4, 7] },
      // a loop with no junction on it
      { kind: 'path', cells: [10, 11, 12, 10] },
    ]);
    const drawn = chains
      .map(
        ({ cells, kind, closed }) =>
          `${kind}:${cells.join('-')}${closed ? ':closed' : ''}`,
      )
      .sort();
    const reversed = (chain: string) =>
      chain.replace(/[\d-]+/, (cells) => cells.split('-').reverse().join('-'));
    const expected = ['road:1-2-3', 'road:3-4', 'path:3-5-6', 'path:4-7'];
    for (const chain of expected)
      expect(
        drawn.includes(chain) || drawn.includes(reversed(chain)),
        chain,
      ).toBe(true);
    expect(drawn.filter((chain) => chain.endsWith(':closed'))).toHaveLength(1);
    expect(drawn).toHaveLength(5);
    expect(Object.fromEntries(ends)).toEqual({
      1: 'road',
      3: 'road',
      4: 'road',
      6: 'path',
      7: 'path',
    });
  });
});

test.describe('ground marks of the real world', () => {
  let view: WorldView;
  let town: TownView;
  let mapping: SiteMapping;
  let rivers: RiverLayout;
  let marks: PlanetMarks;
  let ground: MarkGround;
  let geometry: BufferGeometry;
  let water: { polygon: Point[]; holes?: Point[][] }[];

  test.beforeAll(async ({ playwright }) => {
    ({ view, town, mapping, rivers, marks, ground, geometry, water } =
      await loadWorld(playwright));
  });

  test('a road is 3 m wide and a path 1.5 m, edge 1 on the middle line and 0 at the borders', () => {
    const marked = vertices(geometry);
    for (const kind of ['road', 'path'] as const) {
      const ribbon = marked.filter(
        (vertex) =>
          vertex.kind === kind && vertex.half === ROUTE_WIDTH[kind] / 2,
      );
      expect(ribbon.length).toBeGreaterThan(1000);
      const middle = ribbon.filter((vertex) => vertex.across === 0);
      const borders = ribbon.filter(
        (vertex) => Math.abs(vertex.across) === ROUTE_WIDTH[kind] / 2,
      );
      expect(middle.length + borders.length).toBe(ribbon.length);
      expect(borders.every((vertex) => vertex.edge === 0)).toBe(true);
      // the middle line is whole except over the half width where a ribbon ends (under a junction or a bridge)
      const whole = middle.filter((vertex) => vertex.edge === 1).length;
      expect(whole / middle.length).toBeGreaterThan(0.9);
      expect(
        middle.every((vertex) => vertex.edge >= 0 && vertex.edge <= 1),
      ).toBe(true);
    }
  });

  test('every cell of every road and path lies on a ribbon at least as wide as its own', () => {
    const radius = view.radius_m;
    const positions = decodeWorld(view).positions;
    // ribbon samples in 2 m buckets, with the widest ribbon through each
    const key = (point: Vector3, dx = 0, dy = 0, dz = 0) =>
      [point.x, point.y, point.z]
        .map((v, k) => Math.floor((v * radius) / 2) + [dx, dy, dz][k])
        .join(',');
    const buckets = new Map<string, { point: Vector3; width: number }[]>();
    for (const ribbon of marks.ribbons)
      for (const point of ribbon.points) {
        const bucket = buckets.get(key(point)) ?? [];
        bucket.push({ point, width: ribbon.width });
        buckets.set(key(point), bucket);
      }
    const nearest = (point: Vector3, width: number) => {
      let best = Infinity;
      for (const dx of [-1, 0, 1])
        for (const dy of [-1, 0, 1])
          for (const dz of [-1, 0, 1])
            for (const sample of buckets.get(key(point, dx, dy, dz)) ?? [])
              if (sample.width >= width)
                best = Math.min(best, sample.point.angleTo(point) * radius);
      return best;
    };
    const missed: string[] = [];
    for (const road of view.places.roads) {
      const cells = road.cells.map((cell) =>
        new Vector3().fromArray(positions, cell * 3),
      );
      const lead = (road.lead ?? []).map((point) => new Vector3(...point));
      for (const point of [...lead, ...cells]) {
        const distance = nearest(point, ROUTE_WIDTH[road.kind]);
        if (distance > 1) missed.push(`${road.id} ${distance.toFixed(1)} m`);
      }
    }
    expect(missed).toEqual([]);
  });

  test('no mark lies on a drawn river: roads and paths cross on bridges resting on both banks', () => {
    const radius = view.radius_m;
    /** Metres from a unit direction to the nearest drawn river's water (< 0 on it). */
    const fromWater = (at: Vector3) => {
      const point = at.clone().multiplyScalar(radius);
      let best = Infinity;
      for (const { points } of rivers.runs)
        for (let j = 1; j < points.length; j++) {
          const a = points[j - 1].direction.clone().multiplyScalar(radius);
          if (a.distanceTo(point) > 30) continue;
          const b = points[j].direction.clone().multiplyScalar(radius).sub(a);
          const t = Math.min(
            1,
            Math.max(0, point.clone().sub(a).dot(b) / b.lengthSq()),
          );
          const width =
            points[j - 1].width + (points[j].width - points[j - 1].width) * t;
          best = Math.min(
            best,
            a.addScaledVector(b, t).distanceTo(point) - width / 2,
          );
        }
      return best;
    };
    // a ribbon's middle never; its border only where it grazes the water, by less than its half width
    const wet = vertices(geometry).filter((vertex) => {
      const gap = fromWater(vertex.position.clone().normalize());
      const ribbon =
        (vertex.kind === 'road' || vertex.kind === 'path') &&
        vertex.across !== 0;
      return ribbon ? gap < -vertex.half : gap < 0;
    });
    expect(wet.map((vertex) => vertex.kind)).toEqual([]);
    expect(marks.bridges.length).toBeGreaterThanOrEqual(10);
    const end = new Vector3();
    for (const bridge of marks.bridges) {
      expect(fromWater(bridge.centre)).toBeLessThan(0);
      for (const side of [-1, 1]) {
        end
          .copy(bridge.centre)
          .multiplyScalar(radius)
          .addScaledVector(bridge.along, (side * bridge.length) / 2)
          .normalize();
        // on a bank, or where the ribbon ends at a junction on the water (the next ribbon has its own bridge)
        const junction = marks.patches.some(
          (patch) =>
            (patch.kind === 'road' || patch.kind === 'path') &&
            patch.centre.angleTo(end) * radius < 4,
        );
        expect(fromWater(end) > 0 || junction).toBe(true);
      }
    }
    // every crossing the world routes over a river cell is drawn as a bridge
    for (const bridge of view.places.bridges) {
      if (bridge.cell === null) continue;
      const at = new Vector3(...bridge.position);
      const nearest = Math.min(
        ...marks.bridges.map((span) => span.centre.angleTo(at) * radius),
      );
      expect(nearest, bridge.id).toBeLessThan(30);
    }
  });

  test('camps wear a 10 m disc round the fire, a scorch at it and a path from each shelter', () => {
    const camps = view.sites.filter((site) => site.kind === 'camp');
    expect(camps.length).toBeGreaterThanOrEqual(2);
    for (const camp of camps) {
      const campMapping = anchorMapping(camp.anchor, view.radius_m);
      const fire = camp.placements!.find(
        (placement) => placement.kind === 'fire_pit',
      )!;
      const hearth = campMapping
        .toWorld(fire.x, 0, fire.z, new Vector3())
        .normalize();
      const at = (kind: MarkKind, radius: number) =>
        marks.patches.filter(
          (patch) =>
            patch.kind === kind &&
            patch.radius === radius &&
            patch.centre.angleTo(hearth) * view.radius_m < 0.01,
        );
      expect(at('worn', CAMP_WORN_RADIUS)).toHaveLength(1);
      expect(at('scorch', SCORCH_RADIUS)).toHaveLength(1);
      const shelters = camp.placements!.filter(
        (placement) => placement.kind === 'lean_to',
      );
      for (const shelter of shelters) {
        const door = campMapping
          .toWorld(shelter.x, 0, shelter.z, new Vector3())
          .normalize();
        const paths = marks.ribbons.filter(
          (ribbon) =>
            ribbon.kind === 'path' &&
            ribbon.points[0].angleTo(door) * view.radius_m < 0.01 &&
            ribbon.points.at(-1)!.angleTo(hearth) * view.radius_m < 0.01,
        );
        expect(paths).toHaveLength(1);
      }
    }
  });

  test('work spots wear patches: worn at the water, dug at flint and obsidian, iron sand at its bar', () => {
    const expected: Record<string, MarkKind> = {
      fishing_spot: 'worn',
      waterhole: 'worn',
      flint_seam: 'dug',
      obsidian_field: 'dug',
      iron_sand_bar: 'iron_sand',
    };
    const spots = view.places.features.filter(
      (feature) => feature.kind in expected,
    );
    expect(spots.length).toBeGreaterThan(10);
    for (const spot of spots) {
      const at = new Vector3(...spot.position);
      expect(
        marks.patches.some(
          (patch) =>
            patch.kind === expected[spot.kind] &&
            patch.centre.angleTo(at) < 1e-9,
        ),
        spot.id,
      ).toBe(true);
    }
  });

  test("no mark lies on the town's water", () => {
    const wet = buildWalkWorld([], water, new Map());
    const local = new Vector3();
    // a ribbon's border vertices may reach over a bank by its half width: count points deeper in than that
    const deep = ([x, z]: Point) =>
      [
        [0, 0],
        [1.5, 0],
        [-1.5, 0],
        [0, 1.5],
        [0, -1.5],
      ].every(([dx, dz]) => isWater(wet, [x + dx, z + dz]));
    const marked = vertices(
      buildMarks({
        areas: { areas: town.areas, mapping },
        planet: { marks, ground },
      }),
    );
    const onWater = marked.filter(({ position }) => {
      mapping.toLocal(position, local);
      return (
        Math.hypot(local.x, local.z) < TOWN_GROUND_RADIUS &&
        deep([local.x, local.z])
      );
    });
    expect(onWater).toEqual([]);
    // the west road's lead crosses the mill stream: its ribbon stops at the banks
    expect(
      marked.some(({ position }) => {
        mapping.toLocal(position, local);
        return Math.abs(local.z - 104) < 1 && local.x < -160 && local.x > -170;
      }),
    ).toBe(true);
  });

  test('town areas: each kind its mark, edge 0 on the outline and 1 a band inside', () => {
    const marked = vertices(
      buildMarks({ areas: { areas: town.areas, mapping: FLAT_MAPPING } }),
    );
    const kinds = new Set(marked.map((vertex) => vertex.kind));
    expect([...kinds].sort()).toEqual([
      'farmland',
      'packed',
      'paving',
      'raked',
      'road',
    ]);
    const plaza = town.areas.find((area) => area.kind === 'plaza')!;
    const [minX, maxX] = [
      Math.min(...plaza.polygon.map(([x]) => x)),
      Math.max(...plaza.polygon.map(([x]) => x)),
    ];
    const [minZ, maxZ] = [
      Math.min(...plaza.polygon.map(([, z]) => z)),
      Math.max(...plaza.polygon.map(([, z]) => z)),
    ];
    const paving = marked.filter(
      ({ kind, position }) =>
        kind === 'paving' &&
        position.x >= minX - 1e-6 &&
        position.x <= maxX + 1e-6 &&
        position.z >= minZ - 1e-6 &&
        position.z <= maxZ + 1e-6,
    );
    expect(paving.length).toBeGreaterThan(8);
    for (const { position, edge, half } of paving) {
      const inside = Math.min(
        position.x - minX,
        maxX - position.x,
        position.z - minZ,
        maxZ - position.z,
      );
      expect(edge).toBeCloseTo(Math.min(1, inside / half), 4);
    }
  });
});

/** Catches the scenes and the camera of the page's renderer (browser code as a string: no DOM types here). */
const CATCH_SCENE = `
window.__THREE_DEVTOOLS__ = new EventTarget();
window.__scenes = [];
window.__THREE_DEVTOOLS__.addEventListener('observe', ({ detail }) => {
  if (detail.isScene) window.__scenes.push(detail);
  if (detail.isWebGLRenderer) {
    const render = detail.render.bind(detail);
    detail.render = (scene, camera) => {
      window.__camera = camera;
      render(scene, camera);
    };
  }
});`;

/** Mean sRGB colour (0..255) of the 5×5 pixels round where a world point lands on the canvas. */
const pixelAt = (page: Page, point: Vector3) =>
  page.evaluate<number[] | null>(`(() => {
    const camera = window.__camera;
    const ndc = camera.position.clone().set(${point.x}, ${point.y}, ${point.z}).project(camera);
    const source = document.querySelector('canvas');
    const x = Math.round(((ndc.x + 1) / 2) * source.width);
    const y = Math.round(((1 - ndc.y) / 2) * source.height);
    if (ndc.z > 1 || x < 2 || y < 2 || x > source.width - 3 || y > source.height - 3) return null;
    const canvas = document.createElement('canvas');
    canvas.width = source.width;
    canvas.height = source.height;
    const context = canvas.getContext('2d');
    context.drawImage(source, 0, 0);
    const { data } = context.getImageData(x - 2, y - 2, 5, 5);
    const mean = [0, 0, 0];
    for (let i = 0; i < data.length; i += 4) for (let k = 0; k < 3; k++) mean[k] += data[i + k] / 25;
    return mean;
  })()`);

/** CIELAB of an sRGB colour (0..255, D65). */
function lab([r, g, b]: number[]) {
  const linear = (c: number) => {
    const v = c / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const [lr, lg, lb] = [r, g, b].map(linear);
  const xyz = [
    (0.4124 * lr + 0.3576 * lg + 0.1805 * lb) / 0.95047,
    0.2126 * lr + 0.7152 * lg + 0.0722 * lb,
    (0.0193 * lr + 0.1192 * lg + 0.9505 * lb) / 1.08883,
  ].map((t) =>
    t > 216 / 24389 ? Math.cbrt(t) : ((t * 24389) / 27 + 16) / 116,
  );
  return [116 * xyz[1] - 16, 500 * (xyz[0] - xyz[1]), 200 * (xyz[1] - xyz[2])];
}

const deltaE = (a: number[], b: number[]) => {
  const [p, q] = [lab(a), lab(b)];
  return Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
};

/** Compass bearing (degrees) from one unit direction to another. */
function bearing(from: Vector3, to: Vector3) {
  const { east, north } = tangentFrame(from);
  const toward = to.clone().sub(from);
  return (
    ((Math.atan2(toward.dot(east), toward.dot(north)) * 180) / Math.PI + 360) %
    360
  );
}

test.describe('ground marks on screen', () => {
  test('a road stands out from the grass 5 m off it (ΔE > 10)', async ({
    page,
    playwright,
  }) => {
    test.setTimeout(120_000);
    const { view, terrain, marks, ground } = await loadWorld(playwright);
    const radius = view.radius_m;
    const town = new Vector3(
      ...view.sites.find((site) => site.kind === 'town')!.anchor.position,
    );
    const others = (ribbon: (typeof marks.ribbons)[number]) =>
      marks.ribbons
        .filter((other) => other !== ribbon)
        .flatMap((other) => other.points);
    const offset = (from: Vector3, side: Vector3, metres: number) =>
      from
        .clone()
        .multiplyScalar(radius)
        .addScaledVector(side, metres)
        .normalize();
    // a stretch of road out in the grassland, level, with no other mark near it
    let spot: { centre: Vector3; off: Vector3; stand: Vector3 } | null = null;
    for (const ribbon of marks.ribbons.filter(
      (candidate) => candidate.kind === 'road' && candidate.width === 3,
    )) {
      const near = others(ribbon);
      for (let i = 30; i < ribbon.points.length - 30 && !spot; i += 10) {
        const centre = ribbon.points[i];
        const along = ribbon.points[i + 1].clone().sub(ribbon.points[i - 1]);
        const side = new Vector3().crossVectors(along, centre).normalize();
        const [off, stand] = [
          offset(centre, side, -5),
          offset(centre, side, 14),
        ];
        const heights = [centre, off, stand].map((point) =>
          ground.heightAt(point),
        );
        if (
          centre.angleTo(town) * radius < 400 ||
          view.biome_names[terrain.biomeAt(centre)] !== 'grassland' ||
          heights.some((height) => height === null) ||
          Math.max(...(heights as number[])) -
            Math.min(...(heights as number[])) >
            1.5 ||
          marks.bridges.some(
            (bridge) => bridge.centre.angleTo(centre) * radius < 30,
          ) ||
          near.some((point) => point.angleTo(centre) * radius < 15) ||
          marks.patches.some(
            (patch) =>
              patch.centre.angleTo(centre) * radius < patch.radius + 10,
          )
        )
          continue;
        spot = { centre, off, stand };
      }
      if (spot) break;
    }
    expect(spot).not.toBeNull();
    const { centre, off, stand } = spot!;
    const { lat, lon } = latLonFromDirection(stand);
    await page.addInitScript({ content: CATCH_SCENE });
    await stillWorld(page);
    const errors: string[] = [];
    const world = await openGlobe(
      page,
      errors,
      `?at=${lat.toFixed(5)},${lon.toFixed(5)},${bearing(stand, centre).toFixed(1)}&time=12:00`,
    );
    // the camera flies in behind the player first
    await expect(world).toHaveAttribute('data-camera-flying', 'false', {
      timeout: 10_000,
    });
    await page.waitForTimeout(1000);
    const at = (point: Vector3) =>
      point.clone().multiplyScalar(radius + ground.heightAt(point)! + 0.05);
    const [road, grass] = await Promise.all([
      pixelAt(page, at(centre)),
      pixelAt(page, at(off)),
    ]);
    expect(road).not.toBeNull();
    expect(grass).not.toBeNull();
    expect(deltaE(road!, grass!)).toBeGreaterThan(10);
    expect(errors).toEqual([]);
  });

  test('the world draws its ground marks in one mesh: town areas, roads, paths and camps', async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const errors: string[] = [];
    await page.addInitScript({ content: CATCH_SCENE });
    await stillWorld(page);
    await openGlobe(page, errors, '?time=12:00');
    const kinds = await page.evaluate<string[][]>(`(() => {
      const found = [];
      for (const scene of window.__scenes)
        scene.traverse((object) => {
          const mark = object.isMesh && object.geometry.getAttribute('mark');
          if (!mark) return;
          const kinds = new Set();
          for (let i = 0; i < mark.count; i++) kinds.add(Math.round(mark.getX(i)));
          found.push([...kinds].sort((a, b) => a - b));
        });
      return found;
    })()`);
    // one mesh (the town's five area kinds used to be five), holding every kind the world lays
    expect(kinds).toHaveLength(1);
    expect(kinds[0].map((kind) => MARK_KINDS[Number(kind)]).sort()).toEqual([
      'dug',
      'farmland',
      'iron_sand',
      'packed',
      'path',
      'paving',
      'raked',
      'road',
      'scorch',
      'worn',
    ]);
    expect(errors).toEqual([]);
  });
});
