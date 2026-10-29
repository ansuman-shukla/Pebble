/*
 * Props drawn from code where the catalogue has no model. Each one stands in for a vendored file: a scene resting
 * on y = 0 facing +z, its real size, and colliders shaped like a Polyfork colliders file (convex parts).
 */
import {
  BoxGeometry,
  type BufferGeometry,
  DoubleSide,
  Group,
  Mesh,
  MeshStandardMaterial,
  PlaneGeometry,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

import type { ColliderFile, ColliderPart } from './collision';

export interface ProceduralProp {
  /** Real size in metres, like the manifest's `size_m`. */
  size: { x: number; y: number; z: number };
  build: () => Group;
  colliders: ColliderFile;
}

type Box = [
  x: number,
  y: number,
  z: number,
  width: number,
  height: number,
  depth: number,
];

const LOOM_ID = 'procedural-loom';
const LOOM_SIZE = { x: 1.2, y: 1.4, z: 0.8 };
const POST = 0.08;
const BEAM = 0.06;
const WARP_THREADS = 24;
const WARP_WIDTH = 0.9;
const BREAST_BEAM: [y: number, z: number] = [0.75, 0.36]; // front, where the weaver sits and the cloth rolls up
const WARP_BEAM: [y: number, z: number] = [1.25, -0.36]; // back, high, where the threads come from

/** A floor loom: four posts, top and side rails, the warp beam (back) and breast beam (front), threads between. */
function loomFrame(): Box[] {
  const [x, y, z] = [
    LOOM_SIZE.x / 2 - POST / 2,
    LOOM_SIZE.y,
    LOOM_SIZE.z / 2 - POST / 2,
  ];
  const posts: Box[] = [-x, x].flatMap((px) =>
    [-z, z].map((pz): Box => [px, y / 2, pz, POST, y, POST]),
  );
  const rails: Box[] = [-x, x].flatMap((px) => [
    [px, y - POST / 2, 0, POST, POST, LOOM_SIZE.z] as Box,
    [px, 0.15, 0, POST, POST, LOOM_SIZE.z] as Box,
  ]);
  const beams: Box[] = [BREAST_BEAM, WARP_BEAM].map(([by, bz]): Box => [
    0,
    by,
    bz,
    LOOM_SIZE.x - 2 * POST,
    BEAM,
    BEAM,
  ]);
  return [...posts, ...rails, ...beams];
}

function boxGeometry([x, y, z, width, height, depth]: Box): BufferGeometry {
  return new BoxGeometry(width, height, depth).translate(x, y, z);
}

/** The warp: thin planes from the warp beam down to the breast beam, evenly spaced across the frame. */
function warpGeometry(): BufferGeometry {
  const [fy, fz] = BREAST_BEAM;
  const [by, bz] = WARP_BEAM;
  const length = Math.hypot(by - fy, bz - fz);
  const tilt = Math.atan2(bz - fz, by - fy); // turns the plane's length (+y) from the breast beam to the warp beam
  const strip = WARP_WIDTH / WARP_THREADS / 3;
  const threads = Array.from({ length: WARP_THREADS }, (_, index) =>
    new PlaneGeometry(strip, length)
      .rotateX(tilt)
      .translate(
        -WARP_WIDTH / 2 + ((index + 0.5) * WARP_WIDTH) / WARP_THREADS,
        (fy + by) / 2,
        (fz + bz) / 2,
      ),
  );
  return mergeGeometries(threads);
}

function buildLoom(): Group {
  const wood = new Mesh(
    mergeGeometries(loomFrame().map(boxGeometry)),
    new MeshStandardMaterial({ color: '#8a5a32', roughness: 0.9 }),
  );
  wood.name = 'loom-frame';
  const warp = new Mesh(
    warpGeometry(),
    new MeshStandardMaterial({
      color: '#efe6d2',
      roughness: 1,
      side: DoubleSide,
    }),
  );
  warp.name = 'loom-warp';
  const loom = new Group();
  loom.add(wood, warp);
  return loom;
}

/** One convex part: the corners of a box. */
function boxPart([x0, y0, z0]: number[], [x1, y1, z1]: number[]): ColliderPart {
  return [x0, x1].flatMap((x) =>
    [y0, y1].flatMap((y) =>
      [z0, z1].map((z): [number, number, number] => [x, y, z]),
    ),
  );
}

export const PROCEDURAL_PROPS: Record<string, ProceduralProp> = {
  [LOOM_ID]: {
    size: LOOM_SIZE,
    build: buildLoom,
    colliders: {
      id: LOOM_ID,
      parts: [
        boxPart(
          [-LOOM_SIZE.x / 2, 0, -LOOM_SIZE.z / 2],
          [LOOM_SIZE.x / 2, LOOM_SIZE.y, LOOM_SIZE.z / 2],
        ),
      ],
    },
  },
};

export const isProcedural = (id: string) => Object.hasOwn(PROCEDURAL_PROPS, id);

const scenes = new Map<string, Group>();

/** The prop's scene, built once and shared like a loaded GLB (clone it before changing it). */
export function proceduralScene(id: string): Group {
  let scene = scenes.get(id);
  if (!scene) {
    scene = PROCEDURAL_PROPS[id].build();
    scenes.set(id, scene);
  }
  return scene;
}
