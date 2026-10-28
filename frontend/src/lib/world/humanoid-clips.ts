import type { Bone, Object3D } from 'three';

import { animate, type CharacterAnimation } from '@/vendor/polyfork/clips.mjs';

/**
 * Clips that keep the hips' sideways motion from the capture. Polyfork plays every clip on the spot by pinning
 * the hips' x/z, but the Idle's weight shift lives in that motion: pinned, the legs keep shifting under a still
 * pelvis and the feet slide about 18 cm from side to side while the character stands.
 */
const PLANTED_CLIPS = new Set(['Idle']);

/**
 * Loads Polyfork's humanoid clips (Idle, Walk, Run unless `clips` says otherwise) onto a character: the
 * standing Idle on planted feet, every other clip on the spot.
 */
export async function animateHumanoid(
  character: Object3D,
  clips?: string[],
): Promise<CharacterAnimation> {
  const hips = character
    .getObjectsByProperty('name', 'Hips')
    .find((object) => (object as Bone).isBone);
  if (!hips) throw new Error('animateHumanoid: the character has no Hips bone');
  const rest = hips.position.clone();
  const animation = await animate(character, { clips, inPlace: false });
  for (const [name, action] of Object.entries(animation.actions)) {
    if (PLANTED_CLIPS.has(name)) continue;
    const track = action
      .getClip()
      .tracks.find((candidate) => candidate.name === `${hips.uuid}.position`);
    if (!track) throw new Error(`animateHumanoid: "${name}" moves no hips`);
    // what Polyfork's in-place option does: the hips keep their height, not their x/z
    for (let i = 0; i < track.values.length; i += 3) {
      track.values[i] = rest.x;
      track.values[i + 2] = rest.z;
    }
  }
  return animation;
}
