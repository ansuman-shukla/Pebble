import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo } from 'react';

import { advanceProps } from '@/lib/world/prop-motion';
import { SmokeCloud, type SmokingFire } from '@/lib/world/smoke';

/** Inside the Canvas: smoke and sparks over `fires` (the fires as drawn, by id): two draw calls for them all. */
export function FireSmoke({
  fires,
}: {
  fires: ReadonlyMap<string, SmokingFire>;
}) {
  const cloud = useMemo(() => new SmokeCloud(), []);
  useEffect(() => () => cloud.dispose(), [cloud]);
  useFrame(({ camera, clock }) => {
    advanceProps(clock.elapsedTime);
    cloud.frame(camera.position, fires);
  });
  return (
    <>
      <primitive object={cloud.puffs} />
      <primitive object={cloud.sparks} />
    </>
  );
}
