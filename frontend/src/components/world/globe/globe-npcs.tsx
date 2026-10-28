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
import type { LiveCitizen } from '@/lib/live/live-contract';
import type { Speech } from '@/lib/live/live-state';
import {
  advance,
  citizenPath,
  headingAt,
  joinAt,
  pointAt,
  type WalkPath,
  walking,
} from '@/lib/live/walk-path';
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
import { groundUnder, type WalkTown } from '@/lib/world/walk-charts';
import type { CharacterAnimation } from '@/vendor/polyfork/clips.mjs';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

/*
 * The citizens on the planet, where the live feed says they are. Between ticks a walker walks the path the tick
 * streamed ahead (`route`) at its ground speed × the clock's speed (`walk-path.ts`): at ×1 that's a real 1.4 m/s
 * for a real minute, along the route's corners; a new tick eases the drawn spot onto the new path. Each one faces
 * the way it walks (its heading when standing),
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
/** How fast the drawn spot eases onto a new tick's path, or a standing citizen onto a new spot (1/s). */
const CATCH_UP_RATE = 3;
/** Drawn farther off than this (a resync, a hidden tab), the citizen is put on the spot at once. */
const SNAP_M = 30;

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
  /** The path the feed streamed for this tick (one point when standing) and how far along it the citizen is. */
  path: WalkPath;
  /** Drawn spot minus the spot on the path (unit-sphere vector), easing to zero after a new tick. */
  offset: Vector3;
  /** Rendered yaw (radians, the heading convention). */
  yaw: number;
  /** Game metres per second of the gait: the path's speed while walking on, else 0. */
  pace: number;
}

const wrapAngle = (angle: number) =>
  Math.atan2(Math.sin(angle), Math.cos(angle));

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

const currentPace = (track: Track) => track.pace;

/** Where the citizen is drawn: on its path, eased by the catch-up offset (a unit direction into `out`). */
const drawnAt = (track: Track, out: Vector3) =>
  pointAt(track.path, out).add(track.offset).normalize();

/** Puts a new frame's path under the citizen, joined where it is drawn now (no jump, no step back). */
function follow(track: Track, citizen: LiveCitizen, radius: number) {
  const drawn = drawnAt(track, new Vector3());
  const path = citizenPath(citizen, radius);
  const off = joinAt(path, drawn, radius);
  track.path = path;
  if (off > SNAP_M) track.offset.set(0, 0, 0);
  else track.offset.subVectors(drawn, pointAt(path, new Vector3()));
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
  advance(track.path, delta * rate);
  track.offset.multiplyScalar(Math.exp(-CATCH_UP_RATE * delta));
  const onward = walking(track.path);
  track.pace = onward && rate > 0 ? track.path.speed : 0;
  const direction = drawnAt(track, scratch.direction);
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

function newTrack(citizen: LiveCitizen, radius: number): Track {
  return {
    path: citizenPath(citizen, radius),
    offset: new Vector3(),
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
  rate,
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
  const trackRef = useRef<Track>(newTrack(citizen, radius));
  const viewRef = useRef<NpcView>(newView(citizen));
  const scratch = useMemo(
    () => ({
      direction: new Vector3(),
      local: new Vector3(),
      going: new Vector3(),
    }),
    [],
  );
  const { activity, action_label: label } = citizen;
  const pose = useMemo(
    () => npcLook({ activity, action_label: label }),
    [activity, label],
  );

  // every new frame: the walk ahead it streams, joined where the citizen is drawn (a speed change alone sends the
  // same citizens and keeps the path)
  const onFrame = useEffectEvent((next: LiveCitizen) => {
    follow(trackRef.current, next, radius);
    viewRef.current.activity = next.activity;
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
  paused,
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
          peopleRef={peopleRef}
          views={views}
          followId={followId}
          subjectRef={subjectRef}
        />
      ))}
    </>
  );
}
