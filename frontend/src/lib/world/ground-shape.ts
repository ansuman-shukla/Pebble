import { Shape, ShapeGeometry, Vector2 } from 'three';

import type { Point } from './collision';

/** A flat shape on the ground; Shape y is world -z because the mesh is rotated -90° about x. */
export function groundShape(outline: Point[], holes: Point[][] = []) {
  const toShape = (points: Point[]) =>
    new Shape(points.map(([x, z]) => new Vector2(x, -z)));
  const shape = toShape(outline);
  shape.holes = holes.map(toShape);
  return new ShapeGeometry(shape);
}

/** Corners of a round disc of `radius` (local x, z), counter-clockwise seen from above. */
export function discOutline(radius: number, segments = 96): Point[] {
  return Array.from({ length: segments }, (_, i) => {
    const angle = (i / segments) * Math.PI * 2;
    return [Math.cos(angle) * radius, -Math.sin(angle) * radius];
  });
}

/** The part of a polygon inside a convex polygon (Sutherland-Hodgman); empty if none is. */
export function clipToConvex(polygon: Point[], convex: Point[]): Point[] {
  // orientation of the clip polygon, so "inside" is on the correct side of each edge
  const area = convex.reduce((sum, [x1, z1], i) => {
    const [x2, z2] = convex[(i + 1) % convex.length];
    return sum + x1 * z2 - x2 * z1;
  }, 0);
  let result = polygon;
  convex.forEach(([ax, az], i) => {
    const [bx, bz] = convex[(i + 1) % convex.length];
    const side = ([x, z]: Point) =>
      Math.sign(area) * ((bx - ax) * (z - az) - (bz - az) * (x - ax));
    const input = result;
    result = [];
    input.forEach((current, k) => {
      const previous = input[(k + input.length - 1) % input.length];
      const [sc, sp] = [side(current), side(previous)];
      if (sc >= 0 !== sp >= 0) {
        const t = sp / (sp - sc);
        result.push([
          previous[0] + (current[0] - previous[0]) * t,
          previous[1] + (current[1] - previous[1]) * t,
        ]);
      }
      if (sc >= 0) result.push(current);
    });
  });
  return result;
}

/** Water areas cut to a site's round ground disc (parts outside it are dropped). */
export function clipWater<W extends { polygon: Point[]; holes?: Point[][] }>(
  water: W[],
  radius: number,
): W[] {
  const disc = discOutline(radius);
  return water.flatMap((area) => {
    const polygon = clipToConvex(area.polygon, disc);
    if (polygon.length < 3) return [];
    const holes = (area.holes ?? [])
      .map((hole) => clipToConvex(hole, disc))
      .filter((hole) => hole.length >= 3);
    return [{ ...area, polygon, holes }];
  });
}
