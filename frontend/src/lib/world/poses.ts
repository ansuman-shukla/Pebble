/*
 * Procedural motion layered over a citizen's clip (10 §4.4-4.5), for what Polyfork has no clip for: a hunter's
 * crouched creep, gestures (wave, bow, point and a 0.4 m jump), a bow in prayer with the hands together before the
 * chest, a hand picking high or low, a sleeper's breathing, and the
 * moves between postures (lying down and getting up roll over 1.2 s, a death falls in 0.8 s with the knees giving way,
 * sitting down settles over 0.8 s). Each frame, after the mixer:
 *
 *   mixer ─▶ layer (bones) ─▶ layToRest (posture, `rest-posture.ts`) ─▶ ease between postures ─▶ hop (jump)
 *
 * Bones are turned about axes of the character's own frame (x its left, y up, z ahead), so a layer works on top of
 * whatever the clip did, whatever each rig's bone axes are. Times are clip seconds (the clock's visual rate applied).
 */
import { type Bone, type Object3D, Quaternion, Vector3 } from 'three';

import type { Cue } from '@/lib/live/live-state';
import type { Layer } from '@/lib/live/motion';
import { visualRate } from '@/lib/world/visual-rate';

const DEG = Math.PI / 180;

/** The bones the layers move. */
export interface Rig {
  character: Object3D;
  /** Every bone's turn as the clip last posed it (and the hips' place), before any layer or posture. */
  clip: { bone: Bone; turn: Quaternion }[];
  hipsAt: Vector3;
  hips: Bone;
  spine: Bone;
  chest: Bone;
  neck: Bone;
  head: Bone;
  arms: Record<'left' | 'right', { arm: Bone; fore: Bone; hand: Bone }>;
  legs: Record<'left' | 'right', { up: Bone; leg: Bone; foot: Bone }>;
}

export function rigOf(character: Object3D): Rig {
  const bone = (name: string) => {
    const found = character
      .getObjectsByProperty('name', name)
      .find((object) => (object as Bone).isBone) as Bone | undefined;
    if (!found) throw new Error(`poses: the character has no ${name}`);
    return found;
  };
  const side = (prefix: 'Left' | 'Right') => ({
    arm: bone(`${prefix}Arm`),
    fore: bone(`${prefix}ForeArm`),
    hand: bone(`${prefix}Hand`),
  });
  const leg = (prefix: 'Left' | 'Right') => ({
    up: bone(`${prefix}UpLeg`),
    leg: bone(`${prefix}Leg`),
    foot: bone(`${prefix}Foot`),
  });
  const bones: Bone[] = [];
  character.traverse((object) => {
    if ((object as Bone).isBone) bones.push(object as Bone);
  });
  return {
    character,
    clip: bones.map((each) => ({ bone: each, turn: each.quaternion.clone() })),
    hipsAt: bone('Hips').position.clone(),
    hips: bone('Hips'),
    spine: bone('Spine'),
    chest: bone('Spine2'),
    neck: bone('Neck'),
    head: bone('Head'),
    arms: { left: side('Left'), right: side('Right') },
    legs: { left: leg('Left'), right: leg('Right') },
  };
}

/**
 * Layers and postures turn bones on top of what the clip set, so before the mixer runs each bone goes back to how
 * the clip last posed it (`unlayer`), and after it that pose is kept (`keepClipPose`): a bone the clip has no track
 * for would otherwise keep turning frame after frame, and the mixer skips writing a value it already wrote (a still
 * or paused clip), which would leave a bone where the last frame's layer put it.
 */
export function unlayer(rig: Rig) {
  for (const { bone, turn: posed } of rig.clip) bone.quaternion.copy(posed);
  rig.hips.position.copy(rig.hipsAt);
}

export function keepClipPose(rig: Rig) {
  for (const { bone, turn: posed } of rig.clip) posed.copy(bone.quaternion);
  rig.hipsAt.copy(rig.hips.position);
}

const X = new Vector3(1, 0, 0);
const axis = new Vector3();
const turn = new Quaternion();
const parentTurn = new Quaternion();
const characterTurn = new Quaternion();

/** The parent's turn in the character's frame. */
function parentInCharacter(rig: Rig, bone: Bone) {
  rig.character.getWorldQuaternion(characterTurn).invert();
  return bone.parent!.getWorldQuaternion(parentTurn).premultiply(characterTurn);
}

/** Turns a bone by `angle` about an axis of the character's frame (after the clip posed it). */
function turnAbout(rig: Rig, bone: Bone, along: Vector3, angle: number) {
  if (angle === 0) return;
  axis.copy(along).applyQuaternion(parentInCharacter(rig, bone).invert());
  bone.quaternion.premultiply(turn.setFromAxisAngle(axis, angle));
  bone.updateMatrixWorld(true);
}

const from = new Vector3();
const to = new Vector3();
const aim = new Quaternion();
const swing = new Quaternion();
const IDENTITY = new Quaternion();

/** Swings a bone so its child points `weight` of the way to `direction` (the character's frame). */
function aimAt(
  rig: Rig,
  bone: Bone,
  child: Object3D,
  direction: Vector3,
  weight: number,
) {
  if (weight <= 0) return;
  const { character } = rig;
  character.worldToLocal(child.getWorldPosition(from));
  from.sub(character.worldToLocal(bone.getWorldPosition(to))).normalize();
  swing.setFromUnitVectors(from, to.copy(direction).normalize());
  aim.slerpQuaternions(IDENTITY, swing, weight);
  // the swing in the character's frame, then in the parent's
  const parent = parentInCharacter(rig, bone);
  aim.premultiply(parent.clone().invert()).multiply(parent);
  bone.quaternion.premultiply(aim);
  bone.updateMatrixWorld(true);
}

/** 0 → 1 → 0 over `length` s: eased in and out over `edge` s. */
function envelope(t: number, length: number, edge: number) {
  if (t <= 0 || t >= length) return 0;
  const rise = Math.min(t / edge, (length - t) / edge, 1);
  return rise * rise * (3 - 2 * rise);
}

/** How long one gesture lasts (s) before it repeats, and the pause after it. */
export const GESTURE_LENGTH: Record<
  Exclude<
    Layer,
    'stalk' | 'laden' | 'pray' | 'reach' | 'reach_high' | 'swirl' | 'weave'
  >,
  number
> = {
  wave: 2.2,
  bow: 1.8,
  nod: 1.2,
  shake_head: 1.4,
  point: 1.6,
  laugh: 2,
  jump: 0.6,
};
const GESTURE_PAUSE = 1;
/** A blow taken shows the first 0.6 s of `Hard landing` (10 §4.5). */
const HIT_SECONDS = 0.6;

/** How long a cue plays once (clip seconds). */
export const cueSeconds = (kind: Cue['kind']) =>
  kind === 'hit' ? HIT_SECONDS : GESTURE_LENGTH[kind];

/**
 * Whether a cue that came `age` real seconds ago has played out at the clock's `rate` (paused, by real time): a body
 * drawn only now (it was far, its model wasn't loaded) doesn't replay a wave or a blow from minutes ago.
 */
export const cueOver = (kind: Cue['kind'], age: number, rate: number) =>
  age * Math.max(visualRate(rate), 1) >= cueSeconds(kind);

/** A hop: 0.15 s crouching, 0.4 s up and down to 0.4 m, 0.05 s landing (m above the ground at clip time t). */
export const JUMP_HEIGHT = 0.4;
const CROUCH_S = 0.15;
const FLIGHT_S = 0.4;

export function hopHeight(t: number) {
  const flight = (t - CROUCH_S) / FLIGHT_S;
  if (flight <= 0 || flight >= 1) return 0;
  return JUMP_HEIGHT * 4 * flight * (1 - flight);
}

/** How deep the knees bend in a hop (0 standing, 1 deepest: crouching to take off, tucked at the top, landing). */
function hopBend(t: number) {
  if (t <= 0 || t >= GESTURE_LENGTH.jump) return 0;
  if (t < CROUCH_S) return Math.sin((t / CROUCH_S) * (Math.PI / 2));
  const flight = (t - CROUCH_S) / FLIGHT_S;
  if (flight < 1) return 0.3 + 0.4 * Math.sin(flight * Math.PI);
  return (
    1 - (t - CROUCH_S - FLIGHT_S) / (GESTURE_LENGTH.jump - CROUCH_S - FLIGHT_S)
  );
}

/** Where in its cycle a repeating gesture is (s since its latest start). */
const cycle = (layer: keyof typeof GESTURE_LENGTH, t: number) =>
  t % (GESTURE_LENGTH[layer] + GESTURE_PAUSE);

const footAt = new Vector3();
const lowestFoot = (rig: Rig) =>
  Math.min(
    ...(['left', 'right'] as const).map(
      (side) =>
        rig.character.worldToLocal(rig.legs[side].foot.getWorldPosition(footAt))
          .y,
    ),
  );

/** Bends both knees by `amount` (radians at the thigh, twice that at the knee) and lowers the hips to keep the feet down. */
function bendKnees(rig: Rig, amount: number) {
  if (amount <= 0) return;
  const before = lowestFoot(rig);
  for (const side of ['left', 'right'] as const) {
    turnAbout(rig, rig.legs[side].up, X, -amount);
    turnAbout(rig, rig.legs[side].leg, X, 2 * amount);
  }
  const drop = lowestFoot(rig) - before;
  rig.hips.position.y -= drop / rig.hips.parent!.getWorldScale(footAt).y;
  rig.hips.updateMatrixWorld(true);
}

/** A hand reaching down to the ground ahead and back up, every REACH_S seconds (or up ahead, into a bush). */
const REACH_S = 1.7;
const REACH = new Vector3(-0.15, -0.75, 0.65);
const REACH_HIGH = new Vector3(-0.2, 0.45, 0.85);
/** Praying, the hands meet this far ahead of the chest and above it (m, the character's frame), this far apart. */
const PRAY_HANDS = new Vector3(0, 0.02, 0.26);
const PALM_GAP = 0.03;
/** Which way a praying arm's elbow bends: down and out to its side. */
const ELBOW_OUT = 0.6;
const shoulderAt = new Vector3();
const elbowAt = new Vector3();
const wristAt = new Vector3();
const target = new Vector3();
const toward = new Vector3();
const bendTo = new Vector3();
/** A pan swirled in a small circle once a second. */
const SWIRL_HZ = 1;
const swirled = new Vector3();
/**
 * Weaving seated: the upper arms forward and down, the forearms reaching ahead over the loom's breast beam, the hands
 * carrying the shuttle across the warp and back every WEAVE_S seconds, leaning in a little as it goes.
 */
const WEAVE_S = 2.4;
const WEAVE_ARM = new Vector3(0.2, -0.65, 0.7);
const WEAVE_FORE = new Vector3(0.12, 0.15, 1);
const WEAVE_ACROSS = 0.6;
const wove = new Vector3();
const WAVE_ARM = new Vector3(-0.55, 0.8, 0.2);
const WAVE_FORE = [new Vector3(-0.15, 1, 0.25), new Vector3(-0.75, 0.6, 0.25)];
const POINT = new Vector3(-0.2, 0.15, 1);
const JUMP_ARMS = {
  left: new Vector3(0.5, 0.6, 0.6),
  right: new Vector3(-0.5, 0.6, 0.6),
};
const waved = new Vector3();

/**
 * Layers `layer` over the clip at layer time `t` (clip seconds since it began; gestures repeat with a pause):
 * `moving` while the body is carried along its path (the stalk crouch bends the walk only then).
 * Returns how high the body hops (m, the caller lifts it).
 */
export function layer(
  rig: Rig,
  kind: Layer | null,
  t: number,
  moving: boolean,
) {
  if (!kind) return 0;
  rig.character.updateMatrixWorld(true);
  switch (kind) {
    case 'stalk':
      if (!moving) return 0;
      turnAbout(rig, rig.spine, X, 18 * DEG);
      turnAbout(rig, rig.chest, X, 10 * DEG);
      turnAbout(rig, rig.head, X, -15 * DEG);
      bendKnees(rig, 22 * DEG);
      return 0;
    case 'reach':
    case 'reach_high': {
      const weight = Math.sin((t / REACH_S) * Math.PI) ** 2;
      const { arm, fore, hand } = rig.arms.right;
      const to = kind === 'reach' ? REACH : REACH_HIGH;
      aimAt(rig, arm, fore, to, 0.7 * weight);
      aimAt(rig, fore, hand, to, 0.8 * weight);
      return 0;
    }
    case 'swirl': {
      const angle = t * 2 * Math.PI * SWIRL_HZ;
      swirled.set(
        -0.1 + 0.25 * Math.cos(angle),
        -0.6,
        0.75 + 0.25 * Math.sin(angle),
      );
      aimAt(rig, rig.arms.right.fore, rig.arms.right.hand, swirled, 0.6);
      aimAt(rig, rig.arms.left.fore, rig.arms.left.hand, swirled, 0.4);
      return 0;
    }
    case 'weave': {
      const lean = 6 + 2 * Math.cos((t / WEAVE_S) * 4 * Math.PI);
      turnAbout(rig, rig.spine, X, lean * DEG);
      const across = WEAVE_ACROSS * Math.sin((t / WEAVE_S) * 2 * Math.PI);
      for (const side of ['left', 'right'] as const) {
        const { arm, fore, hand } = rig.arms[side];
        const out = side === 'left' ? 1 : -1;
        wove.copy(WEAVE_ARM).setX(out * WEAVE_ARM.x);
        aimAt(rig, arm, fore, wove, 0.8);
        wove.copy(WEAVE_FORE).setX(out * WEAVE_FORE.x + across);
        aimAt(rig, fore, hand, wove, 0.9);
      }
      return 0;
    }
    case 'laden':
      turnAbout(rig, rig.spine, X, 9 * DEG);
      turnAbout(rig, rig.chest, X, 5 * DEG);
      turnAbout(rig, rig.head, X, -8 * DEG);
      return 0;
    case 'pray': {
      const bow = 14 + 6 * Math.sin((t * 2 * Math.PI) / 6);
      turnAbout(rig, rig.spine, X, (bow / 2) * DEG);
      turnAbout(rig, rig.chest, X, (bow / 2) * DEG);
      turnAbout(rig, rig.head, X, 12 * DEG);
      handsTogether(rig);
      return 0;
    }
    case 'wave': {
      const at = cycle(kind, t);
      const weight = envelope(at, GESTURE_LENGTH.wave, 0.3);
      const { arm, fore, hand } = rig.arms.right;
      aimAt(rig, arm, fore, WAVE_ARM, weight);
      const swing = 0.5 + 0.5 * Math.sin(at * 2 * Math.PI * 2.2);
      waved.lerpVectors(WAVE_FORE[0], WAVE_FORE[1], swing);
      aimAt(rig, fore, hand, waved, weight);
      return 0;
    }
    case 'point': {
      const weight = envelope(cycle(kind, t), GESTURE_LENGTH.point, 0.35);
      const { arm, fore, hand } = rig.arms.right;
      aimAt(rig, arm, fore, POINT, weight);
      aimAt(rig, fore, hand, POINT, weight);
      turnAbout(rig, rig.head, X, 8 * DEG * weight);
      return 0;
    }
    case 'bow': {
      const weight = envelope(cycle(kind, t), GESTURE_LENGTH.bow, 0.6);
      turnAbout(rig, rig.spine, X, 22 * DEG * weight);
      turnAbout(rig, rig.chest, X, 14 * DEG * weight);
      turnAbout(rig, rig.head, X, 10 * DEG * weight);
      return 0;
    }
    case 'jump': {
      const at = cycle(kind, t);
      bendKnees(rig, 35 * DEG * hopBend(at));
      const up = Math.sin(
        Math.min(Math.max(at - CROUCH_S, 0) / FLIGHT_S, 1) * Math.PI,
      );
      for (const side of ['left', 'right'] as const)
        aimAt(
          rig,
          rig.arms[side].arm,
          rig.arms[side].fore,
          JUMP_ARMS[side],
          up * 0.8,
        );
      return hopHeight(at);
    }
    // nod, shake_head and laugh are clips (Agree, Head shake, Laughing)
    case 'nod':
    case 'shake_head':
    case 'laugh':
      return 0;
  }
}

/**
 * Puts the hands together before the chest (gassho): each arm reaches its wrist to PALM_GAP beside a point ahead of
 * the chest (two-bone reach: the elbow where the upper arm and forearm meet, bent down and out), whatever the clip
 * under it sways.
 */
function handsTogether(rig: Rig) {
  const { character } = rig;
  const local = (bone: Object3D, out: Vector3) =>
    character.worldToLocal(bone.getWorldPosition(out));
  const middle = local(rig.chest, new Vector3()).add(PRAY_HANDS);
  for (const side of ['left', 'right'] as const) {
    const { arm, fore, hand } = rig.arms[side];
    const out = side === 'left' ? 1 : -1;
    local(arm, shoulderAt);
    const upper = shoulderAt.distanceTo(local(fore, elbowAt));
    const lower = elbowAt.distanceTo(local(hand, wristAt));
    target.copy(middle).setX(middle.x + out * PALM_GAP);
    toward.subVectors(target, shoulderAt);
    const reach = Math.min(
      Math.max(toward.length(), Math.abs(upper - lower) + 1e-3),
      upper + lower - 1e-3,
    );
    toward.normalize();
    // the elbow off the shoulder-to-hands line, towards down and out
    bendTo.set(out * ELBOW_OUT, -1, 0);
    bendTo.addScaledVector(toward, -bendTo.dot(toward)).normalize();
    const along = (upper ** 2 + reach ** 2 - lower ** 2) / (2 * upper * reach);
    const angle = Math.acos(Math.min(Math.max(along, -1), 1));
    elbowAt
      .copy(toward)
      .multiplyScalar(Math.cos(angle))
      .addScaledVector(bendTo, Math.sin(angle));
    aimAt(rig, arm, fore, elbowAt, 1);
    local(fore, elbowAt);
    aimAt(rig, fore, hand, toward.subVectors(target, elbowAt), 1);
  }
}

/** The clip a gesture plays under its layer (the rest are procedural over Idle). */
export const GESTURE_CLIPS = {
  nod: 'Agree',
  shake_head: 'Head shake',
  laugh: 'Laughing',
} as const;

/** A sleeper breathes: the chest swells ±1.5 % four times a minute (10 §4.4). */
const BREATH = 0.015;
const BREATH_HZ = 0.25;

export function breathe(rig: Rig, asleep: boolean, t: number) {
  const swell = asleep ? 1 + BREATH * Math.sin(t * 2 * Math.PI * BREATH_HZ) : 1;
  rig.chest.scale.setScalar(swell);
}

/** How long the move into a posture takes (s of clip time), by where the body goes from and to. */
export function easeSeconds(from: string, to: string, dying: boolean) {
  if (from === to) return 0;
  if (dying) return 0.8;
  const lying = (posture: string) =>
    posture === 'sleeping' || posture === 'lying';
  if (lying(from) || lying(to)) return 1.2;
  return 0.8;
}

/** Where the posture frame and the character in it are placed (`rest-posture.ts` writes them). */
export interface Placement {
  posed: Vector3;
  turn: Quaternion;
  character: Vector3;
}

export const newPlacement = (): Placement => ({
  posed: new Vector3(),
  turn: new Quaternion(),
  character: new Vector3(),
});

/** Copies how `posed` and `character` are placed now into `out`. */
export function placementOf(
  posed: Object3D,
  character: Object3D,
  out: Placement,
) {
  out.posed.copy(posed.position);
  out.turn.copy(posed.quaternion);
  out.character.copy(character.position);
  return out;
}

/** Places `posed` and `character` as `placement` says. */
export function place(
  posed: Object3D,
  character: Object3D,
  placement: Placement,
) {
  posed.position.copy(placement.posed);
  posed.quaternion.copy(placement.turn);
  character.position.copy(placement.character);
}

/** A move between postures under way: where the body was placed when it began, and how far it has got. */
export interface Easing {
  from: Placement;
  elapsed: number;
  length: number;
  /** A death: the knees give way as it falls. */
  dying: boolean;
}

export const startEasing = (
  from: Placement,
  length: number,
  dying: boolean,
): Easing | null =>
  length > 0 ? { from: copyPlacement(from), elapsed: 0, length, dying } : null;

const copyPlacement = (from: Placement): Placement => ({
  posed: from.posed.clone(),
  turn: from.turn.clone(),
  character: from.character.clone(),
});

const smooth = (x: number) => x * x * (3 - 2 * x);
/** A fall speeds up like a body toppling. */
const falling = (x: number) => x * x;
const keyBones = new Vector3();

/**
 * Moves the body `dt` clip seconds on from where it was placed towards where its new posture laid it (`to`), never
 * below the ground: the hips come down only as far as the feet, head and hands allow. Returns false once done.
 */
export function ease(
  easing: Easing,
  rig: Rig,
  posed: Object3D,
  to: Placement,
  dt: number,
): boolean {
  easing.elapsed = Math.min(easing.elapsed + dt, easing.length);
  const x = easing.elapsed / easing.length;
  const e = easing.dying ? falling(x) : smooth(x);
  const { character } = rig;
  const { from } = easing;
  if (easing.dying) bendKnees(rig, 40 * DEG * Math.sin(x * Math.PI));
  posed.position.lerpVectors(from.posed, to.posed, e);
  posed.quaternion.slerpQuaternions(from.turn, to.turn, e);
  character.position.lerpVectors(from.character, to.character, e);
  // keep every end of the body above the ground the posture rests on
  posed.updateMatrixWorld(true);
  let low = 0;
  for (const bone of [
    rig.head,
    rig.hips,
    rig.legs.left.foot,
    rig.legs.right.foot,
    rig.arms.left.hand,
    rig.arms.right.hand,
  ]) {
    bone.getWorldPosition(keyBones);
    posed.parent?.worldToLocal(keyBones);
    low = Math.min(low, keyBones.y);
  }
  posed.position.y -= low;
  return easing.elapsed < easing.length;
}
