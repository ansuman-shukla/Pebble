import { useFrame } from '@react-three/fiber';
import { type RefObject, useEffect, useMemo, useRef } from 'react';
import {
  type AmbientLight,
  BufferGeometry,
  Color,
  type DirectionalLight,
  Float32BufferAttribute,
  type Fog,
  type HemisphereLight,
  type Points,
  type PointsMaterial,
  Vector3,
} from 'three';

import { type GameClock, sunDirection } from '@/lib/world/game-clock';

/*
 * Sun, sky and stars driven by the game clock. The sun is a directional light circling the planet; its shadow
 * box (SHADOW_HALF each way) follows the focus (the player, or the ground under the camera). The sky colour and
 * fog follow the focus's local sun height (day blue, dusk orange, night dark blue) and fade to space as the camera
 * climbs, where the stars show.
 */

const SHADOW_HALF = 40;
const SUN_DISTANCE = 300;
/** Moving the box in whole steps keeps shadow edges from crawling every frame. */
const SHADOW_SNAP = 2;
const TICK_INTERVAL = 0.25;
const STAR_COUNT = 1500;

const DAY = new Color('#a9cfea');
const DUSK = new Color('#e7a06a');
const NIGHT = new Color('#0d1a33');
const SPACE = new Color('#03060e');

const smoothstep = (edge0: number, edge1: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
};

/** 0 below this camera altitude (metres above sea level) ... */
const SPACE_FROM = 300;
/** ... 1 above this one. */
const SPACE_TO = 2500;

/** How far the camera is from the surface's sky (0) towards space (1). */
const spaceFactor = (altitude: number) =>
  smoothstep(SPACE_FROM, SPACE_TO, altitude);

function starGeometry() {
  const values: number[] = [];
  let seed = 12345;
  const next = () => {
    seed = (Math.imul(seed, 1103515245) + 12345) >>> 0;
    return seed / 4294967296;
  };
  for (let i = 0; i < STAR_COUNT; i++) {
    const z = next() * 2 - 1;
    const angle = next() * Math.PI * 2;
    const ring = Math.sqrt(1 - z * z);
    values.push(ring * Math.cos(angle), z, ring * Math.sin(angle));
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(values, 3));
  return geometry;
}

const sun = new Vector3();
const up = new Vector3();
const focus = new Vector3();
const sky = new Color();

export function GlobeSky({
  clockRef,
  townLon,
  radius,
  focusRef,
  onTick,
}: {
  clockRef: RefObject<GameClock>;
  townLon: number;
  radius: number;
  /** Surface point the light and the sky colour follow. */
  focusRef: RefObject<Vector3>;
  /** Called a few times a second with the town time in game minutes. */
  onTick?: (minutes: number) => void;
}) {
  const light = useRef<DirectionalLight>(null);
  const hemisphere = useRef<HemisphereLight>(null);
  const ambient = useRef<AmbientLight>(null);
  const stars = useRef<Points>(null);
  const sinceTick = useRef(Infinity);
  const fog = useRef<Fog>(null);
  const background = useRef<Color>(null);
  const geometry = useMemo(() => starGeometry(), []);
  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame(({ camera }, delta) => {
    const time = clockRef.current;
    time.minutes += delta * time.rate;
    sinceTick.current += delta;
    if (onTick && sinceTick.current >= TICK_INTERVAL) {
      sinceTick.current = 0;
      onTick(time.minutes);
    }

    sunDirection(time.minutes, townLon, sun);
    up.copy(focusRef.current).normalize();
    const elevation = sun.dot(up);
    const daylight = smoothstep(-0.1, 0.15, elevation);
    const dusk =
      smoothstep(-0.25, 0, elevation) * (1 - smoothstep(0, 0.3, elevation));
    const space = spaceFactor(camera.position.length() - radius);

    sky
      .copy(NIGHT)
      .lerp(DAY, daylight)
      .lerp(DUSK, dusk * 0.7);
    background.current?.copy(sky).lerp(SPACE, space);
    if (fog.current) {
      fog.current.color.copy(sky).lerp(SPACE, space);
      fog.current.near = 250 + space * 1e5;
      fog.current.far = 1400 + space * 1e5;
    }

    const sunLight = light.current;
    if (sunLight) {
      sunLight.intensity = 2.4 * (daylight + (1 - daylight) * space);
      focus.copy(focusRef.current);
      focus.set(
        Math.round(focus.x / SHADOW_SNAP) * SHADOW_SNAP,
        Math.round(focus.y / SHADOW_SNAP) * SHADOW_SNAP,
        Math.round(focus.z / SHADOW_SNAP) * SHADOW_SNAP,
      );
      sunLight.position.copy(focus).addScaledVector(sun, SUN_DISTANCE);
      sunLight.target.position.copy(focus);
      sunLight.target.updateMatrixWorld();
    }
    if (hemisphere.current) {
      hemisphere.current.position.copy(up);
      hemisphere.current.intensity =
        (0.25 + 1.1 * daylight) * (1 - space * 0.8);
    }
    if (ambient.current) ambient.current.intensity = 0.55 + space * 0.15;
    if (stars.current) {
      stars.current.position.copy(camera.position);
      stars.current.scale.setScalar((camera as { far?: number }).far! * 0.9);
      const material = stars.current.material as PointsMaterial;
      material.opacity = Math.max(space, 1 - daylight) * 0.9;
    }
  });

  return (
    <>
      <color ref={background} attach="background" args={[DAY]} />
      <fog ref={fog} attach="fog" args={[DAY, 250, 1400]} />
      <ambientLight ref={ambient} color="#3d4f88" />
      <hemisphereLight ref={hemisphere} args={['#ffffff', '#7a6a4a', 1]} />
      <directionalLight
        ref={light}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0005}
        shadow-normalBias={0.04}
        shadow-camera-left={-SHADOW_HALF}
        shadow-camera-right={SHADOW_HALF}
        shadow-camera-top={SHADOW_HALF}
        shadow-camera-bottom={-SHADOW_HALF}
        shadow-camera-near={SUN_DISTANCE - 150}
        shadow-camera-far={SUN_DISTANCE + 150}
      />
      <points ref={stars} geometry={geometry} frustumCulled={false}>
        <pointsMaterial
          color="#ffffff"
          size={1.6}
          sizeAttenuation={false}
          transparent
          fog={false}
          depthWrite={false}
        />
      </points>
    </>
  );
}
