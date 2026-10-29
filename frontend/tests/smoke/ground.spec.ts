import { expect, type Page, test } from '@playwright/test';
import { type BufferGeometry, Vector3 } from 'three';

import type { WorldView } from '../../src/lib/client/types.gen';
import {
  buildTerrain,
  decodeWorld,
  type GlobeTerrain,
  WATER_SURFACE,
} from '../../src/lib/world/globe';
import {
  type GroundPoint,
  groundWeights,
  quantizeWeights,
  terrainGeometry,
} from '../../src/lib/world/globe-mesh';
import {
  GROUND_LAYERS,
  type GroundLayer,
  type GroundWeights,
  groundBlendGlsl,
  groundQuality,
  weightsArray,
} from '../../src/lib/world/ground-shader';
import type { GroundBreakup } from '../../src/lib/world/ground-style';
import { openGlobe, WORLD_URL } from './globe-helpers';

/*
 * The ground shader (bible §5.1): 8 layer weights per terrain vertex that follow the rules (rock on steep slopes,
 * sand on beaches, snow in snow biomes, forest floor in forests, mud on lake beds), and a street-level view that
 * shows patches of dirt and gravel in the grass instead of a flat green plane (its frame cost:
 * ground-budget.spec.ts).
 */

const layer = (name: GroundLayer) => GROUND_LAYERS.indexOf(name);
const flat = new Float64Array(GROUND_LAYERS.length);

const claims = (weights: Partial<Record<GroundLayer, number>>) =>
  GROUND_LAYERS.map((name) => weights[name] ?? 0);

/** Weights of a ground point with one biome's claims (the mesh blends them by area). */
function weigh(point: Partial<GroundPoint> & { claims?: number[] }) {
  groundWeights(
    {
      claims: point.claims ?? claims({}),
      slope: point.slope ?? 0,
      height: point.height ?? 20,
      lakeLevel: point.lakeLevel ?? Infinity,
    },
    flat,
  );
  return Object.fromEntries(
    GROUND_LAYERS.map((name, k) => [name, flat[k]]),
  ) as Record<GroundLayer, number>;
}

const sum = (weights: Record<GroundLayer, number>) =>
  Object.values(weights).reduce((total, value) => total + value, 0);

test.describe('ground layer rules', () => {
  test('level grassland is all grass; a 45° slope is rock', () => {
    expect(weigh({}).grass).toBe(1);
    const steep = weigh({ slope: 45 });
    expect(steep.rock).toBe(1);
    expect(steep.grass).toBe(0);
    const between = weigh({ slope: 34 });
    expect(between.rock).toBeCloseTo(0.5, 6);
    expect(sum(between)).toBeCloseTo(1, 6);
    expect(weigh({ slope: 28 }).rock).toBe(0);
    expect(weigh({ slope: 40 }).rock).toBe(1);
  });

  test('biomes lay their own layer and share the rest with grass', () => {
    const forest = weigh({ claims: claims({ forest_floor: 0.7 }) });
    expect(forest.forest_floor).toBeCloseTo(0.7, 6);
    expect(forest.grass).toBeCloseTo(0.3, 6);
    const savanna = weigh({ claims: claims({ dirt: 0.3 }) });
    expect(savanna.dirt).toBeCloseTo(0.3, 6);
    const tundra = weigh({ claims: claims({ gravel: 0.4 }) });
    expect(tundra.gravel).toBeCloseTo(0.4, 6);
    const wetland = weigh({ claims: claims({ mud: 0.6 }) });
    expect(wetland.mud).toBeCloseTo(0.6, 6);
    const mountain = weigh({ claims: claims({ rock: 0.5 }) });
    expect(mountain.rock).toBeCloseTo(0.5, 6);
    expect(mountain.grass).toBeCloseTo(0.5, 6);
    // a steep forest slope is rock, not leaf litter
    const cliff = weigh({ claims: claims({ forest_floor: 0.7 }), slope: 50 });
    expect(cliff.rock).toBe(1);
    expect(cliff.forest_floor).toBe(0);
  });

  test('snow covers snow biomes and high ground, and slides off steep slopes onto rock', () => {
    expect(weigh({ claims: claims({ snow: 1 }) }).snow).toBe(1);
    expect(weigh({ height: 260 }).snow).toBe(1);
    expect(weigh({ height: 240 }).snow).toBeCloseTo(0.5, 6);
    expect(weigh({ height: 215 }).snow).toBe(0);
    const steep = weigh({ claims: claims({ snow: 1 }), slope: 45 });
    expect(steep.rock).toBeGreaterThanOrEqual(0.6);
    expect(steep.snow).toBeGreaterThan(0);
    expect(sum(steep)).toBeCloseTo(1, 6);
    expect(weigh({ claims: claims({ snow: 1 }), slope: 55 }).snow).toBe(0);
  });

  test('sand lines the sea and the lakes; lake beds are mud, the sea floor sand then mud', () => {
    expect(weigh({ height: WATER_SURFACE + 0.001 }).sand).toBeCloseTo(1, 2);
    expect(weigh({ height: 1.35 }).sand).toBeCloseTo(0.5, 1);
    expect(weigh({ height: 3 }).sand).toBe(0);
    expect(weigh({ claims: claims({ sand: 0.6 }), height: 5 }).sand).toBe(0.6);
    expect(weigh({ height: 30.75, lakeLevel: 30 }).sand).toBeCloseTo(0.5, 6);
    expect(weigh({ height: 32, lakeLevel: 30 }).sand).toBe(0);
    expect(weigh({ height: 30.01, lakeLevel: 30 }).mud).toBe(1);
    expect(weigh({ height: -1 }).sand).toBe(1);
    // just under the water surface the sea floor rule wins over any biome
    expect(weigh({ claims: claims({ snow: 1 }), height: 0.1 }).sand).toBe(1);
    expect(weigh({ height: -10 }).mud).toBe(1);
    const shelf = weigh({ height: -4.75 });
    expect(shelf.sand).toBeCloseTo(0.5, 6);
    expect(shelf.mud).toBeCloseTo(0.5, 6);
  });

  test('weights pack into bytes summing to 255, the largest remainders rounding up', () => {
    const bytes = new Uint8Array(4);
    quantizeWeights([0.1, 0.45, 0.45, 0], bytes, 0);
    expect([...bytes]).toEqual([25, 115, 115, 0]);
    quantizeWeights([0.2, 0.3, 0.1, 0.4], bytes, 0);
    expect([...bytes]).toEqual([51, 77, 25, 102]);
  });

  test('constant weights put the unnamed rest on grass', () => {
    expect(weightsArray({})).toEqual([1, 0, 0, 0, 0, 0, 0, 0]);
    expect(weightsArray({ dirt: 0.25 })).toEqual([
      0.75, 0, 0.25, 0, 0, 0, 0, 0,
    ]);
    expect(weightsArray({ grass: 0.5, rock: 0.5 })).toEqual([
      0.5, 0, 0, 0, 0, 0.5, 0, 0,
    ]);
  });

  test('pages pick the quality with ?ground=', () => {
    expect(groundQuality('?ground=flat')).toBe('flat');
    expect(groundQuality('?mock=1&ground=low')).toBe('low');
    expect(groundQuality('?ground=best')).toBe('full');
    expect(groundQuality('')).toBe('full');
  });
});

test.describe('ground layers of the real world', () => {
  let view: WorldView;
  let terrain: GlobeTerrain;
  let mesh: BufferGeometry;

  test.beforeAll(async ({ playwright }) => {
    const api = await playwright.request.newContext();
    const response = await api.get(WORLD_URL);
    expect(response.ok()).toBe(true);
    view = (await response.json()) as WorldView;
    await api.dispose();
    terrain = buildTerrain(decodeWorld(view));
    mesh = terrainGeometry(terrain, view.biome_names);
  });

  /** The 8 weights of vertex v as read by the shader (RGBA8, 0..1). */
  function weightsOf(v: number) {
    const a = mesh.getAttribute('ground0');
    const b = mesh.getAttribute('ground1');
    return [
      a.getX(v),
      a.getY(v),
      a.getZ(v),
      a.getW(v),
      b.getX(v),
      b.getY(v),
      b.getZ(v),
      b.getW(v),
    ];
  }

  /** Per vertex: the slope (degrees) of the area-weighted normal of the faces around it. */
  function slopes() {
    const position = mesh.getAttribute('position');
    const index = mesh.index!.array;
    const sums = new Float64Array(position.count * 3);
    const [a, b, c] = [0, 0, 0].map(() => new Vector3());
    for (let f = 0; f < index.length; f += 3) {
      a.fromBufferAttribute(position, index[f]);
      b.fromBufferAttribute(position, index[f + 1]).sub(a);
      c.fromBufferAttribute(position, index[f + 2]).sub(a);
      b.cross(c);
      for (let k = 0; k < 3; k++) {
        const v = index[f + k] * 3;
        sums[v] += b.x;
        sums[v + 1] += b.y;
        sums[v + 2] += b.z;
      }
    }
    return Float64Array.from({ length: position.count }, (_, v) => {
      a.fromArray(sums, v * 3).normalize();
      b.fromBufferAttribute(position, v).normalize();
      return (Math.acos(a.dot(b)) * 180) / Math.PI;
    });
  }

  test('every vertex has 8 weights summing to 1', () => {
    const count = mesh.getAttribute('position').count;
    let worst = 0;
    for (let v = 0; v < count; v++)
      worst = Math.max(
        worst,
        Math.abs(weightsOf(v).reduce((total, w) => total + w, 0) - 1),
      );
    // the plan allows ± 0.01; the bytes sum to exactly 255
    expect(worst).toBeLessThan(1e-6);
  });

  test('level ground carries the layer of its biome (bible §5.1) and grass the rest', () => {
    const own: Record<string, [GroundLayer, number]> = {
      grassland: ['grass', 1],
      beach: ['sand', 0.6],
      broadleaf_forest: ['forest_floor', 0.7],
      taiga: ['forest_floor', 0.7],
      wetland: ['mud', 0.6],
      hills: ['gravel', 0.25],
      mountain: ['rock', 0.5],
      savanna: ['dirt', 0.3],
      tundra: ['gravel', 0.4],
      volcanic: ['gravel', 0.6],
      snow: ['snow', 1],
      ice: ['snow', 1],
    };
    const { biomes, cellCount, heights } = terrain.globe;
    const vertices = slopes();
    const byte = 1 / 255 + 1e-6;
    const failures: string[] = [];
    const seen = new Set<string>();
    // a cell's own point is mesh vertex `cell` and reads only that cell's biome; level, above the beach band and
    // below the snow line nothing else claims it
    for (let cell = 0; cell < cellCount; cell++) {
      const biome = view.biome_names[biomes[cell]];
      if (!own[biome] || vertices[cell] >= 28) continue;
      if (heights[cell] <= 2.6 || heights[cell] >= 215) continue;
      const [name, share] = own[biome];
      const weights = weightsOf(cell);
      seen.add(biome);
      if (Math.abs(weights[layer(name)] - share) > byte)
        failures.push(`${biome} cell ${cell}: ${name} ${weights[layer(name)]}`);
      if (
        Math.abs(
          weights[layer('grass')] -
            (name === 'grass' ? 1 : name === 'snow' ? 0 : 1 - share),
        ) > byte
      )
        failures.push(
          `${biome} cell ${cell}: grass ${weights[layer('grass')]}`,
        );
    }
    expect(failures).toEqual([]);
    // the volcano has no level ground below the snow line
    expect([...seen].sort()).toEqual(
      Object.keys(own)
        .filter((biome) => biome !== 'volcanic')
        .sort(),
    );
  });

  test('slopes of 45° and more are rock, beaches sand, snow biomes snow, forests forest floor, lake beds mud', () => {
    const { biomes, cellCount, heights } = terrain.globe;
    const names = view.biome_names;
    const vertices = slopes();
    const position = mesh.getAttribute('position');
    const radius = terrain.globe.radius;
    const point = new Vector3();
    // dry land (lake beds lie flat at their surface: mud only)
    const dry = (v: number) =>
      point.fromBufferAttribute(position, v).length() - radius >
        WATER_SURFACE + 0.05 && weightsOf(v)[layer('mud')] < 1;
    let steep = 0;
    const steepFailures: string[] = [];
    for (let v = 0; v < vertices.length; v++) {
      if (vertices[v] < 45 || !dry(v)) continue;
      steep += 1;
      const rock = weightsOf(v)[layer('rock')];
      if (rock < 0.6) steepFailures.push(`vertex ${v}: rock ${rock}`);
    }
    expect(steep).toBeGreaterThan(1000);
    expect(steepFailures).toEqual([]);

    // a cell's own point is mesh vertex `cell` and reads only that cell's biome
    const failures: string[] = [];
    const counts: Record<string, number> = {};
    const check = (
      cell: number,
      kind: string,
      name: GroundLayer,
      at: number,
    ) => {
      counts[kind] = (counts[kind] ?? 0) + 1;
      const weight = weightsOf(cell)[layer(name)];
      if (weight < at) failures.push(`${kind} cell ${cell}: ${name} ${weight}`);
    };
    for (let cell = 0; cell < cellCount; cell++) {
      const biome = names[biomes[cell]];
      const gentle = vertices[cell] < 28;
      if (biome === 'lake' && heights[cell] > WATER_SURFACE)
        check(cell, 'lake', 'mud', 1);
      if (biome === 'beach' && gentle && heights[cell] > WATER_SURFACE)
        check(cell, 'beach', 'sand', 0.5);
      if ((biome === 'snow' || biome === 'ice') && vertices[cell] < 35)
        check(cell, 'snow', 'snow', 0.8);
      if (
        (biome === 'broadleaf_forest' || biome === 'taiga') &&
        gentle &&
        heights[cell] > 3
      )
        check(cell, 'forest', 'forest_floor', 0.6);
    }
    expect(failures).toEqual([]);
    for (const kind of ['lake', 'beach', 'snow', 'forest'])
      expect(counts[kind], kind).toBeGreaterThan(50);
  });
});

interface BlendSample {
  first: number;
  second: number;
  /** The two layers' ids mixed by the first one's share: jumps wherever the blend jumps. */
  mixed: number;
  /** The first layer's share (0.5..1). */
  share: number;
}

/** A path through the blend's inputs: weights and fields go linearly from `from` to `to`. */
interface BlendPath {
  from: { weights: GroundWeights; f0: number; f1: number };
  to: { weights: GroundWeights; f0: number; f1: number };
}

const SAMPLES = 1024;

/*
 * Runs the shader's own breakup and pick (`groundBlendGlsl`) on the GPU at SAMPLES points along a path and reads
 * back which two layers draw and their mix. Browser code goes in as a string: the test TypeScript has no DOM types.
 */
async function blendAlong(
  page: Page,
  rules: GroundBreakup[],
  { from, to }: BlendPath,
): Promise<BlendSample[]> {
  const shader = `#version 300 es
precision highp float;
precision highp int;
uniform float wFrom[8];
uniform float wTo[8];
uniform vec2 fFrom;
uniform vec2 fTo;
out vec4 color;
${groundBlendGlsl(rules)}
void main() {
  float x = (gl_FragCoord.x - 0.5) / ${SAMPLES - 1}.0;
  float w[8];
  for (int i = 0; i < 8; i++) w[i] = mix(wFrom[i], wTo[i], x);
  vec2 f = mix(fFrom, fTo, x);
  int first;
  int second;
  float t = groundBlend(w, f.x, f.y, 0.04, first, second);
  color = vec4(float(first) / 7.0, float(second) / 7.0, mix(float(second), float(first), t) / 7.0, t);
}`;
  const pixels = await page.evaluate<number[]>(`(() => {
    const canvas = document.createElement('canvas');
    canvas.width = ${SAMPLES};
    canvas.height = 1;
    const gl = canvas.getContext('webgl2', { premultipliedAlpha: false });
    const compile = (type, source) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, source);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl.VERTEX_SHADER, '#version 300 es\\nvoid main() { gl_Position = vec4(vec2(gl_VertexID & 1, gl_VertexID >> 1) * 4.0 - 1.0, 0.0, 1.0); }'));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, ${JSON.stringify(shader)}));
    gl.linkProgram(program);
    gl.useProgram(program);
    const set = (name, value) => (value.length === 8 ? gl.uniform1fv : gl.uniform2fv).call(gl, gl.getUniformLocation(program, name), value);
    set('wFrom', ${JSON.stringify(weightsArray(from.weights))});
    set('wTo', ${JSON.stringify(weightsArray(to.weights))});
    set('fFrom', [${from.f0}, ${from.f1}]);
    set('fTo', [${to.f0}, ${to.f1}]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    const out = new Uint8Array(${SAMPLES} * 4);
    gl.readPixels(0, 0, ${SAMPLES}, 1, gl.RGBA, gl.UNSIGNED_BYTE, out);
    return [...out];
  })()`);
  return Array.from({ length: SAMPLES }, (_, k) => ({
    first: Math.round((pixels[k * 4] / 255) * 7),
    second: Math.round((pixels[k * 4 + 1] / 255) * 7),
    mixed: (pixels[k * 4 + 2] / 255) * 7,
    share: pixels[k * 4 + 3] / 255,
  }));
}

/** The largest change of the mix between neighbouring samples (in layer ids). */
const largestStep = (samples: BlendSample[]) =>
  Math.max(
    ...samples.slice(1).map((s, k) => Math.abs(s.mixed - samples[k].mixed)),
  );

test.describe('ground blend', () => {
  test('the blend of the top two layers never jumps where the pick changes', async ({
    page,
  }) => {
    // grass leads by a hair, so it shares the band with the second; dirt and sand trade second place midway
    const samples = await blendAlong(page, [], {
      from: {
        weights: { grass: 0.36, dirt: 0.34, sand: 0.3 },
        f0: 0.5,
        f1: 0.5,
      },
      to: { weights: { grass: 0.36, dirt: 0.3, sand: 0.34 }, f0: 0.5, f1: 0.5 },
    });
    expect(samples[0]).toMatchObject({
      first: layer('grass'),
      second: layer('dirt'),
    });
    expect(samples.at(-1)).toMatchObject({
      first: layer('grass'),
      second: layer('sand'),
    });
    // a smooth sweep moves the mix by hundredths of a layer per sample (8-bit readback: steps of 7/255); the
    // second place changing hands mid-blend would jump it by half a layer
    expect(largestStep(samples)).toBeLessThan(0.2);
    // grass and dirt trade first place with sand close behind
    const close = await blendAlong(page, [], {
      from: {
        weights: { grass: 0.35, dirt: 0.31, sand: 0.3 },
        f0: 0.5,
        f1: 0.5,
      },
      to: { weights: { grass: 0.31, dirt: 0.35, sand: 0.3 }, f0: 0.5, f1: 0.5 },
    });
    expect(close[0].first).toBe(layer('grass'));
    expect(close.at(-1)!.first).toBe(layer('dirt'));
    expect(largestStep(close)).toBeLessThan(0.2);
  });

  test('two layers sharing the ground evenly split it into patches, not a mix', async ({
    page,
  }) => {
    // level mountain: rock and grass half and half
    const samples = await blendAlong(page, [], {
      from: { weights: { grass: 0.5, rock: 0.5 }, f0: 0.35, f1: 0.5 },
      to: { weights: { grass: 0.5, rock: 0.5 }, f0: 0.65, f1: 0.5 },
    });
    const firsts = new Set(samples.map((s) => s.first));
    expect([...firsts].sort()).toEqual([layer('grass'), layer('rock')].sort());
    // only a narrow band along the patches' edges blends the two
    const crisp = samples.filter((s) => s.share > 0.99).length;
    expect(crisp / SAMPLES).toBeGreaterThan(0.75);
  });

  test("a patch's edge shows no third layer between the two", async ({
    page,
  }) => {
    // tundra-like ground (grass and gravel) crossing the edge of a dirt patch where the fields barely lift any
    // layer: split half and half at the edge, grass and dirt (0.3 each) would sink below the gravel (0.4)
    const samples = await blendAlong(
      page,
      [{ from: 'grass', to: 'dirt', field: 0, cut: 0.48, amount: 1 }],
      {
        from: { weights: { grass: 0.6, gravel: 0.4 }, f0: 0.46, f1: 0.5 },
        to: { weights: { grass: 0.6, gravel: 0.4 }, f0: 0.54, f1: 0.5 },
      },
    );
    expect(samples[0].first).toBe(layer('grass'));
    expect(samples.at(-1)!.first).toBe(layer('dirt'));
    expect(samples.filter((s) => s.first === layer('gravel'))).toEqual([]);
    expect(largestStep(samples)).toBeLessThan(0.2);
  });
});

interface GroundPixels {
  green: number;
  earth: number;
  /** Mean lightness step (0..255) between pixels 2 apart: the ground's fine texture. */
  texture: number;
}

/*
 * Shares of pixels by colour family in the lower part of the canvas (the ground in front of the player), and how
 * much the lightness changes from pixel to pixel. Browser code goes in as a string: the test TypeScript has no
 * DOM types.
 */
const GROUND_PIXELS = `(() => {
  const source = document.querySelector('canvas');
  const canvas = document.createElement('canvas');
  canvas.width = source.width;
  canvas.height = source.height;
  const context = canvas.getContext('2d');
  context.drawImage(source, 0, 0);
  const top = Math.floor(source.height * 0.62);
  const width = source.width;
  const { data } = context.getImageData(0, top, width, source.height - top);
  const light = (i) => (data[i] + data[i + 1] + data[i + 2]) / 3;
  let [green, earth, total, steps] = [0, 0, 0, 0];
  for (let i = 0; i < data.length - 8; i += 16) {
    const [r, g, b] = [data[i], data[i + 1], data[i + 2]];
    total += 1;
    steps += Math.abs(light(i) - light(i + 8));
    if (g > r + 8 && g > b + 8) green += 1;
    else if (r >= g - 4 && r > b + 6) earth += 1;
  }
  return { green: green / total, earth: earth / total, texture: steps / total };
})()`;

const groundPixels = (page: Page) => page.evaluate<GroundPixels>(GROUND_PIXELS);

// South of the town, outside its walls and ground disc: open grassland at street level, facing the town.
const OUTSIDE_THE_WALLS = '?at=31.2,12,0&time=12:00';
// The spawn at the south gate: the town's own grass.
const TOWN_GATE = '?time=12:00';

test.describe('ground at street level', () => {
  for (const [name, query, minGreen] of [
    ['outside the walls', OUTSIDE_THE_WALLS, 0.3],
    ['at the town gate', TOWN_GATE, 0.1],
  ] as const)
    test(`the grass breaks into bare patches ${name}, unlike the flat ground`, async ({
      page,
    }) => {
      test.setTimeout(120_000);
      const errors: string[] = [];
      await openGlobe(page, errors, `${query}&ground=flat`);
      await page.waitForTimeout(1500);
      const plain = await groundPixels(page);
      // outside the walls the flat ground is a plain green plane
      if (query === OUTSIDE_THE_WALLS) expect(plain.earth).toBeLessThan(0.02);
      await openGlobe(page, errors, query);
      await page.waitForTimeout(1500);
      const detailed = await groundPixels(page);
      // the shader shows earth and gravel in the grass, and texture (the gate's road is earth in both)
      expect(detailed.earth).toBeGreaterThan(plain.earth + 0.05);
      expect(detailed.green).toBeGreaterThan(minGreen);
      expect(detailed.texture).toBeGreaterThan(plain.texture * 4);
      expect(errors).toEqual([]);
    });

  test('the low quality compiles and still shows patches', async ({ page }) => {
    test.setTimeout(90_000);
    const errors: string[] = [];
    await openGlobe(page, errors, `${OUTSIDE_THE_WALLS}&ground=low`);
    await page.waitForTimeout(1500);
    expect((await groundPixels(page)).earth).toBeGreaterThan(0.05);
    expect(errors).toEqual([]);
  });
});
