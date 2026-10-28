import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import { type DirectionalLight, Vector3 } from 'three';

/*
 * Sky colour, distance fog, a hemisphere fill and a sun whose shadow box (SHADOW_HALF each way) follows the
 * ground point the camera looks at, so one 2048 map stays sharp wherever you are in the town.
 */

const SKY = '#cfe3ef';
const FOG: [number, number] = [180, 900];
const SUN_OFFSET = new Vector3(60, 100, 40);
const SHADOW_HALF = 40;
/** Furthest along the view the shadow box is moved (looking at the horizon would push it far away). */
const SHADOW_REACH = 30;
/** Moving the box in whole steps keeps shadow edges from crawling every frame. */
const SHADOW_SNAP = 2;

const look = new Vector3();
const focus = new Vector3();

export function TownSky() {
  const sun = useRef<DirectionalLight>(null);

  useFrame(({ camera }) => {
    const light = sun.current;
    if (!light) return;
    camera.getWorldDirection(look);
    const toGround =
      look.y < -1e-3 ? camera.position.y / -look.y : SHADOW_REACH;
    focus
      .copy(camera.position)
      .addScaledVector(look, Math.min(toGround, SHADOW_REACH));
    focus.set(
      Math.round(focus.x / SHADOW_SNAP) * SHADOW_SNAP,
      0,
      Math.round(focus.z / SHADOW_SNAP) * SHADOW_SNAP,
    );
    light.position.copy(focus).add(SUN_OFFSET);
    light.target.position.copy(focus);
    light.target.updateMatrixWorld();
  });

  return (
    <>
      <color attach="background" args={[SKY]} />
      <fog attach="fog" args={[SKY, ...FOG]} />
      <hemisphereLight args={['#ffffff', '#8a7a5a', 1.5]} />
      <directionalLight
        ref={sun}
        intensity={2.2}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0005}
        shadow-normalBias={0.04}
        shadow-camera-left={-SHADOW_HALF}
        shadow-camera-right={SHADOW_HALF}
        shadow-camera-top={SHADOW_HALF}
        shadow-camera-bottom={-SHADOW_HALF}
        shadow-camera-near={1}
        shadow-camera-far={300}
      />
    </>
  );
}
