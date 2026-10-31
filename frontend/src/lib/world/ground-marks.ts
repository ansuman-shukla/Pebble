/*
 * Ground marks (bible §5.1): the sharp things lying on the ground shader, all in one merged mesh:
 * - the town's areas (streets of packed earth, gravel roads, paved plazas, raked courtyards, furrowed fields);
 * - the world's roads (3 m, gravel ruts) and paths (1.5 m, trodden earth): Catmull-Rom ribbons through their cells,
 *   each cell-to-cell step drawn once (a road wins over a path), split into chains at junctions, draped on the drawn
 *   ground every metre, with a round patch at each junction or end and a gap where a bridge carries them over a river;
 * - camp ground: a worn disc round the fire, the fire's scorch and paths from the shelters to it;
 * - the hotspots' work spots: worn, dug or iron-sand patches.
 * Every vertex carries its kind, how far in from the mark's border it lies (`edge`: 0 at the border, 1 at the
 * middle line or deeper than the border band), its signed metres from the mark's middle line and its half width,
 * so the material draws ruts and furrows, eats a noisy ragged border into it and fades that border over a pixel
 * (alpha to coverage) rather than a polygon edge. Marks never lie on water.
 */
import {
  BufferGeometry,
  CatmullRomCurve3,
  Color,
  CustomBlending,
  Float32BufferAttribute,
  MeshStandardMaterial,
  OneFactor,
  type PerspectiveCamera,
  ShapeUtils,
  Vector2,
  Vector3,
  ZeroFactor,
} from 'three';

import type { Road, Site, TownArea, WorldPlaces } from '../client/types.gen';
import {
  buildWalkWorld,
  isWater,
  type Point,
  type WalkWater,
} from './collision';
import {
  anchorMapping,
  cellDirection,
  type Globe,
  type GlobeTerrain,
  type SiteMapping,
  tangent,
  tangentFrame,
} from './globe';
import { type GroundQuality, groundLookGlsl } from './ground-shader';
import { MARK_STYLE } from './ground-style';
import type { LocalMapping } from './local-mapping';
import type { RiverLayout } from './river-courses';

type RiverPoint = RiverLayout['runs'][number]['points'][number];

export const MARK_KINDS = [
  'road',
  'path',
  'paving',
  'raked',
  'packed',
  'farmland',
  'worn',
  'dug',
  'scorch',
  'iron_sand',
] as const;
export type MarkKind = (typeof MARK_KINDS)[number];

type RouteKind = Road['kind'];

/** Widths (metres) of the network's ribbons (bible §1.3). */
export const ROUTE_WIDTH: Record<RouteKind, number> = { road: 3, path: 1.5 };
/** Metres between a ribbon's draped samples. */
const STEP = 1;
/** Longest edge of a patch's triangles (metres), so they follow the ground under them... */
const MAX_EDGE = 1.5;
/** ...and of an area's, which lies on the town's flat plateau: it sags under 1 cm on the planet (map-geometry.ts). */
const AREA_EDGE = 8;
/** Camp ground (bible §5.1): a worn disc round the fire, its scorch, paths from the shelters to it. */
export const CAMP_WORN_RADIUS = 10;
export const SCORCH_RADIUS = 1.6;
const CAMP_PATH_WIDTH = 1.2;
/** The patch each kind of work spot wears into the ground. */
const SPOT_MARKS: Partial<
  Record<
    WorldPlaces['features'][number]['kind'],
    { kind: MarkKind; radius: number }
  >
> = {
  fishing_spot: { kind: 'worn', radius: 0.8 },
  gold_pool: { kind: 'worn', radius: 0.8 },
  waterhole: { kind: 'worn', radius: 3 },
  den: { kind: 'worn', radius: 1.5 },
  flint_seam: { kind: 'dug', radius: 1.5 },
  obsidian_field: { kind: 'dug', radius: 1.5 },
  iron_sand_bar: { kind: 'iron_sand', radius: 4 },
};
/** The mark of each town area kind, and the width (metres) of the band where its border rags. */
const AREA_MARKS: Record<TownArea['kind'], { kind: MarkKind; band: number }> = {
  street: { kind: 'packed', band: 0.8 },
  road: { kind: 'road', band: 0.8 },
  plaza: { kind: 'paving', band: 0.3 },
  courtyard: { kind: 'raked', band: 0.3 },
  field: { kind: 'farmland', band: 0.6 },
};
/** Height (metres) of each layer of marks over the drawn ground: a later one draws over an earlier one. */
const LIFT = {
  area: 0.01,
  camp: 0.05,
  spot: 0.06,
  path: 0.07,
  road: 0.08,
  junction: 0.09,
  scorch: 0.1,
};
/** A junction's patch reaches this many half widths of its widest route from the junction, over the tapered ends. */
const JUNCTION_REACH = 1.6;
/** A bridge reaches this far (metres) onto each bank. */
const BRIDGE_BANK = 1.2;
/** A ribbon sample this close (metres) to a drawn river's water lies under the bridge. */
const BRIDGE_MARGIN = 1;
/** Bucket size (metres) of the river index: more than half the widest river plus a river sample's spacing. */
const BUCKET = 16;

/** The drawn ground under a unit direction: its height above sea level, or null where water lies (no mark there). */
export interface MarkGround {
  radius: number;
  heightAt(direction: Vector3): number | null;
}

interface Ribbon {
  kind: RouteKind;
  width: number;
  /** Unit directions every STEP metres along its middle line (a closed one ends where it starts). */
  points: Vector3[];
  closed: boolean;
  /** Sample index ranges [from, to] left undrawn (under a bridge). */
  gaps: [number, number][];
}

interface Patch {
  kind: MarkKind;
  centre: Vector3;
  radius: number;
  lift: number;
}

/** Where a bridge carries a road or path over a river. */
export interface BridgeSpan {
  /** Unit direction of its middle. */
  centre: Vector3;
  /** Unit tangent along the road. */
  along: Vector3;
  /** Metres from bank to bank. */
  length: number;
  /** Width (metres) of the road it carries. */
  width: number;
}

/** The marks outside the town's areas: the network's ribbons, the patches and the bridges. */
export interface PlanetMarks {
  ribbons: Ribbon[];
  patches: Patch[];
  bridges: BridgeSpan[];
}

interface Chain {
  cells: number[];
  /** A loop with no junction on it. */
  closed: boolean;
  kind: RouteKind;
}

const rank = (kind: RouteKind) => (kind === 'road' ? 2 : 1);
const stepKey = (a: number, b: number) => (a < b ? `${a},${b}` : `${b},${a}`);

/**
 * The network's cell routes as chains between junctions: each cell-to-cell step once (a road wins over a path); a
 * chain breaks where a cell has other than two neighbours or its two steps differ in kind. `ends` holds those
 * cells with the widest kind meeting there.
 */
export function routeChains(roads: Pick<Road, 'kind' | 'cells'>[]) {
  const steps = new Map<string, RouteKind>();
  const links = new Map<number, Set<number>>();
  const link = (a: number, b: number) => {
    const set = links.get(a);
    if (set) set.add(b);
    else links.set(a, new Set([b]));
  };
  for (const road of roads)
    for (let i = 1; i < road.cells.length; i++) {
      const [a, b] = [road.cells[i - 1], road.cells[i]];
      if (a === b) continue;
      const key = stepKey(a, b);
      const old = steps.get(key);
      if (!old || rank(road.kind) > rank(old)) steps.set(key, road.kind);
      link(a, b);
      link(b, a);
    }
  const kindOf = (a: number, b: number) => steps.get(stepKey(a, b))!;
  const breaks = (cell: number) => {
    const near = [...links.get(cell)!];
    return near.length !== 2 || kindOf(cell, near[0]) !== kindOf(cell, near[1]);
  };
  const seen = new Set<string>();
  const walk = (start: number, next: number): Chain => {
    const cells = [start, next];
    const kind = kindOf(start, next);
    seen.add(stepKey(start, next));
    let [previous, here] = [start, next];
    while (here !== start && !breaks(here)) {
      const after = [...links.get(here)!].find((cell) => cell !== previous)!;
      seen.add(stepKey(here, after));
      cells.push(after);
      [previous, here] = [here, after];
    }
    const closed = here === start && !breaks(start);
    return { cells: closed ? cells.slice(0, -1) : cells, closed, kind };
  };
  const chains: Chain[] = [];
  const ends = new Map<number, RouteKind>();
  for (const [cell, near] of links) {
    if (!breaks(cell)) continue;
    ends.set(
      cell,
      [...near].some((other) => kindOf(cell, other) === 'road')
        ? 'road'
        : 'path',
    );
    for (const other of near)
      if (!seen.has(stepKey(cell, other))) chains.push(walk(cell, other));
  }
  // what is left are loops without a junction
  for (const [cell, near] of links)
    for (const other of near)
      if (!seen.has(stepKey(cell, other))) chains.push(walk(cell, other));
  return { chains, ends };
}

/** Points every STEP metres along a centripetal Catmull-Rom curve through unit directions, as unit directions. */
function sampleCurve(points: Vector3[], closed: boolean, radius: number) {
  const kept = points.filter(
    (point, i) => i === 0 || point.angleTo(points[i - 1]) * radius > 0.5,
  );
  if (kept.length < 2) return [];
  const curve = new CatmullRomCurve3(
    kept.map((point) => point.clone().multiplyScalar(radius)),
    closed,
    'centripetal',
  );
  curve.arcLengthDivisions = kept.length * 64;
  const count = Math.max(1, Math.round(curve.getLength() / STEP));
  return curve.getSpacedPoints(count).map((point) => point.normalize());
}

/** Unit directions of a straight line between two local points of a site, every STEP metres. */
function siteLine(mapping: LocalMapping, from: Point, to: Point) {
  const length = Math.hypot(to[0] - from[0], to[1] - from[1]);
  const count = Math.max(1, Math.round(length / STEP));
  return Array.from({ length: count + 1 }, (_, i) => {
    const t = i / count;
    return mapping
      .toWorld(
        from[0] + (to[0] - from[0]) * t,
        0,
        from[1] + (to[1] - from[1]) * t,
        new Vector3(),
      )
      .normalize();
  });
}

/** Unit tangent of a ribbon at sample i (from its neighbours). */
function alongAt(points: Vector3[], i: number, target: Vector3) {
  const next = points[Math.min(points.length - 1, i + 1)];
  const previous = points[Math.max(0, i - 1)];
  return tangent(target.subVectors(next, previous), points[i]);
}

/** The drawn rivers' segments in buckets of BUCKET metres, for "how far is the water from here". */
function riverIndex(rivers: RiverLayout, radius: number) {
  const buckets = new Map<string, [RiverPoint, RiverPoint][]>();
  const key = (x: number, y: number, z: number) =>
    `${Math.floor(x / BUCKET)},${Math.floor(y / BUCKET)},${Math.floor(z / BUCKET)}`;
  for (const { points } of rivers.runs)
    for (let j = 1; j < points.length; j++) {
      const { x, y, z } = points[j].direction.clone().multiplyScalar(radius);
      const bucket = buckets.get(key(x, y, z));
      if (bucket) bucket.push([points[j - 1], points[j]]);
      else buckets.set(key(x, y, z), [[points[j - 1], points[j]]]);
    }
  const point = new Vector3();
  const [a, b, on] = [new Vector3(), new Vector3(), new Vector3()];
  /** Metres from a unit direction to the nearest drawn water (< 0 on it), up to a bucket away. */
  return (at: Vector3) => {
    point.copy(at).multiplyScalar(radius);
    let best = Infinity;
    for (let dx = -1; dx <= 1; dx++)
      for (let dy = -1; dy <= 1; dy++)
        for (let dz = -1; dz <= 1; dz++)
          for (const [p, q] of buckets.get(
            key(
              point.x + dx * BUCKET,
              point.y + dy * BUCKET,
              point.z + dz * BUCKET,
            ),
          ) ?? []) {
            a.copy(p.direction).multiplyScalar(radius);
            b.copy(q.direction).multiplyScalar(radius).sub(a);
            const t = Math.min(
              1,
              Math.max(0, on.subVectors(point, a).dot(b) / b.lengthSq()),
            );
            on.copy(a).addScaledVector(b, t);
            best = Math.min(
              best,
              on.distanceTo(point) - (p.width + (q.width - p.width) * t) / 2,
            );
          }
    return best;
  };
}

/**
 * Where bridges carry the ribbons over the drawn rivers: each stretch of a ribbon whose middle line runs onto drawn
 * water is left undrawn and spanned from bank to bank along the road (with BRIDGE_MARGIN to spare). The world's bridges stand on the river
 * cells its routes cross, but the drawn river runs smoothed beside those cells' centres and a ribbon curving between
 * two cells can meet it elsewhere, so the drawn crossings are found from the drawn ribbons and rivers (the town's
 * own water stops its ribbons through the ground instead).
 */
function bridgeSpans(
  ribbons: Ribbon[],
  rivers: RiverLayout,
  radius: number,
): BridgeSpan[] {
  const fromWater = riverIndex(rivers, radius);
  const spans: BridgeSpan[] = [];
  for (const ribbon of ribbons) {
    const near = ribbon.points.map(fromWater);
    for (let from = 0; from < near.length; from++) {
      if (near[from] >= BRIDGE_MARGIN) continue;
      let to = from;
      while (to + 1 < near.length && near[to + 1] < BRIDGE_MARGIN) to += 1;
      // a ribbon only grazing the water keeps to the bank
      if (Math.min(...near.slice(from, to + 1)) < 0) {
        const middle = Math.round((from + to) / 2);
        ribbon.gaps.push([from, to]);
        spans.push({
          centre: ribbon.points[middle],
          along: alongAt(ribbon.points, middle, new Vector3()),
          length: (to - from) * STEP + 2 * BRIDGE_BANK,
          width: ribbon.width,
        });
      }
      from = to;
    }
  }
  return spans;
}

/** The marks the world view lays outside the town's areas (directions only: draping happens in `buildMarks`). */
export function planetMarks({
  globe,
  places,
  sites,
  rivers,
}: {
  globe: Globe;
  places: Pick<WorldPlaces, 'roads' | 'features'>;
  sites: Site[];
  rivers: RiverLayout;
}): PlanetMarks {
  const { radius } = globe;
  const cell = (index: number) => cellDirection(globe, index, new Vector3());
  const { chains, ends } = routeChains(places.roads);
  const ribbon = (
    kind: RouteKind,
    points: Vector3[],
    { width = ROUTE_WIDTH[kind], closed = false } = {},
  ): Ribbon => ({ kind, width, points, closed, gaps: [] });
  const ribbons: Ribbon[] = chains.map((chain) =>
    ribbon(
      chain.kind,
      sampleCurve(chain.cells.map(cell), chain.closed, radius),
      {
        closed: chain.closed,
      },
    ),
  );
  // a gate's lead (shared by every road leaving that gate) runs from the gate to the road's first cell
  const leads = new Map<string, Ribbon>();
  for (const road of places.roads) {
    const lead = road.lead ?? [];
    const key = JSON.stringify(lead);
    if (lead.length === 0 || leads.has(key)) continue;
    const points = [
      ...lead.map((point) => new Vector3(...point)),
      cell(road.cells[0]),
    ];
    leads.set(key, ribbon(road.kind, sampleCurve(points, false, radius)));
  }
  ribbons.push(...leads.values());
  const patches: Patch[] = [...ends].map(([index, kind]) => ({
    kind,
    centre: cell(index),
    radius: (ROUTE_WIDTH[kind] / 2) * JUNCTION_REACH,
    lift: LIFT.junction,
  }));
  for (const site of sites) {
    if (site.kind !== 'camp') continue;
    const mapping = anchorMapping(site.anchor, radius);
    const placements = site.placements ?? [];
    const fire = placements.find((placement) => placement.kind === 'fire_pit');
    const hearth: Point = fire ? [fire.x, fire.z] : [0, 0];
    const centre = siteLine(mapping, hearth, hearth)[0];
    patches.push(
      { kind: 'worn', centre, radius: CAMP_WORN_RADIUS, lift: LIFT.camp },
      { kind: 'scorch', centre, radius: SCORCH_RADIUS, lift: LIFT.scorch },
    );
    for (const shelter of placements.filter(
      (placement) => placement.kind === 'lean_to',
    ))
      ribbons.push(
        ribbon('path', siteLine(mapping, [shelter.x, shelter.z], hearth), {
          width: CAMP_PATH_WIDTH,
        }),
      );
  }
  for (const feature of places.features) {
    const spot = SPOT_MARKS[feature.kind];
    if (spot)
      patches.push({
        ...spot,
        centre: new Vector3(...feature.position),
        lift: LIFT.spot,
      });
  }
  return {
    ribbons,
    patches,
    bridges: bridgeSpans(ribbons, rivers, radius),
  };
}

/**
 * The drawn ground on the globe: no marks on the drawn rivers, nor on the town's moat and stream; the town's disc
 * at its plateau height (local metres), else the terrain.
 */
export function globeMarkGround({
  terrain,
  rivers,
  town,
}: {
  terrain: GlobeTerrain;
  rivers: RiverLayout;
  town: {
    mapping: SiteMapping;
    groundRadius: number;
    height: number;
    water: WalkWater[];
  };
}): MarkGround {
  const radius = terrain.globe.radius;
  const fromWater = riverIndex(rivers, radius);
  const wet = buildWalkWorld([], town.water, new Map());
  const local = new Vector3();
  return {
    radius,
    heightAt(direction) {
      if (fromWater(direction) < 0) return null;
      town.mapping.toLocal(local.copy(direction).multiplyScalar(radius), local);
      if (Math.hypot(local.x, local.z) < town.groundRadius)
        return isWater(wet, [local.x, local.z]) ? null : town.height;
      return terrain.heightAt(direction);
    },
  };
}

/** The merged mesh's vertices and triangles. */
class MarkMesh {
  private positions: number[] = [];
  private marks: number[] = [];
  private perps: number[] = [];
  private indices: number[] = [];
  private readonly normal = new Vector3();
  private readonly ab = new Vector3();
  private readonly ac = new Vector3();
  private readonly points = [new Vector3(), new Vector3(), new Vector3()];

  vertex(
    position: Vector3,
    kind: MarkKind,
    edge: number,
    across: number,
    half: number,
    perp: Vector3,
  ) {
    this.positions.push(position.x, position.y, position.z);
    this.marks.push(MARK_KINDS.indexOf(kind), edge, across, half);
    this.perps.push(perp.x, perp.y, perp.z);
    return this.positions.length / 3 - 1;
  }

  /** A triangle facing `up` (wound counter-clockwise seen from there). */
  triangle(a: number, b: number, c: number, up: Vector3) {
    const [pa, pb, pc] = [a, b, c].map((index, k) =>
      this.points[k].fromArray(this.positions, index * 3),
    );
    this.normal.crossVectors(
      this.ab.subVectors(pb, pa),
      this.ac.subVectors(pc, pa),
    );
    if (this.normal.dot(up) >= 0) this.indices.push(a, b, c);
    else this.indices.push(a, c, b);
  }

  geometry() {
    const geometry = new BufferGeometry();
    geometry.setAttribute(
      'position',
      new Float32BufferAttribute(this.positions, 3),
    );
    geometry.setAttribute('mark', new Float32BufferAttribute(this.marks, 4));
    geometry.setAttribute(
      'markPerp',
      new Float32BufferAttribute(this.perps, 3),
    );
    geometry.setIndex(this.indices);
    geometry.computeVertexNormals();
    return geometry;
  }
}

const NO_PERP = new Vector3();

/** Metres from each drawn sample to the nearest end of its run of drawn samples (a closed ribbon's ends join). */
function runDistances(drawn: boolean[], closed: boolean) {
  const out = drawn.map(() => Infinity);
  for (const order of [drawn.keys(), [...drawn.keys()].reverse()]) {
    let run = closed ? Infinity : -STEP;
    for (const i of order) {
      run = drawn[i] ? run + STEP : -STEP;
      out[i] = Math.min(out[i], run);
    }
  }
  return out;
}

const ACROSS = [-1, 0, 1];

/**
 * A ribbon draped on the ground: three vertices across (both borders and the middle line) at every sample, its
 * edge tapering to 0 over a half width at each end (where it meets a junction's patch, a bridge or water), so no
 * straight cut shows.
 */
function drapeRibbon(mesh: MarkMesh, ribbon: Ribbon, ground: MarkGround) {
  const { radius } = ground;
  const half = ribbon.width / 2;
  const lift = LIFT[ribbon.kind];
  const along = new Vector3();
  const at = new Vector3();
  const hidden = (i: number) =>
    ribbon.gaps.some(([from, to]) => i >= from && i <= to);
  const samples = ribbon.points.map((point, i) => {
    if (hidden(i)) return null;
    alongAt(ribbon.points, i, along);
    const side = new Vector3().crossVectors(along, point).normalize();
    // a border over water (a ribbon grazing a river or the town's stream) lies level with the middle
    const heights = ACROSS.map((across) =>
      ground.heightAt(
        at
          .copy(point)
          .multiplyScalar(radius)
          .addScaledVector(side, across * half)
          .normalize(),
      ),
    );
    const middle = heights[1];
    if (middle === null) return null;
    const corners = ACROSS.map((across, k) =>
      at
        .copy(point)
        .multiplyScalar(radius)
        .addScaledVector(side, across * half)
        .normalize()
        .multiplyScalar(radius + (heights[k] ?? middle) + lift)
        .clone(),
    );
    return { corners, side };
  });
  const toEnd = runDistances(
    samples.map((sample) => sample !== null),
    ribbon.closed,
  );
  const rows = samples.map(
    (sample, i) =>
      sample &&
      sample.corners.map((corner, k) =>
        mesh.vertex(
          corner,
          ribbon.kind,
          Math.min(1 - Math.abs(ACROSS[k]), toEnd[i] / half),
          ACROSS[k] * half,
          half,
          sample.side,
        ),
      ),
  );
  for (let i = 1; i < rows.length; i++) {
    const [a, b] = [rows[i - 1], rows[i]];
    if (!a || !b) continue;
    const up = ribbon.points[i];
    for (let k = 0; k < 2; k++) {
      mesh.triangle(a[k], a[k + 1], b[k + 1], up);
      mesh.triangle(a[k], b[k + 1], b[k], up);
    }
  }
}

/** A round patch draped on the ground: rings and spokes at most MAX_EDGE apart, edge 1 at its centre. */
function drapePatch(mesh: MarkMesh, patch: Patch, ground: MarkGround) {
  const { radius } = ground;
  const { east, south } = tangentFrame(patch.centre);
  const rings = Math.max(1, Math.ceil(patch.radius / MAX_EDGE));
  const spokes = Math.max(
    24,
    Math.ceil((2 * Math.PI * patch.radius) / MAX_EDGE),
  );
  const at = new Vector3();
  const place = (x: number, z: number, edge: number) => {
    at.copy(patch.centre)
      .multiplyScalar(radius)
      .addScaledVector(east, x)
      .addScaledVector(south, z)
      .normalize();
    const height = ground.heightAt(at);
    if (height === null) return null;
    return mesh.vertex(
      at.multiplyScalar(radius + height + patch.lift),
      patch.kind,
      edge,
      0,
      patch.radius,
      NO_PERP,
    );
  };
  const middle = place(0, 0, 1);
  let inner: (number | null)[] = Array.from({ length: spokes }, () => middle);
  for (let ring = 1; ring <= rings; ring++) {
    const r = (ring / rings) * patch.radius;
    const outer = Array.from({ length: spokes }, (_, k) => {
      const angle = (k / spokes) * 2 * Math.PI;
      return place(
        Math.cos(angle) * r,
        Math.sin(angle) * r,
        1 - r / patch.radius,
      );
    });
    for (let k = 0; k < spokes; k++) {
      const next = (k + 1) % spokes;
      const [a, b, c, d] = [inner[k], inner[next], outer[k], outer[next]];
      if (a === null || b === null || c === null || d === null) continue;
      if (ring > 1) mesh.triangle(a, b, d, patch.centre);
      mesh.triangle(a, d, c, patch.centre);
    }
    inner = outer;
  }
}

interface AreaVertex {
  x: number;
  z: number;
  edge: number;
}

/** A polygon moved `band` metres inwards along its corners' bisectors. */
function inset(polygon: Point[], band: number): Point[] {
  const area = polygon.reduce((sum, [x1, z1], i) => {
    const [x2, z2] = polygon[(i + 1) % polygon.length];
    return sum + x1 * z2 - x2 * z1;
  }, 0);
  const inward = ([ax, az]: Point, [bx, bz]: Point) => {
    const length = Math.hypot(bx - ax, bz - az);
    const sign = Math.sign(area);
    return new Vector2(
      (-(bz - az) * sign) / length,
      ((bx - ax) * sign) / length,
    );
  };
  return polygon.map((point, i) => {
    const previous = polygon[(i + polygon.length - 1) % polygon.length];
    const next = polygon[(i + 1) % polygon.length];
    const n1 = inward(previous, point);
    const n2 = inward(point, next);
    const bisector = n1.clone().add(n2).normalize();
    const reach = band / Math.max(bisector.dot(n1), 0.2);
    return [point[0] + bisector.x * reach, point[1] + bisector.y * reach];
  });
}

/** Splits a triangle (longest edge in half) until no edge is longer than AREA_EDGE. */
function splitArea(triangle: AreaVertex[], out: AreaVertex[][]) {
  const stack = [triangle];
  while (stack.length) {
    const [a, b, c] = stack.pop()!;
    const length = (p: AreaVertex, q: AreaVertex) =>
      Math.hypot(p.x - q.x, p.z - q.z);
    const edges: [number, AreaVertex, AreaVertex, AreaVertex][] = [
      [length(a, b), a, b, c],
      [length(b, c), b, c, a],
      [length(c, a), c, a, b],
    ];
    const [longest, p, q, r] = edges.reduce((best, edge) =>
      edge[0] > best[0] ? edge : best,
    );
    if (longest <= AREA_EDGE) {
      out.push([a, b, c]);
      continue;
    }
    const middle = {
      x: (p.x + q.x) / 2,
      z: (p.z + q.z) / 2,
      edge: (p.edge + q.edge) / 2,
    };
    stack.push([p, middle, r], [middle, q, r]);
  }
}

/**
 * A town area: its polygon with a ragged band along the border (edge 0 → 1 over `band` metres) round an inner
 * polygon, `across` measured from the line along its longest side through its middle, mapped onto the world.
 */
function areaMark(mesh: MarkMesh, area: TownArea, mapping: LocalMapping) {
  const { kind, band } = AREA_MARKS[area.kind];
  const outline = area.polygon;
  const longest = outline
    .map((point, i) => {
      const next = outline[(i + 1) % outline.length];
      return new Vector2(next[0] - point[0], next[1] - point[1]);
    })
    .reduce((best, side) => (side.length() > best.length() ? side : best))
    .normalize();
  const perp = new Vector2(-longest.y, longest.x);
  const centre = outline
    .reduce((sum, [x, z]) => sum.add(new Vector2(x, z)), new Vector2())
    .divideScalar(outline.length);
  const inner = inset(outline, band);
  const triangles: AreaVertex[][] = [];
  const vertex = ([x, z]: Point, edge: number) => ({ x, z, edge });
  outline.forEach((point, i) => {
    const j = (i + 1) % outline.length;
    const [a, b] = [vertex(point, 0), vertex(outline[j], 0)];
    const [c, d] = [vertex(inner[j], 1), vertex(inner[i], 1)];
    splitArea([a, b, c], triangles);
    splitArea([a, c, d], triangles);
  });
  for (const [a, b, c] of ShapeUtils.triangulateShape(
    inner.map(([x, z]) => new Vector2(x, z)),
    [],
  ))
    splitArea(
      [vertex(inner[a], 1), vertex(inner[b], 1), vertex(inner[c], 1)],
      triangles,
    );
  const position = new Vector3();
  const across = new Vector3();
  const up = new Vector3();
  for (const triangle of triangles) {
    const [a, b, c] = triangle.map(({ x, z, edge }) => {
      mapping.toWorld(x, LIFT.area, z, position);
      mapping
        .toWorld(x + perp.x, LIFT.area, z + perp.y, across)
        .sub(position)
        .normalize();
      const offset = (x - centre.x) * perp.x + (z - centre.y) * perp.y;
      return mesh.vertex(position, kind, edge, offset, band, across);
    });
    const { x, z } = triangle[0];
    mapping.toWorld(x, 1, z, up).sub(mapping.toWorld(x, 0, z, position));
    mesh.triangle(a, b, c, up);
  }
}

/** The one merged mesh of marks: the town's areas through its mapping and the planet's marks draped on the ground. */
export function buildMarks({
  areas,
  planet,
}: {
  areas?: { areas: TownArea[]; mapping: LocalMapping };
  planet?: { marks: PlanetMarks; ground: MarkGround };
}) {
  const mesh = new MarkMesh();
  for (const area of areas?.areas ?? []) areaMark(mesh, area, areas!.mapping);
  if (planet) {
    for (const ribbon of planet.marks.ribbons)
      drapeRibbon(mesh, ribbon, planet.ground);
    for (const patch of planet.marks.patches)
      drapePatch(mesh, patch, planet.ground);
  }
  return mesh.geometry();
}

// --- the material ---

/** View distances (metres) where the patterns end, and where the marks narrow away to nothing. */
const PATTERN_END = { full: 300, low: 150 };
const FADE: [number, number] = [2000, 2600];
/** The low-poly facets the ground shows (ground-shader.ts FACETS), so marks shade like the ground under them. */
const FACETS = 0.35;
const FACETS_FADE: [number, number] = [250, 1200];

const glslFloat = (value: number) => value.toFixed(4);
const glslColor = (hex: string) => {
  const { r, g, b } = new Color(hex);
  return `vec3(${[r, g, b].map(glslFloat).join(', ')})`;
};

function markConstants() {
  const kinds = MARK_KINDS.map((kind) => MARK_STYLE.kinds[kind]);
  const list = (type: string, values: string[]) =>
    `${type}[${values.length}](${values.join(', ')})`;
  return [
    ...MARK_KINDS.flatMap((kind) =>
      Object.entries(MARK_STYLE.kinds[kind].colors).map(
        ([name, hex]) => `const vec3 mark_${kind}_${name} = ${glslColor(hex)};`,
      ),
    ),
    `const vec3 MARK_BASE[${kinds.length}] = ${list(
      'vec3',
      kinds.map(({ base }) => glslColor(base)),
    )};`,
    `const float MARK_RAG[${kinds.length}] = ${list(
      'float',
      kinds.map(({ rag }) => glslFloat(rag)),
    )};`,
    `const float MARK_ROUGHNESS[${kinds.length}] = ${list(
      'float',
      kinds.map(({ roughness }) => glslFloat(roughness)),
    )};`,
    `const float MARK_DEPTH[${kinds.length}] = ${list(
      'float',
      kinds.map(({ bump }) => glslFloat(bump)),
    )};`,
  ].join('\n');
}

const VERTEX_COMMON = /* glsl */ `
attribute vec4 mark;
attribute vec3 markPerp;
varying vec4 vMark;
varying vec3 vMarkPerp;
varying vec3 vMarkPlanet;
`;

const VERTEX_MAIN = /* glsl */ `
vMark = mark;
vMarkPerp = markPerp;
vMarkPlanet = position;
`;

const FRAGMENT_COMMON = /* glsl */ `
varying vec4 vMark;
varying vec3 vMarkPerp;
varying vec3 vMarkPlanet;
uniform float markPixel;
uniform float markFacets;
uniform vec2 markFacetsFade;
`;

/*
 * The mark's colour, roughness and relief from its pattern, and its coverage: 0.5 where the noisy ragged border
 * cuts the mark, rising a unit a metre inwards (three's alpha to coverage turns that into a pixel-wide fade).
 */
const FRAGMENT_COLOR = /* glsl */ `
float markRoughness;
float markRelief = 0.0;
{
  int kind = int(vMark.x + 0.5);
  float halfWidth = vMark.w;
  float across = vMark.z;
  vec3 p = vMarkPlanet;
  float dist = length(vViewPosition);
  float facing = max(abs(dot(normalize(vNormal), vViewPosition)) / dist, 0.05);
  float fw = dist * markPixel * sqrt(1.0 + 1.0 / (facing * facing));
  float extra;
  vec4 g = groundNoises(p, fw, extra);
  // far away a mark narrows away to nothing instead of thinning into a shimmering line
  float edge = vMark.y * halfWidth - halfWidth * smoothstep(${glslFloat(FADE[0])}, ${glslFloat(FADE[1])}, dist);
  // the ragged border eats up to the kind's rag into the mark (at most most of a narrow one), along noise at 4 m, 1 m
  // and 0.4 m
  float ragNoise = clamp(extra * 0.45 + g.z * 0.35 + gFine(p + 23.0, 2.7, fw) * 0.2, 0.0, 1.0);
  float rag = min(MARK_RAG[kind], 0.8 * halfWidth) * (0.15 + 0.85 * ragNoise);
  vec3 color = MARK_BASE[kind];
  markRoughness = MARK_ROUGHNESS[kind];
#ifndef MARK_FLAT
  if (dist < MARK_PATTERN_END) {
    float roughness = markRoughness;
    vec4 look = markLook(kind, p, across, edge, vMarkPerp, fw, g, roughness);
    float far = smoothstep(MARK_PATTERN_END * 0.8, MARK_PATTERN_END, dist);
    color = mix(look.rgb, color, far);
    markRoughness = mix(roughness, markRoughness, far);
    markRelief = (look.a - 0.5) * MARK_DEPTH[kind] * (1.0 - smoothstep(0.015, 0.05, fw)) * (1.0 - smoothstep(30.0, 40.0, dist));
  }
  color *= 0.92 + 0.16 * g.x;
#endif
  diffuseColor.rgb = color;
  diffuseColor.a = 0.5 + edge - rag;
}
`;

const FRAGMENT_NORMAL = /* glsl */ `
{
  vec3 facet = normalize(cross(dFdx(vViewPosition), dFdy(vViewPosition)));
  float fade = 1.0 - smoothstep(markFacetsFade.x, markFacetsFade.y, length(vViewPosition));
  normal = normalize(mix(normal, facet, markFacets * fade));
#ifdef MARK_BUMP
  normal = groundBump(-vViewPosition, normal, markRelief);
#endif
}
`;

/**
 * The marks' material: lit, shadowed and fogged like the ground; its ragged borders fade by alpha to coverage while
 * the colour is written opaque and the alpha already in the frame is kept (the canvas shows through nothing).
 */
export function markMaterial(quality: GroundQuality = 'full') {
  const material = new MeshStandardMaterial({
    roughness: 1,
    alphaTest: 0.5,
    alphaToCoverage: true,
    blending: CustomBlending,
    blendSrc: OneFactor,
    blendDst: ZeroFactor,
    blendSrcAlpha: ZeroFactor,
    blendDstAlpha: OneFactor,
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  });
  const defines: Record<string, string> = {
    MARK_PATTERN_END: glslFloat(
      PATTERN_END[quality === 'low' ? 'low' : 'full'],
    ),
  };
  if (quality === 'flat') defines.MARK_FLAT = '';
  if (quality === 'full') defines.MARK_BUMP = '';
  material.defines = defines;
  const pixel = { value: 0.002 };
  const buffer = new Vector2();
  material.onBeforeRender = (renderer, _scene, camera) => {
    const { fov } = camera as PerspectiveCamera;
    pixel.value =
      (2 * Math.tan((fov * Math.PI) / 360)) /
      renderer.getDrawingBufferSize(buffer).y;
  };
  material.onBeforeCompile = (shader) => {
    shader.uniforms.markPixel = pixel;
    shader.uniforms.markFacets = { value: FACETS };
    shader.uniforms.markFacetsFade = { value: FACETS_FADE };
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', `#include <common>\n${VERTEX_COMMON}`)
      .replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>\n${VERTEX_MAIN}`,
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>\n${groundLookGlsl()}\n${markConstants()}\n${FRAGMENT_COMMON}\n${MARK_STYLE.patterns}`,
      )
      .replace(
        '#include <color_fragment>',
        `#include <color_fragment>\n${FRAGMENT_COLOR}`,
      )
      .replace(
        '#include <roughnessmap_fragment>',
        '#include <roughnessmap_fragment>\nroughnessFactor = markRoughness;',
      )
      .replace(
        '#include <normal_fragment_maps>',
        `#include <normal_fragment_maps>\n${FRAGMENT_NORMAL}`,
      );
  };
  material.customProgramCacheKey = () => `marks-${quality}`;
  return material;
}
