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
