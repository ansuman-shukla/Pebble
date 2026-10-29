import { useFrame } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import {
  AdditiveBlending,
  CanvasTexture,
  ConeGeometry,
  type Group,
  MeshBasicMaterial,
  type PointLight,
  Quaternion,
  type Sprite,
  SpriteMaterial,
  Vector3,
} from 'three';

import { FireSmoke } from '@/components/world/globe/fire-smoke';
import type { LiveFire } from '@/lib/live/live-contract';
import { assetSize, PROPS } from '@/lib/world/assets';
import { type GlobeTerrain, tangentFrame } from '@/lib/world/globe';
import { groundUnder, type WalkTown } from '@/lib/world/walk-charts';

/*
 * The live fires: every lit fire within reach of the camera flickers as a few additive flame cones and a glow
 * sprite sized by its strength (embers, low, burning), and the nearest few cast warm light. The light count is
 * fixed (unused lights go dark) so lighting never changes the scene's shaders. Smoke and sparks rise over them
 * (fire-smoke.tsx). Cold fires draw no flames: the pit or basket prop is already there, its flame or fuel hidden.
 */

/** Flames are drawn within this distance of the camera. */
const DRAWN = 600;
/** This many point lights follow the nearest lit fires. */
const LIGHTS = 3;
const LIGHT_REACH = 250;
const LIGHT_INTENSITY = 40;
const LIGHT_DISTANCE = 30;
/** A fire basket holds its fire at the top of the basket. */
const BASKET_TOP = assetSize(PROPS.fire_basket).y - 0.15;
const PIT_LIFT = 0.1;
const FLAME_COLORS = ['#ff6a00', '#ffa31a', '#ffe08a'];

const flameGeometry = new ConeGeometry(0.22, 0.9, 7, 1, true).translate(
  0,
  0.45,
  0,
);
const flameMaterials = FLAME_COLORS.map(
  (color, index) =>
    new MeshBasicMaterial({
      color,
      transparent: true,
      opacity: 0.85 - index * 0.15,
      blending: AdditiveBlending,
      depthWrite: false,
    }),
);

function glowTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const context = canvas.getContext('2d')!;
  const gradient = context.createRadialGradient(
    size / 2,
    size / 2,
    0,
    size / 2,
    size / 2,
    size / 2,
  );
  gradient.addColorStop(0, 'rgba(255,200,120,1)');
  gradient.addColorStop(0.35, 'rgba(255,140,40,0.45)');
  gradient.addColorStop(1, 'rgba(255,100,0,0)');
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  return new CanvasTexture(canvas);
}

/** What the page and the tests can read of a drawn fire. */
interface FireView {
  id: string;
  lit: boolean;
  strength: number;
  /** World position of the flame's base. */
  position: Vector3;
  /** Drawn (lit and within reach of the camera). */
  drawn: boolean;
  /** One of the point lights is on it. */
  lighted: boolean;
}

export type FireViews = Map<string, FireView>;

const flicker = (time: number, seed: number) =>
  1 + 0.18 * Math.sin(time * 13 + seed) + 0.1 * Math.sin(time * 7.3 + seed * 2);

function baseOf(
  fire: LiveFire,
  terrain: GlobeTerrain,
  town: WalkTown,
  target: Vector3,
) {
  const direction = target.set(...fire.position.unit);
  const ground = groundUnder(terrain, town, direction, new Vector3());
  const lift = fire.kind === 'basket' ? BASKET_TOP : PIT_LIFT;
  return direction.multiplyScalar(terrain.globe.radius + ground + lift);
}

function Flame({
  fire,
  terrain,
  town,
  views,
  glow,
}: {
  fire: LiveFire;
  terrain: GlobeTerrain;
  town: WalkTown;
  views: FireViews;
  glow: SpriteMaterial;
}) {
  const group = useRef<Group>(null);
  const sprite = useRef<Sprite>(null);
  const base = useMemo(
    () => baseOf(fire, terrain, town, new Vector3()),
    [fire, terrain, town],
  );
  const viewRef = useRef<FireView>({
    id: fire.id,
    lit: fire.lit,
    strength: fire.strength,
    position: base,
    drawn: false,
    lighted: false,
  });
  useLayoutEffect(() => {
    const view = viewRef.current;
    view.lit = fire.lit;
    view.strength = fire.strength;
    view.position = base;
  }, [fire, base]);
  useEffect(() => {
    views.set(fire.id, viewRef.current);
    return () => {
      views.delete(fire.id);
    };
  }, [fire.id, views]);
  const seed = useMemo(
    () => [...fire.id].reduce((sum, char) => sum + char.charCodeAt(0), 0),
    [fire.id],
  );
  const size = fire.kind === 'basket' ? 0.6 : 1;
  // flames stand up along the surface normal
  const quaternion = useMemo(
    () =>
      new Quaternion().setFromUnitVectors(
        new Vector3(0, 1, 0),
        tangentFrame(base.clone().normalize()).up,
      ),
    [base],
  );

  useFrame(({ camera, clock }) => {
    const body = group.current;
    if (!body) return;
    const view = viewRef.current;
    view.drawn = view.lit && camera.position.distanceTo(view.position) < DRAWN;
    body.visible = view.drawn;
    if (!view.drawn) return;
    const time = clock.elapsedTime;
    const strength = Math.max(view.strength, 0.2) * size;
    body.children.forEach((flame, index) => {
      if (flame === sprite.current) return;
      const wave = flicker(time + index * 0.37, seed + index);
      const width = strength * (1 - index * 0.2);
      flame.scale.set(width, strength * wave * (1.2 - index * 0.25), width);
    });
    const glowSize = 2.4 * strength * flicker(time, seed);
    sprite.current?.scale.set(glowSize, glowSize, 1);
  });

  return (
    <group ref={group} position={base} quaternion={quaternion} visible={false}>
      {flameMaterials.map((material, index) => (
        <mesh
          key={index}
          geometry={flameGeometry}
          material={material}
          rotation-y={index * 1.1}
        />
      ))}
      <sprite ref={sprite} material={glow} position-y={0.35 * size} />
    </group>
  );
}

function FireLights({ views }: { views: FireViews }) {
  const lights = useRef<(PointLight | null)[]>([]);
  useFrame(({ camera, clock }) => {
    const lit = [...views.values()]
      .filter((view) => view.drawn)
      .map((view) => ({
        view,
        distance: camera.position.distanceTo(view.position),
      }))
      .filter(({ distance }) => distance < LIGHT_REACH)
      .sort((a, b) => a.distance - b.distance)
      .slice(0, LIGHTS);
    for (const view of views.values()) view.lighted = false;
    lights.current.forEach((light, index) => {
      if (!light) return;
      const target = lit[index]?.view;
      if (!target) {
        light.intensity = 0;
        return;
      }
      target.lighted = true;
      light.position
        .copy(target.position)
        .addScaledVector(target.position.clone().normalize(), 0.8);
      light.intensity =
        LIGHT_INTENSITY *
        Math.max(target.strength, 0.2) *
        flicker(clock.elapsedTime, index * 17);
    });
  });
  return (
    <>
      {Array.from({ length: LIGHTS }, (_, index) => (
        <pointLight
          key={index}
          ref={(light) => {
            lights.current[index] = light;
          }}
          color="#ff9a3c"
          intensity={0}
          distance={LIGHT_DISTANCE}
          decay={2}
        />
      ))}
    </>
  );
}

/** Inside the Canvas: every lit fire of the feed, flickering, the nearest ones lighting their surroundings. */
export function GlobeFires({
  fires,
  terrain,
  town,
  views,
}: {
  fires: LiveFire[];
  terrain: GlobeTerrain;
  town: WalkTown;
  /** Filled with what is drawn of each fire. */
  views: FireViews;
}) {
  const glow = useMemo(
    () =>
      new SpriteMaterial({
        map: glowTexture(),
        blending: AdditiveBlending,
        depthWrite: false,
        transparent: true,
      }),
    [],
  );
  useEffect(() => () => glow.map?.dispose(), [glow]);

  return (
    <>
      {fires.map((fire) => (
        <Flame
          key={fire.id}
          fire={fire}
          terrain={terrain}
          town={town}
          views={views}
          glow={glow}
        />
      ))}
      <FireLights views={views} />
      <FireSmoke fires={views} />
    </>
  );
}

/** Hidden DOM hooks for tests: the fires as drawn, refreshed every 0.1 s. */
export function FireHooks({ views }: { views: FireViews }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const timer = window.setInterval(() => {
      const element = root.current;
      if (!element) return;
      const all = [...views.values()];
      element.dataset.fires = String(all.length);
      element.dataset.lit = all
        .filter((view) => view.lit)
        .map((view) => view.id)
        .sort()
        .join(',');
      element.dataset.drawn = all
        .filter((view) => view.drawn)
        .map((view) => view.id)
        .sort()
        .join(',');
      element.dataset.lighted = all
        .filter((view) => view.lighted)
        .map((view) => view.id)
        .sort()
        .join(',');
    }, 100);
    return () => window.clearInterval(timer);
  }, [views]);
  return <div ref={root} hidden data-testid="fires" data-fires={0} />;
}
