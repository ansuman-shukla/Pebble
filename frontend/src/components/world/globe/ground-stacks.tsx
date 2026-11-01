import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo } from 'react';
import { InstancedMesh, Vector3 } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import type { LiveStack } from '@/lib/live/live-contract';
import { assetUrl, PROPS } from '@/lib/world/assets';
import type { GlobeTerrain } from '@/lib/world/globe';
import {
  DRAWN_STACK_PROPS,
  stackPropGeometry,
  stackPropMaterial,
} from '@/lib/world/ground-stack-props';
import {
  CAPACITY,
  type DrawnStack,
  STACK_MODEL_LOOKS,
  StackField,
  type StackLook,
  type StackLookMeshes,
} from '@/lib/world/ground-stacks';
import { tierMeshes } from '@/lib/world/instanced-tiers';
import type { NodeStages } from '@/lib/world/node-stages';
import type { Scatter } from '@/lib/world/scatter';
import { groundPlacer, type WalkTown } from '@/lib/world/walk-charts';

/*
 * Everything lying on the ground near the camera's focus, from the live feed's stacks (ground-stacks.ts): logs,
 * meat, woodpiles, goods put down. Catalogue models where there are some, looks drawn from code for the rest.
 */

/** Above this camera altitude nothing small is drawn (as the nodes). */
const MAX_ALTITUDE = 1500;

declare global {
  interface Window {
    /** The ground stacks drawn now, as piles, and how many instances each look's meshes draw. */
    __pebbleStacks?: {
      drawn: () => DrawnStack[];
      instances: () => Partial<Record<StackLook, number>>;
    };
  }
}

export function GlobeStacks({
  stacks,
  terrain,
  town,
  scatter,
  stages,
  focusRef,
}: {
  stacks: LiveStack[];
  terrain: GlobeTerrain;
  town: WalkTown;
  scatter: Scatter;
  stages: NodeStages;
  focusRef: RefObject<Vector3>;
}) {
  const models = useGLTF(
    STACK_MODEL_LOOKS.map((kind) => assetUrl(PROPS[kind])),
  );
  const { field, material, drawnLooks } = useMemo(() => {
    const modelLooks = STACK_MODEL_LOOKS.map(
      (look, index): StackLookMeshes => ({
        look,
        meshes: tierMeshes(
          kindParts(models[index].scene, PROPS[look]),
          CAPACITY,
          true,
        ),
      }),
    );
    const material = stackPropMaterial();
    const drawnLooks = DRAWN_STACK_PROPS.map((look): StackLookMeshes => {
      const mesh = new InstancedMesh(
        stackPropGeometry(look),
        material,
        CAPACITY,
      );
      mesh.count = 0;
      mesh.visible = false;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      return { look, meshes: [mesh] };
    });
    const field = new StackField(
      [...modelLooks, ...drawnLooks],
      scatter,
      stages,
      groundPlacer(terrain, town),
    );
    return { field, material, drawnLooks };
  }, [models, scatter, stages, terrain, town]);
  useEffect(
    () => () => {
      // the models' geometry and materials are shared (kind-parts); the drawn looks' are ours
      for (const mesh of field.meshes()) mesh.dispose();
      for (const { meshes } of drawnLooks)
        for (const mesh of meshes) mesh.geometry.dispose();
      material.dispose();
    },
    [field, material, drawnLooks],
  );
  useEffect(() => field.set(stacks, performance.now() / 1000), [field, stacks]);
  useEffect(() => {
    window.__pebbleStacks = {
      drawn: () => field.drawn(),
      instances: () => field.instances(),
    };
    return () => {
      delete window.__pebbleStacks;
    };
  }, [field]);

  useFrame(({ camera }) =>
    field.frame(
      focusRef.current,
      camera.position.length() - terrain.globe.radius > MAX_ALTITUDE,
      performance.now() / 1000,
    ),
  );

  return (
    <>
      {field.meshes().map((mesh) => (
        <primitive key={mesh.uuid} object={mesh} />
      ))}
    </>
  );
}
