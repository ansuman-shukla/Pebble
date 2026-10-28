import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import { InstancedMesh, Matrix4, Quaternion, Vector3 } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import { assetUrl, kindScale, PROPS, type PropKind } from '@/lib/world/assets';
import { BIOME_PROPS, GROUND_COVER } from '@/lib/world/biome-props';
import type { Scatter, ScatterInstance } from '@/lib/world/scatter';

/*
 * Biome props around the focus, in two distance tiers: ground cover (grass, flowers, ferns, pebbles, reeds)
 * within NEAR_REACH, everything else within FAR_REACH. The cells within FAR_REACH + REBUILD are scattered
 * (each cell is cached; it always grows the same) and re-gathered when the focus moves more than REBUILD
 * metres; every RESPLIT metres the gathered instances are re-filtered by tier and drawn as one InstancedMesh
 * per sub-mesh of each kind. Instances within SHADOW_REACH go into a second set that casts shadows.
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

const Y_AXIS = new Vector3(0, 1, 0);
const upright = new Quaternion();
const yawTurn = new Quaternion();
const scaled = new Vector3();
const part = new Matrix4();

function modelMatrix(instance: ScatterInstance) {
  const up = instance.position.clone().normalize();
  upright
    .setFromUnitVectors(Y_AXIS, up)
    .multiply(yawTurn.setFromAxisAngle(Y_AXIS, instance.yaw));
  return new Matrix4().compose(
    instance.position,
    upright,
    scaled.setScalar(instance.scale * kindScale(instance.kind)),
  );
}

interface KindSet {
  kind: PropKind;
  reach: number;
  inModel: Matrix4[];
  near: InstancedMesh[];
  far: InstancedMesh[];
}

function hide(set: KindSet) {
  for (const mesh of [...set.near, ...set.far]) mesh.visible = false;
}

function fill(meshes: InstancedMesh[], inModel: Matrix4[], models: Matrix4[]) {
  meshes.forEach((mesh, index) => {
    const count = Math.min(models.length, mesh.instanceMatrix.count);
    for (let i = 0; i < count; i++)
      mesh.setMatrixAt(i, part.multiplyMatrices(models[i], inModel[index]));
    mesh.count = count;
    // an empty instanced mesh would still cost a draw call
    mesh.visible = count > 0;
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  });
}

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
        const make = (capacity: number, shadow: boolean) =>
          parts.map(({ geometry, material }) => {
            const mesh = new InstancedMesh(geometry, material, capacity);
            mesh.count = 0;
            mesh.visible = false;
            mesh.castShadow = shadow;
            mesh.receiveShadow = true;
            return mesh;
          });
        return {
          kind,
          reach: GROUND_COVER.has(kind) ? NEAR_REACH : FAR_REACH,
          inModel: parts.map((p) => p.inModel),
          near: make(NEAR_CAPACITY, true),
          far: make(CAPACITY, false),
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
            .push({ instance, model: modelMatrix(instance) });
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
        fill(set.near, set.inModel, near);
        fill(set.far, set.inModel, far);
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
