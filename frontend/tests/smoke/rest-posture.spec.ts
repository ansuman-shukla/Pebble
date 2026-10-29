import { expect, test } from '@playwright/test';
import {
  type Bone,
  Group,
  type Object3D,
  Quaternion,
  type SkinnedMesh,
  Vector3,
} from 'three';

import { CITIZEN_LOOKS } from '../../src/lib/world/citizen-looks';
import { animateHumanoid } from '../../src/lib/world/humanoid-clips';
import {
  groundTilt,
  holdPosture,
  type Posture,
  restOf,
  settle,
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
