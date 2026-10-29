/*
 * Bodies at rest on the ground: sitting on it (resting) and lying on the back (asleep, dead). Polyfork has no clip
 * for either (its `Sitting` is a chair sit), so the posture is layered on top of the clip each frame:
 *
 *   seated:   the chair clip on a seat: lifted so the hips rest at the seat's height, the knees lowered to reach
 *             down towards the ground (a child's feet dangle)
 *   sitting:  the chair clip's upper body and thighs, knees straightened (legs out in front), the hips set down
 *   kneeling: the clip's upper body on upright thighs, the shins flat on the ground behind
 *   lying:    a still standing frame (Idle, frozen) with straight legs, turned onto its back about the hips (the dead)
 *   sleeping: lying, but the right knee drawn up (its foot flat on the ground) and the head turned aside, so a
 *             sleeper doesn't look dead
 *
 * then lifted by the posed body's own depth (its lowest skinned vertex, measured again whenever the posture or the
 * clip under it changes, until the cross-fade into it is done: a child, an elder or a long coat each rest on their own
 * underside, and a clip that loads late doesn't sink them) and tilted to the ground sampled under its back, front and
 * sides, so it rests ON the ground on a slope too. Held tools are hidden while sitting or lying.
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

export type Posture =
  'standing' | 'seated' | 'sitting' | 'kneeling' | 'sleeping' | 'lying';

const onBack = (posture: Posture) =>
  posture === 'sleeping' || posture === 'lying';

const LEGS = ['Left', 'Right'].flatMap((side) =>
  ['UpLeg', 'Leg', 'Foot'].map((bone) => `${side}${bone}`),
);
/**
 * What a sitter hides (whatever hangs off its hands: a hand prop must be attached under these to be hidden too),
 * and what a body on its back also hides (a hat, a straw cape, a stole).
 */
const IN_HAND = new Set(['attach-lefthand', 'attach-righthand']);
const HIDDEN_ON_BACK = new Set([...IN_HAND, 'attach-hat', 'attach-neck']);
const DEG = Math.PI / 180;
/**
 * Leg bones turn from straight about their x axis (radians; negative swings forward). Sitting on the ground, legs
 * out in front: thighs raised level, knees bent this little.
 */
const SIT_BENDS: Record<string, number> = {
  UpLeg: -90 * DEG,
  Leg: 5 * DEG,
  Foot: 0,
};
/**
 * Kneeling: thighs upright (leaning a little ahead), shins flat on the ground behind, feet stretched back. Not seiza
 * (sitting on the heels): a long robe's hem, skinned partly to the hips, would stay where it hangs standing and
 * reach far under the folded legs.
 */
const KNEEL_BENDS: Record<string, number> = {
  UpLeg: -15 * DEG,
  Leg: 105 * DEG,
  Foot: 80 * DEG,
};
/** How each posture on the ground bends the legs from straight (on the back they lie straight). */
const LEG_BENDS: Partial<Record<Posture, Record<string, number>>> = {
  sitting: SIT_BENDS,
  kneeling: KNEEL_BENDS,
};
/**
 * A sleeper's drawn-up right leg, lying on its back: the thigh rises `thigh` from the line of the straight leg and
 * the shin slopes back down `shin` from it to the foot, whose sole lies flat on the ground (radians).
 */
interface Knee {
  thigh: number;
  shin: number;
}
/** Until `settle` measures how far down the foot must reach (and lower when a short leg can't reach from it). */
const SLEEP_KNEE: Knee = { thigh: 35 * DEG, shin: 60 * DEG };
/** The steepest the shin goes before the thigh comes down instead. */
const STEEPEST_SHIN = 80 * DEG;
/** A sleeper's head turns this far to its side (radians, about the head's up axis). */
const SLEEP_HEAD = 25 * DEG;
/**
 * How high a seat is (m): the feed doesn't carry a slot's height yet, so every seat is a bench's (a camp's log seat
 * is 0.4).
 */
export const SEAT_HEIGHT = 0.45;
/**
 * Where Polyfork's chair sit (`Sitting`) puts the underside of the hips, as a share of the rig's hip height at rest
 * (0.44-0.50 measured over adults and children).
 */
const CHAIR_SEAT = 0.47;
/** A seated body's knees come down at most this far to reach for the ground (radians). */
const SEAT_KNEE_DROP = 25 * DEG;
const X = new Vector3(1, 0, 0);
const UP = new Vector3(0, 1, 0);

/**
 * The rig's own resting pose (straight legs, head ahead), hips and the ankle's height over the sole, captured
 * before any clip plays.
 */
export interface Rest {
  hips: Bone;
  hipsAt: Vector3;
  hipsTurn: Quaternion;
  head: Bone;
  headTurn: Quaternion;
  legs: Map<string, { bone: Bone; straight: Quaternion }>;
  ankle: number;
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
  const head = bone('Head');
  return {
    hips,
    hipsAt: hips.position.clone(),
    hipsTurn: hips.quaternion.clone(),
    head,
    headTurn: head.quaternion.clone(),
    legs: new Map(
      LEGS.map((name) => {
        const leg = bone(name);
        return [name, { bone: leg, straight: leg.quaternion.clone() }];
      }),
    ),
    // the character is built standing on y = 0
    ankle: character.worldToLocal(
      bone('RightFoot').getWorldPosition(new Vector3()),
    ).y,
  };
}

const bend = new Quaternion();

const turnLeg = (rest: Rest, name: string, angle: number) => {
  const { bone, straight } = rest.legs.get(name)!;
  bone.quaternion.copy(straight).multiply(bend.setFromAxisAngle(X, angle));
};

const drawKnee = (rest: Rest, { thigh, shin }: Knee) => {
  turnLeg(rest, 'RightUpLeg', -thigh);
  turnLeg(rest, 'RightLeg', thigh + shin);
  turnLeg(rest, 'RightFoot', Math.PI / 2 - shin);
};

/**
 * Bends the clip just played into the posture (`layToRest` does, after every mixer update): sitting puts the legs of the chair
 * sit out in front; on the back the legs straighten (a sleeper's knee drawn up, its head turned aside) and the hips
 * go back where the rig keeps them (no sway).
 */
export function holdPosture(
  rest: Rest,
  posture: Posture,
  knee?: Knee | null,
  lift = 0,
) {
  if (posture === 'standing') return;
  if (posture === 'seated') {
    lowerKnees(rest, lift);
    return;
  }
  const bends = LEG_BENDS[posture];
  for (const name of LEGS)
    turnLeg(rest, name, bends?.[name.replace(/^(Left|Right)/, '')] ?? 0);
  if (!onBack(posture)) return;
  rest.hips.position.copy(rest.hipsAt);
  rest.hips.quaternion.copy(rest.hipsTurn);
  if (posture !== 'sleeping') return;
  drawKnee(rest, knee ?? SLEEP_KNEE);
  rest.head.quaternion
    .copy(rest.headTurn)
    .multiply(bend.setFromAxisAngle(UP, SLEEP_HEAD));
}

/**
 * A seated body lifted `lift` m above the chair clip's own seat lowers its knees (thighs sloping down, shins as the
 * clip has them) so its feet come down by as much, as far as SEAT_KNEE_DROP allows.
 */
function lowerKnees(rest: Rest, lift: number) {
  if (lift <= 0) return;
  for (const side of ['Left', 'Right']) {
    const thigh = rest.legs.get(`${side}UpLeg`)!.bone;
    const shin = rest.legs.get(`${side}Leg`)!.bone;
    const length = shin.position.length() * thigh.getWorldScale(scaleOf).y;
    const drop = Math.min(
      Math.asin(Math.min(lift / length, 1)),
      SEAT_KNEE_DROP,
    );
    thigh.quaternion.multiply(bend.setFromAxisAngle(X, drop));
    shin.quaternion.multiply(bend.setFromAxisAngle(X, -drop));
  }
}

const scaleOf = new Vector3();

/**
 * Tools in hand are hidden while sitting; on the back or kneeling a hat, a straw cape or a stole are hidden too (a
 * kneeler's cape would reach the ground behind it, and the hat comes off to pray).
 */
export function showWorn(character: Object3D, posture: Posture) {
  const hidden =
    onBack(posture) || posture === 'kneeling'
      ? HIDDEN_ON_BACK
      : posture === 'standing'
        ? null
        : IN_HAND;
  character.traverse((object) => {
    if (HIDDEN_ON_BACK.has(object.name))
      object.visible = !hidden?.has(object.name);
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
  /** A sleeper's drawn-up leg that sets its foot on the ground (null in other postures). */
  knee: Knee | null;
}

const shown = (object: Object3D) => {
  for (let at: Object3D | null = object; at; at = at.parent)
    if (!at.visible) return false;
  return true;
};

/** The bones a kneeler rests on: skin that follows only them sets how low it goes. */
const SHINS = new Set(
  ['Left', 'Right'].flatMap((side) =>
    ['Leg', 'Foot', 'ToeBase'].map((bone) => `${side}${bone}`),
  ),
);

/** How much of vertex `i`'s skin follows `bones` (0-1). */
function weightOn(mesh: SkinnedMesh, i: number, bones: ReadonlySet<string>) {
  const { skinIndex, skinWeight } = mesh.geometry.attributes;
  let weight = 0;
  for (let k = 0; k < 4; k++)
    if (bones.has(mesh.skeleton.bones[skinIndex.getComponent(i, k)].name))
      weight += skinWeight.getComponent(i, k);
  return weight;
}

/**
 * The lowest point and the reach of the posed body's skin, in the frame `posed` sits in; with `restsOn`, the lowest
 * point of the skin that (nearly) only follows those bones (a kneeler's shins: a long robe's hem, skinned partly to the hips,
 * hangs where it would standing and goes into the ground like cloth spread on it, instead of holding the body up).
 */
function measure(
  posed: Object3D,
  character: Object3D,
  restsOn?: ReadonlySet<string>,
) {
  posed.updateMatrixWorld(true);
  const vertex = new Vector3();
  const reach = { low: Infinity, back: 0, front: 0, half: 0 };
  character.traverse((object) => {
    const mesh = object as SkinnedMesh;
    if (!mesh.isSkinnedMesh || !shown(mesh)) return;
    mesh.skeleton.update();
    const count = mesh.geometry.attributes.position.count;
    for (let i = 0; i < count; i++) {
      mesh.getVertexPosition(i, vertex);
      mesh.localToWorld(vertex);
      posed.parent?.worldToLocal(vertex);
      if (!restsOn || weightOn(mesh, i, restsOn) > 0.9)
        reach.low = Math.min(reach.low, vertex.y);
      reach.back = Math.min(reach.back, vertex.z);
      reach.front = Math.max(reach.front, vertex.z);
      reach.half = Math.max(reach.half, Math.abs(vertex.x));
    }
  });
  if (!Number.isFinite(reach.low))
    throw new Error('rest-posture: no visible skin to rest on');
  return reach;
}

/** Where a bone is in the frame `posed` sits in. */
const boneAt = (posed: Object3D, bone: Object3D) => {
  const at = bone.getWorldPosition(new Vector3());
  return posed.parent ? posed.parent.worldToLocal(at) : at;
};

const asinWithin = (value: number, low: number, high: number) =>
  Math.asin(Math.min(high, Math.max(low, value)));

/**
 * The drawn-up leg that sets a sleeper's right foot flat on the ground at `low` (its back's underside, measured with
 * the leg straight): the knee rises with the thigh and the shin reaches down from it to the ankle's height over the
 * sole; a leg too short to reach from the usual knee lowers its thigh.
 */
function kneeToGround(posed: Object3D, rest: Rest, low: number): Knee {
  const [hip, knee, ankle] = ['RightUpLeg', 'RightLeg', 'RightFoot'].map(
    (name) => boneAt(posed, rest.legs.get(name)!.bone),
  );
  const thighLength = hip.distanceTo(knee);
  const shinLength = knee.distanceTo(ankle);
  const ankleAt = low + rest.ankle;
  const thigh = Math.min(
    SLEEP_KNEE.thigh,
    asinWithin(
      (ankleAt + shinLength * Math.sin(STEEPEST_SHIN) - hip.y) / thighLength,
      0,
      1,
    ),
  );
  const kneeAt = hip.y + thighLength * Math.sin(thigh);
  return { thigh, shin: asinWithin((kneeAt - ankleAt) / shinLength, 0, 1) };
}

/**
 * Turns the posed body into its posture frame (`posed` holds the character: lying on its back with the hips over
 * the origin) and measures, from every skinned vertex (a few thousand: sampling could miss a heel), how far to lift
 * it so its lowest point is on the ground; a sleeper's drawn-up foot is set on that ground. Sets `posed` up with
 * that lift and returns it with the body's reach.
 */
export function settle(
  posed: Object3D,
  character: Object3D,
  rest: Rest,
  posture: Posture,
): Footprint {
  const lying = onBack(posture);
  if (posture === 'seated') return seat(posed, character, rest);
  posed.position.set(0, 0, 0);
  posed.rotation.set(lying ? -Math.PI / 2 : 0, 0, 0);
  character.position.set(0, lying ? -rest.hipsAt.y : 0, 0);
  let knee: Knee | null = null;
  if (posture === 'sleeping') {
    for (const name of ['RightUpLeg', 'RightLeg', 'RightFoot'])
      turnLeg(rest, name, 0);
    knee = kneeToGround(posed, rest, measure(posed, character).low);
    drawKnee(rest, knee);
  }
  const { low, back, front, half } = measure(
    posed,
    character,
    posture === 'kneeling' ? SHINS : undefined,
  );
  posed.position.y = -low;
  posed.updateMatrixWorld(true);
  return {
    lift: -low,
    back,
    front,
    half,
    hips: boneAt(posed, rest.hips).y,
    knee,
  };
}

/**
 * A seated body: lifted (never tilted) so the chair clip's seat comes to SEAT_HEIGHT; never lowered (an adult's own
 * chair is up to 0.03 m higher), so its feet stay on the ground.
 */
function seat(posed: Object3D, character: Object3D, rest: Rest): Footprint {
  const lift = Math.max(SEAT_HEIGHT - CHAIR_SEAT * rest.hipsAt.y, 0);
  posed.position.set(0, lift, 0);
  posed.rotation.set(0, 0, 0);
  character.position.set(0, 0, 0);
  posed.updateMatrixWorld(true);
  return {
    lift,
    back: 0,
    front: 0,
    half: 0,
    hips: boneAt(posed, rest.hips).y,
    knee: null,
  };
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
 * Lays a sitting or lying body on the ground (call every frame after the mixer's update): bends it into its
 * posture, hides what it doesn't hold at rest, measures its footprint again when its shape changed, and tilts it
 * to the ground under its ends.
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
  holdPosture(rest, shape.posture, state.print?.knee, state.print?.lift);
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
  if (shape.posture === 'seated') {
    tilt.quaternion.identity();
    return;
  }
  under.back = ground(print.back, 0);
  under.front = ground(print.front, 0);
  under.left = ground(0, -print.half);
  under.right = ground(0, print.half);
  groundTilt(print, under, tilt.quaternion);
}
