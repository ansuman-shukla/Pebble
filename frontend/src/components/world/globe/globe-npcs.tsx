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
import { type Group, Matrix4, type Mesh, Vector3 } from 'three';

import type { GlobePlayerState } from './globe-player';
import { Label } from '@/components/world/labels';
import { MAX_FRAME, smoothing } from '@/components/world/player/motion';
import { type LiveCitizen, tickMs } from '@/lib/live/live-contract';
import type { Speech } from '@/lib/live/live-state';
import {
  activityWords,
  BASE_CLIPS,
  type NpcClip,
  type NpcLook,
  npcLook,
  PLANTED_CLIPS,
} from '@/lib/live/npc-activity';
import { CITIZEN_LOOKS, type CitizenLook } from '@/lib/world/citizen-looks';
import { type GlobeTerrain, tangentFrame } from '@/lib/world/globe';
import type { LabelStore } from '@/lib/world/label-store';
import { animateHumanoid } from '@/lib/world/humanoid-clips';
import type { WalkTown } from '@/lib/world/walk-charts';
import type { CharacterAnimation } from '@/vendor/polyfork/clips.mjs';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

/*
 * The citizens on the planet, where the live feed says they are. Between ticks each one glides from where it
 * was drawn to the new position over one tick at the feed's speed (1 s at ×1, a minute at one tick a minute),
 * turns smoothly to its heading and stands on the rendered ground (the town's plateau on its disc, else the
 * terrain). Models load only within NEAR metres of the camera (and hide again past it); clips load per activity
 * as first needed.
 */

/** Full models within this distance of the camera (they hide past HIDE). */
const NEAR = 400;
const HIDE = 420;
const LABEL_HEIGHT = 2.1;
/** Speech bubbles hang this far above the name label. */
const SPEECH_ABOVE = 0.45;
/** Lying bodies (sleeping, dead): the back rests this far above the ground, labels hang low. */
const LYING_LIFT = 0.12;
const LYING_LABEL_HEIGHT = 0.7;
/** The seated clip lowers the hips onto a seat; on the ground the body sits this much lower. */
const SITTING_DROP = 0.42;
const SITTING_LABEL_HEIGHT = 1.5;
/** Children and teens are shorter: their labels hang lower. */
const AGE_LABEL_SCALE: Partial<Record<string, number>> = {
  kid: 0.7,
  teen: 0.93,
};
/** Turning rate towards the heading (1/s). */
const TURN_RATE = 8;
/** Game seconds per tick (one game minute). */
const TICK_SECONDS = 60;
/** The shortest glide (ms): one frame at 60 fps. */
const MIN_GLIDE = 16;

/** How long a glide to a new frame's position takes: one tick at the feed's speed. */
const glideMs = (speed: number) =>
  speed > 0 ? Math.max(tickMs(speed), MIN_GLIDE) : tickMs(1);

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
  /** The clip playing, '' until the model is loaded (or while it is far). */
  clip: string;
  loaded: boolean;
  /** Within reach of the camera: the model is shown and animated. */
  near: boolean;
  /** Left then right foot in the model's own frame (x, y, z each), while it is animated. */
  feet: number[];
}

export type NpcViews = Map<string, NpcView>;

interface Track {
  from: Vector3;
  to: Vector3;
  /** performance.now() when the glide started, and its length (ms). */
  start: number;
  duration: number;
  /** Rendered yaw (radians, the heading convention). */
  yaw: number;
  /** Game metres per second of the current glide (the gait's pace). */
  pace: number;
}

const wrapAngle = (angle: number) =>
  Math.atan2(Math.sin(angle), Math.cos(angle));

/** Ground height under a direction as it is drawn: the town's own disc, else the terrain. */
function groundUnder(
  terrain: GlobeTerrain,
  town: WalkTown,
  direction: Vector3,
  scratch: Vector3,
) {
  town.mapping.toLocal(scratch.copy(direction), scratch);
  return Math.hypot(scratch.x, scratch.z) < town.groundRadius
    ? town.height
    : terrain.heightAt(direction);
}

/** Plays the clip of the citizen's look (the gait paced to its walk) and records it for the page. */
function playLook(
  animation: CharacterAnimation,
  look: NpcLook,
  pace: number,
  view: NpcView,
) {
  const action =
    look.clip === 'Walk'
      ? animation.locomotion(pace)
      : animation.play(animation.actions[look.clip] ? look.clip : 'Idle');
  action.paused = look.still;
  view.clip = visibleClip(view, action.getClip().name);
  view.loaded = true;
}

const visibleClip = (view: NpcView, clip: string) => (view.near ? clip : '');

function NpcModel({
  look,
  pose,
  trackRef,
  viewRef,
}: {
  look: CitizenLook;
  pose: NpcLook;
  trackRef: RefObject<Track>;
  viewRef: RefObject<NpcView>;
}) {
  const character = useMemo(() => createCharacter(look.config), [look]);
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
      playLook(animation, pose, currentPace(trackRef.current), viewRef.current);
  }, [animation, pose, trackRef, viewRef]);

  useFrame((_, delta) => {
    if (!animation || !viewRef.current.near) return;
    if (pose.clip === 'Walk')
      playLook(animation, pose, currentPace(trackRef.current), viewRef.current);
    animation.update(Math.min(delta, MAX_FRAME));
    viewRef.current.feet = feet.flatMap((bone) =>
      character.worldToLocal(bone.getWorldPosition(foot)).toArray(),
    );
  });

  return (
    <group
      rotation-x={pose.pose === 'lying' ? -Math.PI / 2 : 0}
      position-y={
        pose.pose === 'lying'
          ? LYING_LIFT
          : pose.pose === 'sitting'
            ? -SITTING_DROP
            : 0
      }
    >
      <primitive object={character} />
    </group>
  );
}

/** The gait's pace now: the glide's while it lasts, standing once it has arrived (e.g. the clock paused). */
const currentPace = (track: Track) =>
  performance.now() - track.start < track.duration ? track.pace : 0;

/** Starts the glide to a new frame's position from wherever the citizen is drawn now. */
function startGlide(
  track: Track,
  citizen: LiveCitizen,
  interval: number,
  radius: number,
) {
  const now = performance.now();
  const t = Math.min((now - track.start) / track.duration, 1);
  track.from.lerp(track.to, t).normalize();
  track.to.set(...citizen.position.unit);
  track.start = now;
  track.duration = interval;
  track.pace =
    citizen.activity === 'walking'
      ? (track.from.angleTo(track.to) * radius) / TICK_SECONDS
      : 0;
}

interface PlaceContext {
  terrain: GlobeTerrain;
  town: WalkTown;
  scratch: { direction: Vector3; local: Vector3 };
  heading: number;
  delta: number;
}

/** Moves the citizen along its glide, onto the ground, turning towards its heading. */
function placeAlong(
  track: Track,
  view: NpcView,
  body: Group,
  context: PlaceContext,
) {
  const { terrain, town, scratch, heading, delta } = context;
  const radius = terrain.globe.radius;
  const t = Math.min((performance.now() - track.start) / track.duration, 1);
  const direction = scratch.direction
    .lerpVectors(track.from, track.to, t)
    .normalize();
  const ground = groundUnder(terrain, town, direction, scratch.local);
  const { east, south, up } = tangentFrame(direction);
  const wanted = (heading * Math.PI) / 180;
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

function newTrack(citizen: LiveCitizen): Track {
  const at = new Vector3(...citizen.position.unit);
  return {
    from: at.clone(),
    to: at.clone(),
    start: 0,
    duration: 1,
    yaw: (citizen.heading_deg * Math.PI) / 180,
    pace: 0,
  };
}

function newView(citizen: LiveCitizen): NpcView {
  return {
    id: citizen.id,
    pose: { position: new Vector3(), facing: new Vector3(), ground: 0 },
    activity: citizen.activity,
    clip: '',
    loaded: false,
    near: false,
    feet: [],
  };
}

function Npc({
  citizen,
  speech,
  terrain,
  town,
  labels,
  interval,
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
  /** Real milliseconds per tick: how long a glide to a new frame's position takes. */
  interval: number;
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
  const trackRef = useRef<Track>(newTrack(citizen));
  const viewRef = useRef<NpcView>(newView(citizen));
  const scratch = useMemo(
    () => ({ direction: new Vector3(), local: new Vector3() }),
    [],
  );
  const { activity, action_label: label } = citizen;
  const pose = useMemo(
    () => npcLook({ activity, action_label: label }),
    [activity, label],
  );

  // every new frame: glide from where the citizen is drawn to the new spot over one tick interval (a speed change
  // alone doesn't restart the glide)
  const glide = useEffectEvent((next: LiveCitizen) => {
    startGlide(trackRef.current, next, interval, radius);
    viewRef.current.activity = next.activity;
  });
  useLayoutEffect(() => glide(citizen), [citizen]);

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
      delta: Math.min(frameDelta, MAX_FRAME),
    });
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
      lying: LYING_LABEL_HEIGHT,
    }[pose.pose] * (AGE_LABEL_SCALE[look.config.age ?? 'adult'] ?? 1);
  return (
    <group ref={group}>
      {mounted && (
        <NpcModel
          look={look}
          pose={pose}
          trackRef={trackRef}
          viewRef={viewRef}
        />
      )}
      <Label
        store={labels}
        id={`npc-${citizen.id}`}
        text={`${citizen.name} · ${activityWords(citizen)}`}
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
  /** The feed's speed (ticks per real second): how long glides between frames take. */
  speed: number;
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
          interval={glideMs(speed)}
          peopleRef={peopleRef}
          views={views}
          followId={followId}
          subjectRef={subjectRef}
        />
      ))}
    </>
  );
}
