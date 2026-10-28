/*
 * Picking a point on the rendered planet with a ray (a click on the screen): the first point where the ray
 * meets the ground or the sea surface, found by marching along it and refining by bisection.
 */
import { Vector3 } from 'three';

/** Nothing on the planet stands higher than this above sea level (the volcano peaks near 320 m). */
const HIGHEST = 450;
const MIN_STEP = 0.25;
const REFINE = 24;

/**
 * Where a ray from `origin` along the unit `direction` first meets the surface whose height above sea level is
 * `floorAt(direction)` (never below the sea), on a planet of `radius`; null if it misses the planet.
 */
export function pickSurface(
  origin: Vector3,
  direction: Vector3,
  radius: number,
  floorAt: (direction: Vector3) => number,
): Vector3 | null {
  // enter the shell that holds every surface point
  const outer = radius + HIGHEST;
  const along = -origin.dot(direction);
  const closest = origin.lengthSq() - along * along;
  if (closest > outer * outer) return null;
  const half = Math.sqrt(outer * outer - closest);
  let t = Math.max(along - half, 0);
  const end = along + half;
  const point = new Vector3();
  const above = (distance: number) => {
    point.copy(origin).addScaledVector(direction, distance);
    return point.length() - radius - Math.max(floorAt(point), 0);
  };
  let height = above(t);
  if (height <= 0) return point.copy(origin).addScaledVector(direction, t);
  while (t < end) {
    // the gap to the ground bounds how far the ray can safely go (slopes under ~60°)
    const step = Math.max(height * 0.5, MIN_STEP);
    const next = t + step;
    const nextHeight = above(next);
    if (nextHeight <= 0) {
      let low = t;
      let high = next;
      for (let k = 0; k < REFINE; k++) {
        const middle = (low + high) / 2;
        if (above(middle) > 0) low = middle;
        else high = middle;
      }
      return point.copy(origin).addScaledVector(direction, high).clone();
    }
    t = next;
    height = nextHeight;
  }
  return null;
}
