/*
 * The looks drawn from code for things lying on the ground that the catalogue has no model for (meat, a hide, fish,
 * cloth, a reed bundle, a tool): one vertex-coloured geometry each, resting on y = 0, its length along x.
 */
import {
  BoxGeometry,
  type BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  Float32BufferAttribute,
  IcosahedronGeometry,
  MeshStandardMaterial,
  OctahedronGeometry,
} from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

export const DRAWN_STACK_PROPS = [
  'meat',
  'hide',
  'fish',
  'cloth',
  'reeds',
  'tool',
] as const;
export type DrawnStackProp = (typeof DRAWN_STACK_PROPS)[number];

const MEAT = '#8e2b23';
const FAT = '#d9b8a0';
const BONE = '#e8dcc0';
const HIDE = '#8a6440';
const HIDE_BELLY = '#b08a5c';
const FISH = '#9fb2bd';
const FISH_BACK = '#56707e';
const CLOTH = '#2f4a7a';
const CLOTH_EDGE = '#c9b98f';
const REED = '#b9a35a';
const TIE = '#6b5a2e';
const SHAFT = '#7a5230';
const HEAD = '#8a8f96';

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

/** A few cuts of meat with the bone showing, about 0.5 m across. */
function meat() {
  const cuts: [number, number, number][] = [
    [0, 0.07, 0],
    [0.2, 0.06, 0.12],
    [-0.16, 0.06, 0.14],
  ];
  return cuts.flatMap(([x, y, z], index) => [
    painted(
      new IcosahedronGeometry(0.13, 0)
        .scale(1.3, 0.55, 1)
        .rotateY(index * 1.3)
        .translate(x, y, z),
      MEAT,
    ),
    painted(
      new IcosahedronGeometry(0.06, 0)
        .scale(1.2, 0.6, 1)
        .translate(x + 0.05, y + 0.05, z),
      FAT,
    ),
    painted(
      new CylinderGeometry(0.022, 0.022, 0.2, 5)
        .rotateZ(Math.PI / 2)
        .rotateY(index * 1.3)
        .translate(x, y + 0.02, z),
      BONE,
    ),
  ]);
}

/** A hide spread flat, its pale belly up at the middle. */
function hide() {
  return [
    painted(
      new CylinderGeometry(0.5, 0.45, 0.03, 7).scale(1.2, 1, 0.75),
      HIDE,
    ).translate(0, 0.015, 0),
    painted(
      new CylinderGeometry(0.3, 0.28, 0.01, 6).scale(1.1, 1, 0.6),
      HIDE_BELLY,
    ).translate(0, 0.035, 0),
  ];
}

/** Three fish side by side. */
function fish() {
  return [-0.1, 0, 0.1].flatMap((z, index) => {
    const x = (index - 1) * 0.04;
    return [
      painted(
        new OctahedronGeometry(1, 0).scale(0.2, 0.05, 0.06),
        FISH,
      ).translate(x, 0.05, z),
      painted(
        new OctahedronGeometry(1, 0).scale(0.16, 0.025, 0.03),
        FISH_BACK,
      ).translate(x, 0.09, z),
      painted(
        new ConeGeometry(0.05, 0.1, 4).rotateZ(Math.PI / 2),
        FISH_BACK,
      ).translate(x - 0.24, 0.05, z),
    ];
  });
}

/** Two folded bolts of cloth. */
function cloth() {
  return [
    painted(new BoxGeometry(0.5, 0.1, 0.32), CLOTH).translate(0, 0.05, 0),
    painted(new BoxGeometry(0.46, 0.09, 0.3), CLOTH)
      .rotateY(0.25)
      .translate(0.02, 0.145, 0),
    painted(new BoxGeometry(0.51, 0.02, 0.33), CLOTH_EDGE).translate(0, 0.1, 0),
  ];
}

/** A bundle of reeds lying along x, tied twice. */
function reeds() {
  const stalks = Array.from({ length: 9 }, (_, index) => {
    const row = Math.floor(index / 3);
    const column = index % 3;
    return painted(
      new CylinderGeometry(0.02, 0.02, 1.3, 5).rotateZ(Math.PI / 2),
      REED,
    ).translate((index % 2) * 0.05, 0.03 + row * 0.035, (column - 1) * 0.04);
  });
  const ties = [-0.35, 0.35].map((x) =>
    painted(
      new CylinderGeometry(0.085, 0.085, 0.04, 6).rotateZ(Math.PI / 2),
      TIE,
    ).translate(x, 0.065, 0),
  );
  return [...stalks, ...ties];
}

/** A tool lying in the grass: a shaft along x and its head. */
function tool() {
  return [
    painted(
      new CylinderGeometry(0.025, 0.025, 1.4, 5).rotateZ(Math.PI / 2),
      SHAFT,
    ).translate(0, 0.03, 0),
    painted(new BoxGeometry(0.16, 0.05, 0.1), HEAD).translate(0.72, 0.03, 0),
  ];
}

const BUILDERS: Record<DrawnStackProp, () => BufferGeometry[]> = {
  meat,
  hide,
  fish,
  cloth,
  reeds,
  tool,
};

/** One material for every drawn-from-code stack look (their colours are in the vertices). */
export const stackPropMaterial = () =>
  new MeshStandardMaterial({ vertexColors: true, roughness: 0.9 });

/** The look's geometry (a new one: dispose it with its mesh). */
export const stackPropGeometry = (look: DrawnStackProp) =>
  mergeGeometries(BUILDERS[look]());
