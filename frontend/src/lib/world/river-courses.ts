/*
 * Where the rivers run and how wide: each river's cell path smoothed into a curve (the zig-zag from cell to
 * cell averaged out, then a Catmull-Rom spline sampled every few metres), its width growing with the water that
 * has joined it (thin at the spring, wider downstream, fanning out at the mouth), its flow speed set by the
 * slope, and the curve split into dry runs: a run stops at the shore of the sea or a lake (a few metres past it,
 * fading out, so the ribbon never lies over open water), at a site's own ground (the town) and at a waterfall,
 * where the river drops off a cliff and falls as a sheet instead of running down the face.
 */
import { Vector3 } from 'three';

import type { Point } from './collision';
import {
  cellDirection,
  type GlobeTerrain,
  type SiteMapping,
  tangent,
  WATER_BIOMES,
  WATER_SURFACE,
} from './globe';

/** Metres between samples along a river. */
const STEP = 4;
/** [1, 2, 1] / 4 passes over the cell path: one cancels the cell-to-cell zig-zag, the second rounds the bends. */
const SMOOTHING_PASSES = 2;
/** A smoothed river may run this far (metres) above its straight cell path before it is pulled back. */
const CLIMB = 1;
/** Samples over which that pull eases in and out. */
const EASE = 4;
/** Width (metres) of a river carrying `flow` cells of water: WIDTH_BASE + WIDTH_GAIN·√flow, at most WIDTH_MAX. */
const WIDTH_BASE = 2;
const WIDTH_GAIN = 1.15;
const WIDTH_MAX = 13;
/** Width at the very spring, growing to the river's own width over SOURCE_TAPER metres. */
const SPRING_WIDTH = 0.5;
const SOURCE_TAPER = 40;
/** Over the last MOUTH_FAN metres before the shore a river widens by up to MOUTH_SPREAD of its width. */
const MOUTH_FAN = 30;
const MOUTH_SPREAD = 0.45;
/** A ribbon runs on this far past the shore (or begins this far inside a lake it leaves), fading out. */
const SHORE_OVERRUN = 4;
/** The fade at the ends of a run (metres): into or out of open water, at a join, at a site's ground. */
const FADE = 10;
/** Flow speed (m/s): FLOW_BASE on the level, FLOW_GAIN per unit of slope, at most FLOW_MAX. */
const FLOW_BASE = 0.6;
const FLOW_GAIN = 6;
const FLOW_MAX = 5;
/** A river that drops at least FALL_DROP metres at a slope of at least FALL_SLOPE falls instead of running. */
const FALL_SLOPE = 0.7;
const FALL_DROP = 12;
/** A river leaving a lake carries at least this many cells of water. */
const OUTFLOW_FLOW = 12;
/** A river within this many metres of a channel's end as it reaches a site is led into the channel... */
const CHANNEL_REACH = 60;
/** ...bending onto the channel's line over this many metres before (and after) it. */
const CHANNEL_APPROACH = 45;
/** A river kept off a site's ground runs this far (metres) outside its edge. */
const SITE_MARGIN = 8;
/** [1, 2, 1] / 4 passes over the bent or pushed part of a course. */
const ROUTE_SMOOTHING = 6;
/** Shore and site edges are found to this many halvings of a step (4 m / 2⁸ ≈ 2 cm). */
const EDGE_REFINE = 8;

interface RiverPoint {
  /** Unit direction of the centreline. */
  direction: Vector3;
  /** Water surface height above sea level (before the ribbon's lift). */
  height: number;
  /** Width of the water, metres. */
  width: number;
  /** Metres downstream from the river's source. */
  along: number;
  /** Flow speed, m/s. */
  speed: number;
  /** 1 on the open river, down to 0 where the ribbon begins, ends or joins other water. */
  fade: number;
  /** True in a site's channel: the water lies flat at `height` instead of following the ground. */
  flat: boolean;
}

/** A stretch of river drawn as one ribbon. */
interface RiverRun {
  river: number;
  points: RiverPoint[];
}

/** Where a river drops off a cliff. */
export interface Waterfall {
  river: number;
  /** Unit direction of the lip and the water height there. */
  lip: Vector3;
  lipHeight: number;
  /** Unit direction where the water lands and its height there (the pool's surface when it lands in water). */
  foot: Vector3;
  footHeight: number;
  width: number;
  /** True when the fall lands in a lake or the sea (it gets a ring of foam). */
  intoWater: boolean;
}

export interface RiverLayout {
  runs: RiverRun[];
  falls: Waterfall[];
}

/** A cone of directions the rivers stay out of (a site that lays its own ground and water). */
interface RiverHole {
  up: Vector3;
  /** Angular radius, radians. */
  angle: number;
}

/** A straight channel through a site's ground (the town's mill stream) that a river passing the site runs in. */
export interface RiverChannel {
  /** Unit directions of the channel's two ends. */
  ends: [Vector3, Vector3];
  width: number;
  /** Height of its water surface above sea level. */
  height: number;
}

/** A site's ground the rivers keep out of, except through its channels. */
export interface RiverSite {
  hole: RiverHole;
  channels: RiverChannel[];
}

/**
 * The channels of a site's straight streams (four-sided water areas of kind `stream`): from the middle of one
 * short side to the other, as wide as the short sides, `waterY` below the site's plateau.
 */
export function streamChannels(
  water: { kind: string; polygon: Point[] }[],
  mapping: SiteMapping,
  plateau: number,
  waterY: number,
): RiverChannel[] {
  return water
    .filter((area) => area.kind === 'stream' && area.polygon.length === 4)
    .map(({ polygon }) => {
      const side = (k: number) => {
        const [a, b] = [polygon[k], polygon[(k + 1) % 4]];
        return {
          length: Math.hypot(b[0] - a[0], b[1] - a[1]),
          middle: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] as Point,
        };
      };
      // the short sides are opposite each other: 0 and 2, or 1 and 3
      const [first, second] =
        side(0).length <= side(1).length
          ? [side(0), side(2)]
          : [side(1), side(3)];
      const end = ({ middle: [x, z] }: { middle: Point }) =>
        mapping.toWorld(x, waterY, z, new Vector3()).normalize();
      return {
        ends: [end(first), end(second)],
        width: (first.length + second.length) / 2,
        height: plateau + waterY,
      };
    });
}

/** A lake's shore counts as water this far (metres) above the lake's surface. */
const LAKE_SHORE = 0.05;

/**
 * Whether the ground at a direction lies under the sea or a lake's surface (not just inside a water cell: the
 * ground of a water cell still slopes up towards its dry neighbours).
 */
export function isOpenWater(
  terrain: GlobeTerrain,
  direction: Vector3,
  hint?: number,
) {
  const { biomes, heights } = terrain.globe;
  const height = terrain.heightAt(direction, hint);
  if (height <= WATER_SURFACE) return true;
  const cell = terrain.nearestCell(direction, hint);
  return WATER_BIOMES.has(biomes[cell]) && height <= heights[cell] + LAKE_SHORE;
}

const smoothstep = (edge0: number, edge1: number, x: number) => {
  const t = Math.min(Math.max((x - edge0) / (edge1 - edge0), 0), 1);
  return t * t * (3 - 2 * t);
};

const widthFor = (flow: number) =>
  Math.min(WIDTH_BASE + WIDTH_GAIN * Math.sqrt(flow), WIDTH_MAX);

/** Cells of water each river carries at each of its cells: its own length so far plus the rivers joined. */
function riverFlows(terrain: GlobeTerrain, rivers: number[][]) {
  const { biomes } = terrain.globe;
  const lakeOf = lakeComponents(terrain);
  const flows = rivers.map((cells) => cells.map((_, i) => i + 1));
  // rivers end on the river they join, or in a lake whose outflow carries them on
  const endsIn = new Map<number, number[]>();
  rivers.forEach((cells, r) => {
    const last = cells[cells.length - 1];
    const key = WATER_BIOMES.has(biomes[last])
      ? -1 - (lakeOf[last] ?? 0)
      : last;
    endsIn.set(key, [...(endsIn.get(key) ?? []), r]);
  });
  for (let pass = 0; pass < rivers.length; pass++) {
    let changed = false;
    rivers.forEach((cells, r) => {
      const first = cells[0];
      let carried =
        lakeOf[first] !== undefined
          ? Math.max(
              OUTFLOW_FLOW,
              ...(endsIn.get(-1 - lakeOf[first]) ?? [])
                .filter((other) => other !== r)
                .map((other) => flows[other][flows[other].length - 1]),
            )
          : 0;
      cells.forEach((cell, i) => {
        for (const other of endsIn.get(cell) ?? [])
          if (other !== r) carried += flows[other][flows[other].length - 1];
        const flow = i + 1 + carried;
        if (flow !== flows[r][i]) {
          flows[r][i] = flow;
          changed = true;
        }
      });
    });
    if (!changed) break;
  }
  return flows;
}

/** Lake cells labelled by the connected lake they belong to. */
function lakeComponents(terrain: GlobeTerrain) {
  const { biomes, heights, cellCount } = terrain.globe;
  const label: (number | undefined)[] = new Array(cellCount);
  let next = 0;
  const isLake = (cell: number) =>
    WATER_BIOMES.has(biomes[cell]) && heights[cell] > WATER_SURFACE;
  for (let cell = 0; cell < cellCount; cell++) {
    if (!isLake(cell) || label[cell] !== undefined) continue;
    const stack = [cell];
    label[cell] = next;
    while (stack.length > 0) {
      for (const neighbour of terrain.neighbours(stack.pop()!))
        if (isLake(neighbour) && label[neighbour] === undefined) {
          label[neighbour] = next;
          stack.push(neighbour);
        }
    }
    next += 1;
  }
  return label;
}

/** The cell path averaged with [1, 2, 1] / 4 a few times, the ends kept. */
function smoothPath(points: Vector3[]) {
  let current = points.map((point) => point.clone());
  for (let pass = 0; pass < SMOOTHING_PASSES; pass++)
    current = current.map((point, i) =>
      i === 0 || i === current.length - 1
        ? point.clone()
        : point
            .clone()
            .multiplyScalar(2)
            .add(current[i - 1])
            .add(current[i + 1])
            .normalize(),
    );
  return current;
}

/** Uniform Catmull-Rom through the points (ends doubled), `per` samples per segment, on the unit sphere. */
function spline(points: Vector3[], per: number) {
  const samples: { direction: Vector3; index: number }[] = [];
  if (points.length === 1) return [{ direction: points[0].clone(), index: 0 }];
  const at = (i: number) => points[Math.min(Math.max(i, 0), points.length - 1)];
  for (let i = 0; i + 1 < points.length; i++) {
    const [p0, p1, p2, p3] = [at(i - 1), at(i), at(i + 1), at(i + 2)];
    for (let s = 0; s < per; s++) {
      const t = s / per;
      const t2 = t * t;
      const t3 = t2 * t;
      const point = new Vector3()
        .addScaledVector(p0, -t3 + 2 * t2 - t)
        .addScaledVector(p1, 3 * t3 - 5 * t2 + 2)
        .addScaledVector(p2, -3 * t3 + 4 * t2 + t)
        .addScaledVector(p3, t3 - t2)
        .normalize();
      samples.push({ direction: point, index: i + t });
    }
  }
  samples.push({
    direction: points[points.length - 1].clone(),
    index: points.length - 1,
  });
  return samples;
}

/**
 * The river's centreline: the spline through the smoothed path wherever it stays in the river's valley, eased
 * back towards the spline through the cells themselves wherever it would climb more than CLIMB metres above
 * that (an authored channel is cut into the ground cell by cell, and smoothing must not lift the river out).
 */
function centreline(
  terrain: GlobeTerrain,
  cells: number[],
  per: number,
): { direction: Vector3; index: number }[] {
  const raw = cells.map((cell) =>
    cellDirection(terrain.globe, cell, new Vector3()),
  );
  const smooth = spline(smoothPath(raw), per);
  const hint = (index: number) => cells[Math.round(index)];
  // the same spline through the cells themselves: it stays in a channel cut cell by cell
  const straight = spline(raw, per).map(({ direction }) => direction);
  const blend = (i: number, amount: number) =>
    straight[i].clone().lerp(smooth[i].direction, amount).normalize();
  const allowed = smooth.map(({ index }, i) => {
    const limit = terrain.heightAt(straight[i], hint(index)) + CLIMB;
    const fits = (amount: number) =>
      terrain.heightAt(blend(i, amount), hint(index)) <= limit;
    if (fits(1)) return 1;
    let [low, high] = [0, 1];
    for (let k = 0; k < 5; k++) {
      const middle = (low + high) / 2;
      if (fits(middle)) low = middle;
      else high = middle;
    }
    return low;
  });
  // ease the pull in and out: a running minimum, then a running mean (never above the allowed amount)
  const window = (i: number) =>
    allowed.slice(Math.max(i - EASE, 0), i + EASE + 1);
  const eroded = allowed.map((_, i) => Math.min(...window(i)));
  return smooth.map(({ index }, i) => {
    const near = eroded.slice(Math.max(i - EASE, 0), i + EASE + 1);
    const amount = near.reduce((sum, value) => sum + value, 0) / near.length;
    return { direction: blend(i, amount), index };
  });
}

type Block = 'water' | 'hole' | null;

/** A point the river passes: from its centreline, or routed through a site's channel. */
interface Guide {
  direction: Vector3;
  /** Nearest cell along the river (a lookup hint). */
  cell: number;
  flow: number;
  /** Set on points led into or along a channel: they may enter the site's ground. */
  routed?: boolean;
  /** In a channel: its water height and width. */
  level?: number;
  minWidth?: number;
}

/**
 * Keeps a river off a site's ground. Where it reaches the ground near one end of a channel (within
 * CHANNEL_REACH) it is led through: its course up to the point nearest the channel's far end becomes the
 * channel's line, and the points before and after bend onto that line over CHANNEL_APPROACH metres, so the
 * ribbon flows straight into one end and out of the other. Anywhere else a river grazing the ground is pushed
 * out to run along its edge.
 */
function throughChannels(
  guides: Guide[],
  site: RiverSite,
  unused: Set<RiverChannel>,
  radius: number,
) {
  const { up, angle } = site.hole;
  const holeCos = Math.cos(angle);
  const inside = (guide: Guide) => guide.direction.dot(up) > holeCos;
  const distance = (a: Vector3, b: Vector3) => a.angleTo(b) * radius;
  const rest = guides.map((guide) => ({
    ...guide,
    direction: guide.direction.clone(),
  }));
  const result: Guide[] = [];
  /** Bends a guide onto the channel's line extended past `end` (away from `other`). */
  const bend = (guide: Guide, end: Vector3, other: Vector3) => {
    const away = distance(guide.direction, end);
    if (away >= CHANNEL_APPROACH) return false;
    const onLine = end
      .clone()
      .addScaledVector(end.clone().sub(other).normalize(), away / radius)
      .normalize();
    guide.direction
      .lerp(onLine, 1 - smoothstep(0, CHANNEL_APPROACH, away))
      .normalize();
    guide.routed = true;
    return true;
  };
  /** Moves a guide inside the ground out to just past its edge. */
  const pushOut = (guide: Guide) => {
    const outward = tangent(guide.direction.clone(), up);
    const edge = angle + SITE_MARGIN / radius;
    guide.direction
      .copy(up)
      .multiplyScalar(Math.cos(edge))
      .addScaledVector(outward, Math.sin(edge));
    guide.routed = true;
    return guide;
  };
  for (let i = 0; i < rest.length;) {
    const entry = rest[i];
    if (!inside(entry)) {
      result.push(entry);
      i += 1;
      continue;
    }
    const nearest = [...unused]
      .flatMap((channel) =>
        channel.ends.map((end, k) => ({
          channel,
          from: end,
          to: channel.ends[1 - k],
          away: distance(entry.direction, end),
        })),
      )
      .sort((a, b) => a.away - b.away)[0];
    if (!nearest || nearest.away > CHANNEL_REACH) {
      result.push(pushOut(entry));
      i += 1;
      continue;
    }
    const { channel, from, to } = nearest;
    unused.delete(channel);
    for (let k = result.length - 1; k >= 0; k--)
      if (!bend(result[k], from, to)) break;
    // the river may weave in and out of the ground beside the channel: the channel replaces its course up to
    // the point nearest the channel's far end
    let closest = i;
    for (let k = i; k < rest.length; k++)
      if (
        distance(rest[k].direction, to) < distance(rest[closest].direction, to)
      )
        closest = k;
    const exit = rest[closest];
    const steps = Math.max(1, Math.ceil(distance(from, to) / STEP));
    for (let s = 0; s <= steps; s++)
      result.push({
        direction: from
          .clone()
          .lerp(to, s / steps)
          .normalize(),
        cell: (s < steps / 2 ? entry : exit).cell,
        flow: entry.flow + (exit.flow - entry.flow) * (s / steps),
        routed: true,
        level: channel.height,
        minWidth: channel.width,
      });
    i = closest + 1;
    for (let k = i; k < rest.length; k++) if (!bend(rest[k], to, from)) break;
  }
  // round off the corners where the course was bent or pushed, and a few points either side (the channel
  // itself stays straight)
  const near = result.map((_, k) =>
    result
      .slice(Math.max(k - ROUTE_SMOOTHING, 0), k + ROUTE_SMOOTHING + 1)
      .some((guide) => guide.routed),
  );
  near.forEach((smooth, k) => {
    if (smooth) result[k].routed = true;
  });
  for (let pass = 0; pass < ROUTE_SMOOTHING; pass++)
    result.forEach((guide, k) => {
      const [before, after] = [result[k - 1], result[k + 1]];
      if (!near[k] || guide.level !== undefined || !before || !after) return;
      guide.direction
        .multiplyScalar(2)
        .add(before.direction)
        .add(after.direction)
        .normalize();
    });
  return result;
}

export function riverLayout(
  terrain: GlobeTerrain,
  rivers: number[][],
  site: RiverSite | null = null,
): RiverLayout {
  const { globe } = terrain;
  const { radius } = globe;
  const flows = riverFlows(terrain, rivers);
  const hole = site?.hole;
  const holeCos = hole ? Math.cos(hole.angle) : 2;
  const blockAt = (direction: Vector3, hint: number, routed = false): Block => {
    if (hole && !routed && direction.dot(hole.up) > holeCos) return 'hole';
    return isOpenWater(terrain, direction, hint) ? 'water' : null;
  };
  /** The last free point between a free and a blocked one (by bisection). */
  const edge = (free: Vector3, blocked: Vector3, hint: number) => {
    let [low, high] = [free, blocked];
    for (let k = 0; k < EDGE_REFINE; k++) {
      const middle = low.clone().lerp(high, 0.5).normalize();
      if (blockAt(middle, hint)) high = middle;
      else low = middle;
    }
    return low;
  };
  const runs: RiverRun[] = [];
  const falls: Waterfall[] = [];
  // each channel carries the first river that reaches it
  const unusedChannels = new Set(site?.channels ?? []);

  /** The surface of the water at a direction: its lake's height, else the sea's. */
  const waterLevel = (direction: Vector3) => {
    const cell = terrain.nearestCell(direction);
    return WATER_BIOMES.has(globe.biomes[cell])
      ? Math.max(globe.heights[cell], WATER_SURFACE)
      : WATER_SURFACE;
  };

  rivers.forEach((cells, r) => {
    if (cells.length < 2) return;
    const segment =
      cellDirection(globe, cells[0], new Vector3()).angleTo(
        cellDirection(globe, cells[1], new Vector3()),
      ) * radius;
    const per = Math.max(2, Math.round(segment / STEP));
    // a river that leaves a lake starts at full width; a spring starts thin
    const spring = !WATER_BIOMES.has(globe.biomes[cells[0]]);
    type Sample = Guide & { block: Block; height: number; along: number };
    let guides: Guide[] = centreline(terrain, cells, per).map(
      ({ direction, index }) => {
        const k = Math.min(Math.floor(index), cells.length - 1);
        const f = index - k;
        const next = Math.min(k + 1, cells.length - 1);
        return {
          direction,
          cell: cells[Math.round(index)],
          flow: flows[r][k] * (1 - f) + flows[r][next] * f,
        };
      },
    );
    if (site) guides = throughChannels(guides, site, unusedChannels, radius);
    let along = 0;
    const samples: Sample[] = guides.map((guide, i) => {
      if (i > 0)
        along += guides[i - 1].direction.angleTo(guide.direction) * radius;
      return {
        ...guide,
        block:
          guide.level === undefined
            ? blockAt(guide.direction, guide.cell, guide.routed)
            : null,
        height:
          guide.level ??
          Math.max(
            terrain.heightAt(guide.direction, guide.cell),
            WATER_SURFACE,
          ),
        along,
      };
    });

    // falls: steep dry stretches that drop far enough; the river leaves the ground at the lip
    const steep = samples.map((sample, i) => {
      const next = samples[i + 1];
      if (!next || sample.block || next.block === 'hole') return false;
      const run = next.along - sample.along;
      return run > 0 && (sample.height - next.height) / run >= FALL_SLOPE;
    });
    const fallAt = new Map<number, number>(); // lip index -> foot index
    for (let i = 0; i < samples.length;) {
      if (!steep[i]) {
        i += 1;
        continue;
      }
      let j = i;
      while (steep[j]) j += 1;
      if (samples[i].height - samples[j].height >= FALL_DROP) fallAt.set(i, j);
      i = j;
    }

    const width = (sample: Sample) =>
      Math.max(
        sample.minWidth ?? 0,
        spring
          ? SPRING_WIDTH +
              (widthFor(sample.flow) - SPRING_WIDTH) *
                smoothstep(0, SOURCE_TAPER, sample.along)
          : widthFor(sample.flow),
      );
    const speedAt = (i: number) => {
      const a = samples[Math.max(i - 1, 0)];
      const b = samples[Math.min(i + 1, samples.length - 1)];
      const run = b.along - a.along;
      const slope = run > 0 ? Math.max(0, (a.height - b.height) / run) : 0;
      return Math.min(FLOW_BASE + FLOW_GAIN * slope, FLOW_MAX);
    };

    /** Ends of the current run: why it started and the point it started at. */
    let run: RiverPoint[] = [];
    let startsFrom: 'source' | 'water' | 'hole' | 'fall' = 'source';
    const point = (
      direction: Vector3,
      sample: Sample,
      i: number,
      along = sample.along,
    ): RiverPoint => ({
      direction,
      height:
        sample.level ??
        Math.max(terrain.heightAt(direction, sample.cell), WATER_SURFACE),
      width: width(sample),
      along,
      speed: speedAt(i),
      fade: 1,
      flat: sample.level !== undefined,
    });
    const finish = (endsAt: 'water' | 'hole' | 'fall' | 'join') => {
      if (run.length >= 2) {
        shapeEnds(run, startsFrom, endsAt);
        runs.push({ river: r, points: run });
      }
      run = [];
    };

    for (let i = 0; i < samples.length; i++) {
      const sample = samples[i];
      const previous = samples[i - 1];
      if (sample.block) {
        if (run.length > 0 && previous) {
          const shore = edge(previous.direction, sample.direction, sample.cell);
          const shoreAlong =
            previous.along + previous.direction.angleTo(shore) * radius;
          run.push(point(shore, sample, i, shoreAlong));
          if (sample.block === 'water') overrun(run, radius, 1);
          finish(sample.block);
        }
        startsFrom = sample.block;
        continue;
      }
      if (run.length === 0 && previous?.block) {
        const shore = edge(sample.direction, previous.direction, sample.cell);
        const shoreAlong =
          sample.along - sample.direction.angleTo(shore) * radius;
        run.push(point(shore, sample, i, shoreAlong));
        if (previous.block === 'water') overrun(run, radius, -1);
      }
      run.push(point(sample.direction, sample, i));
      const foot = fallAt.get(i);
      if (foot !== undefined) {
        const landing = samples[foot];
        const intoWater = landing.block === 'water';
        const footDirection = intoWater
          ? edge(samples[foot - 1].direction, landing.direction, landing.cell)
          : landing.direction;
        falls.push({
          river: r,
          lip: sample.direction.clone(),
          lipHeight: sample.height,
          foot: footDirection,
          footHeight: intoWater
            ? waterLevel(landing.direction)
            : landing.height,
          width: width(sample),
          intoWater,
        });
        finish('fall');
        startsFrom = 'fall';
        // the ribbon picks up again where the water lands on dry ground
        i = foot - 1;
        if (!intoWater) {
          run.push(point(landing.direction, landing, foot));
          i = foot;
        }
      }
    }
    finish('join');
  });
  return { runs, falls };
}

/**
 * Carries a run past the shore it starts (side −1) or ends (side +1) at by SHORE_OVERRUN metres, straight on
 * along the river, so the ribbon fades into the water instead of stopping at a hard line.
 */
function overrun(run: RiverPoint[], radius: number, side: 1 | -1) {
  const [shore, inland] =
    side === 1 ? [run[run.length - 1], run[run.length - 2]] : [run[0], run[1]];
  if (!inland) return;
  const heading = shore.direction
    .clone()
    .sub(inland.direction)
    .normalize()
    .multiplyScalar(SHORE_OVERRUN / radius);
  const beyond: RiverPoint = {
    ...shore,
    direction: shore.direction.clone().add(heading).normalize(),
    along: shore.along + side * SHORE_OVERRUN,
  };
  if (side === 1) run.push(beyond);
  else run.unshift(beyond);
}

/**
 * Fades and widths at a run's ends: a spring tapers in (the width already does), a river fans out towards its
 * mouth, and every end that meets other water, a site's ground or a join fades out over FADE metres.
 */
function shapeEnds(
  run: RiverPoint[],
  startsFrom: 'source' | 'water' | 'hole' | 'fall',
  endsAt: 'water' | 'hole' | 'fall' | 'join',
) {
  const first = run[0].along;
  const last = run[run.length - 1].along;
  for (const point of run) {
    const fromStart = point.along - first;
    const toEnd = last - point.along;
    if (startsFrom === 'source')
      point.fade *= smoothstep(0, FADE / 2, fromStart);
    if (startsFrom === 'water' || startsFrom === 'hole')
      point.fade *= smoothstep(0, FADE, fromStart);
    if (endsAt === 'water') {
      point.width *=
        1 + MOUTH_SPREAD * smoothstep(MOUTH_FAN, SHORE_OVERRUN, toEnd);
      point.fade *= smoothstep(0, FADE, toEnd);
    }
    if (endsAt === 'hole' || endsAt === 'join')
      point.fade *= smoothstep(0, FADE, toEnd);
  }
}
