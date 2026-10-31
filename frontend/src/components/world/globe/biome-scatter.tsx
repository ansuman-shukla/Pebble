import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import type { InstancedMesh, Matrix4, Vector3 } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import { assetUrl, PROPS, type PropKind } from '@/lib/world/assets';
import { BIOME_PROPS, GROUND_COVER } from '@/lib/world/biome-props';
import {
  fillMeshes,
  hideMeshes,
  tierMeshes,
} from '@/lib/world/instanced-tiers';
import {
  type Scatter,
  type ScatterInstance,
  scatterMatrix,
} from '@/lib/world/scatter';

/*
 * Biome props around the focus, in two distance tiers:
 * ground cover (grass, flowers, ferns, pebbles, reeds) within NEAR_REACH, everything else within FAR_REACH.
 * The cells within FAR_REACH + REBUILD are scattered (each cell is cached; it always grows the same) and
 * re-gathered when the focus moves more than REBUILD metres; every RESPLIT metres the gathered instances are
 * re-filtered by tier and drawn as one InstancedMesh per merged part of each kind. Instances within SHADOW_REACH
 * go into a second set that casts shadows.
 */

const NEAR_REACH = 150;
const FAR_REACH = 500;
const REBUILD = 100;
const SHADOW_REACH = 70;
const RESPLIT = 20;
/** Above this camera altitude the terrain colours carry the look and no props are drawn. */
const MAX_ALTITUDE = 1500;
const CAPACITY = 6000;
const NEAR_CAPACITY = 1500;

const KINDS = [
  ...new Set(
    Object.values(BIOME_PROPS).flatMap((props) =>
      props.map((prop) => prop.kind),
    ),
  ),
];

interface KindSet {
  kind: PropKind;
  reach: number;
  near: InstancedMesh[];
  far: InstancedMesh[];
}

const hide = (set: KindSet) => hideMeshes([...set.near, ...set.far]);

export function BiomeScatter({
  scatter,
  focusRef,
  radius,
}: {
  scatter: Scatter;
  focusRef: RefObject<Vector3>;
  radius: number;
}) {
  const models = useGLTF(KINDS.map((kind) => assetUrl(PROPS[kind])));
  const sets = useMemo(
    () =>
      KINDS.map((kind, index): KindSet => {
        const parts = kindParts(models[index].scene, PROPS[kind]);
        return {
          kind,
          reach: GROUND_COVER.has(kind) ? NEAR_REACH : FAR_REACH,
          near: tierMeshes(parts, NEAR_CAPACITY, true),
          far: tierMeshes(parts, CAPACITY, false),
        };
      }),
    [models],
  );
  useEffect(
    () => () =>
      sets.forEach((set) =>
        [...set.near, ...set.far].forEach((mesh) => mesh.dispose()),
      ),
    [sets],
  );

  const state = useRef({
    /** Instances per cell: a cell always grows the same. */
    cache: new Map<number, ScatterInstance[]>(),
    builtAt: null as Vector3 | null,
    splitAt: null as Vector3 | null,
    instances: new Map<
      PropKind,
      { instance: ScatterInstance; model: Matrix4 }[]
    >(),
    hidden: true,
  });

  useFrame(({ camera }) => {
    const current = state.current;
    const focus = focusRef.current;
    if (camera.position.length() - radius > MAX_ALTITUDE) {
      if (!current.hidden) sets.forEach(hide);
      current.hidden = true;
      current.splitAt = null;
      return;
    }
    if (!current.builtAt || current.builtAt.distanceTo(focus) > REBUILD) {
      current.builtAt = focus.clone();
      current.splitAt = null;
      current.instances = new Map(KINDS.map((kind) => [kind, []]));
      for (const cell of scatter.cellsAround(focus, FAR_REACH + REBUILD)) {
        let grown = current.cache.get(cell);
        if (!grown) {
          grown = scatter.cell(cell);
          current.cache.set(cell, grown);
        }
        for (const instance of grown)
          current.instances
            .get(instance.kind)!
            .push({ instance, model: scatterMatrix(instance) });
      }
    }
    if (!current.splitAt || current.splitAt.distanceTo(focus) > RESPLIT) {
      current.splitAt = focus.clone();
      current.hidden = false;
      for (const set of sets) {
        const near: Matrix4[] = [];
        const far: Matrix4[] = [];
        for (const { instance, model } of current.instances.get(set.kind)!) {
          const distance = instance.position.distanceTo(focus);
          if (distance < SHADOW_REACH) near.push(model);
          else if (distance < set.reach) far.push(model);
        }
        fillMeshes(set.near, near);
        fillMeshes(set.far, far);
      }
    }
  });

  return (
    <>
      {sets.flatMap((set) =>
        [...set.near, ...set.far].map((mesh) => (
          <primitive key={mesh.uuid} object={mesh} />
        )),
      )}
    </>
  );
}
