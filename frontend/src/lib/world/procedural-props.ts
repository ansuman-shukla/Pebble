/*
 * Props drawn from code where the catalogue has no model. Each one stands in for a vendored file: a scene resting
 * on y = 0 facing +z, its real size, and colliders shaped like a Polyfork colliders file (convex parts).
 */
import {
  BoxGeometry,
  type BufferGeometry,
  CircleGeometry,
  Color,
  CylinderGeometry,
  DoubleSide,
  Float32BufferAttribute,
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

/** How much of the warp is already woven (from the breast beam back), and the cloth rolled on the beam. */
const WOVEN = 0.35;
const CLOTH_ROLL = 0.035;

/** The cloth woven so far: a panel over the front of the warp and the roll it winds onto at the breast beam. */
function clothGeometry(): BufferGeometry {
  const [fy, fz] = BREAST_BEAM;
  const [by, bz] = WARP_BEAM;
  const length = Math.hypot(by - fy, bz - fz) * WOVEN;
  const tilt = Math.atan2(bz - fz, by - fy);
  const along = [
    (bz - fz) / Math.hypot(by - fy, bz - fz),
    (by - fy) / Math.hypot(by - fy, bz - fz),
  ];
  // just above the threads (towards the weaver's side of the plane) so it hides them where it lies
  const panel = new PlaneGeometry(WARP_WIDTH, length)
    .rotateX(tilt)
    .translate(
      0,
      fy + (along[1] * length) / 2 + 0.01,
      fz + (along[0] * length) / 2 + 0.01,
    );
  const roll = new CylinderGeometry(CLOTH_ROLL, CLOTH_ROLL, WARP_WIDTH, 10)
    .rotateZ(Math.PI / 2)
    .translate(0, fy, fz);
  roll.deleteAttribute('uv');
  panel.deleteAttribute('uv');
  return mergeGeometries([panel.toNonIndexed(), roll.toNonIndexed()]);
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
  const cloth = new Mesh(
    clothGeometry(),
    new MeshStandardMaterial({
      color: '#3d5a8a',
      roughness: 1,
      side: DoubleSide,
    }),
  );
  cloth.name = 'loom-cloth';
  const loom = new Group();
  loom.add(wood, warp, cloth);
  return loom;
}

/*
 * Furniture under slots (D198): a log seat, the weaver's stool and the lord's folding seat. Each is one mesh painted
 * by vertex colour (one material, so one draw call for all its instances, two with shadows), sat on at its slot's
 * height: `FURNITURE_SEAT` is where the hips rest on it as built; furniture.ts stretches it to the slot's.
 */
const LOG_ID = 'procedural-log-seat';
const STOOL_ID = 'procedural-stool';
const LORD_SEAT_ID = 'procedural-lord-seat';
/** A log seat as built: 1 m long (stretched to the seats on it), lying along x, its top at the seat height. */
const LOG_SIZE = { x: 1, y: 0.4, z: 0.4 };
const STOOL_SIZE = { x: 0.36, y: 0.3, z: 0.3 };
/** The lord's seat: a folding stool (shogi) on a straw mat in the castle court. */
const LORD_SEAT_SIZE = { x: 1.1, y: 0.45, z: 0.9 };
const LORD_MAT = 0.04;

const STREAMER_ID = 'procedural-hide-streamer';
/** A band's hide streamer: a pole with a strip of hide tied at its top (beside a claim cairn, 10 §1.5). */
const STREAMER_SIZE = { x: 0.6, y: 1.8, z: 0.06 };
const STREAMER_HIDE = { length: 0.55, height: 0.24 };

/** Where the hips rest on each piece as built (metres above the ground). */
export const FURNITURE_SEAT: Record<string, number> = {
  [LOG_ID]: LOG_SIZE.y,
  [STOOL_ID]: STOOL_SIZE.y,
  [LORD_SEAT_ID]: LORD_SEAT_SIZE.y,
};

/** Paints every vertex of a (non-indexed) geometry one colour. */
function painted(geometry: BufferGeometry, color: string): BufferGeometry {
  const flat = geometry.index ? geometry.toNonIndexed() : geometry;
  flat.deleteAttribute('uv');
  const { r, g, b } = new Color(color);
  const count = flat.getAttribute('position').count;
  flat.setAttribute(
    'color',
    new Float32BufferAttribute(
      Array.from({ length: count }, () => [r, g, b]).flat(),
      3,
    ),
  );
  return flat;
}

/** One vertex-coloured mesh from painted parts. */
function paintedMesh(name: string, parts: BufferGeometry[]): Group {
  const mesh = new Mesh(
    mergeGeometries(parts),
    new MeshStandardMaterial({ vertexColors: true, roughness: 0.9 }),
  );
  mesh.name = name;
  const group = new Group();
  group.add(mesh);
  return group;
}

const paintedBox = (box: Box, color: string) =>
  painted(boxGeometry(box), color);

/**
 * A pole and the strip of hide tied at its top, hanging out along +x. The strip is a part named `banner-cloth`,
 * so the wind waves it like the town's banners (wind.ts, D148): fixed at the pole, free at its tip.
 */
function buildHideStreamer(): Group {
  const pole = 0.04;
  const { length, height } = STREAMER_HIDE;
  const group = paintedMesh('hide-streamer-pole', [
    paintedBox(
      [0, STREAMER_SIZE.y / 2, 0, pole, STREAMER_SIZE.y, pole],
      '#5c4026',
    ),
  ]);
  const hide = new Mesh(
    painted(
      new PlaneGeometry(length, height).translate(
        pole / 2 + length / 2,
        STREAMER_SIZE.y - height / 2 - 0.04,
        0,
      ),
      '#b98a5a',
    ),
    new MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.95,
      side: DoubleSide,
    }),
  );
  hide.name = 'banner-cloth';
  group.add(hide);
  return group;
}

/** A barked log lying along x with pale cut ends, resting on the ground. */
function buildLogSeat(): Group {
  const radius = LOG_SIZE.y / 2;
  const bark = new CylinderGeometry(radius, radius, LOG_SIZE.x, 9, 1, true)
    .rotateZ(Math.PI / 2)
    .translate(0, radius, 0);
  const ends = [-1, 1].map((side) =>
    new CircleGeometry(radius, 9)
      .rotateY((side * Math.PI) / 2)
      .translate((side * LOG_SIZE.x) / 2, radius, 0),
  );
  return paintedMesh('log-seat', [
    painted(bark, '#6b4a2e'),
    ...ends.map((end) => painted(end, '#c9a46a')),
  ]);
}

/** A low four-legged stool. */
function buildStool(): Group {
  const { x, y, z } = STOOL_SIZE;
  const top = 0.04;
  const leg = 0.04;
  const legs = [-1, 1].flatMap((sx) =>
    [-1, 1].map((sz): Box => [
      sx * (x / 2 - leg),
      (y - top) / 2,
      sz * (z / 2 - leg),
      leg,
      y - top,
      leg,
    ]),
  );
  return paintedMesh('stool', [
    paintedBox([0, y - top / 2, 0, x, top, z], '#8a5a32'),
    ...legs.map((part) => paintedBox(part, '#6e4526')),
  ]);
}

/** The lord's folding seat: a red cloth slung between two rails on crossed black legs, on a straw mat. */
function buildLordSeat(): Group {
  const seat = { x: 0.6, z: 0.42 };
  const y = LORD_SEAT_SIZE.y;
  const bar = 0.035;
  const rise = y - LORD_MAT - bar;
  const length = Math.hypot(seat.z, rise);
  const tilt = Math.atan2(seat.z, rise);
  const legs = [-1, 1].flatMap((side) =>
    [-1, 1].map((cross) =>
      painted(
        new BoxGeometry(bar, length, bar)
          .rotateX(cross * tilt)
          .translate(
            side * (seat.x / 2 - bar / 2) + cross * bar * 0.5,
            LORD_MAT + rise / 2,
            0,
          ),
        '#2a1d17',
      ),
    ),
  );
  const rails = [-1, 1].map((side) =>
    paintedBox(
      [0, y - bar / 2, (side * seat.z) / 2, seat.x + 0.06, bar, bar],
      '#2a1d17',
    ),
  );
  return paintedMesh('lord-seat', [
    paintedBox(
      [0, LORD_MAT / 2, 0, LORD_SEAT_SIZE.x, LORD_MAT, LORD_SEAT_SIZE.z],
      '#b9a769',
    ),
    paintedBox([0, y - bar / 2, 0, seat.x, 0.02, seat.z], '#8e2323'),
    ...rails,
    ...legs,
  ]);
}

/** One convex part: the corners of a box. */
function boxPart([x0, y0, z0]: number[], [x1, y1, z1]: number[]): ColliderPart {
  return [x0, x1].flatMap((x) =>
    [y0, y1].flatMap((y) =>
      [z0, z1].map((z): [number, number, number] => [x, y, z]),
    ),
  );
}

/** A solid box collider of a prop's whole size, resting on y = 0. */
const wholeBox = (id: string, size: ProceduralProp['size']): ColliderFile => ({
  id,
  parts: [
    boxPart([-size.x / 2, 0, -size.z / 2], [size.x / 2, size.y, size.z / 2]),
  ],
});

export const PROCEDURAL_PROPS: Record<string, ProceduralProp> = {
  [LOG_ID]: {
    size: LOG_SIZE,
    build: buildLogSeat,
    colliders: wholeBox(LOG_ID, LOG_SIZE),
  },
  [STOOL_ID]: {
    size: STOOL_SIZE,
    build: buildStool,
    colliders: wholeBox(STOOL_ID, STOOL_SIZE),
  },
  [LORD_SEAT_ID]: {
    size: LORD_SEAT_SIZE,
    build: buildLordSeat,
    colliders: wholeBox(LORD_SEAT_ID, LORD_SEAT_SIZE),
  },
  [LOOM_ID]: {
    size: LOOM_SIZE,
    build: buildLoom,
    colliders: wholeBox(LOOM_ID, LOOM_SIZE),
  },
  [STREAMER_ID]: {
    size: STREAMER_SIZE,
    build: buildHideStreamer,
    colliders: wholeBox(STREAMER_ID, STREAMER_SIZE),
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
