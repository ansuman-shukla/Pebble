/*
 * Dens and claim markers on the globe (10 §1.5, §1.6, §4.6), from the world's places. A den is a cave mouth with
 * bones scattered at it: the den's spot (where its predators sleep and from where they charge) is the mouth, the
 * cave stands behind it and opens toward its hotspot, and two scatters of bones lie before it. A claimed hotspot's
 * marker stands where its owner's road or path enters it, on the roadside (half the drawn route's width and a metre
 * off its middle line, square to it, on the side the marker's spot lies, else on the right going in), facing the road: the town's a
 * boundary stone with a banner beside it, a band's a cairn with a hide streamer. Each piece stands on the drawn
 * ground under it.
 */
import { Matrix4, Vector3 } from 'three';

import type { Feature, WorldPlaces } from '@/lib/client/types.gen';
import { tangent, tangentFrame } from '@/lib/world/globe';

/** The cave mouth stands this far behind the den's spot (half its 1.9 m depth, and a little room). */
export const CAVE_BACK_M = 1.5;
/** The bones lie this far before the den's spot, toward the hotspot, two scatters this far apart across. */
export const BONES_OUT_M = 1.8;
export const BONES_APART_M = 1.4;
/** The bones are drawn this much larger than the scatter model (0.9 x 1.5 m is lost at a cave's mouth). */
export const BONES_SCALE = 1.5;
/** A marker stands this far past the edge of the route it marks. */
export const ROADSIDE_M = 1;
/** The town's banner stands this far beside its boundary stone (along the stone's +x). */
export const BANNER_SIDE_M = 1.1;
/** A band's hide streamer stands this far beside its cairn (along the cairn's −x). */
export const STREAMER_SIDE_M = 0.7;
/** The boundary stone: the garden rock (0.9 x 0.5 x 0.8 m) stood up as a waist-high stone. */
export const STONE_SCALE = new Vector3(1.3, 2.4, 1.3);

export interface WildMarks {
  caves: Matrix4[];
  bones: Matrix4[];
  stones: Matrix4[];
  banners: Matrix4[];
  cairns: Matrix4[];
  streamers: Matrix4[];
}

/** The surface height (metres above sea level) under a unit direction. */
type HeightAt = (direction: Vector3) => number;

const ONE = new Vector3(1, 1, 1);

/** A model's frame at a unit direction, its front (+z) along `front`, standing on the ground there. */
function standing(
  direction: Vector3,
  front: Vector3,
  heightAt: HeightAt,
  radius: number,
  scale: Vector3 = ONE,
) {
  const z = tangent(front.clone(), direction);
  const x = new Vector3().crossVectors(direction, z);
  return new Matrix4()
    .makeBasis(x, direction, z)
    .scale(scale)
    .setPosition(
      direction.clone().multiplyScalar(radius + heightAt(direction)),
    );
}

/** The unit direction `metres` from `direction` along the tangent `along`. */
function stepped(
  direction: Vector3,
  along: Vector3,
  metres: number,
  radius: number,
) {
  return direction
    .clone()
    .multiplyScalar(radius)
    .addScaledVector(along, metres)
    .normalize();
}

/** The tangent at a feature toward its hotspot's centre (south where it has none or stands on it). */
function towardHotspot(feature: Feature, places: WorldPlaces) {
  const at = new Vector3(...feature.position);
  const hotspot = places.hotspots.find((spot) => spot.id === feature.hotspot);
  const centre = hotspot ? new Vector3(...hotspot.centre) : at;
  return tangent(centre.clone().sub(at), at, tangentFrame(at).south);
}

/** A drawn road or path (ground-marks.ts ribbons): its width and its middle line, a unit direction every metre. */
export interface DrawnRoute {
  width: number;
  points: Vector3[];
}

interface Roadside {
  /** Where the marker stands: on the roadside, off the route's middle line. */
  at: Vector3;
  /** The tangent from there to the route's middle line (the way it faces). */
  toRoad: Vector3;
}

/**
 * Where a marker at `spot` stands: off the nearest drawn route by half its width plus ROADSIDE_M, square to the
 * route there, on the side the spot lies (on the right going toward `inward` when the spot is on the line).
 */
function roadside(
  spot: Vector3,
  inward: Vector3,
  routes: readonly DrawnRoute[],
  radius: number,
): Roadside | null {
  let best: { route: DrawnRoute; index: number; gap: number } | null = null;
  for (const route of routes)
    route.points.forEach((point, index) => {
      const gap = point.angleTo(spot);
      if (!best || gap < best.gap) best = { route, index, gap };
    });
  if (!best) return null;
  const { route, index, gap } = best as {
    route: DrawnRoute;
    index: number;
    gap: number;
  };
  const { points } = route;
  const point = points[index];
  const ahead = points[Math.min(index + 1, points.length - 1)];
  const behind = points[Math.max(index - 1, 0)];
  const along = tangent(ahead.clone().sub(behind), point);
  const across = new Vector3().crossVectors(along, point); // right of the way along
  let sign = Math.sign(spot.clone().sub(point).dot(across));
  if (gap * radius < 0.05 || sign === 0) sign = along.dot(inward) >= 0 ? 1 : -1;
  const at = stepped(
    point,
    across,
    sign * (route.width / 2 + ROADSIDE_M),
    radius,
  );
  return { at, toRoad: across.clone().multiplyScalar(-sign) };
}

export function wildMarks(
  places: WorldPlaces,
  routes: readonly DrawnRoute[],
  heightAt: HeightAt,
  radius: number,
): WildMarks {
  const marks: WildMarks = {
    caves: [],
    bones: [],
    stones: [],
    banners: [],
    cairns: [],
    streamers: [],
  };
  const bonesScale = new Vector3(BONES_SCALE, BONES_SCALE, BONES_SCALE);
  for (const feature of places.features) {
    const at = new Vector3(...feature.position);
    const inward = towardHotspot(feature, places);
    if (feature.kind === 'den') {
      const cave = stepped(at, inward, -CAVE_BACK_M, radius);
      marks.caves.push(standing(cave, inward, heightAt, radius));
      const across = new Vector3().crossVectors(at, inward).normalize();
      const out = stepped(at, inward, BONES_OUT_M, radius);
      for (const side of [-1, 1]) {
        const bones = stepped(out, across, (side * BONES_APART_M) / 2, radius);
        // the second scatter lies askew, as a predator dragged it
        const lie = inward.clone().applyAxisAngle(bones, side * 0.6);
        marks.bones.push(standing(bones, lie, heightAt, radius, bonesScale));
      }
    } else if (feature.kind === 'marker') {
      const place = roadside(at, inward, routes, radius) ?? {
        at,
        toRoad: inward.clone().negate(),
      };
      const beside = new Vector3()
        .crossVectors(place.at, place.toRoad)
        .normalize(); // the piece's +x
      if (feature.owner === 'town') {
        marks.stones.push(
          standing(place.at, place.toRoad, heightAt, radius, STONE_SCALE),
        );
        const banner = stepped(place.at, beside, BANNER_SIDE_M, radius);
        marks.banners.push(standing(banner, place.toRoad, heightAt, radius));
      } else {
        marks.cairns.push(standing(place.at, place.toRoad, heightAt, radius));
        const streamer = stepped(place.at, beside, -STREAMER_SIDE_M, radius);
        marks.streamers.push(
          standing(streamer, place.toRoad, heightAt, radius),
        );
      }
    }
  }
  return marks;
}
