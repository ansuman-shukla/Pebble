import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import type { InstancedMesh, Matrix4, Vector3 } from 'three';

import { kindParts } from '@/components/world/kind-parts';
import { assetUrl, PROPS, type PropKind } from '@/lib/world/assets';
import { NODE_LOOK_KINDS } from '@/lib/world/biome-props';
import {
  fillMeshes,
  hideMeshes,
  tierMeshes,
} from '@/lib/world/instanced-tiers';
import {
  type NodeInstance,
  type Scatter,
  scatterMatrix,
} from '@/lib/world/scatter';

/*
 * Every usable wild thing where the simulation has it (10 §1.1, §5.2): the flora table's trees, nut trees, berry
 * bushes, root patches, reed beds and deadwood, and the mineral seams, never cleared around sites. Tiered like the
 * decor: the cells within FAR_REACH + REBUILD are gathered when the focus moves more than REBUILD metres, every
 * RESPLIT metres the instances are split by distance (within SHADOW_REACH into the set that casts shadows, small
 * things out to SMALL_REACH, the rest out to FAR_REACH) into one InstancedMesh per merged part of each look.
 */

const SHADOW_REACH = 70;
/** Low things (bushes, root patches, reed beds, stumps) are drawn this far ... */
const SMALL_REACH = 300;
/** ... trees, deadwood and seams this far. */
const FAR_REACH = 500;
const REBUILD = 100;
const RESPLIT = 20;
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

interface LookSet {
  kind: PropKind;
  reach: number;
  near: InstancedMesh[];
  far: InstancedMesh[];
}

interface Gathered {
  node: NodeInstance;
  model: Matrix4;
}

/** What the page's test hooks read: the nodes drawn now. */
interface DrawnNode {
  id: string;
  look: PropKind;
  /** World metres of the model's base. */
  position: [number, number, number];
}

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

export function GlobeNodes({
  scatter,
  focusRef,
  radius,
}: {
  scatter: Scatter;
  focusRef: RefObject<Vector3>;
  radius: number;
}) {
  const models = useGLTF(NODE_LOOK_KINDS.map((kind) => assetUrl(PROPS[kind])));
  const sets = useMemo(
    () =>
      NODE_LOOK_KINDS.map((kind, index): LookSet => {
        const parts = kindParts(models[index].scene, PROPS[kind]);
        return {
          kind,
          reach: SMALL_LOOKS.has(kind) ? SMALL_REACH : FAR_REACH,
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
    builtAt: null as Vector3 | null,
    splitAt: null as Vector3 | null,
    gathered: new Map<PropKind, Gathered[]>(),
    drawn: [] as NodeInstance[],
    hidden: true,
  });

  useEffect(() => {
    window.__pebbleNodes = {
      drawn: () => {
        const { splitAt, drawn } = state.current;
        return (
          splitAt && {
            focus: splitAt.toArray(),
            nodes: drawn.map(({ id, kind, position }) => ({
              id,
              look: kind,
              position: position.toArray(),
            })),
          }
        );
      },
    };
    return () => {
      delete window.__pebbleNodes;
    };
  }, []);

  useFrame(({ camera }) => {
    const current = state.current;
    const focus = focusRef.current;
    if (camera.position.length() - radius > MAX_ALTITUDE) {
      if (!current.hidden)
        sets.forEach((set) => hideMeshes([...set.near, ...set.far]));
      current.hidden = true;
      current.splitAt = null;
      current.drawn = [];
      return;
    }
    if (!current.builtAt || current.builtAt.distanceTo(focus) > REBUILD) {
      current.builtAt = focus.clone();
      current.splitAt = null;
      current.gathered = new Map(NODE_LOOK_KINDS.map((kind) => [kind, []]));
      for (const cell of scatter.cellsAround(focus, FAR_REACH + REBUILD))
        for (const node of scatter.nodes(cell))
          current.gathered
            .get(node.kind)!
            .push({ node, model: scatterMatrix(node) });
    }
    if (!current.splitAt || current.splitAt.distanceTo(focus) > RESPLIT) {
      current.splitAt = focus.clone();
      current.hidden = false;
      current.drawn = [];
      for (const set of sets) {
        const near: Gathered[] = [];
        const far: Gathered[] = [];
        for (const gathered of current.gathered.get(set.kind)!) {
          const distance = gathered.node.position.distanceTo(focus);
          if (distance < SHADOW_REACH) near.push(gathered);
          else if (distance < set.reach) far.push(gathered);
        }
        const nearShown = near.slice(0, NEAR_CAPACITY);
        const farShown = far.slice(0, CAPACITY);
        fillMeshes(
          set.near,
          nearShown.map(({ model }) => model),
        );
        fillMeshes(
          set.far,
          farShown.map(({ model }) => model),
        );
        for (const { node } of [...nearShown, ...farShown])
          current.drawn.push(node);
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
