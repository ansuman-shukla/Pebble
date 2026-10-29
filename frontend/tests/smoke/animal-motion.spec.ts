import { readFileSync } from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import {
  type AnimationClip,
  AnimationMixer,
  Matrix4,
  type Object3D,
  Vector3,
} from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

import type { RoutePoint } from '../../src/lib/client/types.gen';
import {
  type AnimalActivity,
  type AnimalGait,
  bodyMatrix,
  clipOf,
  FALL_S,
  followAnimal,
  layerOf,
  layerPose,
  moveAnimal,
  newAnimalTrack,
  paceOf,
  POUNCE_S,
  poseBones,
  rigOf,
  shownActivity,
  slopePitch,
  strideSpeed,
  unbendBones,
  wantedYaw,
} from '../../src/lib/live/animal-motion';
import { ANIMALS, type AnimalKind } from '../../src/lib/world/assets';
import { tangentFrame } from '../../src/lib/world/globe';
import { SPEEDS } from './animal-speeds';

/*
 * How an animal is drawn, without a browser (10 §4.2, §4.6; D145-D146): it walks the timed paths its ticks stream,
 * its gait clips paced to its own stride (feet still on the ground), shows what it does through procedural layers,
 * and changes state where its move ends. The drawn scenes are `animals.spec.ts`.
 */

test.describe.configure({ timeout: 120_000 });

const ROOT = path.resolve(import.meta.dirname, '../..');
const R = 2000;
/** A direction `x` metres east and `z` metres north of a spot on the planet (small distances: a flat chart). */
const at = (x: number, z: number): [number, number, number] =>
  new Vector3(x / R, z / R, 1).normalize().toArray();

interface Loaded {
  root: Object3D;
  clips: AnimationClip[];
}
const models = new Map<string, Promise<Loaded>>();

/** An asset's model and clips, loaded once (no browser: three's loader parses the GLB). */
function load(asset: string): Promise<Loaded> {
  const found = models.get(asset);
  if (found) return found;
  const bytes = readFileSync(
    path.join(ROOT, `public/assets/polyfork/${asset}/${asset}.glb`),
  );
  const loading = new GLTFLoader()
    .parseAsync(
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
      '',
    )
    .then((gltf) => ({ root: gltf.scene, clips: gltf.animations }));
  models.set(asset, loading);
  return loading;
}

/** The bible's speeds (m/s): walk and run (10 §4.6). */

/**
 * Runs a model's gait clip for two seconds at `speed` (m/s) as the globe does (the clip at `pace`, the body moving
 * forward at speed), finely stepped; returns the largest slip of any
 * foot over a stance (metres it drifts on the ground from touching down to lifting off; planted: within 5 mm of its
 * lowest, 1.5 % of the hip height for small animals).
 */
async function footSlip(
  kind: AnimalKind,
  activity: AnimalActivity,
  gait: AnimalGait,
  speed: number,
  pace = paceOf,
) {
  const spec = ANIMALS[kind];
  const scale = spec.scale ?? 1;
  const { root, clips } = await load(spec.asset);
  const rig = rigOf(root);
  const clip = clipOf(kind, activity, gait, speed);
  const name = spec[clip];
  const found = clips.find((c) => c.name === name);
  if (!found) throw new Error(`${kind} has no ${name}`);
  const stride = strideSpeed(rig, found);
  const mixer = new AnimationMixer(root);
  const action = mixer.clipAction(found);
  action.play();
  action.timeScale = pace(speed, stride == null ? null : stride * scale);
  const frame = 1 / 2400;
  const toRoot = new Matrix4();
  const spot = new Vector3();
  const tracks = rig.legs.map(() => [] as { y: number; z: number }[]);
  let walked = 0;
  for (let t = 0; t < 2; t += frame) {
    mixer.update(frame);
    walked += speed * frame;
    root.updateMatrixWorld(true);
    toRoot.copy(root.matrixWorld).invert();
    rig.legs.forEach((leg, k) => {
      leg.foot.getWorldPosition(spot).applyMatrix4(toRoot);
      tracks[k].push({ y: spot.y * scale, z: spot.z * scale + walked });
    });
  }
  mixer.uncacheRoot(root);
  let slip = 0;
  const band = Math.min(0.005, 0.015 * rig.hipHeight * scale);
  for (const track of tracks) {
    const lowest = Math.min(...track.map(({ y }) => y));
    let stance: number[] = [];
    for (const { y, z } of [...track, { y: Infinity, z: 0 }]) {
      if (y < lowest + band) {
        stance.push(z);
        continue;
      }
      if (stance.length > 1)
        slip = Math.max(slip, Math.abs(stance[stance.length - 1] - stance[0]));
      stance = [];
    }
  }
  return slip;
}

test('every land animal walks and runs at the bible’s speeds with its feet still on the ground', async () => {
  for (const [kind, [walk, run]] of Object.entries(SPEEDS) as [
    AnimalKind,
    [number, number],
  ][]) {
    expect
      .soft(await footSlip(kind, 'walking', 'walk', walk), `${kind} walking`)
      .toBeLessThan(0.04);
    expect
      .soft(await footSlip(kind, 'fleeing', 'run', run), `${kind} running`)
      .toBeLessThan(0.04);
  }
  // the clip played at its own speed instead would skate (the moonwalk of audit F15)
  expect(await footSlip('deer', 'fleeing', 'run', 11, () => 1)).toBeGreaterThan(
    0.3,
  );
});

test('a deer’s run clip shows its planted feet moving back at its stride speed', async () => {
  const { root, clips } = await load(ANIMALS.deer.asset);
  const rig = rigOf(root);
  const run = clips.find((clip) => clip.name === 'Run')!;
  const walk = clips.find((clip) => clip.name === 'Walk')!;
  expect(strideSpeed(rig, run)).toBeCloseTo(2.21, 1);
  expect(strideSpeed(rig, walk)).toBeCloseTo(0.5, 1);
  expect(paceOf(11, 2.2)).toBeCloseTo(5, 5);
  expect(paceOf(3, null)).toBe(1); // swimmers have no feet to plant
});

test('gaits pick the clip, activities the layer', () => {
  expect(clipOf('deer', 'walking', 'walk', 1)).toBe('move');
  expect(clipOf('deer', 'trotting', 'trot', 5)).toBe('run');
  expect(clipOf('deer', 'walking', 'trot', 5)).toBe('run'); // the gait says how the path was walked
  expect(clipOf('deer', 'fleeing', 'run', 11)).toBe('run');
  expect(clipOf('deer', 'fleeing', 'walk', 11)).toBe('run'); // a feed without gaits still runs a flight
  expect(clipOf('wolf', 'stalking', 'stalk', 0.7)).toBe('move');
  expect(clipOf('wolf', 'stalking', 'run', 10)).toBe('run'); // the run into a pounce
  expect(clipOf('wolf', 'chasing', 'run', 0)).toBe('idle'); // standing: no gait on the spot
  expect(clipOf('rabbit', 'walking', 'walk', 0.5)).toBe('run'); // rabbits hop
  expect(clipOf('fish', 'swimming', 'swim', 0.3)).toBe('move');
  expect(clipOf('fish', 'swimming', 'run', 2)).toBe('run');

  const layers: [AnimalKind, AnimalActivity, AnimalGait, string][] = [
    ['deer', 'grazing', 'walk', 'graze'],
    ['deer', 'alert', 'walk', 'alert'],
    ['deer', 'fleeing', 'run', 'flee'],
    ['deer', 'drinking', 'walk', 'drink'],
    ['deer', 'dead', 'run', 'dead'],
    ['deer', 'remains', 'walk', 'remains'],
    ['rabbit', 'frozen', 'walk', 'frozen'],
    ['wolf', 'prowling', 'walk', 'prowl'],
    ['wolf', 'stalking', 'stalk', 'stalk'],
    ['wolf', 'hunting', 'stalk', 'stalk'],
    ['wolf', 'hunting', 'run', 'none'],
    ['wolf', 'pouncing', 'run', 'pounce'],
    ['wolf', 'attacking', 'walk', 'bite'],
    ['bear', 'attacking', 'walk', 'rear'],
    ['polar_bear', 'attacking', 'walk', 'rear'],
    ['wolf', 'feeding', 'walk', 'feed'],
    ['wolf', 'sleeping', 'walk', 'sleep'],
    ['duck', 'floating', 'walk', 'none'],
  ];
  for (const [kind, activity, gait, layer] of layers)
    expect(layerOf(kind, activity, gait), `${kind} ${activity}`).toBe(layer);
});

test('layers move as the bible says: grazing chews at 2 Hz, a pounce leaps 0.5 m, the dead fall in 0.8 s', () => {
  const graze = (t: number) => layerPose('graze', t);
  expect(graze(0).reach).toBe(1);
  expect(graze(0).jaw).toBeCloseTo(0, 5);
  expect(graze(0.25).jaw).toBeGreaterThan(0.1); // open half a beat in...
  expect(graze(0.5).jaw).toBeCloseTo(0, 5); // ...closed again at 2 Hz
  expect(layerPose('pounce', POUNCE_S / 2).lift).toBeCloseTo(0.5, 5);
  expect(layerPose('pounce', POUNCE_S).lift).toBeCloseTo(0, 5);
  expect(layerPose('pounce', POUNCE_S / 4).crouch).toBe(0);
  expect(layerPose('dead', 0).roll).toBe(0);
  expect(layerPose('dead', FALL_S / 2).roll).toBeLessThan(Math.PI / 4); // slow, then fast
  expect(layerPose('dead', FALL_S).roll).toBeCloseTo(Math.PI / 2, 5);
  expect(layerPose('dead', 3).roll).toBeCloseTo(Math.PI / 2, 5);
  expect(layerPose('stalk', 1).crouch).toBeCloseTo(0.2, 5);
  expect(layerPose('rear', 1).rear).toBeCloseTo((50 * Math.PI) / 180, 5);
  expect(layerPose('rear', 2.7).rear).toBe(0); // down on all fours to bite
  expect(layerPose('rear', 2.7).jaw).toBeGreaterThan(0.1);
  expect(layerPose('sleep', 1)).toMatchObject({ fold: 1, still: true });
  expect(layerPose('alert', 1).neck).toBeLessThan(0); // head up
  expect(layerPose('alert', 1).ears).toBeGreaterThan(0); // ears forward
  expect(layerPose('none', 1)).toMatchObject({ reach: 0, crouch: 0, roll: 0 });
});

test('a crouch keeps the feet where they stand, sleep folds the legs under, and nothing piles up frame to frame', async () => {
  const { root, clips } = await load(ANIMALS.wolf.asset);
  const rig = rigOf(root);
  const mixer = new AnimationMixer(root);
  mixer.clipAction(clips.find((clip) => clip.name === 'Idle')!).play();
  const feet = () =>
    rig.legs.map((leg) =>
      leg.foot
        .getWorldPosition(new Vector3())
        .applyMatrix4(new Matrix4().copy(root.matrixWorld).invert()),
    );
  const frame = (layer: Parameters<typeof layerPose>[0]) => {
    unbendBones(rig);
    mixer.update(0); // a still clip: the mixer writes nothing new
    root.updateMatrixWorld(true);
    const standing = feet();
    const hips = rig.hips!.position.y;
    poseBones(rig, layerPose(layer, 1));
    root.updateMatrixWorld(true);
    return { standing, posed: feet(), hips, sunk: rig.hips!.position.y };
  };
  for (let k = 0; k < 5; k++) {
    const { standing, posed, hips, sunk } = frame('stalk');
    expect(hips - sunk).toBeCloseTo(0.2 * rig.hipHeight, 5);
    posed.forEach((foot, n) =>
      expect(foot.distanceTo(standing[n])).toBeLessThan(0.002),
    );
  }
  const { standing, posed, hips, sunk } = frame('sleep');
  expect(hips - sunk).toBeCloseTo(0.55 * rig.hipHeight, 5);
  posed.forEach((foot, n) => {
    expect(foot.y).toBeCloseTo(standing[n].y, 2); // still on the ground...
    const tucked = rig.legs[n].front ? -1 : 1; // ...front feet back, hind feet forward
    expect((foot.z - standing[n].z) * tucked).toBeGreaterThan(
      0.3 * rig.hipHeight,
    );
  });
  // the clip's own pose comes back once the layer ends
  const after = frame('none');
  expect(after.sunk).toBeCloseTo(hips, 5);
});

test('grazing puts the muzzle down whatever the build: the neck ends pointing well below level', async () => {
  for (const kind of ['deer', 'wolf', 'bear', 'rabbit'] as AnimalKind[]) {
    const { root, clips } = await load(ANIMALS[kind].asset);
    const rig = rigOf(root);
    const mixer = new AnimationMixer(root);
    mixer.clipAction(clips.find((clip) => clip.name === 'Idle')!).play();
    unbendBones(rig);
    mixer.update(0);
    poseBones(rig, layerPose('graze', 0));
    root.updateMatrixWorld(true);
    const toRoot = new Matrix4().copy(root.matrixWorld).invert();
    const spot = (bone: Object3D) =>
      bone.getWorldPosition(new Vector3()).applyMatrix4(toRoot);
    const neck = spot(rig.head!).sub(spot(rig.neck!));
    expect(Math.atan2(neck.y, neck.z), kind).toBeLessThan(-0.6); // over 35° down
    unbendBones(rig);
    mixer.uncacheRoot(root);
  }
});

test('the body rolls onto its flank about its centre, rears about its hind feet and pitches to the slope', () => {
  const rig = { halfWidth: 0.4, centreY: 1, hindZ: -0.5 };
  const dead = bodyMatrix(layerPose('dead', 2), rig, new Matrix4());
  // the body's centre ends half its width above the ground, its feet out to the side
  expect(new Vector3(0, 1, 0).applyMatrix4(dead).toArray()).toEqual([
    expect.closeTo(0, 5),
    expect.closeTo(0.4, 5),
    expect.closeTo(0, 5),
  ]);
  expect(Math.abs(new Vector3(0, 0, 0).applyMatrix4(dead).x)).toBeCloseTo(1, 5);
  const reared = bodyMatrix(layerPose('rear', 1), rig, new Matrix4());
  expect(
    new Vector3(0, 0, -0.5)
      .applyMatrix4(reared)
      .distanceTo(new Vector3(0, 0, -0.5)),
  ).toBeLessThan(1e-9); // hind feet stay put
  expect(new Vector3(0, 1, 0.8).applyMatrix4(reared).y).toBeGreaterThan(1.5); // the chest goes up
  const leaping = bodyMatrix(
    layerPose('pounce', POUNCE_S / 2),
    rig,
    new Matrix4(),
  );
  expect(new Vector3().applyMatrix4(leaping).y).toBeCloseTo(0.5, 5);
  expect(slopePitch(0.5, 0, 2)).toBeCloseTo(Math.atan(0.25), 5);
  expect(slopePitch(-5, 0, 2)).toBeCloseTo((-25 * Math.PI) / 180, 5);
});

/** A frame of the feed for one animal: where it is, its timed route (x, z metres, seconds), what it does. */
function animalFrame(
  position: [number, number],
  route: [number, number, number][],
  activity: AnimalActivity,
  gait: AnimalGait = 'walk',
) {
  const points: RoutePoint[] = route.map(([x, z, t]) => ({
    unit: at(x, z),
    height_m: 8,
    t_s: t,
  }));
  return {
    position: { unit: at(...position) },
    route: points,
    speed_mps: 0,
    heading_deg: 0,
    activity,
    gait,
  };
}

test('a caught prey runs to where it is caught and falls there; a move without a route is walked, not jumped', () => {
  // drawn a little off where its path starts (still easing on from the last tick): it waits there all the same
  const grazing = animalFrame([0.3, 0], [], 'grazing');
  const track = newAnimalTrack(grazing, R);
  expect(shownActivity(track)).toBe('grazing');
  // the tick it is caught: it bolts 30 m from 20 s on and the tick says dead where its flight ends
  followAnimal(
    track,
    animalFrame(
      [30, 0],
      [
        [0, 0, 0],
        [0, 0, 20],
        [30, 0, 22.7],
      ],
      'dead',
      'run',
    ),
    R,
    1,
  );
  const spot = new Vector3();
  moveAnimal(track, 10, 1, spot);
  expect(shownActivity(track)).toBe('grazing'); // grazing until it bolts...
  moveAnimal(track, 11, 1, spot);
  expect(shownActivity(track)).toBe('running'); // ...running on its path...
  expect(spot.angleTo(new Vector3(...at(30, 0))) * R).toBeGreaterThan(5);
  moveAnimal(track, 2, 1, spot);
  expect(shownActivity(track)).toBe('dead'); // ...dead where it ends
  expect(spot.angleTo(new Vector3(...at(30, 0))) * R).toBeLessThan(1e-3);

  // a wolf running in: still chasing until it gets there, then the pounce
  const wolf = newAnimalTrack(
    animalFrame(
      [-20, 0],
      [
        [-40, 0, 0],
        [-20, 0, 30],
      ],
      'stalking',
      'stalk',
    ),
    R,
  );
  moveAnimal(wolf, 30, 1, spot); // the stalk's tick, walked
  followAnimal(
    wolf,
    animalFrame(
      [29, 0],
      [
        [-20, 0, 0],
        [-20, 0, 18],
        [29, 0, 22.9],
      ],
      'pouncing',
      'run',
    ),
    R,
    1,
  );
  moveAnimal(wolf, 10, 1, spot);
  expect(shownActivity(wolf)).toBe('stalking'); // crouched, waiting...
  moveAnimal(wolf, 10, 1, spot);
  expect(shownActivity(wolf)).toBe('running'); // ...the stalk breaks into a run...
  moveAnimal(wolf, 3.5, 1, spot);
  expect(shownActivity(wolf)).toBe('pouncing'); // ...and the leap where it ends

  // a feed from before animal routes: the animal moved 60 m with no route: walked over the tick
  const old = newAnimalTrack(animalFrame([0, 0], [], 'walking'), R);
  followAnimal(old, animalFrame([60, 0], [], 'walking'), R, 1, true);
  moveAnimal(old, 30, 1, spot);
  expect(spot.angleTo(new Vector3(...at(30, 0))) * R).toBeLessThan(0.05);
  moveAnimal(old, 30, 1, spot);
  expect(spot.angleTo(new Vector3(...at(60, 0))) * R).toBeLessThan(0.05);
  // a dead one that respawns elsewhere is a resync, not a walk
  const respawn = newAnimalTrack(animalFrame([0, 0], [], 'remains'), R);
  followAnimal(respawn, animalFrame([500, 0], [], 'grazing'), R, 1, true);
  expect(respawn.fade).not.toBeNull();
  // and in a feed with routes, a move without one is a jump (a skip): a resync too
  const skipped = newAnimalTrack(animalFrame([0, 0], [], 'grazing'), R);
  followAnimal(skipped, animalFrame([60, 0], [], 'grazing'), R, 1);
  expect(skipped.fade).not.toBeNull();
  // a path starting a few metres off (a tick that came late) is eased onto, no fade
  const late = newAnimalTrack(animalFrame([0, 0], [], 'grazing'), R);
  followAnimal(
    late,
    animalFrame(
      [60, 0],
      [
        [5, 0, 0],
        [60, 0, 55],
      ],
      'walking',
    ),
    R,
    1,
  );
  expect(late.fade).toBeNull();
  // standing about, then a walk to its meal: shown walking on the way (not still standing about)
  const idle = newAnimalTrack(animalFrame([0, 0], [], 'idle'), R);
  followAnimal(
    idle,
    animalFrame(
      [20, 0],
      [
        [0, 0, 0],
        [20, 0, 20],
      ],
      'feeding',
    ),
    R,
    1,
  );
  moveAnimal(idle, 10, 1, spot);
  expect(shownActivity(idle)).toBe('walking');
  moveAnimal(idle, 11, 1, spot);
  expect(shownActivity(idle)).toBe('feeding');
});

test('a body faces along the leg it walks, keeps its way while it waits on its path, and takes the feed’s heading standing', () => {
  // grazing facing east, then a tick that waits 8 s and bolts 30 m north
  const track = newAnimalTrack(
    { ...animalFrame([0, 0], [], 'grazing'), heading_deg: 90 },
    R,
  );
  const spot = new Vector3();
  const yawAt = (current: number) => {
    const { east, south } = tangentFrame(spot);
    return wantedYaw(track, east, south, current, 45);
  };
  moveAnimal(track, 0, 1, spot);
  expect(yawAt(1)).toBeCloseTo(Math.PI / 4, 6); // standing: the feed's heading
  followAnimal(
    track,
    animalFrame(
      [0, 30],
      [
        [0, 0, 0],
        [0, 0, 8],
        [0, 30, 10.5],
      ],
      'fleeing',
      'run',
    ),
    R,
    1,
  );
  moveAnimal(track, 4, 1, spot);
  expect(yawAt(Math.PI / 2)).toBe(Math.PI / 2); // waiting: still the way it grazed (not south, yaw 0)
  moveAnimal(track, 5, 1, spot);
  expect(Math.abs(yawAt(Math.PI / 2))).toBeCloseTo(Math.PI, 2); // running north
  moveAnimal(track, 5, 1, spot);
  expect(yawAt(0)).toBeCloseTo(Math.PI / 4, 6); // there: the feed's heading again
});
