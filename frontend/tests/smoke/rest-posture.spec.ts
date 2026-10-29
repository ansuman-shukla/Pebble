import { expect, test } from '@playwright/test';
import {
  AnimationClip,
  AnimationMixer,
  type Bone,
  Group,
  Object3D,
  Quaternion,
  type SkinnedMesh,
  Vector3,
  VectorKeyframeTrack,
} from 'three';

import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { animateHumanoid } from '../../src/lib/world/humanoid-clips';
import {
  groundTilt,
  holdPosture,
  layToRest,
  type Posture,
  type Resting,
  reshaped,
  restOf,
  settle,
  type Shape,
  shapeOf,
  showWorn,
} from '../../src/lib/world/rest-posture';
import { createCharacter } from '../../src/vendor/polyfork/humanoid.mjs';

/*
 * Sitting and lying citizens rest ON the ground (no browser; the clips come from Polyfork's CDN): the lowest point
 * of the skinned body is within 3 cm of the ground under it, on flat ground and on slopes, with the hips (and the
 * head and feet when lying) just above it.
 */

const TOUCH = 0.03;
/** Ground planes in the body's frame (x = its side, z = its facing): flat, 15° along, 15° across, both. */
const SLOPE = Math.tan((15 * Math.PI) / 180);
const GROUNDS: [string, number, number][] = [
  ['flat', 0, 0],
  ['uphill ahead', 0, SLOPE],
  ['downhill ahead', 0, -SLOPE],
  ['sloping sideways', SLOPE, 0],
  ['sloping both ways', -SLOPE * 0.7, SLOPE * 0.7],
];
const LOOKS = ['town-farmer', 'band-a-hunter', 'town-child', 'band-a-healer'];
/** The clip each posture plays under it (`npc-activity.ts`). */
const CLIP: Record<Exclude<Posture, 'standing'>, string> = {
  sitting: 'Sitting',
  lying: 'Idle',
};

const shown = (object: Object3D) => {
  for (let at: Object3D | null = object; at; at = at.parent)
    if (!at.visible) return false;
  return true;
};

/** The lowest height of any skinned vertex above the plane y = sx·x + sz·z (in `frame`'s coordinates). */
function clearance(
  character: Object3D,
  frame: Object3D,
  sx: number,
  sz: number,
) {
  frame.updateMatrixWorld(true);
  const vertex = new Vector3();
  let lowest = Infinity;
  character.traverse((object) => {
    const mesh = object as SkinnedMesh;
    if (!mesh.isSkinnedMesh || !shown(mesh)) return;
    mesh.skeleton.update();
    for (let i = 0; i < mesh.geometry.attributes.position.count; i++) {
      mesh.getVertexPosition(i, vertex);
      frame.worldToLocal(mesh.localToWorld(vertex));
      lowest = Math.min(lowest, vertex.y - (sx * vertex.x + sz * vertex.z));
    }
  });
  return lowest;
}

const boneHeight = (
  character: Object3D,
  frame: Object3D,
  name: string,
  sx: number,
  sz: number,
) => {
  const at = frame.worldToLocal(
    character.getObjectByName(name)!.getWorldPosition(new Vector3()),
  );
  return at.y - (sx * at.x + sz * at.z);
};

for (const posture of ['sitting', 'lying'] as const) {
  for (const id of LOOKS) {
    test(`${id} ${posture} rests on the ground, flat and on slopes`, async () => {
      const look = CITIZEN_LOOKS.find((candidate) => candidate.id === id)!;
      const character = createCharacter(look.config);
      const rest = restOf(character);
      const animation = await animateHumanoid(character, {
        clips: [CLIP[posture]],
      });
      animation.play(CLIP[posture]).paused = posture === 'lying';
      animation.update(0.4);
      holdPosture(rest, posture);
      showWorn(character, posture);
      const world = new Group();
      const tilt = new Group();
      const posed = new Group();
      world.add(tilt);
      tilt.add(posed);
      posed.add(character);
      const print = settle(posed, character, rest, posture);
      let held = 0;
      character.traverse((object) => {
        if (object.name.startsWith('attach-') && object.name.endsWith('hand'))
          held += shown(object) ? 1 : 0;
      });
      expect(held, 'held tools put away').toBe(0);
      // the ground is read under the body's ends: lying, the head lies behind the hips and the feet ahead
      const tall = look.config.age === 'kid' ? 0.6 : 1;
      expect(print.front).toBeGreaterThan(0.4 * tall);
      if (posture === 'lying') expect(print.back).toBeLessThan(-0.5 * tall);
      // the body turns about its hips: they stay over the spot the citizen is at
      const hipsAt = world.worldToLocal(
        rest.hips.getWorldPosition(new Vector3()),
      );
      expect(Math.hypot(hipsAt.x, hipsAt.z)).toBeLessThan(0.05);
      for (const [ground, sx, sz] of GROUNDS) {
        const height = (z: number, x = 0) => sx * x + sz * z;
        groundTilt(
          print,
          {
            back: height(print.back),
            front: height(print.front),
            left: height(0, -print.half),
            right: height(0, print.half),
          },
          tilt.quaternion,
        );
        const low = clearance(character, world, sx, sz);
        expect(Math.abs(low), `${ground}: lowest vertex ${low}`).toBeLessThan(
          TOUCH,
        );
        const hips = boneHeight(character, world, 'Hips', sx, sz);
        if (posture === 'sitting') {
          // on the ground (on a fold of cape or tunic at most), not on a chair of air (the clip's hips: 0.56 m)
          expect(hips, `${ground}: hips`).toBeGreaterThan(0.04);
          expect(hips, `${ground}: hips`).toBeLessThan(0.27);
        } else
          for (const bone of ['Head', 'Hips', 'LeftFoot', 'RightFoot']) {
            // an elder's stoop and long hair pillow the head a little higher
            const above = boneHeight(character, world, bone, sx, sz);
            expect(above, `${ground}: ${bone}`).toBeGreaterThan(0.02);
            expect(above, `${ground}: ${bone}`).toBeLessThan(
              bone === 'Head' ? 0.3 : 0.25,
            );
          }
      }
      tilt.quaternion.copy(new Quaternion());
    });
  }
}

test('a sleeper keeps still: its hips stay put while the clip under it would sway', async () => {
  const look = CITIZEN_LOOKS.find(
    (candidate) => candidate.id === 'town-farmer',
  )!;
  const character = createCharacter(look.config);
  const rest = restOf(character);
  const animation = await animateHumanoid(character, { clips: ['Idle'] });
  animation.play('Idle');
  const hips = character.getObjectByName('Hips') as Bone;
  const seen: Vector3[] = [];
  for (let k = 0; k < 20; k++) {
    animation.update(0.5); // the Idle shifts its weight over ~10 s
    holdPosture(rest, 'lying');
    seen.push(hips.position.clone());
  }
  for (const at of seen) expect(at.distanceTo(rest.hipsAt)).toBeLessThan(1e-6);
});

test('a resting body is measured again only when its posture or clip changed, or while the clips cross-fade', () => {
  const mixer = new AnimationMixer(new Object3D());
  const clip = (name: string) =>
    mixer.clipAction(new AnimationClip(name, 1, []));
  const [idle, sitting] = [clip('Idle'), clip('Sitting')];
  const shape = (over: Partial<Shape> = {}): Shape => ({
    posture: 'sitting',
    action: sitting,
    fading: false,
    ...over,
  });
  expect(reshaped(null, shape()), 'first frame at rest').toBe(true);
  expect(reshaped(shape(), shape()), 'settled').toBe(false);
  expect(reshaped(shape({ posture: 'lying' }), shape()), 'posture').toBe(true);
  expect(reshaped(shape({ action: idle }), shape()), 'clip arrived').toBe(true);
  expect(reshaped(shape({ action: null }), shape()), 'clips loaded').toBe(true);
  expect(reshaped(shape(), shape({ fading: true })), 'fading').toBe(true);
  expect(reshaped(shape({ fading: true }), shape()), 'fade just done').toBe(
    true,
  );
  const standing = shape({ posture: 'standing', action: idle });
  expect(reshaped(null, standing), 'standing').toBe(false);
  expect(reshaped(shape(), standing), 'stood up').toBe(false);
});

test('a body is fading while another clip still blends into it', () => {
  const box = new Object3D();
  const mixer = new AnimationMixer(box);
  const clip = (name: string) =>
    mixer.clipAction(
      new AnimationClip(name, 1, [
        new VectorKeyframeTrack('.position', [0, 1], [0, 0, 0, 0, 1, 0]),
      ]),
    );
  const [idle, sitting, unused] = [clip('Idle'), clip('Sitting'), clip('Run')];
  const all = [idle, sitting, unused];
  idle.play();
  mixer.update(0.1);
  expect(shapeOf('sitting', idle, all)).toEqual({
    posture: 'sitting',
    action: idle,
    fading: false, // Run was never played: its weight doesn't count
  });
  idle.paused = true; // a still sleeper getting up still blends out
  sitting.reset().play();
  idle.crossFadeTo(sitting, 0.2, false);
  mixer.update(0.1);
  expect(shapeOf('sitting', sitting, all).fading, 'mid fade').toBe(true);
  expect(shapeOf('sitting', null, all).fading, 'others blend').toBe(true);
  mixer.update(0.15);
  expect(shapeOf('sitting', sitting, all).fading, 'faded in').toBe(false);
  sitting.setEffectiveWeight(0.5);
  expect(shapeOf('sitting', sitting, all).fading, 'part weight').toBe(true);
});

for (const step of [1 / 60, 0.25]) {
  test(`a sitter whose clip loads late still rests on the ground once it plays (${step.toFixed(2)} s frames)`, async () => {
    const look = CITIZEN_LOOKS.find(
      (candidate) => candidate.id === 'band-a-hunter',
    )!;
    const character = createCharacter(look.config);
    const rest = restOf(character);
    const world = new Group();
    const tilt = new Group();
    const posed = new Group();
    world.add(tilt);
    tilt.add(posed);
    posed.add(character);
    const body = { character, rest, tilt, posed, ground: () => 0 };
    const state: Resting = { shape: null, print: null };
    // sitting down before `Sitting` has loaded: the citizen's page plays Idle in its place
    let animation = await animateHumanoid(character, { clips: ['Idle'] });
    let playing = animation.play('Idle');
    let measured = 0;
    const frames = (seconds: number) => {
      for (let t = 0; t < seconds; t += step) {
        animation.update(step);
        holdPosture(rest, 'sitting');
        const print = state.print;
        layToRest(
          state,
          shapeOf('sitting', playing, Object.values(animation.actions)),
          body,
        );
        if (state.print !== print) measured++;
      }
    };
    frames(1);
    expect(measured, 'measured once on the stand-in').toBe(1);
    // the clip arrives: the page loads every clip again and cross-fades into it
    animation.mixer.stopAllAction();
    animation = await animateHumanoid(character, {
      clips: ['Idle', 'Sitting'],
    });
    playing = animation.play('Sitting');
    measured = 0;
    frames(1);
    const low = clearance(character, world, 0, 0);
    expect(Math.abs(low), `lowest vertex ${low}`).toBeLessThan(TOUCH);
    expect(measured, 'measured through the fade').toBeGreaterThan(0);
    expect(measured).toBeLessThanOrEqual(Math.ceil(0.2 / step) + 2);
    measured = 0;
    frames(1);
    expect(measured, 'settled: no measuring every frame').toBe(0);
  });
}
