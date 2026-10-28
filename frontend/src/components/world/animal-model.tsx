import { useAnimations, useGLTF } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js';

import { ANIMALS, type AnimalKind, assetUrl } from '@/lib/world/assets';
import { recolor } from '@/lib/world/recolor';

/** Which of the animal's baked clips plays: standing (or floating), walking (swimming), running (swimming fast). */
export type AnimalGait = 'idle' | 'move' | 'run';

type AnimalModelProps = {
  kind: AnimalKind;
  gait: AnimalGait;
  /** Frozen on the clip's first frame (remains). */
  still?: boolean;
  /** Told the clip's name once it plays. */
  onClip?: (clip: string) => void;
};

export function AnimalModel({
  kind,
  gait,
  still = false,
  onClip,
}: AnimalModelProps) {
  const spec = ANIMALS[kind];
  const { scene, animations } = useGLTF(assetUrl(spec.asset));
  const model = useMemo(() => {
    const copy = clone(scene);
    if (spec.recolor) recolor(copy, spec.recolor);
    return copy;
  }, [scene, spec]);
  const { actions } = useAnimations(animations, model);

  useEffect(() => {
    const name = spec[gait];
    const action = actions[name];
    action?.reset().fadeIn(0.2).play();
    action?.setEffectiveTimeScale(still ? 0 : 1); // remains lie still on the first frame
    onClip?.(name);
    return () => {
      action?.fadeOut(0.2);
    };
  }, [actions, gait, still, spec, onClip]);

  return <primitive object={model} scale={spec.scale ?? 1} />;
}
