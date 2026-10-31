/*
 * Dens and claim markers on the globe (10 §1.5, §1.6, §4.6), from the world's places. A den is a cave mouth with a
 * scatter of bones at it: the den's spot (where its predators sleep and from where they charge) is the mouth, the
 * cave stands behind it and opens toward its hotspot, and the bones lie before it. A claimed hotspot's marker
 * stands where its owner's road or path enters it, facing out to whoever comes: the town's a boundary stone with a
 * banner beside it, a band's a cairn. Each piece stands on the drawn ground under it.
 */
import { Matrix4, Vector3 } from 'three';

import type { Feature, WorldPlaces } from '@/lib/client/types.gen';
import { tangent, tangentFrame } from '@/lib/world/globe';

/** The cave mouth stands this far behind the den's spot (half its 1.9 m depth, and a little room). */
export const CAVE_BACK_M = 1.5;
/** The bones lie this far before the den's spot, toward the hotspot. */
export const BONES_OUT_M = 1.8;
/** The bones are drawn this much larger than the scatter model (0.9 x 1.5 m is lost at a cave's mouth). */
export const BONES_SCALE = 1.5;
/** The town's banner stands this far beside its boundary stone (along the stone's +x). */
export const BANNER_SIDE_M = 0.9;
/** The boundary stone is drawn this much larger than the garden rock it is (0.5 m tall is a pebble at a road). */
export const STONE_SCALE = 1.6;

export interface WildMarks {
  caves: Matrix4[];
  bones: Matrix4[];
  stones: Matrix4[];
  banners: Matrix4[];
  cairns: Matrix4[];
}

/** The surface height (metres above sea level) under a unit direction. */
type HeightAt = (direction: Vector3) => number;

/** A model's frame at a unit direction, its front (+z) along `front`, standing on the ground there. */
function standing(
  direction: Vector3,
  front: Vector3,
  heightAt: HeightAt,
  radius: number,
  scale = 1,
) {
  const z = tangent(front.clone(), direction);
  const x = new Vector3().crossVectors(direction, z);
  return new Matrix4()
    .makeBasis(x, direction, z)
    .scale(new Vector3(scale, scale, scale))
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

export function wildMarks(
  places: WorldPlaces,
  heightAt: HeightAt,
  radius: number,
): WildMarks {
  const marks: WildMarks = {
    caves: [],
    bones: [],
    stones: [],
    banners: [],
    cairns: [],
  };
  for (const feature of places.features) {
    const at = new Vector3(...feature.position);
    const inward = towardHotspot(feature, places);
    if (feature.kind === 'den') {
      const cave = stepped(at, inward, -CAVE_BACK_M, radius);
      marks.caves.push(standing(cave, inward, heightAt, radius));
      const bones = stepped(at, inward, BONES_OUT_M, radius);
      marks.bones.push(standing(bones, inward, heightAt, radius, BONES_SCALE));
    } else if (feature.kind === 'marker') {
      const outward = inward.clone().negate();
      if (feature.owner === 'town') {
        marks.stones.push(standing(at, outward, heightAt, radius, STONE_SCALE));
        const beside = new Vector3().crossVectors(at, outward).normalize();
        const banner = stepped(at, beside, BANNER_SIDE_M, radius);
        marks.banners.push(standing(banner, outward, heightAt, radius));
      } else marks.cairns.push(standing(at, outward, heightAt, radius));
    }
  }
  return marks;
}
