import { useAnimations, useGLTF } from '@react-three/drei';
import { useEffect, useMemo } from 'react';
import { clone } from 'three/examples/jsm/utils/SkeletonUtils.js';

import { ANIMALS, type AnimalKind, assetUrl } from '@/lib/world/assets';
import { recolor } from '@/lib/world/recolor';

type AnimalModelProps = { kind: AnimalKind; moving: boolean };

export function AnimalModel({ kind, moving }: AnimalModelProps) {
  const spec = ANIMALS[kind];
  const { scene, animations } = useGLTF(assetUrl(spec.asset));
  const model = useMemo(() => {
    const copy = clone(scene);
    if (spec.recolor) recolor(copy, spec.recolor);
    return copy;
  }, [scene, spec]);
  const { actions } = useAnimations(animations, model);

  useEffect(() => {
    const action = actions[moving ? spec.move : spec.idle];
    action?.reset().fadeIn(0.2).play();
    return () => {
      action?.fadeOut(0.2);
    };
  }, [actions, moving, spec]);

  return <primitive object={model} scale={spec.scale ?? 1} />;
}
