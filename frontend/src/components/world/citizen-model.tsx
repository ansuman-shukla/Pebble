import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useState } from 'react';
import type { Mesh } from 'three';

import type { CitizenLook } from '@/lib/world/citizen-looks';
import { animate, type CharacterAnimation } from '@/vendor/polyfork/clips.mjs';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

type CitizenModelProps = {
  look: CitizenLook;
  motion: 'Idle' | 'Walk';
  onReady?: (id: string) => void;
};

export function CitizenModel({ look, motion, onReady }: CitizenModelProps) {
  const character = useMemo(() => createCharacter(look.config), [look]);
  const [animation, setAnimation] = useState<CharacterAnimation | null>(null);

  useEffect(() => {
    let mounted = true;
    animate(character).then((loaded) => {
      if (!mounted) return;
      setAnimation(loaded);
      onReady?.(look.id);
    });
    return () => {
      mounted = false;
      character.traverse((object) => (object as Mesh).geometry?.dispose());
    };
  }, [character, look.id, onReady]);

  useEffect(() => {
    animation?.play(motion);
  }, [animation, motion]);

  useFrame((_, delta) => animation?.update(delta));

  return <primitive object={character} />;
}
