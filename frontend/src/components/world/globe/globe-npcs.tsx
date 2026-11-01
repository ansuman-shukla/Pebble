import { useFrame } from '@react-three/fiber';
import {
  memo,
  type RefObject,
  useEffect,
  useEffectEvent,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  type AnimationAction,
  type Group,
  type Material,
  Matrix4,
  type Mesh,
  type Object3D,
  Vector3,
} from 'three';

import type { GlobePlayerState } from './globe-player';
import { LabelAnchor } from '@/components/world/labels';
import { MAX_FRAME, smoothing } from '@/components/world/player/motion';
import type { LiveCitizen } from '@/lib/live/live-contract';
import { type Cue, type TickClock, tickElapsed } from '@/lib/live/live-state';
import {
  follow,
  keepRight,
  moveOn,
  newTrack,
  shownDoing,
  type Doing,
  type Track,
} from '@/lib/live/drawn-track';
import {
  BAKED_HIP,
  BASE_CLIPS,
  type BodyPose,
  gaitOf,
  type HeldProp,
  isPlanted,
  type Layer,
  type Motion,
  type MotionLook,
  motionLook,
  motionOf,
  type NpcClip,
} from '@/lib/live/motion';
import {
  type Crowd,
  type CrowdBody,
  giveOf,
  newCrowdBody,
  separate,
  standsUntilBack,
} from '@/lib/live/separation';
import type { ShownDoings } from '@/lib/live/shown-doings';
import { groundSpeed, headingAt, walking } from '@/lib/live/walk-path';
import { CITIZEN_LOOKS, type CitizenLook } from '@/lib/world/citizen-looks';
import { type GameClock, sunDirection } from '@/lib/world/game-clock';
import { type GlobeTerrain, tangentFrame } from '@/lib/world/globe';
import {
  freeHand,
  holderOf,
  loadProp,
  propAsset,
  propModel,
} from '@/lib/world/hand-props';
import type { LabelStore } from '@/lib/world/label-store';
import { animateHumanoid } from '@/lib/world/humanoid-clips';
import {
  breathe,
  cueOver,
  cueSeconds,
  ease,
  easeSeconds,
  type Easing,
  GESTURE_CLIPS,
  layer,
  newPlacement,
  place,
  type Placement,
  placementOf,
  rigOf,
  keepClipPose,
  startEasing,
  unlayer,
} from '@/lib/world/poses';
import {
  type GroundProbe,
  layToRest,
  type Posture,
  type Resting,
  restOf,
  shapeOf,
  showWorn,
} from '@/lib/world/rest-posture';
import { clockRate, visualRate } from '@/lib/world/visual-rate';
import { groundUnder, type WalkTown } from '@/lib/world/walk-charts';
import type { CharacterAnimation } from '@/vendor/polyfork/clips.mjs';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

/*
 * The citizens on the planet, where the live feed says they are. Between ticks a mover walks the timed path its
 * tick streamed (`route`, from where it stood when the tick began) with game seconds passing at the clock's speed
 * (`walk-path.ts`): at ×1 a real 1.4 m/s for a real minute, along the route's corners, so every move is drawn as
 * walking, one tick behind the sim. A new tick joins the drawn spot onto its path (normally where the last one
 * ended); one drawn far off (a reconnect, a hidden tab) fades out and back in on its path instead of jumping. Each
 * one faces the way it walks (its heading, or its seat's, when standing), turns smoothly to it and stands on the
 * rendered ground (the town's plateau on its disc, else the terrain).
 *
 * What the body does comes from its motion (`motion.ts`, 10 §4.5): on the move a gait (walk, formal, loaded, run)
 * paced to the drawn ground speed so planted feet don't slip; standing still the motion's clip (chopping, mining,
 * planting, fishing...) with what it holds in hand (`hand-props.ts`) and a procedural layer where Polyfork has no
 * clip (`poses.ts`: the hunter's creep, gestures and the jump, prayer, breathing). Sitters and sleepers rest on the
 * ground or a seat (`rest-posture.ts`), easing into it (lying down 1.2 s, a death's fall 0.8 s), and one going
 * inside opens the door and is gone. Every clip plays sped up with the clock (a fast-forwarded film, `visualRate`),
 * up to ×10: past that legs would blur, so they keep that cadence and the body glides. Models load only within NEAR
 * metres of the camera (and hide again past it); clips load per motion as first needed, props within PROP_NEAR.
 * The labels hang over the head bone (priority 1), over the body before the model is there.
 * Drawn bodies are kept apart (`separation.ts`): walkers part as they meet and people drawn on one spot stand
 * round it; sitters and sleepers never move.
 */

/** Full models within this distance of the camera (they hide past HIDE). */
const NEAR = 400;
const HIDE = 420;
/** Held things are drawn within this distance of the camera (they are a few centimetres wide). */
const PROP_NEAR = 80;
const LABEL_HEIGHT = 2.1;
/** Labels hang lower over lying and sitting bodies. */
const LYING_LABEL_HEIGHT = 0.7;
const SITTING_LABEL_HEIGHT = 1.2;
/** Children and teens are shorter: their labels hang lower. */
const AGE_LABEL_SCALE: Partial<Record<string, number>> = {
  kid: 0.7,
  teen: 0.93,
};
/** Labels over a loaded model hang this far above its head bone (the base of the skull). */
const HEAD_LABEL_LIFT = 0.55;
/** Turning rate towards the heading (1/s). */
const TURN_RATE = 8;
/** The sun this far below the horizon (its height over the local up) is night for a guard's torch. */
const DUSK = -0.05;

const LOOKS = new Map(CITIZEN_LOOKS.map((look) => [look.id, look]));
const basis = new Matrix4();
const side = new Vector3();
const foot = new Vector3();
const sun = new Vector3();
const up = new Vector3();
const anchored = new Vector3();

/** What the page and the tests can read of a drawn citizen (mutated every frame). */
interface NpcView {
  id: string;
  /** World position of the feet and the facing tangent (the follow camera reads these). */
  pose: GlobePlayerState;
  activity: string;
  /** How the body rests (from the motion shown). */
  posture: BodyPose;
  /** The motion shown (`motion.ts`). */
  motion: Motion;
  /** What it holds ('' for nothing), the procedural layer over its clip ('' for none). */
  prop: string;
  layer: string;
  /** Gone inside (the body is hidden after the door). */
  hidden: boolean;
  /** The clip playing, '' until the model is loaded (or while it is far). */
  clip: string;
  loaded: boolean;
  /** Within reach of the camera: the model is shown and animated. */
  near: boolean;
  /** Left then right foot in the model's own frame (x, y, z each), while it is animated. */
  feet: number[];
  /** Seconds of clip time its animation has played (clips run sped up with the clock). */
  clipClock: number;
  /** How high its head bone and its labels' anchor are above its feet (m), while it is animated. */
  heights: { head: number; label: number };
}

export type NpcViews = Map<string, NpcView>;

const wrapAngle = (angle: number) =>
  Math.atan2(Math.sin(angle), Math.cos(angle));

const wearsSpear = (look: CitizenLook) => {
  const garment = look.config.wear.righthand;
  return (typeof garment === 'string' ? garment : garment?.name) === 'yari';
};

/** A clip played on top of the motion for a while: a move between postures, a blow taken. */
interface Passing {
  clip: NpcClip;
  left: number;
}

/** A gesture or a blow shown once (a cue), whatever the motion. */
interface OneShot {
  cue: Cue;
  left: number;
}

/** How a model's body is placed and moving between frames. */
interface BodyState {
  /** The pose and the posture `rest-posture.ts` laid last frame (null before the first). */
  pose: BodyPose | null;
  posture: Posture | null;
  passing: Passing | null;
  oneShot: OneShot | null;
  layer: { kind: Layer | null; clock: number };
  /** Seconds of clip time since the model first moved (breathing). */
  clock: number;
  easing: Easing | null;
  /** Where the posture laid the body, and where it was drawn (eased, hopping). */
  laid: Placement;
  drawn: Placement;
}

const newBody = (): BodyState => ({
  pose: null,
  posture: null,
  passing: null,
  oneShot: null,
  layer: { kind: null, clock: 0 },
  clock: 0,
  easing: null,
  laid: newPlacement(),
  drawn: newPlacement(),
});

/** The clip that moves a body from one pose into another (sitting down, standing up, opening the door). */
function passingClip(from: BodyPose | null, to: BodyPose): NpcClip | null {
  if (from === null) return null;
  if (to === 'seated' && from !== 'seated') return 'Sit down';
  if (from === 'seated' && to === 'standing') return 'Stand up';
  if (to === 'inside') return 'Opening';
  return null;
}

/** The clip a cue plays, if any (the other gestures are procedural over the clip playing). */
function cueClipOf(cue: Cue): NpcClip | null {
  if (cue.kind === 'hit') return 'Hard landing';
  return cue.kind in GESTURE_CLIPS
    ? GESTURE_CLIPS[cue.kind as keyof typeof GESTURE_CLIPS]
    : null;
}

/** The clips a body doing `shown` may need: its clip, its gaits and its moves between poses (fetched once each). */
function clipsFor(shown: MotionLook, look: string, cue: Cue | null): NpcClip[] {
  const clips: NpcClip[] = [shown.clip];
  const gait = gaitOf(shown.motion, 1, BAKED_HIP, look);
  if (gait) clips.push(gait.clip);
  if (shown.motion === 'jog' || shown.motion === 'run') clips.push('Run');
  if (shown.pose === 'seated') clips.push('Sit down', 'Stand up');
  if (shown.pose === 'inside') clips.push('Opening');
  if (shown.layer && shown.layer in GESTURE_CLIPS)
    clips.push(GESTURE_CLIPS[shown.layer as keyof typeof GESTURE_CLIPS]);
  const played = cue && cueClipOf(cue);
  if (played) clips.push(played);
  return clips;
}

/** Draws the character's materials this opaque (transparent only while below 1). */
function setOpacity(character: Object3D, opacity: number) {
  character.traverse((object) => {
    const material = (object as Mesh).material as Material | undefined;
    if (!material) return;
    const transparent = opacity < 1;
    if (material.transparent !== transparent) {
      material.transparent = transparent;
      material.needsUpdate = true;
    }
    material.opacity = opacity;
  });
}

/** The prop a body holds (attached under its hand or on its back), swapped when what it holds changes. */
function useHeldProp(character: Object3D, held: HeldProp | null) {
  const propRef = useRef<Object3D | null>(null);
  useEffect(() => {
    if (!held) return;
    let live = true;
    const holder = holderOf(character, held.at);
    const attach = (scene: Object3D | null) => {
      if (!live) return;
      const prop = propModel(held.kind, scene);
      holder.add(prop);
      propRef.current = prop;
    };
    const asset = propAsset(held.kind);
    if (asset) void loadProp(asset).then(attach);
    else attach(null);
    return () => {
      live = false;
      const prop = propRef.current;
      if (prop) holder.remove(prop);
      propRef.current = null;
    };
  }, [character, held]);
  return propRef;
}

// memo: a tick brings a new citizen object every time, but the model only changes with what the body is shown doing
const NpcModel = memo(function NpcModel({
  look,
  shown,
  cue,
  rate,
  trackRef,
  viewRef,
  ground,
  labels,
  subject,
}: {
  look: CitizenLook;
  shown: MotionLook;
  /** The latest gesture or blow of this citizen (shown once when it is new). */
  cue: Cue | null;
  /** The clock: game seconds per real second (0 paused). */
  rate: number;
  trackRef: RefObject<Track>;
  viewRef: RefObject<NpcView>;
  ground: GroundProbe;
  labels: LabelStore;
  subject: string;
}) {
  const character = useMemo(() => createCharacter(look.config), [look]);
  const rest = useMemo(() => restOf(character), [character]);
  const rig = useMemo(() => rigOf(character), [character]);
  const tilt = useRef<Group>(null);
  const posed = useRef<Group>(null);
  const resting = useRef<Resting>({ shape: null, print: null });
  const body = useRef<BodyState>(newBody());
  const [hidden, setHidden] = useState(false);
  const feet = useMemo(
    () =>
      ['LeftFoot', 'RightFoot'].flatMap(
        (name) => character.getObjectByName(name) ?? [],
      ),
    [character],
  );
  const [clips, setClips] = useState<readonly NpcClip[]>(() => [
    ...new Set([...BASE_CLIPS, ...clipsFor(shown, look.id, cue)]),
  ]);
  const [animation, setAnimation] = useState<CharacterAnimation | null>(null);
  const actions = useMemo(
    () => (animation ? Object.values(animation.actions) : []),
    [animation],
  );
  // a new motion's clips join the loaded set (Polyfork fetches each clip once per page)
  const wanted = clipsFor(shown, look.id, cue).filter(
    (clip) => !clips.includes(clip),
  );
  if (wanted.length) setClips([...clips, ...new Set(wanted)]);

  useEffect(() => {
    let mounted = true;
    animateHumanoid(character, {
      clips,
      planted: new Set(clips.filter(isPlanted)),
    }).then((loaded) => {
      if (!mounted) return;
      setAnimation((previous) => {
        previous?.mixer.stopAllAction();
        return loaded;
      });
    });
    return () => {
      mounted = false;
    };
  }, [character, clips]);

  useEffect(
    () => () =>
      character.traverse((object) => (object as Mesh).geometry?.dispose()),
    [character],
  );

  // the labels hang over the head bone while the body is drawn (sitting and lying bodies too)
  useEffect(() => {
    if (hidden) return;
    return labels.anchor(subject, rig.head, HEAD_LABEL_LIFT, 1);
  }, [labels, subject, rig, hidden]);

  // a new cue (a gesture, a blow) plays once; one that played out before the model was drawn doesn't
  const playCue = useEffectEvent((next: Cue) => {
    const age = (performance.now() - next.at) / 1000;
    if (cueOver(next.kind, age, rate)) return;
    body.current.oneShot = { cue: next, left: cueSeconds(next.kind) };
  });
  useEffect(() => {
    if (cue) playCue(cue);
  }, [cue]);

  const held = shown.pose === 'standing' ? shown.prop : null;
  const propRef = useHeldProp(character, held);
  const wornFor = useRef<{ held: HeldProp | null; posture: Posture | null }>({
    held: null,
    posture: null,
  });

  const shownOpacity = useRef(1);
  useFrame(({ camera }, delta) => {
    const track = trackRef.current;
    const view = viewRef.current;
    if (track.opacity !== shownOpacity.current) {
      setOpacity(character, track.opacity);
      shownOpacity.current = track.opacity;
    }
    view.motion = shown.motion;
    view.prop = held ? held.kind : '';
    if (!animation || !view.near || !tilt.current || !posed.current) return;
    const state = body.current;
    const dt = Math.min(delta, MAX_FRAME) * visualRate(rate);
    state.clock += dt;
    const has = (clip: NpcClip) => clip in animation.actions;
    const gait = gaitOf(
      shown.motion,
      groundSpeed(track.path),
      rest.hipsAt.y,
      look.id,
      has,
    );
    const wanted: BodyPose = gait ? 'standing' : shown.pose;
    if (wanted !== state.pose) {
      const clip = gait ? null : passingClip(state.pose, wanted);
      // a move whose clip is still loading waits for it (the door opens before the body is gone)
      if (!clip || has(clip)) {
        state.passing = clip
          ? { clip, left: animation.actions[clip].getClip().duration }
          : null;
        state.pose = wanted;
      }
    }
    const pose = state.pose ?? wanted;
    // a cue counts down once its clip is there (a first nod waits for Agree to load)
    const oneShot = state.oneShot;
    const cueClip = oneShot && cueClipOf(oneShot.cue);
    if (oneShot && (!cueClip || has(cueClip))) {
      oneShot.left -= dt;
      if (oneShot.left <= 0) state.oneShot = null;
    }
    const hit = oneShot?.cue.kind === 'hit' && has('Hard landing');
    const gesture =
      oneShot && oneShot.cue.kind !== 'hit' ? oneShot.cue.kind : null;
    const layerKind: Layer | null = gesture ?? shown.layer;
    if (layerKind !== state.layer.kind)
      state.layer = { kind: layerKind, clock: 0 };
    else state.layer.clock += dt;

    let action: AnimationAction;
    if (gait) action = animation.play(gait.clip, { timeScale: gait.timeScale });
    else if (hit) {
      action = animation.play('Hard landing', { loop: false });
    } else if (state.passing) {
      action = animation.play(state.passing.clip, { loop: false });
      state.passing.left -= dt;
      if (state.passing.left <= 0) state.passing = null;
    } else {
      const gestureClip =
        layerKind && layerKind in GESTURE_CLIPS
          ? GESTURE_CLIPS[layerKind as keyof typeof GESTURE_CLIPS]
          : null;
      const clip = gestureClip ?? shown.clip;
      action = animation.play(has(clip) ? clip : 'Idle', {
        timeScale: shown.pace,
      });
    }
    if (shown.still && !gait) action.time = 0;
    action.paused = shown.still && !gait;
    view.clip = view.near ? action.getClip().name : '';
    view.loaded = true;
    view.layer = layerKind ?? '';
    unlayer(rig);
    animation.update(dt);
    keepClipPose(rig);

    const hop = layer(rig, layerKind, state.layer.clock, gait !== null);
    breathe(rig, pose === 'sleeping', state.clock);
    // gone inside: the body stands at the door until it is through, then it is hidden
    const posture: Posture = pose === 'inside' ? 'standing' : pose;
    const inside = pose === 'inside' && !state.passing;
    if (inside !== hidden) setHidden(inside);
    posed.current.visible = !inside;
    view.hidden = inside;

    place(posed.current, character, state.laid);
    layToRest(
      resting.current,
      shapeOf(posture, action, actions, shown.seat ?? undefined),
      {
        character,
        rest,
        tilt: tilt.current,
        posed: posed.current,
        ground,
      },
    );
    placementOf(posed.current, character, state.laid);
    if (posture !== state.posture) {
      if (state.posture !== null) {
        const dying = posture === 'lying' && state.posture !== 'sleeping';
        state.easing = startEasing(
          state.drawn,
          easeSeconds(state.posture, posture, dying),
          dying,
        );
      }
      state.posture = posture;
    }
    // what the hands show: by posture (`showWorn`), then the look's own things put away for a prop
    const worn = wornFor.current;
    if (held !== worn.held || posture !== worn.posture) {
      showWorn(character, posture);
      freeHand(character, held);
      wornFor.current = { held, posture };
    }
    if (state.easing && !ease(state.easing, rig, posed.current, state.laid, dt))
      state.easing = null;
    posed.current.position.y += hop;
    placementOf(posed.current, character, state.drawn);

    if (propRef.current)
      propRef.current.visible =
        camera.position.distanceTo(view.pose.position) < PROP_NEAR;
    view.clipClock = animation.mixer.time;
    view.feet = feet.flatMap((bone) =>
      character.worldToLocal(bone.getWorldPosition(foot)).toArray(),
    );
    const { position } = view.pose;
    up.copy(position).normalize();
    const above = (at: Vector3) => at.sub(position).dot(up);
    view.heights.head = above(rig.head.getWorldPosition(anchored));
    if (labels.anchorPosition(subject, anchored))
      view.heights.label = above(anchored);
  });

  return (
    <group ref={tilt}>
      <group ref={posed}>
        <primitive object={character} />
      </group>
    </group>
  );
});

interface PlaceContext {
  terrain: GlobeTerrain;
  town: WalkTown;
  scratch: { direction: Vector3; local: Vector3; going: Vector3 };
  heading: number;
  /** Everyone drawn, and this citizen among them, to keep the bodies apart. */
  crowd: Crowd;
  self: CrowdBody;
  /** Game seconds per real second (0 paused). */
  rate: number;
  delta: number;
}

/**
 * Walks the citizen on along its path, in its lane, clear of the others, onto the ground, turning the way it walks
 * (its heading standing).
 */
/** The body pose a doing takes, whoever does it (separation reads it: a sitter is never pushed). */
function poseOf(doing: Doing): BodyPose {
  const anyone = {
    look: '',
    region: 'town',
    spear: false,
    dark: false,
  } as const;
  return motionLook(motionOf(doing), anyone, {
    dead: doing.activity === 'dead',
    posture: doing.posture,
  }).pose;
}

function placeAlong(
  track: Track,
  view: NpcView,
  body: Group,
  context: PlaceContext,
) {
  const { terrain, town, scratch, heading, rate, delta } = context;
  const radius = terrain.globe.radius;
  const inLane = keepRight(
    track,
    delta,
    moveOn(track, delta, rate, scratch.direction),
    radius,
  );
  const onward = walking(track.path);
  const direction = separate(
    context.crowd,
    context.self,
    inLane,
    // by the posture it is to take: someone about to sit is never pushed, and eases back before sitting
    giveOf(poseOf(shownDoing(track)), onward),
    delta * visualRate(rate),
    radius,
  );
  const ground = groundUnder(terrain, town, direction, scratch.local);
  const { east, south, up } = tangentFrame(direction);
  const going = onward ? headingAt(track.path, scratch.going) : null;
  const wanted = going
    ? Math.atan2(going.dot(east), going.dot(south))
    : (heading * Math.PI) / 180;
  track.yaw += wrapAngle(wanted - track.yaw) * smoothing(TURN_RATE, delta);
  const { position, facing } = view.pose;
  position.copy(direction).multiplyScalar(radius + ground);
  facing
    .copy(east)
    .multiplyScalar(Math.sin(track.yaw))
    .addScaledVector(south, Math.cos(track.yaw));
  view.pose.ground = ground;
  body.position.copy(position);
  basis.makeBasis(side.crossVectors(up, facing), up, facing);
  body.quaternion.setFromRotationMatrix(basis);
}

/** Shows or hides the model by the camera's distance; true when it is near for the first time. */
function updateNear(view: NpcView, body: Group, distance: number) {
  const wasNear = view.near;
  view.near = distance < (wasNear ? HIDE : NEAR);
  body.visible = view.near;
  if (!view.near) view.clip = '';
  return view.near && !wasNear;
}

function copyPose(from: GlobePlayerState, to: GlobePlayerState) {
  to.position.copy(from.position);
  to.facing.copy(from.facing);
  to.ground = from.ground;
}

function newView(citizen: LiveCitizen): NpcView {
  return {
    id: citizen.id,
    pose: { position: new Vector3(), facing: new Vector3(), ground: 0 },
    activity: citizen.activity,
    posture: 'standing',
    motion: 'idle',
    prop: '',
    layer: '',
    hidden: false,
    clip: '',
    loaded: false,
    near: false,
    feet: [],
    clipClock: 0,
    heights: { head: 0, label: 0 },
  };
}

/** Whether the sun is down where a body stands (`direction` from the planet's centre) at the town's `minutes`. */
function isDark(direction: Vector3, clock: GameClock, townLon: number) {
  return sunDirection(clock.minutes, townLon, sun).dot(direction) < DUSK;
}

function Npc({
  citizen,
  terrain,
  town,
  labels,
  doings,
  cue,
  rate,
  clockRef,
  townLon,
  replay,
  tickElapsed,
  peopleRef,
  crowd,
  views,
  followId,
  subjectRef,
}: {
  citizen: LiveCitizen;
  terrain: GlobeTerrain;
  town: WalkTown;
  labels: LabelStore;
  doings: ShownDoings;
  cue: Cue | null;
  /** The clock: game seconds per real second (0 paused). */
  rate: number;
  clockRef: RefObject<GameClock>;
  townLon: number;
  /** A replayed moment: drawn where it says, not a tick behind (no tick follows). */
  replay: boolean;
  /** Game seconds into the current tick now (a citizen first seen mid-tick is drawn that far along). */
  tickElapsed: () => number;
  peopleRef: RefObject<Map<string, Vector3>>;
  crowd: Crowd;
  views: NpcViews;
  followId: string | null;
  subjectRef: RefObject<GlobePlayerState>;
}) {
  const radius = terrain.globe.radius;
  const look = LOOKS.get(citizen.look);
  if (!look) throw new Error(`unknown citizen look ${citizen.look}`);
  const group = useRef<Group>(null);
  const [mounted, setMounted] = useState(false);
  const [firstTrack] = useState(() =>
    newTrack(citizen, radius, replay, tickElapsed()),
  );
  const trackRef = useRef<Track>(firstTrack);
  const viewRef = useRef<NpcView>(newView(citizen));
  const [self] = useState(() => newCrowdBody(citizen.id));
  // what the body is shown doing: the frame's activity, or a moving one while it walks there (drawn-track)
  const [doing, setDoing] = useState(() => shownDoing(firstTrack));
  const [dark, setDark] = useState(false);
  // the ground around the drawn body, for laying a sitter or a sleeper along it
  const ground = useMemo<GroundProbe>(() => {
    const spot = new Vector3();
    const local = new Vector3();
    const across = new Vector3();
    return (forward, side) => {
      const { position, facing, ground: here } = viewRef.current.pose;
      across.copy(position).normalize().cross(facing);
      spot
        .copy(position)
        .addScaledVector(facing, forward)
        .addScaledVector(across, side)
        .normalize();
      return groundUnder(terrain, town, spot, local) - here;
    };
  }, [terrain, town]);
  const scratch = useMemo(
    () => ({
      direction: new Vector3(),
      local: new Vector3(),
      going: new Vector3(),
    }),
    [],
  );
  const gesture = cue && cue.kind !== 'hit' ? cue.kind : null;
  const shown = useMemo(
    () =>
      motionLook(
        motionOf(doing),
        {
          look: look.id,
          region: citizen.region,
          spear: wearsSpear(look),
          dark,
        },
        {
          dead: doing.activity === 'dead',
          gesture,
          posture: doing.posture,
          seat: doing.slot_height_m,
        },
      ),
    [doing, look, citizen.region, dark, gesture],
  );

  // the activity shown changes when a frame comes or the drawn body gets where the frame says it is; someone sitting
  // or lying down while drawn stepped aside stands until back on their spot (separation.ts), never sliding seated
  const showDoing = () => {
    const next = shownDoing(trackRef.current);
    const now =
      next !== doing &&
      shown.pose === 'standing' &&
      standsUntilBack(self, poseOf(next) !== 'standing')
        ? doing
        : next;
    viewRef.current.activity = now.activity;
    if (now !== doing) setDoing(now);
  };

  // every new frame: the move it streams, joined where the citizen is drawn (a speed change alone sends the same
  // citizens and keeps the path)
  const onFrame = useEffectEvent((next: LiveCitizen) => {
    follow(trackRef.current, next, radius, rate);
    showDoing();
  });
  useLayoutEffect(() => onFrame(citizen), [citizen]);
  useEffect(() => doings.show(citizen.id, doing), [doings, citizen.id, doing]);

  useEffect(() => {
    crowd.add(self);
    return () => {
      crowd.delete(self);
    };
  }, [crowd, self]);

  useEffect(() => {
    const id = citizen.id;
    views.set(id, viewRef.current);
    const people = peopleRef.current;
    return () => {
      views.delete(id);
      people.delete(id);
    };
  }, [citizen.id, views, peopleRef]);

  useFrame(({ camera }, frameDelta) => {
    const body = group.current;
    if (!body) return;
    const view = viewRef.current;
    placeAlong(trackRef.current, view, body, {
      terrain,
      town,
      scratch,
      heading: doing.slot_heading ?? citizen.heading_deg,
      crowd,
      self,
      rate,
      delta: Math.min(frameDelta, MAX_FRAME),
    });
    showDoing();
    view.posture = shown.pose;
    const people = peopleRef.current;
    const feet = people.get(citizen.id);
    if (feet) feet.copy(view.pose.position);
    else people.set(citizen.id, view.pose.position.clone());
    const firstNear = updateNear(
      view,
      body,
      camera.position.distanceTo(view.pose.position),
    );
    if (firstNear && !mounted) setMounted(true);
    if (followId === citizen.id) copyPose(view.pose, subjectRef.current);
    const night = isDark(scratch.direction, clockRef.current, townLon);
    if (night !== dark) setDark(night);
  });

  const labelHeight =
    {
      standing: LABEL_HEIGHT,
      seated: SITTING_LABEL_HEIGHT,
      sitting: SITTING_LABEL_HEIGHT,
      kneeling: SITTING_LABEL_HEIGHT,
      sleeping: LYING_LABEL_HEIGHT,
      lying: LYING_LABEL_HEIGHT,
      inside: LABEL_HEIGHT,
    }[shown.pose] * (AGE_LABEL_SCALE[look.config.age ?? 'adult'] ?? 1);
  return (
    <group ref={group}>
      {mounted && (
        <NpcModel
          look={look}
          shown={shown}
          cue={cue}
          rate={rate}
          trackRef={trackRef}
          viewRef={viewRef}
          ground={ground}
          labels={labels}
          subject={citizen.id}
        />
      )}
      {/* gone inside, a body has no label (its house tells who is in) */}
      {shown.pose !== 'inside' && (
        <LabelAnchor store={labels} subject={citizen.id} lift={labelHeight} />
      )}
    </group>
  );
}

/** Each citizen's latest cue (a gesture, a blow), by citizen id. */
function latestCues(cues: readonly Cue[]) {
  const latest = new Map<string, Cue>();
  for (const cue of cues) latest.set(cue.actorId, cue);
  return latest;
}

/** Inside the Canvas: every live citizen, drawn where the feed says. */
export function GlobeNpcs({
  citizens,
  cues = [],
  speed,
  paused,
  tickClock,
  replay = false,
  clockRef,
  townLon,
  terrain,
  town,
  labels,
  doings,
  peopleRef,
  views,
  followId,
  subjectRef,
}: {
  citizens: LiveCitizen[];
  /** Recent gestures and blows (`live-state.ts`): each citizen shows its latest once. */
  cues?: readonly Cue[];
  /** The feed's clock: game seconds per real second, and whether it is paused. */
  speed: number;
  paused: boolean;
  /** How far into the current tick the feed was, and when. */
  tickClock: TickClock;
  /** The citizens of a replayed moment (`?tick=`), which no tick follows. */
  replay?: boolean;
  /** The sky's clock and the town's longitude: where the sun is down, guards hold torches. */
  clockRef: RefObject<GameClock>;
  townLon: number;
  terrain: GlobeTerrain;
  town: WalkTown;
  labels: LabelStore;
  /** Filled with what each citizen is shown doing, for their labels. */
  doings: ShownDoings;
  /** Filled with where everyone's feet are, for the walker's collisions. */
  peopleRef: RefObject<Map<string, Vector3>>;
  /** Filled with what is drawn of each citizen. */
  views: NpcViews;
  followId: string | null;
  /** The followed citizen's pose, for the follow camera. */
  subjectRef: RefObject<GlobePlayerState>;
}) {
  const latest = useMemo(() => latestCues(cues), [cues]);
  const [crowd] = useState<Crowd>(() => new Set());
  // read when a citizen is first drawn (not during later renders)
  const elapsed = () =>
    tickElapsed({ tickClock, speed, paused }, performance.now());

  return (
    <>
      {citizens.map((citizen) => (
        <Npc
          key={citizen.id}
          citizen={citizen}
          terrain={terrain}
          town={town}
          labels={labels}
          doings={doings}
          cue={latest.get(citizen.id) ?? null}
          rate={clockRate(speed, paused)}
          clockRef={clockRef}
          townLon={townLon}
          replay={replay}
          tickElapsed={elapsed}
          peopleRef={peopleRef}
          crowd={crowd}
          views={views}
          followId={followId}
          subjectRef={subjectRef}
        />
      ))}
    </>
  );
}
