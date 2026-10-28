import { useEffect, useMemo, useRef } from 'react';
import type { Mesh } from 'three';

import { animateHumanoid } from '@/lib/world/humanoid-clips';
import { VISITOR_LOOK } from '@/lib/world/visitor-look';
import type { CharacterAnimation } from '@/vendor/polyfork/clips.mjs';
import { createCharacter } from '@/vendor/polyfork/humanoid.mjs';

/** The player's avatar and its locomotion clips (null until loaded, then onReady is called). */
export function useVisitor(onReady: () => void) {
  const character = useMemo(() => createCharacter(VISITOR_LOOK), []);
  const animation = useRef<CharacterAnimation | null>(null);

  useEffect(() => {
    let mounted = true;
    animateHumanoid(character).then((loaded) => {
      if (!mounted) return;
      animation.current = loaded;
      onReady();
    });
    return () => {
      mounted = false;
      animation.current = null;
      character.traverse((object) => (object as Mesh).geometry?.dispose());
    };
  }, [character, onReady]);

  return { character, animation };
}
