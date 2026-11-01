/*
 * Things citizens hold while they work (10 §4.5, D133): a vendored model of `HAND_PROPS` or, where the catalogue has
 * none, a stand-in drawn from code (a pan, a knapping stone, a cup, a rice ball, a pick, a fishing rod), placed in a
 * fist grip. Held things hang under the rig's `attach-lefthand` / `attach-righthand` groups (the palm of each hand
 * bone), so whatever hides those (a sitter's or a sleeper's empty hands, D101) hides them too; a load rides on the back
 * (under the chest bone) and is only drawn while walking loaded. A held torch burns: its flame unlit by the scene,
 * with a flickering glow.
 *
 * A fist grip: the rig is bound in a T-pose with its hand bones turned like the character, fingers along -x and the
 * palm facing down, so a shaft through the fist runs along the hand's z (thumb side +z). Models stand on y = 0 with
 * their handle up y (the spear lies along x), so each kind turns its handle onto z and slides to where it is held.
 */
import {
  AdditiveBlending,
  type Bone,
  BoxGeometry,
  ConeGeometry,
  CylinderGeometry,
  DataTexture,
  DodecahedronGeometry,
  Euler,
  Group,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  type Object3D,
  Quaternion,
  SphereGeometry,
  Sprite,
  SpriteMaterial,
  Vector3,
} from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import type { HeldProp } from '@/lib/live/motion';
import { assetUrl, HAND_PROPS, type HandPropKind } from './assets';

type PropKind = HeldProp['kind'];

/** How a kind sits in the hand (or on the back): turned, then moved (m, in the hand's frame), then scaled. */
interface Grip {
  turn: [number, number, number];
  at: [number, number, number];
  scale: number;
}

const DEG = Math.PI / 180;

/**
 * Handles up y turned onto the hand's z (thumb side: a swung tool's head beyond the thumb); `from` is how far along
 * the handle from its end the fist holds it, `roll` turns the head about the handle.
 */
const handle = (from: number, scale = 1, roll = 0): Grip => ({
  turn: [90 * DEG, roll, 0],
  at: [0, 0, -from * scale],
  scale,
});

/**
 * A torch stands upright out of the fist of Polyfork's `Holding torch` (whose hand points its z ahead and up, its x
 * up): the handle along the hand's (0.83, 0.17, 0.53), measured from the clip.
 */
const UPRIGHT = new Vector3(0.83, 0.17, 0.53).normalize();
const upright = (from: number, scale: number): Grip => {
  const turn = new Euler().setFromQuaternion(
    new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), UPRIGHT),
  );
  const at = UPRIGHT.clone().multiplyScalar(-from * scale);
  return { turn: [turn.x, turn.y, turn.z], at: [at.x, at.y, at.z], scale };
};

const GRIPS: Record<PropKind, Grip> = {
  axe: handle(0.08, 1, 90 * DEG),
  hoe: handle(0.55),
  hammer: handle(0.05, 1, 90 * DEG),
  // a 1.5 m ground stake held as a 0.6 m torch (D133)
  torch: upright(0.25, 0.4),
  // the yari lies along x: turned onto z, held a third of the way up
  spear: { turn: [0, -90 * DEG, 0], at: [0, 0, 0.4], scale: 1 },
  // hanging from the fingers by its handle
  basket: { turn: [0, 90 * DEG, 0], at: [0, -0.38, 0], scale: 0.8 },
  coin_pouch: { turn: [0, 0, 0], at: [0, -0.2, 0], scale: 0.6 },
  // on the back: below the shoulders, behind the chest
  sack: { turn: [0, 0, 0], at: [0, -0.32, -0.24], scale: 0.6 },
  pan: { turn: [0, 0, 0], at: [-0.08, -0.03, 0.12], scale: 1 },
  stone: { turn: [0, 0, 0], at: [-0.03, -0.04, 0], scale: 1 },
  cup: { turn: [0, 0, 0], at: [-0.02, -0.02, 0.04], scale: 1 },
  food: { turn: [0, 0, 0], at: [-0.02, -0.03, 0.03], scale: 1 },
  pick: handle(0.06),
  rod: handle(0.1),
};

const wood = new MeshStandardMaterial({ color: '#7a5a3a', flatShading: true });
const iron = new MeshStandardMaterial({ color: '#5b5f66', flatShading: true });
const stoneGrey = new MeshStandardMaterial({
  color: '#8d8a83',
  flatShading: true,
});
const rice = new MeshStandardMaterial({ color: '#f1ede2', flatShading: true });
const clay = new MeshStandardMaterial({ color: '#a8673f', flatShading: true });
const line = new MeshStandardMaterial({ color: '#d8d2c0' });

const part = (
  geometry: ConstructorParameters<typeof Mesh>[0],
  material: MeshStandardMaterial,
  [x, y, z]: [number, number, number],
) => {
  const mesh = new Mesh(geometry, material);
  mesh.position.set(x, y, z);
  return mesh;
};

/** The stand-ins of D133, each resting on y = 0 with its handle (if any) up y. */
const MADE: Record<
  Exclude<PropKind, Exclude<HandPropKind, 'pick' | 'fishing_rod'>>,
  () => Object3D[]
> = {
  pan: () => [
    part(new CylinderGeometry(0.17, 0.12, 0.05, 10), iron, [0, 0.025, 0]),
  ],
  stone: () => [part(new DodecahedronGeometry(0.05), stoneGrey, [0, 0.05, 0])],
  cup: () => [
    part(new CylinderGeometry(0.04, 0.032, 0.08, 8), clay, [0, 0.04, 0]),
  ],
  food: () => [part(new SphereGeometry(0.045, 6, 4), rice, [0, 0.045, 0])],
  pick: () => [
    part(new CylinderGeometry(0.018, 0.022, 0.7, 6), wood, [0, 0.35, 0]),
    part(new BoxGeometry(0.42, 0.05, 0.05), iron, [0.04, 0.68, 0]),
    part(new ConeGeometry(0.03, 0.12, 4), iron, [0.3, 0.68, 0]).rotateZ(
      -Math.PI / 2,
    ),
  ],
  rod: () => [
    part(new CylinderGeometry(0.006, 0.016, 2.2, 5), wood, [0, 1.1, 0]),
    // the line hangs from the tip (the rod's tip ends up ahead and up)
    part(
      new CylinderGeometry(0.002, 0.002, 1.6, 3),
      line,
      [0, 2.2, -0.8],
    ).rotateX(Math.PI / 2),
  ],
};

/** A burning flame is drawn unlit (it shines by night) in its own vertex colours. */
const burning = new MeshBasicMaterial({ vertexColors: true });
/** Pixels across the glow sprite. */
const GLOW_SPRITE = 32;

/** A round warm glow: bright at the centre fading to nothing at the rim (added light: black is see-through). */
function glowSprite() {
  const pixels = new Uint8Array(GLOW_SPRITE * GLOW_SPRITE * 4);
  const half = GLOW_SPRITE / 2;
  for (let y = 0; y < GLOW_SPRITE; y++)
    for (let x = 0; x < GLOW_SPRITE; x++) {
      const out = Math.hypot(x + 0.5 - half, y + 0.5 - half) / half;
      const glow = Math.round(255 * Math.max(0, 1 - out) ** 2);
      pixels.set([glow, glow, glow, glow], (y * GLOW_SPRITE + x) * 4);
    }
  const texture = new DataTexture(pixels, GLOW_SPRITE, GLOW_SPRITE);
  texture.needsUpdate = true;
  return texture;
}

const torchGlow = new SpriteMaterial({
  map: glowSprite(),
  color: '#ffa04a',
  blending: AdditiveBlending,
  depthWrite: false,
  transparent: true,
});
/** The torch's glow: this wide (model units of the stake, before its grip's scale), round its flame's middle. */
const TORCH_GLOW = 3.2;
const TORCH_FLAME_AT = 1.32;

/**
 * Lights a held torch: its `flame` burns bright (unlit by the scene, so it shows by night) with a flickering glow
 * round it. Models without a flame are left as they are.
 */
function lightFlame(model: Object3D) {
  const flame = model.getObjectByName('flame');
  if (!flame) return;
  flame.traverse((object) => {
    if ((object as Mesh).isMesh) (object as Mesh).material = burning;
  });
  const glow = new Sprite(torchGlow);
  glow.name = 'torch-glow';
  glow.position.set(0, TORCH_FLAME_AT, 0);
  glow.scale.setScalar(TORCH_GLOW);
  const seed = Math.random() * 10;
  glow.onBeforeRender = () => {
    const time = performance.now() / 1000 + seed;
    glow.scale.setScalar(
      TORCH_GLOW *
        (1 + 0.12 * Math.sin(time * 13) + 0.08 * Math.sin(time * 7.3)),
    );
  };
  model.add(glow);
}

/** A held thing's model: `scene` is a loaded vendored model for kinds with one (each holder gets its own copy). */
export function propModel(kind: PropKind, scene: Object3D | null): Group {
  const group = new Group();
  group.name = `prop-${kind}`;
  if (kind in MADE) group.add(...MADE[kind as keyof typeof MADE]());
  else if (scene) {
    const model = scene.clone();
    if (kind === 'torch') lightFlame(model);
    group.add(model);
  }
  const grip = GRIPS[kind];
  group.rotation.copy(new Euler(...grip.turn));
  group.position.set(...grip.at);
  group.scale.setScalar(grip.scale);
  return group;
}

/** The vendored model id of a kind, or null for a stand-in drawn from code. */
export function propAsset(kind: PropKind): string | null {
  if (kind in MADE) return null;
  const prop = HAND_PROPS[kind as HandPropKind];
  return 'asset' in prop ? prop.asset : null;
}

const scenes = new Map<string, Promise<Object3D>>();

/** A vendored prop's scene, loaded once per page. */
export function loadProp(asset: string): Promise<Object3D> {
  let scene = scenes.get(asset);
  if (!scene) {
    scene = new GLTFLoader()
      .loadAsync(assetUrl(asset))
      .then((gltf) => gltf.scene);
    scenes.set(asset, scene);
  }
  return scene;
}

/** Where a held thing hangs on a character: a hand's attach group, or the chest bone for a load. */
export function holderOf(character: Object3D, at: HeldProp['at']): Object3D {
  if (at === 'back') {
    const chest = character
      .getObjectsByProperty('name', 'Spine2')
      .find((object) => (object as Bone).isBone);
    if (!chest) throw new Error('hand-props: the character has no Spine2');
    return chest;
  }
  const name = `attach-${at}hand`;
  const hand = character
    .getObjectsByProperty('name', name)
    .find((object) => (object.parent as Bone | null)?.isBone);
  if (!hand) throw new Error(`hand-props: the character has no ${name} grip`);
  return hand;
}

/**
 * What the look itself carries in its `hands` (a spear, a cane, a coin pouch: the garments under the root-level
 * `attach-*hand` groups), not the props held for a motion.
 */
export function wornInHand(
  character: Object3D,
  hands: readonly HeldProp['at'][] = ['left', 'right'],
): Object3D[] {
  return hands.flatMap((hand) =>
    character
      .getObjectsByProperty('name', `attach-${hand}hand`)
      .filter((worn) => !(worn.parent as Bone | null)?.isBone),
  );
}

/**
 * Hides what the look itself carries in a hand (a cane, a coin pouch, a spear) while it holds a prop in that hand,
 * or in both hands while it `stow`s them for work, and shows it again otherwise; call after `showWorn` (which shows
 * or hides everything in hand by posture).
 */
export function freeHand(
  character: Object3D,
  held: HeldProp | null,
  stow = false,
) {
  const hands = stow
    ? (['left', 'right'] as const)
    : held && held.at !== 'back'
      ? [held.at]
      : [];
  for (const worn of wornInHand(character, hands)) worn.visible = false;
}
