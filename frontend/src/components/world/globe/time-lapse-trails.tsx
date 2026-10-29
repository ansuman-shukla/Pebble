import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import {
  BufferAttribute,
  BufferGeometry,
  DynamicDrawUsage,
  type LineSegments,
  Vector3,
} from 'three';

import type { NpcViews } from './globe-npcs';
import {
  pruneTrails,
  sampleTrail,
  trailStep,
  trailVertices,
  type Trails,
  uploadTrails,
  writeTrails,
} from '@/lib/live/trails';
import { snapMetres } from '@/lib/live/walk-path';
import { isTimeLapse } from '@/lib/world/visual-rate';

/*
 * Fast-forward trails (10 §4.2.3): in time-lapse (above ×10) every drawn citizen drags the last 20 real seconds of
 * its drawn path as a fading line ending at its body, all in one LineSegments. At ×10 and below, or paused, there are
 * none.
 */

/** Trails for at most this many citizens. */
const MOVERS = 64;
/** Lines hang this far above the drawn feet, clear of the ground's facets. */
const LIFT_M = 0.4;
/** A leg longer than a resync at running pace is a fade across, not a walk (`snapMetres`). */
const RUN_MPS = 3.5;
const COLOR: [number, number, number] = [1, 0.93, 0.7];

const OPACITY = 0.8;
const VERTICES = trailVertices(MOVERS);

const lifted = new Vector3();
const alphas = new Float32Array(VERTICES);

type TrailGeometry = BufferGeometry<{
  position: BufferAttribute;
  color: BufferAttribute;
}>;

/** Room for every mover's trail, all one colour (only the alpha changes); nothing drawn until the first sample. */
function newGeometry(): TrailGeometry {
  const geometry: TrailGeometry = new BufferGeometry();
  const attribute = (size: number) =>
    new BufferAttribute(new Float32Array(VERTICES * size), size).setUsage(
      DynamicDrawUsage,
    );
  const colors = attribute(4);
  for (let v = 0; v < VERTICES; v++) colors.setXYZ(v, ...COLOR);
  geometry.setAttribute('position', attribute(3));
  geometry.setAttribute('color', colors);
  geometry.setDrawRange(0, 0);
  return geometry;
}

export function TimeLapseTrails({
  views,
  rate,
}: {
  views: NpcViews;
  /** Game seconds per real second (0 paused). */
  rate: number;
}) {
  const line = useRef<LineSegments<TrailGeometry>>(null);
  const trails = useRef<Trails>(new Map());
  const clock = useRef(0);
  const geometry = useMemo(() => newGeometry(), []);
  useEffect(() => () => geometry.dispose(), [geometry]);

  const lapse = isTimeLapse(rate);
  useEffect(() => {
    if (lapse) return;
    trails.current.clear();
    line.current?.geometry.setDrawRange(0, 0);
  }, [lapse]);

  useFrame((_, delta) => {
    const mesh = line.current;
    if (!lapse || !mesh) return;
    clock.current += delta;
    const now = clock.current;
    const step = trailStep(rate);
    const drawn = new Set<string>();
    for (const view of views.values()) {
      if (drawn.size >= MOVERS) break;
      const { position } = view.pose;
      if (position.lengthSq() === 0) continue; // not placed yet
      drawn.add(view.id);
      lifted.copy(position).setLength(position.length() + LIFT_M);
      sampleTrail(trails.current, view.id, lifted, now, step);
    }
    pruneTrails(trails.current, drawn);
    const { position: positions, color: colors } = mesh.geometry.attributes;
    const vertices = writeTrails(
      trails.current,
      positions.array as Float32Array,
      alphas,
      snapMetres(RUN_MPS, rate),
      now,
    );
    const rgba = colors.array as Float32Array;
    for (let v = 0; v < vertices; v++) rgba[v * 4 + 3] = alphas[v] * OPACITY;
    uploadTrails([positions, colors], vertices);
    mesh.geometry.setDrawRange(0, vertices);
  });

  return (
    <lineSegments
      ref={line}
      geometry={geometry}
      visible={lapse}
      frustumCulled={false}
      renderOrder={2}
    >
      <lineBasicMaterial vertexColors transparent depthWrite={false} />
    </lineSegments>
  );
}
