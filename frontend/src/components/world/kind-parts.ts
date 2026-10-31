import {
  type AnimationClip,
  type BufferGeometry,
  Float32BufferAttribute,
  type Material,
  Matrix4,
  type Mesh,
  MeshDepthMaterial,
  type Object3D,
  PropertyBinding,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import { assetSize } from '@/lib/world/assets';
import { type Doorway, doorwayOf, openDoors } from '@/lib/world/doors';
import {
  bakeClip,
  type ClipTrack,
  type PartMoves,
} from '@/lib/world/prop-motion';
import { withChunks } from '@/lib/world/vertex-chunks';
import {
  CLOTH_PARTS,
  clothWeights,
  SWAY_M,
  swayOf,
  windChunk,
  type WindProfile,
} from '@/lib/world/wind';

/*
 * A kind's GLB as instanced parts (10 §5.3): every sub-mesh baked into model space at rest (the gatehouse's doors
 * opened first, like the walker's colliders) and merged into one part per material, so a model draws in one call
 * (two with its shadow). Sub-meshes that move on their own stay addressable inside the merged part: the ones the
 * model's `tick` loop moves, and the named hooks living props drive (swinging door leaves, a fire's `flame` and
 * `fuel`, the forge's `fire`, dressing like a stall's `crates` or a chest's `lid`). Their vertices carry a
 * `partIndex` and their moves come from a PartMoves texture (prop-motion.ts). Plants sway and banners wave in
 * the wind (wind.ts).
 */

/** Named nodes living props drive (with every mesh under them). */
const LIVE_NODES = new Set([
  'door-l',
  'door-r',
  'flame',
  'fuel',
  'fire',
  'crates',
  'lid',
]);
/** Polyfork names each model's loop `tick`. */
const LOOP_CLIP = 'tick';

/** A sub-mesh that moves inside a merged part (its vertices' `partIndex` is its place in the list + 1). */
export interface MovingPart {
  /** The named node it hangs from (`door-r`, `flame`, `wheel`, …). */
  node: string;
  /** Which of the clip track's moves moves it, when the model's loop does. */
  clip: number | null;
}

/** One instanced part of a kind's GLB: drawn once per instance. */
interface KindPart {
  /** Model space at rest (shared by every user of the model; never dispose it). */
  geometry: BufferGeometry;
  /** The part drawn still (with the wind when the model sways). */
  material: Material;
  /** The still shadow pass's material when the part sways (else the default). */
  depthMaterial?: Material;
  /** The sub-meshes inside it that move (empty for a part that never moves). */
  moving: MovingPart[];
  /** The GLB's own material and the model's wind, to build moving looks from. */
  base: Material;
  wind: WindProfile | null;
}

export interface KindModel {
  parts: KindPart[];
  /** The model's baked `tick` loop, when it was given and moves some part. */
  clip: ClipTrack | null;
  /** The swinging door leaves, when the model has some. */
  doorway: Doorway | null;
}

/** The node at or above `object` named in `names` (up to the model's root), else null. */
function namedAbove(object: Object3D, root: Object3D, names: Set<string>) {
  for (
    let node: Object3D | null = object;
    node && node !== root;
    node = node.parent
  )
    if (names.has(node.name)) return node.name;
  return null;
}

function bakeAtRest(mesh: Mesh, toModel: Matrix4) {
  const geometry = mesh.geometry.clone();
  // drawn in the bind pose like any other instanced part
  geometry.deleteAttribute('skinIndex');
  geometry.deleteAttribute('skinWeight');
  return geometry.applyMatrix4(
    new Matrix4().multiplyMatrices(toModel, mesh.matrixWorld),
  );
}

const signature = (geometry: BufferGeometry, material: Material) =>
  [
    material.uuid,
    geometry.index ? 'indexed' : 'flat',
    ...Object.keys(geometry.attributes)
      .sort()
      .map((name) => `${name}:${geometry.attributes[name].itemSize}`),
  ].join('|');

/** Wind on a still part: its colour and shadow materials, or the GLB's own material when it doesn't sway. */
function stillLooks(base: Material, wind: WindProfile | null) {
  if (!wind) return { material: base };
  const chunks = [windChunk(wind)];
  return {
    material: withChunks(base.clone(), chunks),
    depthMaterial: withChunks(new MeshDepthMaterial(), chunks),
  };
}

/** The wind profile of a model's asset, adding `windCloth` weights to every geometry when it has cloth. */
function windOf(
  id: string,
  meshes: Mesh[],
  geometries: Map<Mesh, BufferGeometry>,
  source: Object3D,
): WindProfile | null {
  const sway = swayOf(id);
  const cloth = meshes.filter((mesh) => namedAbove(mesh, source, CLOTH_PARTS));
  if (!sway && cloth.length === 0) return null;
  const profile: WindProfile = {
    sway: sway ? SWAY_M[sway] : 0,
    height: assetSize(id).y,
  };
  if (cloth.length === 0) return profile;
  for (const mesh of meshes) {
    const geometry = geometries.get(mesh)!;
    let weights = new Float32Array(geometry.attributes.position.count);
    if (cloth.includes(mesh)) {
      const shape = clothWeights(geometry.attributes.position.array);
      weights = shape.weights;
      profile.clothNormal = shape.normal;
    }
    geometry.setAttribute('windCloth', new Float32BufferAttribute(weights, 1));
  }
  return profile;
}

function buildModel(
  scene: Object3D,
  id: string,
  animations: AnimationClip[],
): KindModel {
  const source = scene.clone(true);
  openDoors(source, id);
  source.updateMatrixWorld(true);
  const toModel = source.matrixWorld.clone().invert();
  const doorway = doorwayOf(source, id);
  const live = new Set(
    [...LIVE_NODES].filter(
      (name) => !name.startsWith('door-') || doorway !== null,
    ),
  );
  const loop = animations.find((clip) => clip.name === LOOP_CLIP);
  const targets = new Set(
    loop?.tracks.map(
      (track) => PropertyBinding.parseTrackName(track.name).nodeName,
    ) ?? [],
  );

  const meshes: Mesh[] = [];
  source.traverse((object) => {
    if ((object as Mesh).isMesh) meshes.push(object as Mesh);
  });
  const geometries = new Map(
    meshes.map((mesh) => [mesh, bakeAtRest(mesh, toModel)]),
  );
  const wind = windOf(id, meshes, geometries, source);

  const looping: Mesh[] = [];
  const groups = new Map<
    string,
    {
      material: Material;
      entries: { geometry: BufferGeometry; moving: MovingPart | null }[];
    }
  >();
  for (const mesh of meshes) {
    const geometry = geometries.get(mesh)!;
    const material = mesh.material as Material;
    const node = namedAbove(mesh, source, live);
    // skinned meshes hang beside the bones a loop moves, not under them: instanced, they stay in the bind pose
    const loopNode = namedAbove(mesh, source, targets);
    const moving =
      node || loopNode
        ? {
            node: (node ?? loopNode)!,
            clip: loopNode ? looping.push(mesh) - 1 : null,
          }
        : null;
    const key = signature(geometry, material);
    const group = groups.get(key) ?? { material, entries: [] };
    group.entries.push({ geometry, moving });
    groups.set(key, group);
  }

  const parts = [...groups.values()].map(({ material, entries }) => {
    const moving = entries.flatMap((entry) =>
      entry.moving ? [entry.moving] : [],
    );
    if (moving.length > 0)
      for (const { geometry, moving: part } of entries)
        geometry.setAttribute(
          'partIndex',
          new Float32BufferAttribute(
            new Float32Array(geometry.attributes.position.count).fill(
              part ? moving.indexOf(part) + 1 : 0,
            ),
            1,
          ),
        );
    const geometry =
      entries.length === 1
        ? entries[0].geometry
        : mergeGeometries(entries.map((entry) => entry.geometry));
    return {
      geometry,
      ...stillLooks(material, wind),
      moving,
      base: material,
      wind,
    };
  });

  const clip =
    loop && looping.length > 0 ? bakeClip(source, loop, looping) : null;
  return { parts, clip, doorway };
}

/** A part's colour and shadow materials that apply `moves` to its moving sub-meshes (dispose them with it). */
export function movingLooks(part: KindPart, moves: PartMoves) {
  const chunks = [moves.chunk(), ...(part.wind ? [windChunk(part.wind)] : [])];
  return {
    material: withChunks(part.base.clone(), chunks),
    depthMaterial: withChunks(new MeshDepthMaterial(), chunks),
  };
}

const models = new WeakMap<Object3D, Map<string, KindModel>>();

/**
 * The parts of a loaded model (or procedural scene), built once per scene and asset and shared by every user.
 * Pass the GLB's `animations` to keep the sub-meshes its `tick` loop moves addressable and bake the loop; without
 * them only the live hooks move.
 */
export function kindModel(
  scene: Object3D,
  id: string,
  animations: AnimationClip[] = [],
): KindModel {
  let byId = models.get(scene);
  if (!byId) {
    byId = new Map();
    models.set(scene, byId);
  }
  const key = `${id}|${animations.length > 0 ? 'moving' : 'still'}`;
  let model = byId.get(key);
  if (!model) {
    model = buildModel(scene, id, animations);
    byId.set(key, model);
  }
  return model;
}

/** The parts of a loaded model drawn still (its loop's sub-meshes at rest). */
export const kindParts = (scene: Object3D, id: string) =>
  kindModel(scene, id).parts;
