import { useFrame } from '@react-three/fiber';
import {
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
import { Label } from '@/components/world/labels';
import { MAX_FRAME, smoothing } from '@/components/world/player/motion';
import type { LiveCitizen } from '@/lib/live/live-contract';
import type { Speech } from '@/lib/live/live-state';
import {
  follow,
  moveOn,
  newTrack,
  shownDoing,
  type Track,
} from '@/lib/live/drawn-track';
import { groundSpeed, headingAt, walking } from '@/lib/live/walk-path';
import {
  activityWords,
  BASE_CLIPS,
  clipLapse,
  type NpcClip,
  type NpcLook,
  npcLook,
  PLANTED_CLIPS,
} from '@/lib/live/npc-activity';
import { CITIZEN_LOOKS, type CitizenLook } from '@/lib/world/citizen-looks';
import { type GlobeTerrain, tangentFrame } from '@/lib/world/globe';
import type { LabelStore } from '@/lib/world/label-store';
import { animateHumanoid } from '@/lib/world/humanoid-clips';
import {
  type GroundProbe,
  layToRest,
  type Resting,
  restOf,
  shapeOf,
} from '@/lib/world/rest-posture';
import { groundUnder, type WalkTown } from '@/lib/world/walk-charts';
import type { CharacterAnimation } from '@/vendor/polyfork/clips.mjs';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

/*
 * The citizens on the planet, where the live feed says they are. Between ticks a mover walks the timed path its
 * tick streamed (`route`, from where it stood when the tick began) with game seconds passing at the clock's speed
 * (`walk-path.ts`): at ×1 a real 1.4 m/s for a real minute, along the route's corners, so every move is drawn as
 * walking, one tick behind the sim. A new tick joins the drawn spot onto its path (normally where the last one
 * ended); one drawn far off (a reconnect, a hidden tab) fades out and back in on its path instead of jumping. Each
 * one faces the way it walks (its heading when standing), turns smoothly to its heading and stands on the rendered
 * ground (the town's plateau on its disc, else the terrain); sitters and sleepers rest on it, tilted to the ground
 * under them (`rest-posture.ts`). The gait is paced to the drawn ground speed and every clip plays sped up with the
 * clock (a fast-forwarded film, `clipLapse`), up to ×10: past that legs would blur, so they keep that cadence and
 * the body glides. Models load only within NEAR metres of the camera (and hide again past it); clips load per
 * activity as first needed.
 */

/** Full models within this distance of the camera (they hide past HIDE). */
const NEAR = 400;
const HIDE = 420;
const LABEL_HEIGHT = 2.1;
/** Speech bubbles hang this far above the name label. */
const SPEECH_ABOVE = 0.45;
/** Labels hang lower over lying and sitting bodies. */
const LYING_LABEL_HEIGHT = 0.7;
const SITTING_LABEL_HEIGHT = 1.2;
/** Children and teens are shorter: their labels hang lower. */
const AGE_LABEL_SCALE: Partial<Record<string, number>> = {
  kid: 0.7,
  teen: 0.93,
};
/** Turning rate towards the heading (1/s). */
const TURN_RATE = 8;

const LOOKS = new Map(CITIZEN_LOOKS.map((look) => [look.id, look]));
const basis = new Matrix4();
const side = new Vector3();
const foot = new Vector3();

/** What the page and the tests can read of a drawn citizen (mutated every frame). */
interface NpcView {
  id: string;
  /** World position of the feet and the facing tangent (the follow camera reads these). */
  pose: GlobePlayerState;
  activity: string;
  /** How the body is posed (from the activity shown). */
  posture: NpcLook['pose'];
  /** The clip playing, '' until the model is loaded (or while it is far). */
  clip: string;
  loaded: boolean;
  /** Within reach of the camera: the model is shown and animated. */
  near: boolean;
  /** Left then right foot in the model's own frame (x, y, z each), while it is animated. */
  feet: number[];
  /** Seconds of clip time its animation has played (clips run sped up with the clock). */
  clipClock: number;
}

export type NpcViews = Map<string, NpcView>;

const wrapAngle = (angle: number) =>
  Math.atan2(Math.sin(angle), Math.cos(angle));

/**
 * Plays the gait while the body is drawn moving (paced to its ground speed, game metres per second), else the
 * clip of the citizen's look, records it for the page and returns it.
 */
function playLook(
  animation: CharacterAnimation,
  look: NpcLook,
  speed: number,
  view: NpcView,
): AnimationAction {
  const action =
    speed > 0 || look.clip === 'Walk'
      ? animation.locomotion(speed)
      : animation.play(animation.actions[look.clip] ? look.clip : 'Idle');
  if (look.still) action.time = 0;
  action.paused = look.still;
  view.clip = visibleClip(view, action.getClip().name);
  view.loaded = true;
  return action;
}

const visibleClip = (view: NpcView, clip: string) => (view.near ? clip : '');

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

function NpcModel({
  look,
  pose,
  rate,
  trackRef,
  viewRef,
  ground,
}: {
  look: CitizenLook;
  pose: NpcLook;
  /** The clock: game seconds per real second (0 paused). */
  rate: number;
  trackRef: RefObject<Track>;
  viewRef: RefObject<NpcView>;
  ground: GroundProbe;
}) {
  const character = useMemo(() => createCharacter(look.config), [look]);
  const rest = useMemo(() => restOf(character), [character]);
  const tilt = useRef<Group>(null);
  const posed = useRef<Group>(null);
  const resting = useRef<Resting>({ shape: null, print: null });
  const playing = useRef<AnimationAction | null>(null);
  const feet = useMemo(
    () =>
      ['LeftFoot', 'RightFoot'].flatMap(
        (name) => character.getObjectByName(name) ?? [],
      ),
    [character],
  );
  const [clips, setClips] = useState<readonly NpcClip[]>(() => [
    ...new Set([...BASE_CLIPS, pose.clip]),
  ]);
  const [animation, setAnimation] = useState<CharacterAnimation | null>(null);
  const actions = useMemo(
    () => (animation ? Object.values(animation.actions) : []),
    [animation],
  );
  // a new activity's clip joins the loaded set (Polyfork fetches each clip once per page)
  if (!clips.includes(pose.clip)) setClips([...clips, pose.clip]);

  useEffect(() => {
    let mounted = true;
    animateHumanoid(character, { clips, planted: PLANTED_CLIPS }).then(
      (loaded) => {
        if (!mounted) return;
        setAnimation((previous) => {
          previous?.mixer.stopAllAction();
          return loaded;
        });
      },
    );
    return () => {
      mounted = false;
    };
  }, [character, clips]);

  useEffect(
    () => () =>
      character.traverse((object) => (object as Mesh).geometry?.dispose()),
    [character],
  );

  useEffect(() => {
    if (animation)
      playing.current = playLook(
        animation,
        pose,
        groundSpeed(trackRef.current.path),
        viewRef.current,
      );
  }, [animation, pose, trackRef, viewRef]);

  const shown = useRef(1);
  useFrame((_, delta) => {
    const track = trackRef.current;
    if (track.opacity !== shown.current) {
      setOpacity(character, track.opacity);
      shown.current = track.opacity;
    }
    if (!animation || !viewRef.current.near || !tilt.current || !posed.current)
      return;
    playing.current = playLook(
      animation,
      pose,
      groundSpeed(track.path),
      viewRef.current,
    );
    animation.update(Math.min(delta, MAX_FRAME) * clipLapse(rate));
    layToRest(resting.current, shapeOf(pose.pose, playing.current, actions), {
      character,
      rest,
      tilt: tilt.current,
      posed: posed.current,
      ground,
    });
    viewRef.current.clipClock = animation.mixer.time;
    viewRef.current.feet = feet.flatMap((bone) =>
      character.worldToLocal(bone.getWorldPosition(foot)).toArray(),
    );
  });

  return (
    <group ref={tilt}>
      <group ref={posed}>
        <primitive object={character} />
      </group>
    </group>
  );
}

interface PlaceContext {
  terrain: GlobeTerrain;
  town: WalkTown;
  scratch: { direction: Vector3; local: Vector3; going: Vector3 };
  heading: number;
  /** Game seconds per real second (0 paused). */
  rate: number;
  delta: number;
}

/** Walks the citizen on along its path, onto the ground, turning the way it walks (its heading standing). */
function placeAlong(
  track: Track,
  view: NpcView,
  body: Group,
  context: PlaceContext,
) {
  const { terrain, town, scratch, heading, rate, delta } = context;
  const radius = terrain.globe.radius;
  const direction = moveOn(track, delta, rate, scratch.direction);
  const onward = walking(track.path);
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
    clip: '',
    loaded: false,
    near: false,
    feet: [],
    clipClock: 0,
  };
}

function Npc({
  citizen,
  speech,
  terrain,
  town,
  labels,
  rate,
  replay,
  peopleRef,
  views,
  followId,
  subjectRef,
}: {
  citizen: LiveCitizen;
  speech: Speech | undefined;
  terrain: GlobeTerrain;
  town: WalkTown;
  labels: LabelStore;
  /** The clock: game seconds per real second (0 paused). */
  rate: number;
  /** A replayed moment: drawn where it says, not a tick behind (no tick follows). */
  replay: boolean;
  peopleRef: RefObject<Map<string, Vector3>>;
  views: NpcViews;
  followId: string | null;
  subjectRef: RefObject<GlobePlayerState>;
}) {
  const radius = terrain.globe.radius;
  const look = LOOKS.get(citizen.look);
  if (!look) throw new Error(`unknown citizen look ${citizen.look}`);
  const group = useRef<Group>(null);
  const [mounted, setMounted] = useState(false);
  const [firstTrack] = useState(() => newTrack(citizen, radius, replay));
  const trackRef = useRef<Track>(firstTrack);
  const viewRef = useRef<NpcView>(newView(citizen));
  // what the body is shown doing: the frame's activity, or a moving one while it walks there (drawn-track)
  const [doing, setDoing] = useState(() => shownDoing(firstTrack));
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
  const pose = useMemo(() => npcLook(doing), [doing]);

  // the activity shown changes when a frame comes or the drawn body gets where the frame says it is
  const showDoing = () => {
    const now = shownDoing(trackRef.current);
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
      heading: citizen.heading_deg,
      rate,
      delta: Math.min(frameDelta, MAX_FRAME),
    });
    showDoing();
    view.posture = pose.pose;
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
  });

  const labelHeight =
    {
      standing: LABEL_HEIGHT,
      sitting: SITTING_LABEL_HEIGHT,
      sleeping: LYING_LABEL_HEIGHT,
      lying: LYING_LABEL_HEIGHT,
    }[pose.pose] * (AGE_LABEL_SCALE[look.config.age ?? 'adult'] ?? 1);
  return (
    <group ref={group}>
      {mounted && (
        <NpcModel
          look={look}
          pose={pose}
          rate={rate}
          trackRef={trackRef}
          viewRef={viewRef}
          ground={ground}
        />
      )}
      <Label
        store={labels}
        id={`npc-${citizen.id}`}
        text={`${citizen.name} · ${activityWords(doing)}`}
        height={labelHeight}
      />
      {speech && (
        <Label
          store={labels}
          id={`say-${citizen.id}`}
          text={speech.words}
          height={labelHeight + SPEECH_ABOVE}
          kind="speech"
        />
      )}
    </group>
  );
}

/** Inside the Canvas: every live citizen, drawn where the feed says. */
export function GlobeNpcs({
  citizens,
  speed,
  paused,
  replay = false,
  speech,
  terrain,
  town,
  labels,
  peopleRef,
  views,
  followId,
  subjectRef,
}: {
  citizens: LiveCitizen[];
  /** The feed's clock: game seconds per real second, and whether it is paused. */
  speed: number;
  paused: boolean;
  /** The citizens of a replayed moment (`?tick=`), which no tick follows. */
  replay?: boolean;
  speech: Speech[];
  terrain: GlobeTerrain;
  town: WalkTown;
  labels: LabelStore;
  /** Filled with where everyone's feet are, for the walker's collisions. */
  peopleRef: RefObject<Map<string, Vector3>>;
  /** Filled with what is drawn of each citizen. */
  views: NpcViews;
  followId: string | null;
  /** The followed citizen's pose, for the follow camera. */
  subjectRef: RefObject<GlobePlayerState>;
}) {
  const latest = useMemo(() => {
    const byActor = new Map<string, Speech>();
    for (const said of speech) byActor.set(said.actorId, said);
    return byActor;
  }, [speech]);

  return (
    <>
      {citizens.map((citizen) => (
        <Npc
          key={citizen.id}
          citizen={citizen}
          speech={latest.get(citizen.id)}
          terrain={terrain}
          town={town}
          labels={labels}
          rate={paused ? 0 : speed}
          replay={replay}
          peopleRef={peopleRef}
          views={views}
          followId={followId}
          subjectRef={subjectRef}
        />
      ))}
    </>
  );
}
