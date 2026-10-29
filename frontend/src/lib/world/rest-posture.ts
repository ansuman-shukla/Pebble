/*
 * Bodies at rest on the ground: sitting on it (resting) and lying on the back (asleep, dead). Polyfork has no clip
 * for either (its `Sitting` is a chair sit), so the posture is layered on top of the clip each frame:
 *
 *   sitting: the chair clip's upper body and thighs, knees straightened (legs out in front), the hips set down
 *   lying:   a still standing frame (Idle, frozen) with straight legs, turned onto its back about the hips
 *
 * then lifted by the posed body's own depth (its lowest skinned vertex, measured again whenever the posture or the
 * clip under it changes, until the cross-fade into it is done: a child, an elder or a long coat each rest on their own
 * underside, and a clip that loads late doesn't sink them) and tilted to the ground sampled under its back, front and
 * sides, so it rests ON the ground on a slope too. Held tools are put away while sitting or lying.
 *
 *   tilt (ground fit) ─▶ posed (on its back about the hips, lifted) ─▶ character (bones posed)
 */
import {
  type AnimationAction,
  type Bone,
  type Object3D,
  Quaternion,
  type SkinnedMesh,
  Vector3,
} from 'three';

export type Posture = 'standing' | 'sitting' | 'lying';

const LEGS = ['Left', 'Right'].flatMap((side) =>
  ['UpLeg', 'Leg', 'Foot'].map((bone) => `${side}${bone}`),
);
/** What a sitter puts down (tools in hand), and what a sleeper lays aside too (a hat, a straw cape, a stole). */
const PUT_DOWN = new Set(['attach-lefthand', 'attach-righthand']);
const LAID_ASIDE = new Set([...PUT_DOWN, 'attach-hat', 'attach-neck']);
/** Sitting on the ground, legs out in front: thighs raised this far from hanging (radians), knees bent this little. */
const SIT_THIGH = (90 * Math.PI) / 180;
const SIT_KNEE = (5 * Math.PI) / 180;
const X = new Vector3(1, 0, 0);
const UP = new Vector3(0, 1, 0);

/** The rig's own resting pose (straight legs) and hips, captured before any clip plays. */
export interface Rest {
  hips: Bone;
  hipsAt: Vector3;
  hipsTurn: Quaternion;
  legs: Map<Bone, Quaternion>;
}

export function restOf(character: Object3D): Rest {
  const bone = (name: string) => {
    const found = character
      .getObjectsByProperty('name', name)
      .find((object) => (object as Bone).isBone) as Bone | undefined;
    if (!found) throw new Error(`rest-posture: the character has no ${name}`);
    return found;
  };
  const hips = bone('Hips');
  return {
    hips,
    hipsAt: hips.position.clone(),
    hipsTurn: hips.quaternion.clone(),
    legs: new Map(
      LEGS.map((name) => {
        const leg = bone(name);
        return [leg, leg.quaternion.clone()];
      }),
    ),
  };
}

const bend = new Quaternion();
/** How a ground sitter's leg bones turn from straight (about their x axis, radians). */
const SIT_BENDS: Record<string, number> = {
  UpLeg: -SIT_THIGH,
  Leg: SIT_KNEE,
  Foot: 0,
};

/**
 * Bends the clip just played into the posture (call after every mixer update): sitting puts the legs of the chair
 * sit out in front; lying straightens them and puts the hips back where the rig keeps them (no sway).
 */
export function holdPosture(rest: Rest, posture: Posture) {
  if (posture === 'standing') return;
  for (const [bone, straight] of rest.legs) {
    const turn =
      posture === 'lying'
        ? 0
        : SIT_BENDS[bone.name.replace(/^(Left|Right)/, '')];
    bone.quaternion.copy(straight).multiply(bend.setFromAxisAngle(X, turn));
  }
  if (posture === 'lying') {
    rest.hips.position.copy(rest.hipsAt);
    rest.hips.quaternion.copy(rest.hipsTurn);
  }
}

/** Tools in hand are put down while sitting; a sleeper also lays aside a hat, a straw cape or a stole. */
export function showWorn(character: Object3D, posture: Posture) {
  const aside =
    posture === 'lying' ? LAID_ASIDE : posture === 'sitting' ? PUT_DOWN : null;
  character.traverse((object) => {
    if (LAID_ASIDE.has(object.name)) object.visible = !aside?.has(object.name);
  });
}

/** How a posed body sits in its posture frame: the lift that sets its lowest point on the ground, and its reach. */
export interface Footprint {
  lift: number;
  /** How far it reaches behind (negative) and in front of the origin along its facing, and to either side (m). */
  back: number;
  front: number;
  half: number;
  /** Height of the hips above the ground once lifted (m). */
  hips: number;
}

const shown = (object: Object3D) => {
  for (let at: Object3D | null = object; at; at = at.parent)
    if (!at.visible) return false;
  return true;
};

/**
 * Turns the posed body into its posture frame (`posed` holds the character: lying on its back with the hips over
 * the origin) and measures, from every skinned vertex (a few thousand: sampling could miss a heel), how far to lift
 * it so its lowest point is on the ground. Sets `posed` up with that lift and returns it with the body's reach.
 */
export function settle(
  posed: Object3D,
  character: Object3D,
  rest: Rest,
  posture: Posture,
): Footprint {
  const lying = posture === 'lying';
  posed.position.set(0, 0, 0);
  posed.rotation.set(lying ? -Math.PI / 2 : 0, 0, 0);
  character.position.set(0, lying ? -rest.hipsAt.y : 0, 0);
  posed.updateMatrixWorld(true);
  const vertex = new Vector3();
  let low = Infinity;
  let back = 0;
  let front = 0;
  let half = 0;
  character.traverse((object) => {
    const mesh = object as SkinnedMesh;
    if (!mesh.isSkinnedMesh || !shown(mesh)) return;
    mesh.skeleton.update();
    const count = mesh.geometry.attributes.position.count;
    for (let i = 0; i < count; i++) {
      mesh.getVertexPosition(i, vertex);
      mesh.localToWorld(vertex);
      posed.parent?.worldToLocal(vertex);
      low = Math.min(low, vertex.y);
      back = Math.min(back, vertex.z);
      front = Math.max(front, vertex.z);
      half = Math.max(half, Math.abs(vertex.x));
    }
  });
  if (!Number.isFinite(low))
    throw new Error('rest-posture: no visible skin to rest on');
  posed.position.y = -low;
  posed.updateMatrixWorld(true);
  const hips = rest.hips.getWorldPosition(new Vector3());
  posed.parent?.worldToLocal(hips);
  return { lift: -low, back, front, half, hips: hips.y };
}

/** Ground heights under a resting body, relative to the ground under its origin (m). */
export interface Under {
  back: number;
  front: number;
  left: number;
  right: number;
}

const normal = new Vector3();

/**
 * The tilt that lays the body's underside along the ground sampled under its back and front ends and its sides
 * (a plane through the ground under the origin): written into `out`. `right` is the side of local +x.
 */
export function groundTilt(print: Footprint, under: Under, out: Quaternion) {
  const along = print.front - print.back;
  const across = 2 * print.half;
  const slopeZ = along > 0 ? (under.front - under.back) / along : 0;
  const slopeX = across > 0 ? (under.right - under.left) / across : 0;
  return out.setFromUnitVectors(
    UP,
    normal.set(-slopeX, 1, -slopeZ).normalize(),
  );
}

/**
 * What a resting body's shape hangs on: its posture, the action its clips fade into (a stand-in while the posture's
 * own clip is still loading) and whether that cross-fade is under way.
 */
export interface Shape {
  posture: Posture;
  action: AnimationAction | null;
  fading: boolean;
}

/** The shape of a body playing `action` among `actions` (every clip of its mixer) in `posture`. */
export function shapeOf(
  posture: Posture,
  action: AnimationAction | null,
  actions: Iterable<AnimationAction>,
): Shape {
  let fading = action !== null && action.getEffectiveWeight() < 1;
  for (const other of actions)
    if (
      other !== action &&
      other.isScheduled() &&
      other.getEffectiveWeight() > 0
    )
      fading = true;
  return { posture, action, fading };
}

/**
 * Whether a resting body must be measured again: its posture or its clip changed (the posture's clip arrived and
 * replaced the stand-in), or the clips are cross-fading, or were until this frame. A settled body is not.
 */
export function reshaped(was: Shape | null, now: Shape) {
  if (now.posture === 'standing') return false;
  return (
    was === null ||
    was.posture !== now.posture ||
    was.action !== now.action ||
    was.fading ||
    now.fading
  );
}

/** Heights of the ground under a body (m, relative to the ground under it) `forward` along its facing, `side` across. */
export type GroundProbe = (forward: number, side: number) => number;

/** A body's last shape and, while it rests, its measured footprint. */
export interface Resting {
  shape: Shape | null;
  print: Footprint | null;
}

const under: Under = { back: 0, front: 0, left: 0, right: 0 };

/**
 * Lays a sitting or lying body on the ground (call every frame after `holdPosture`): hides what it doesn't hold at
 * rest, measures its footprint again when its shape changed, and tilts it to the ground under its ends.
 */
export function layToRest(
  state: Resting,
  shape: Shape,
  body: {
    character: Object3D;
    rest: Rest;
    tilt: Object3D;
    posed: Object3D;
    ground: GroundProbe;
  },
) {
  const { character, rest, tilt, posed, ground } = body;
  const was = state.shape;
  state.shape = shape;
  if (shape.posture !== (was?.posture ?? 'standing'))
    showWorn(character, shape.posture);
  if (shape.posture === 'standing') {
    if (state.print === null) return;
    posed.position.set(0, 0, 0);
    posed.rotation.set(0, 0, 0);
    character.position.set(0, 0, 0);
    tilt.quaternion.identity();
    state.print = null;
    return;
  }
  if (state.print === null || reshaped(was, shape))
    state.print = settle(posed, character, rest, shape.posture);
  const { print } = state;
  under.back = ground(print.back, 0);
  under.front = ground(print.front, 0);
  under.left = ground(0, -print.half);
  under.right = ground(0, print.half);
  groundTilt(print, under, tilt.quaternion);
}
