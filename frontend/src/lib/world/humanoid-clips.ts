import type { Bone, Object3D } from 'three';

import { animate, type CharacterAnimation } from '@/vendor/polyfork/clips.mjs';

/**
 * Clips that keep the hips' sideways motion from the capture unless the caller says otherwise. Polyfork plays
 * every clip on the spot by pinning the hips' x/z, but a standing clip's weight shift lives in that motion:
 * pinned, the legs keep shifting under a still pelvis and the feet slide (about 18 cm from side to side in Idle).
 */
const PLANTED_CLIPS: ReadonlySet<string> = new Set(['Idle']);

interface HumanoidClips {
  /** Polyfork clips to load (Idle, Walk, Run by default). */
  clips?: readonly string[];
  /**
   * Standing clips played on planted feet (the hips keep their captured x/z); every other clip, the gaits
   * above all, plays on the spot.
   */
  planted?: ReadonlySet<string>;
}

/** Loads Polyfork's humanoid clips onto a character: the `planted` ones on planted feet, the rest on the spot. */
export async function animateHumanoid(
  character: Object3D,
  { clips, planted = PLANTED_CLIPS }: HumanoidClips = {},
): Promise<CharacterAnimation> {
  const hips = character
    .getObjectsByProperty('name', 'Hips')
    .find((object) => (object as Bone).isBone);
  if (!hips) throw new Error('animateHumanoid: the character has no Hips bone');
  const rest = hips.position.clone();
  const animation = await animate(character, {
    clips: clips && [...clips],
    inPlace: false,
  });
  for (const [name, action] of Object.entries(animation.actions)) {
    if (planted.has(name)) continue;
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
