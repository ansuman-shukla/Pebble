/*
 * Drawn bodies never pass through each other (10 §4.3, D192). Every frame each drawn citizen is shifted off the spot
 * its track draws it at (`drawn-track.ts`, after the keep-right lane) by a small offset on the ground, away from anyone
 * drawn closer than KEEP_M now or about to be: a body on the move looks ahead along its pace (closest approach within
 * LOOK_S, at most LOOK_M of closing in) and, head-on, sidesteps right of the way it goes, like the lanes. Once clear the offset
 * eases back to nothing, so a body at rest stands exactly where the feed says unless it would stand inside someone.
 *
 *   spot (track) ──+ offset──▶ drawn        pushed apart ≤ MAX_MPS · Δt a frame; eased to 0 when clear
 *
 * Who gives way (`giveOf`): a walker more than someone standing still (GIVE); seated, sitting and lying bodies never
 * move, others step round them, and someone sitting or lying down while stepped aside stands until back on the spot
 * (`standsUntilBack`), so nobody slides seated; bodies out of sight (inside a house) leave the crowd. Time is the
 * film's (`visualRate`): at ×10 it all happens ten times faster, past that bodies glide; with the clock at 0 (paused,
 * a replayed moment) bodies on one spot part at once and nothing else moves. Drawn only: the sim, the paths and their
 * joins stay where the feed says.
 *
 * Pure (no DOM, no React): `globe-npcs.tsx` keeps one crowd and one body per citizen; the tests drive it directly.
 */
import { Vector3 } from 'three';

/** Drawn bodies are kept this far apart (centre to centre, metres): the body itself is about 0.5 m across. */
export const KEEP_M = 0.7;
/** A body on the move sees someone coming this long ahead (seconds of motion)... */
const LOOK_S = 1;
/**
 * ...and never further than this (metres of closing in): two runners head-on close 7 m in that second, while
 * time-lapse walkers don't look kilometres ahead.
 */
const LOOK_M = 8;
/** The fastest the offset changes (metres per second of motion): with a walker's pace, under 0.04 m a frame at ×1. */
const MAX_MPS = 0.9;
/** How fast a clear body eases back onto its spot (1/s of motion)... */
const RETURN_RATE = 2;
/** ...and never slower than this over the last few centimetres (metres per second of motion), so it gets there. */
const MIN_RETURN_MPS = 0.25;

/** How readily a body gives way, by what it is drawn doing. */
export const GIVE = { walking: 1, standing: 0.5, resting: 0 } as const;

/** Postures of bodies out of sight, which leave the crowd (nobody steps round them). */
const UNSEEN: ReadonlySet<string> = new Set(['inside', 'hidden']);

/**
 * How readily a body in this posture gives way (`moving`: drawn walking its path), null out of sight. Only a standing
 * body moves; any other posture (seated, sitting, sitting on the ground, sleeping, lying, crouching, or one added
 * later) never does.
 */
export function giveOf(posture: string, moving: boolean): number | null {
  if (UNSEEN.has(posture)) return null;
  if (posture !== 'standing') return GIVE.resting;
  return moving ? GIVE.walking : GIVE.standing;
}

/**
 * Whether a body shown standing that is about to sit or lie down (`resting` next) should stand a moment longer: while
 * it is drawn stepped aside it eases back onto its spot first, then sits there.
 */
export const standsUntilBack = (body: CrowdBody, resting: boolean) =>
  resting && body.offset.lengthSq() > 0;

export interface CrowdBody {
  /** Where its track drew it last frame (unit direction), before the offset. */
  spot: Vector3;
  /** Where it was drawn last frame (unit direction): the spot plus the offset. */
  drawn: Vector3;
  /** How fast its spot moves (metres per second of motion, on the ground). */
  velocity: Vector3;
  /** Drawn minus spot (metres, on the ground). */
  offset: Vector3;
  /** How readily it gives way (GIVE); 0 never moves. */
  give: number;
  /** A fixed direction of its own, to part bodies drawn on one point the same way every time. */
  seed: Vector3;
  /** Drawn at least once (a body joins the crowd before its first frame). */
  placed: boolean;
}

export type Crowd = Set<CrowdBody>;

/** A deterministic unit vector for an id (FNV-1a hash), the same on every page. */
function seedOf(id: string) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < id.length; i++)
    hash = Math.imul(hash ^ id.charCodeAt(i), 0x01000193) >>> 0;
  const turn = (hash / 2 ** 32) * 2 * Math.PI;
  const tilt = ((Math.imul(hash, 0x9e3779b1) >>> 0) / 2 ** 32) * 2 - 1;
  const across = Math.sqrt(1 - tilt * tilt);
  return new Vector3(across * Math.cos(turn), across * Math.sin(turn), tilt);
}

export function newCrowdBody(id: string): CrowdBody {
  return {
    spot: new Vector3(),
    drawn: new Vector3(),
    velocity: new Vector3(),
    offset: new Vector3(),
    give: GIVE.standing,
    seed: seedOf(id),
    placed: false,
  };
}

const flat = (vector: Vector3, up: Vector3) =>
  vector.addScaledVector(up, -vector.dot(up));

const apart = new Vector3();
const closing = new Vector3();
const closest = new Vector3();
const miss = new Vector3();
const away = new Vector3();
const mine = new Vector3();
const theirs = new Vector3();
const push = new Vector3();
const eased = new Vector3();

/** Right of the way a body moves (a unit vector on the ground into `out`), zero standing still. */
function rightOf(body: CrowdBody, up: Vector3, out: Vector3) {
  out.crossVectors(body.velocity, up);
  const length = out.length();
  return length > 1e-6 ? out.divideScalar(length) : out.set(0, 0, 0);
}

/**
 * Which way to part two bodies drawn on (or coming to) one point: each sidesteps right of the way it moves (head-on
 * they part to opposite sides, someone standing steps to the walker's left), else their seeds decide; opposite for
 * the other body, so the pair always parts.
 */
function parting(body: CrowdBody, other: CrowdBody, up: Vector3, out: Vector3) {
  out.subVectors(rightOf(body, up, mine), rightOf(other, up, theirs));
  if (out.lengthSq() < 0.01) flat(out.subVectors(body.seed, other.seed), up);
  return out.normalize();
}

/**
 * How close the body drawn at `spot` + `offset` comes to `other` (metres; Infinity out of reach): now, or for a pair
 * closing in, at their closest within LOOK_S (and LOOK_M). Leaves the other's place at that moment, seen from the
 * body, in `closest`, and which way to step clear of it in `miss`: across the way they close in (stepping back along
 * it only meets them later), or straight away from it when they aren't closing in; zero when they meet head-on.
 */
function closestGap(
  body: CrowdBody,
  other: CrowdBody,
  spot: Vector3,
  offset: Vector3,
  radius: number,
) {
  flat(
    apart
      .copy(spot)
      .multiplyScalar(radius)
      .add(offset)
      .addScaledVector(other.drawn, -radius),
    spot,
  );
  if (apart.lengthSq() > (LOOK_M + KEEP_M) ** 2) return Infinity;
  flat(closing.subVectors(body.velocity, other.velocity), spot); // velocities lie on their own ground
  const speed = closing.length();
  const ahead =
    speed > 1e-6
      ? Math.min(
          Math.max(-apart.dot(closing) / (speed * speed), 0),
          LOOK_S,
          LOOK_M / speed,
        )
      : 0;
  closest.copy(apart).addScaledVector(closing, ahead);
  miss.copy(closest);
  if (ahead > 0)
    miss.addScaledVector(closing, -miss.dot(closing) / (speed * speed));
  return closest.length();
}

/** Whether a body drawn with this offset would come closer than KEEP_M to anyone. */
function wouldCrowd(
  crowd: Crowd,
  body: CrowdBody,
  spot: Vector3,
  offset: Vector3,
  radius: number,
) {
  for (const other of crowd)
    if (
      other !== body &&
      other.placed &&
      closestGap(body, other, spot, offset, radius) < KEEP_M
    )
      return true;
  return false;
}

/**
 * Draws `body` apart from the rest of the crowd: `spot` (a unit direction, changed in place) is where its track draws
 * it this frame, `give` how readily it gives way now (`giveOf`; null: out of sight, it leaves the crowd), `delta`
 * seconds of motion since the last frame (real seconds sped up like the clips, `visualRate`: up to ×10 the film runs
 * faster; 0 with the clock paused or on a replayed moment: bodies on one spot part at once, nothing eases) and
 * `radius` the planet's. Returns `spot`, shifted by the body's offset.
 */
export function separate(
  crowd: Crowd,
  body: CrowdBody,
  spot: Vector3,
  give: number | null,
  delta: number,
  radius: number,
) {
  if (give === null) {
    body.placed = false; // nobody steps round it, and it comes back on its spot
    body.offset.set(0, 0, 0);
    return spot;
  }
  if (!body.placed || delta === 0) body.velocity.set(0, 0, 0);
  else
    flat(
      body.velocity.subVectors(spot, body.spot).multiplyScalar(radius / delta),
      spot,
    );
  body.spot.copy(spot);
  body.placed = true;
  body.give = give;
  flat(body.offset, spot);
  push.set(0, 0, 0);
  let crowded = false;
  let yielding = 0; // the biggest share of a gap it takes (½ between equals)
  if (give > 0)
    for (const other of crowd) {
      if (other === body || !other.placed) continue;
      const gap = closestGap(body, other, spot, body.offset, radius);
      if (gap >= KEEP_M) continue;
      crowded = true;
      if (miss.lengthSq() > 1e-6) away.copy(miss).normalize();
      else parting(body, other, spot, away);
      const share = give / (give + other.give);
      yielding = Math.max(yielding, share);
      push.addScaledVector(away, (KEEP_M - gap) * share);
    }
  const most = MAX_MPS * delta;
  if (crowded) {
    // the one giving way less also steps aside slower, so it still moves less while both step at their fastest; with
    // the clock at 0 nothing animates, so they part at once
    const fastest = most * Math.min(2 * yielding, 1);
    if (delta > 0 && push.lengthSq() > fastest * fastest)
      push.setLength(fastest);
    body.offset.add(push);
  } else if (body.offset.lengthSq() > 0) {
    // clear: ease back onto the spot, unless that would step into someone (a body at rest that would overlap holds)
    const off = body.offset.length();
    const back = Math.min(
      off,
      most,
      Math.max(
        off * (1 - Math.exp(-RETURN_RATE * delta)),
        MIN_RETURN_MPS * delta,
      ),
    );
    eased.copy(body.offset).multiplyScalar(1 - back / off);
    if (give === 0 || !wouldCrowd(crowd, body, spot, eased, radius))
      body.offset.copy(eased);
  }
  if (body.offset.lengthSq() > 0)
    spot.multiplyScalar(radius).add(body.offset).normalize();
  body.drawn.copy(spot);
  return spot;
}
