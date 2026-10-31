import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo } from 'react';
import { type Material, MeshDepthMaterial, type Vector3 } from 'three';

import { kindModel } from '@/components/world/kind-parts';
import { assetSize, assetUrl, PROPS, type PropKind } from '@/lib/world/assets';
import { NODE_LOOK_KINDS, STAGED_LOOKS } from '@/lib/world/biome-props';
import {
  type KindPart,
  type PartLooks,
  tierMeshes,
} from '@/lib/world/instanced-tiers';
import {
  type DrawnNode,
  FAR_REACH,
  NodeField,
  type NodeLook,
} from '@/lib/world/node-field';
import type { NodeStages } from '@/lib/world/node-stages';
import type { Scatter } from '@/lib/world/scatter';
import { StageTexture } from '@/lib/world/staged-material';
import { withChunks } from '@/lib/world/vertex-chunks';
import { windChunk } from '@/lib/world/wind';

/*
 * Every usable wild thing where the simulation has it and as it is now (10 §1.1, §5.2): the flora table's trees,
 * nut trees, berry bushes, root patches, reed beds and deadwood, and the mineral seams, never cleared around
 * sites, drawn by stage from the live feed (NodeField). Low things (bushes, root patches, reed beds, stumps) are
 * drawn out to SMALL_REACH, the rest out to FAR_REACH.
 */

const SMALL_REACH = 300;
/** Above this camera altitude the terrain colours carry the look and no props are drawn. */
const MAX_ALTITUDE = 1500;
const CAPACITY = 6000;
const NEAR_CAPACITY = 1500;
const SMALL_LOOKS = new Set<PropKind>([
  'berry_bush',
  'root_patch',
  'reed_bed',
  'tree_stump',
]);

declare global {
  interface Window {
    /** The nodes drawn now and the focus they were picked around (null while none are drawn). */
    __pebbleNodes?: {
      drawn: () => {
        focus: [number, number, number];
        nodes: DrawnNode[];
      } | null;
    };
  }
}

/** A staged look's materials for one tier: its stage rows first, then its wind (their own copies: disposed). */
function stagedLooks(
  rows: StageTexture,
  height: number,
  pieces: boolean,
  made: Material[],
): PartLooks {
  return (part: KindPart) => {
    const chunks = [
      rows.chunk(height, pieces),
      ...(part.wind ? [windChunk(part.wind)] : []),
    ];
    const material = withChunks(part.base.clone(), chunks);
    const depthMaterial = withChunks(new MeshDepthMaterial(), chunks);
    made.push(material, depthMaterial);
    return { material, depthMaterial };
  };
}

export function GlobeNodes({
  scatter,
  stages,
  focusRef,
  radius,
}: {
  scatter: Scatter;
  stages: NodeStages;
  focusRef: RefObject<Vector3>;
  radius: number;
}) {
  const models = useGLTF(NODE_LOOK_KINDS.map((kind) => assetUrl(PROPS[kind])));
  const { field, made } = useMemo(() => {
    const made: Material[] = [];
    const looks = NODE_LOOK_KINDS.map((kind, index): NodeLook => {
      const model = kindModel(models[index].scene, PROPS[kind]);
      const reach = SMALL_LOOKS.has(kind) ? SMALL_REACH : FAR_REACH;
      if (!STAGED_LOOKS.has(kind))
        return {
          kind,
          reach,
          pieces: model.pieces,
          near: tierMeshes(model.parts, NEAR_CAPACITY, true),
          far: tierMeshes(model.parts, CAPACITY, false),
          stages: null,
        };
      const height = assetSize(PROPS[kind]).y;
      const rows = {
        near: new StageTexture(NEAR_CAPACITY),
        far: new StageTexture(CAPACITY),
      };
      const pieces = model.pieces > 0;
      return {
        kind,
        reach,
        pieces: model.pieces,
        near: tierMeshes(
          model.parts,
          NEAR_CAPACITY,
          true,
          stagedLooks(rows.near, height, pieces, made),
        ),
        far: tierMeshes(
          model.parts,
          CAPACITY,
          false,
          stagedLooks(rows.far, height, pieces, made),
        ),
        stages: rows,
      };
    });
    return { field: new NodeField(looks, scatter, stages), made };
  }, [models, scatter, stages]);
  useEffect(
    () => () => {
      field.dispose();
      for (const material of made) material.dispose();
    },
    [field, made],
  );
  useEffect(() => {
    window.__pebbleNodes = { drawn: () => field.drawn() };
    return () => {
      delete window.__pebbleNodes;
    };
  }, [field]);

  useFrame(({ camera }) =>
    field.frame(
      focusRef.current,
      camera.position.length() - radius > MAX_ALTITUDE,
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
